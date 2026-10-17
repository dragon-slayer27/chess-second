"""Generate the sample reviews shown on /samples and in the public demo.

    python scripts/make_samples.py

The games are real games from eval/games.pgn (the CC0 Lichess database); the student names are
made up. The notes come from whatever model the environment points at (by default Gemma 4 E4B
in a local Ollama), so samples show exactly what a coach would get on their own laptop.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import chess
import chess.pgn

from second.config import load_settings
from second.llm import make_client
from second.review import review_game

ROOT = Path(__file__).resolve().parent.parent


def load_eval_games() -> list[chess.pgn.Game]:
    stream = io.StringIO((ROOT / "eval" / "games.pgn").read_text(encoding="utf-8"))
    games = []
    while (game := chess.pgn.read_game(stream)) is not None:
        games.append(game)
    return games


def main() -> None:
    settings = load_settings()
    llm = make_client(settings)
    games = load_eval_games()
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    for sample in json.loads((ROOT / "scripts" / "samples.json").read_text(encoding="utf-8")):
        game = games[sample["game"]]
        color = chess.WHITE if sample["color"] == "white" else chess.BLACK
        game.headers["White" if color == chess.WHITE else "Black"] = sample["name"]
        game.headers["Black" if color == chess.WHITE else "White"] = "Opponent"
        print(f"{sample['id']}: reviewing...", flush=True)
        review = review_game(
            game,
            settings=settings,
            llm=llm,
            color=color,
            student_name=sample["name"],
            level=sample["level"],
            language=sample["language"],
        )
        review.update({"id": sample["id"], "sample_title": sample["title"], "sample_blurb": sample["blurb"]})
        (out / f"{sample['id']}.json").write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
        stats = review["stats"]
        print(
            f"  {len(review['moments'])} moments, {stats['template_notes']} template notes, "
            f"{stats['hallucinations_caught']} caught, {review['timings']['total_s']}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
