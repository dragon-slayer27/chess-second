"""Does grounding plus verification stop Gemma from inventing chess?

For every blunder and mistake (both colours, up to --per-side per game) in eval/games.pgn:

  raw       Gemma gets the moves so far and is told which move was the mistake. This is
            what happens when someone pastes a game into a chatbot.
  grounded  Gemma gets Second's engine facts instead (its first answer, before verification).
  second    The full pipeline: engine facts, verifier, up to three tries, template fallback.

Every note is checked for chess claims the engine did not confirm, and for piece moves
that are not even legal on the board.

Usage:
    python eval/run_eval.py [--limit 30] [--per-side 1]
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import time
from collections import Counter
from pathlib import Path

import chess
import chess.pgn

from second import fallback
from second.config import load_settings
from second.engine import Analyzer
from second.facts import build_moment
from second.llm import LLMError, make_client
from second.prompts import JUDGEMENT_WORDS, MOMENT_SCHEMA, moment_prompt, system_prompt
from second.review import write_note
from second.verify import SQUARE_ONLY_RE, Allowed, check_text, notation_tokens, verify_moment

HERE = Path(__file__).parent
RAW_SYSTEM = (
    "You are a friendly chess coach. You explain mistakes to a young beginner "
    "(about 7 to 12 years old). Reply with one JSON object and nothing else."
)
CONDITIONS = ("raw", "grounded", "second")


class Recorder:
    """Wraps a model client and remembers every reply and how long it took."""

    def __init__(self, inner):
        self.inner = inner
        self.label = inner.label
        self.log: list[dict] = []

    def chat_json(self, system, user, schema, temperature=0.4):
        start = time.perf_counter()
        try:
            data = self.inner.chat_json(system, user, schema, temperature)
        except LLMError as exc:
            self.log.append({"error": str(exc), "seconds": time.perf_counter() - start})
            raise
        self.log.append({"data": data, "seconds": time.perf_counter() - start})
        return data


def movetext_until(game: chess.pgn.Game, ply: int) -> str:
    board = game.board()
    parts = []
    for index, move in enumerate(game.mainline_moves()):
        if index > ply:
            break
        if board.turn == chess.WHITE:
            parts.append(f"{board.fullmove_number}.")
        elif index == 0:
            parts.append(f"{board.fullmove_number}...")
        parts.append(board.san(move))
        board.push(move)
    return " ".join(parts)


def raw_prompt(game: chess.pgn.Game, moment: dict) -> str:
    judgement = JUDGEMENT_WORDS.get(moment["judgement"], "a mistake")
    return f"""Here is a chess game up to the move in question:
{movetext_until(game, moment["ply"])}

The move {moment["label"]} by {moment["color"].capitalize()} was {judgement}.
Write a JSON object with these keys:
"headline": the main idea in at most 7 words.
"explanation": 2 or 3 short sentences. Say what went wrong and which move would have been better.
"question": one question to ask the student.
"tip": one short rule of thumb."""


def note_text(note: dict) -> str:
    return " ".join(str(note.get(key, "")) for key in ("headline", "explanation", "question", "tip"))


def _legal(board: chess.Board, token: str) -> bool:
    try:
        board.parse_san(token)
        return True
    except ValueError:
        return False


def impossible_moves(text: str, moment: dict) -> list[str]:
    """Piece moves and captures that are illegal before the mistake, after it, and after the reply."""
    before = chess.Board(moment["fen_before"])
    after = chess.Board(moment["fen_after"])
    boards = [before, after]
    if moment.get("reply_uci"):
        reply = after.copy()
        reply.push(chess.Move.from_uci(moment["reply_uci"]))
        boards.append(reply)
    bad = []
    for token in notation_tokens(text):
        if SQUARE_ONLY_RE.fullmatch(token) or token in moment["allowed_sans"]:
            continue
        if not any(_legal(board, token) for board in boards):
            bad.append(token)
    return bad


def score(note: dict, moment: dict) -> dict:
    text = note_text(note)
    issues = [i for i in check_text(text, Allowed.from_moment(moment)) if i.is_hallucination]
    best = moment["best"].rstrip("+#") if moment["best"] else None
    played = moment["played"].rstrip("+#")
    moves = [t for t in notation_tokens(text) if not SQUARE_ONLY_RE.fullmatch(t) and t != played]
    names_best = bool(best and best in notation_tokens(text))
    return {
        "unconfirmed": [str(i) for i in issues],
        "kinds": sorted({i.kind for i in issues}),
        "impossible": impossible_moves(text, moment),
        "suggests_move": bool(moves) or names_best,
        "names_best": names_best,
    }


def collect_moments(games, analyzer, per_side: int, limit: int):
    moments = []
    for number, game in enumerate(games, 1):
        analysis = analyzer.analyse_game(game)
        for color in (chess.WHITE, chess.BLACK):
            serious = [m for m in analysis.moves if m.color == color and m.judgement in ("blunder", "mistake")]
            serious.sort(key=lambda m: m.win_drop, reverse=True)
            for move in sorted(serious[:per_side], key=lambda m: m.ply):
                moments.append((number, game, build_moment(move).to_dict()))
        print(f"  analysed game {number}/{len(games)}: {len(moments)} moments so far", flush=True)
        if len(moments) >= limit:
            break
    return moments[:limit]


def summarise(records: list[dict]) -> dict:
    total = len(records)
    summary = {"moments": total}
    for condition in CONDITIONS:
        scored = [r[condition] for r in records if r[condition].get("score")]
        kinds = Counter(kind for r in scored for kind in r["score"]["kinds"])
        summary[condition] = {
            "notes": len(scored),
            "unconfirmed": sum(1 for r in scored if r["score"]["unconfirmed"]),
            "impossible": sum(1 for r in scored if r["score"]["impossible"]),
            "suggests_move": sum(1 for r in scored if r["score"].get("suggests_move")),
            "names_best": sum(1 for r in scored if r["score"]["names_best"]),
            "median_seconds": round(statistics.median(r["seconds"] for r in scored), 1) if scored else None,
            "kinds": dict(kinds),
        }
    second = [r["second"] for r in records]
    summary["second"]["retried"] = sum(1 for r in second if r.get("attempts", 1) > 1)
    summary["second"]["template"] = sum(1 for r in second if r.get("source") == "template")
    return summary


def pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({round(100 * part / whole)}%)" if whole else "-"


def write_markdown(summary: dict, meta: dict, path: Path, records: list[dict]) -> None:
    raw, grounded, second = summary["raw"], summary["grounded"], summary["second"]
    rows = [
        ("Notes that suggest a concrete move", "suggests_move"),
        ("...and it is Stockfish's better move", "names_best"),
        ("Notes with a piece move that isn't even legal", "impossible"),
        ("Notes with a chess claim the engine didn't confirm", "unconfirmed"),
    ]
    lines = [
        "# Evaluation: does Second stop Gemma from inventing chess?",
        "",
        f"- Model: {meta['model']}",
        f"- Engine: {meta['engine']}",
        f"- Data: {meta['games']} rated blitz/classical games between 1000-1700 players from the CC0 "
        f"[Lichess database](https://database.lichess.org) (January 2013), {summary['moments']} blunders and mistakes.",
        f"- Hardware: {meta['hardware']}",
        f"- Run on {meta['date']}, total time {meta['minutes']} minutes.",
        "",
        '| | Plain Gemma (moves + "explain this mistake") | Gemma + engine facts (first answer) | Second (facts + verifier + retries) |',
        "|---|---|---|---|",
    ]
    for label, key in rows:
        lines.append(
            f"| {label} | {pct(raw[key], raw['notes'])} | {pct(grounded[key], grounded['notes'])} | {pct(second[key], second['notes'])} |"
        )
    lines.append(
        f"| Median time per note | {raw['median_seconds']}s | {grounded['median_seconds']}s | {second['median_seconds']}s |"
    )
    lines += [
        "",
        f"Second needed a retry for {pct(second['retried'], second['notes'])} of notes and fell back to the "
        f"plain template for {pct(second['template'], second['notes'])}.",
    ]
    if second["retried"] == 0:
        lines.append(
            "With the facts in the prompt, Gemma's first answer passed the verifier every time in this run, so the "
            "verifier never had to step in. It is there for the times grounding isn't enough; `tests/test_verify.py` "
            "shows what it catches."
        )
    lines += [
        "",
        "Kinds of unconfirmed claims (number of notes):",
        "",
        "| Kind | Plain Gemma | Gemma + facts |",
        "|---|---|---|",
    ]
    for kind in sorted(set(raw["kinds"]) | set(grounded["kinds"])):
        lines.append(f"| {kind.replace('_', ' ')} | {raw['kinds'].get(kind, 0)} | {grounded['kinds'].get(kind, 0)} |")
    examples = [r for r in records if r["raw"].get("score", {}).get("impossible")][:3]
    if examples:
        lines += ["", "## Examples", ""]
        for record in examples:
            moment = record["moment"]
            lines += [
                f"**{moment['label']}** ({moment['judgement']}, [game]({record['site']})). Stockfish's better move: **{moment['best']}**.",
                "",
                f'- Plain Gemma: "{record["raw"]["note"].get("explanation", "")}" '
                f"(not legal on the board: {', '.join(record['raw']['score']['impossible'])})",
                f'- Second: "{record["second"]["note"].get("explanation", "")}"',
                "",
            ]
    lines += [
        "",
        '"Unconfirmed" means the note mentions a move, square, piece, mate-in-N, move number or evaluation that is not',
        "in the engine facts for that moment. A plain chatbot can occasionally suggest a reasonable move the engine",
        "didn't list, so the stricter row is the one about moves that are not legal on the board at all.",
        "By construction, nothing unconfirmed reaches a student in Second: failed notes are retried, then replaced by a template.",
        "",
        "Every note and score is in `results.json`.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rescore(path: Path) -> None:
    """Re-check saved notes with the current verifier, without calling the model again."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for record in data["records"]:
        for condition in CONDITIONS:
            entry = record[condition]
            if "note" in entry:
                entry["score"] = score(entry["note"], record["moment"])
    data["summary"] = summarise(data["records"])
    data["meta"]["rescored"] = time.strftime("%Y-%m-%d")
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    write_markdown(data["summary"], data["meta"], HERE / "RESULTS.md", data["records"])
    print(json.dumps(data["summary"], indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=Path, default=HERE / "games.pgn")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--per-side", type=int, default=1)
    parser.add_argument("--hardware", default="laptop CPU")
    parser.add_argument("--rescore", action="store_true", help="re-check results.json with the current verifier")
    args = parser.parse_args()
    if args.rescore:
        rescore(HERE / "results.json")
        return

    settings = load_settings()
    text = args.games.read_text(encoding="utf-8")
    stream, games = io.StringIO(text), []
    while (game := chess.pgn.read_game(stream)) is not None:
        games.append(game)

    started = time.perf_counter()
    print("Analysing games with Stockfish...", flush=True)
    with Analyzer(settings.stockfish_path, depth=settings.engine_depth, threads=settings.engine_threads) as engine:
        engine_name = engine.name
        moments = collect_moments(games, engine, args.per_side, args.limit)

    client = Recorder(make_client(settings))
    system = system_prompt("beginner")
    records = []
    for index, (number, game, moment) in enumerate(moments, 1):
        record = {"game": number, "site": game.headers.get("Site"), "moment": moment}
        client.log.clear()
        try:
            note = client.chat_json(RAW_SYSTEM, raw_prompt(game, moment), MOMENT_SCHEMA)
            record["raw"] = {"note": note, "seconds": client.log[-1]["seconds"], "score": score(note, moment)}
        except LLMError as exc:
            record["raw"] = {"error": str(exc)}

        client.log.clear()
        result = write_note(
            client,
            system,
            moment_prompt(moment),
            MOMENT_SCHEMA,
            lambda data, m=moment: verify_moment(data, m),
            lambda m=moment: fallback.moment_note(m),
        )
        first = client.log[0] if client.log else {}
        if "data" in first:
            record["grounded"] = {
                "note": first["data"],
                "seconds": first["seconds"],
                "score": score(first["data"], moment),
            }
        else:
            record["grounded"] = {"error": first.get("error", "no reply")}
        record["second"] = {
            "note": result["note"],
            "source": result["source"],
            "attempts": result["attempts"],
            "caught": result["caught"],
            "seconds": sum(entry["seconds"] for entry in client.log),
            "score": score(result["note"], moment),
        }
        records.append(record)
        s = record["second"]
        print(
            f"[{index}/{len(moments)}] {moment['label']:<14} raw: {len(record['raw'].get('score', {}).get('unconfirmed', []))} unconfirmed"
            f" | grounded: {len(record['grounded'].get('score', {}).get('unconfirmed', []))}"
            f" | second: {s['source']} after {s['attempts']} tries ({s['seconds']:.0f}s)",
            flush=True,
        )
        (HERE / "results.json").write_text(
            json.dumps({"records": records}, indent=1, ensure_ascii=False), encoding="utf-8"
        )

    summary = summarise(records)
    meta = {
        "model": client.label,
        "engine": f"{engine_name}, depth {settings.engine_depth}",
        "games": len({r["game"] for r in records}),
        "hardware": args.hardware,
        "date": time.strftime("%Y-%m-%d"),
        "minutes": round((time.perf_counter() - started) / 60, 1),
    }
    (HERE / "results.json").write_text(
        json.dumps({"meta": meta, "summary": summary, "records": records}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    write_markdown(summary, meta, HERE / "RESULTS.md", records)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
