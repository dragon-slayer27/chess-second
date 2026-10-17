"""Generate the sample reviews shown on /samples and in the public demo.

    python scripts/make_samples.py

Uses whatever model the environment points at (by default Gemma 4 E4B in a local Ollama).
The Lichess games come from eval/games.pgn (CC0); the student names are made up.
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

FRIED_LIVER = """[Event "Club rapid"]
[White "Aarav"]
[Black "Opponent"]
[Result "0-1"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 5. exd5 Nxd5 6. Nxf7 Kxf7 7. Qf3+ Ke6
8. Nc3 Ncb4 9. a3 Nxc2+ 10. Kd1 Nxa1 11. Nxd5 Kd6 12. d4 c6 13. Nc3 exd4
14. Ne4+ Kc7 15. Bf4+ Kb6 16. Qf3 Qe7 17. Re1 Be6 18. Bxe6 Qxe6 19. Nc5 Qd5 0-1
"""

# (sample id, game: "fried-liver" or index into eval/games.pgn, student colour, name, level, parent language, title, blurb)
SAMPLES = [
    (
        "sample-fried-liver",
        "fried-liver",
        chess.WHITE,
        "Aarav",
        "beginner",
        "Hindi",
        "Aarav sacrifices a knight on f7",
        "A beginner's rapid game with a famous attack, a fork on c2 and a note for parents in Hindi.",
    ),
]


def load_eval_games() -> list[chess.pgn.Game]:
    stream = io.StringIO((ROOT / "eval" / "games.pgn").read_text(encoding="utf-8"))
    games = []
    while (game := chess.pgn.read_game(stream)) is not None:
        games.append(game)
    return games


def main() -> None:
    settings = load_settings()
    llm = make_client(settings)
    extra = json.loads((ROOT / "scripts" / "samples.json").read_text(encoding="utf-8"))
    samples = SAMPLES + [
        (
            s["id"],
            s["game"],
            chess.WHITE if s["color"] == "white" else chess.BLACK,
            s["name"],
            s["level"],
            s["language"],
            s["title"],
            s["blurb"],
        )
        for s in extra
    ]
    eval_games = load_eval_games()
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    for sample_id, source, color, name, level, language, title, blurb in samples:
        game = chess.pgn.read_game(io.StringIO(FRIED_LIVER)) if source == "fried-liver" else eval_games[source]
        if source != "fried-liver":
            game.headers["White" if color == chess.WHITE else "Black"] = name
            game.headers["Black" if color == chess.WHITE else "White"] = "Opponent"
        print(f"{sample_id}: reviewing...", flush=True)
        review = review_game(
            game, settings=settings, llm=llm, color=color, student_name=name, level=level, language=language
        )
        review.update({"id": sample_id, "sample_title": title, "sample_blurb": blurb})
        (out / f"{sample_id}.json").write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
        stats = review["stats"]
        print(
            f"  {len(review['moments'])} moments, {stats['template_notes']} template notes, {review['timings']['total_s']}s"
        )


if __name__ == "__main__":
    main()
