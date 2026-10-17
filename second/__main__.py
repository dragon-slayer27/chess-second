"""Command line: review a PGN file in one go, check the setup, or start the web app."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chess

from .config import load_settings
from .games import parse_pgn, player_color
from .llm import LLMError, NoModelClient, make_client
from .prompts import LEVELS
from .report import render_standalone
from .review import review_game
from .store import ReviewStore


def _check(settings) -> int:
    ok = True
    if settings.stockfish_path:
        print(f"[ok] Stockfish: {settings.stockfish_path}")
    else:
        print("[!!] Stockfish not found. Put it in ./bin or set STOCKFISH_PATH.")
        ok = False
    try:
        print(f"[ok] Model: {make_client(settings).check()}")
    except LLMError as exc:
        print(f"[!!] Model: {exc}")
        ok = False
    return 0 if ok else 1


def _review(args, settings) -> int:
    text = sys.stdin.read() if args.pgn == "-" else Path(args.pgn).read_text(encoding="utf-8", errors="replace")
    games = parse_pgn(text, limit=args.max_games)
    if not games:
        print("No games found in that PGN.")
        return 1
    llm = NoModelClient() if args.no_llm else make_client(settings)
    store = ReviewStore(settings.data_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for number, game in enumerate(games, 1):
        if args.color in ("white", "black"):
            color = chess.WHITE if args.color == "white" else chess.BLACK
        else:
            color = player_color(game, args.student)
            if color is None:
                print(f"Game {number}: can't tell which side {args.student or 'the student'} played; use --color.")
                continue
        title = f"{game.headers.get('White', '?')} vs {game.headers.get('Black', '?')}"
        print(f"Game {number}/{len(games)}: {title}")

        def progress(message: str, fraction: float) -> None:
            print(f"\r  {int(fraction * 100):3d}%  {message[:70]:<70}", end="", flush=True)

        review = review_game(
            game,
            settings=settings,
            llm=llm,
            color=color,
            student_name=args.student,
            level=args.level,
            language=args.language,
            progress=progress,
        )
        print()
        store.save(review)
        (out / f"{review['id']}.html").write_text(render_standalone(review), encoding="utf-8")
        (out / f"{review['id']}.pgn").write_text(review["annotated_pgn"], encoding="utf-8")
        stats = review["stats"]
        print(
            f"  {len(review['moments'])} key moments, accuracy {review['accuracy']['student']}%, "
            f"{stats['hallucinations_caught']} invented details caught, {stats['template_notes']} template notes, "
            f"{review['timings']['total_s']}s -> {out / (review['id'] + '.html')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="second",
        description="Game reviews for chess coaches: Stockfish finds it, Gemma explains it, code checks it.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="start the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("check", help="check that Stockfish and the model are ready")
    review = commands.add_parser("review", help="review the games in a PGN file")
    review.add_argument("pgn", help="PGN file, or - to read from stdin")
    review.add_argument("--student", default="", help="student's name or username in the PGN")
    review.add_argument("--color", choices=["auto", "white", "black"], default="auto")
    review.add_argument("--level", choices=list(LEVELS), default="beginner")
    review.add_argument("--language", default="English", help="language of the note for parents")
    review.add_argument("--max-games", type=int, default=None)
    review.add_argument("--out", default="reports", help="folder for the HTML and PGN reports")
    review.add_argument("--no-llm", action="store_true", help="skip the model and use template notes")
    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "check":
        return _check(settings)
    if args.command == "review":
        return _review(args, settings)
    import uvicorn

    print(f"Second is running at http://{args.host}:{args.port}")
    uvicorn.run("second.web:app", host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
