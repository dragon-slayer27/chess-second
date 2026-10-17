"""Build the evaluation set: club-level games from the CC0 Lichess database.

Usage:
    python eval/build_dataset.py path/to/lichess_db_standard_rated_2013-01.pgn.zst

The Lichess database (https://database.lichess.org) is released under CC0.
Player names are replaced by "White"/"Black"; the Site header keeps a link to the original game.
"""

from __future__ import annotations

import argparse
import io
import random
from pathlib import Path

import chess.pgn
import zstandard

HERE = Path(__file__).parent


def candidates(path: Path, scan: int):
    with path.open("rb") as raw:
        reader = zstandard.ZstdDecompressor().stream_reader(raw)
        text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
        for _ in range(scan):
            game = chess.pgn.read_game(text)
            if game is None:
                return
            h = game.headers
            if h.get("Variant", "Standard") != "Standard" or h.get("Termination") != "Normal":
                continue
            if not any(kind in h.get("Event", "") for kind in ("Blitz", "Classical")):
                continue
            try:
                white, black = int(h.get("WhiteElo", "0")), int(h.get("BlackElo", "0"))
            except ValueError:
                continue
            if not (1000 <= white <= 1700 and 1000 <= black <= 1700):
                continue
            moves = sum(1 for _ in game.mainline_moves())
            if not 40 <= moves <= 110:
                continue
            yield game


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--games", type=int, default=16)
    parser.add_argument("--scan", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=HERE / "games.pgn")
    args = parser.parse_args()

    pool = list(candidates(args.database, args.scan))
    random.Random(args.seed).shuffle(pool)
    chosen = pool[: args.games]
    with args.out.open("w", encoding="utf-8") as out:
        for game in chosen:
            game.headers["White"] = "White"
            game.headers["Black"] = "Black"
            print(game, file=out, end="\n\n")
    print(f"{len(pool)} candidates, wrote {len(chosen)} games to {args.out}")


if __name__ == "__main__":
    main()
