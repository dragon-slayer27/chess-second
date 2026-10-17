import io

import chess
import chess.pgn
import pytest

from second.config import find_stockfish
from second.engine import Analyzer

STOCKFISH = find_stockfish()
needs_stockfish = pytest.mark.skipif(STOCKFISH is None, reason="Stockfish is not installed")

SCHOLARS_MATE = """[White "Aarav"]
[Black "Riya"]
[Result "1-0"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0
"""

FRIED_LIVER = """[White "Kabir"]
[Black "Meera"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 5. exd5 Nxd5 6. Nxf7 Kxf7 7. Qf3+ Ke6
8. Nc3 Ncb4 9. a3 Nxc2+ 10. Kd1 Nxa1 11. Nxd5 Kd6 *
"""


def read(pgn: str) -> chess.pgn.Game:
    return chess.pgn.read_game(io.StringIO(pgn))


@pytest.fixture(scope="session")
def analyzer():
    if STOCKFISH is None:
        pytest.skip("Stockfish is not installed")
    with Analyzer(STOCKFISH, depth=10, threads=1, hash_mb=16, max_time=1.0) as engine:
        yield engine
