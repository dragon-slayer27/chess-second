import chess

from conftest import SCHOLARS_MATE, read
from second.motifs import (
    fork_targets,
    habit_sentences,
    hanging_pieces,
    is_back_rank_mate,
    material_swing,
    opening_habits,
)


def test_undefended_piece_is_hanging():
    board = chess.Board("4k3/8/8/3n4/8/8/8/3QK3 w - - 0 1")
    hanging = hanging_pieces(board, chess.BLACK)
    assert hanging == [
        {
            "square": "d5",
            "piece": "knight",
            "value": 3,
            "defended": False,
            "attacker": "queen",
            "attacker_square": "d1",
        }
    ]


def test_defended_pawn_attacked_by_queen_is_not_hanging():
    board = chess.Board("4k3/5p2/8/7Q/8/8/8/4K3 w - - 0 1")
    assert hanging_pieces(board, chess.BLACK) == []


def test_only_checks_the_side_that_is_not_to_move():
    board = chess.Board("4k3/8/8/3n4/8/8/8/3QK3 w - - 0 1")
    assert hanging_pieces(board, chess.WHITE) == []


def test_knight_fork_on_king_and_rook():
    board = chess.Board("r3k3/2N5/8/8/8/8/8/4K3 b - - 0 1")
    targets = fork_targets(board, chess.C7)
    assert [t["piece"] for t in targets] == ["king", "rook"]


def test_single_target_is_not_a_fork():
    board = chess.Board("4k3/2N5/8/8/8/8/8/4K3 b - - 0 1")
    assert fork_targets(board, chess.C7) == []


def test_back_rank_mate():
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    board.push_san("Ra8#")
    assert is_back_rank_mate(board)


def test_ordinary_mate_is_not_back_rank():
    board = chess.Board()
    for san in ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]:
        board.push_san(san)
    assert board.is_checkmate()
    assert not is_back_rank_mate(board)


def test_material_swing_counts_the_recapture():
    board = chess.Board("4k3/8/4p3/3n4/8/8/8/3QK3 w - - 0 1")
    line = [board.parse_san("Qxd5")]
    after = board.copy()
    after.push(line[0])
    line.append(after.parse_san("exd5"))
    assert material_swing(board, line, chess.WHITE) == -6


def test_material_swing_does_not_stop_mid_exchange():
    board = chess.Board("4k3/8/4p3/3n4/8/8/8/3QK3 w - - 0 1")
    qxd5 = board.parse_san("Qxd5")
    after = board.copy()
    after.push(qxd5)
    exd5 = after.parse_san("exd5")
    assert material_swing(board, [qxd5, exd5], chess.WHITE, max_plies=1) == 0


def test_opening_habits_for_scholars_mate():
    habits = opening_habits(read(SCHOLARS_MATE), chess.WHITE)
    assert habits["castled_on_move"] is None
    assert habits["early_queen_moves"] == 2
    assert habits["minors_developed_by_move_10"] == 1
    assert "The student moved the queen 2 times in the first 8 moves." in habit_sentences(habits)
