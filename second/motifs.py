"""Small, deterministic tactical detectors. Everything here can be checked by code."""

from __future__ import annotations

import chess
import chess.pgn

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
PIECE_NAME = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}
STARTING_MINORS = {
    chess.WHITE: {chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT, chess.C1: chess.BISHOP, chess.F1: chess.BISHOP},
    chess.BLACK: {chess.B8: chess.KNIGHT, chess.G8: chess.KNIGHT, chess.C8: chess.BISHOP, chess.F8: chess.BISHOP},
}


def color_name(color: chess.Color) -> str:
    return "White" if color == chess.WHITE else "Black"


def material(board: chess.Board, color: chess.Color) -> int:
    return sum(len(board.pieces(piece_type, color)) * value for piece_type, value in PIECE_VALUE.items())


def material_balance(board: chess.Board, color: chess.Color) -> int:
    return material(board, color) - material(board, not color)


def captured_piece_type(board: chess.Board, move: chess.Move) -> int | None:
    if board.is_en_passant(move):
        return chess.PAWN
    piece = board.piece_at(move.to_square)
    if piece is None or piece.color == board.turn:
        return None
    return piece.piece_type


def hanging_pieces(board: chess.Board, color: chess.Color) -> list[dict]:
    """Pieces of `color` that the side to move can win right now.

    Only meaningful when it is the opponent's turn, so captures are legal moves.
    A piece counts as hanging if it can be captured and is either undefended or
    can be taken by a cheaper piece.
    """
    if board.turn == color:
        return []
    found = []
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        capturers = [m.from_square for m in board.legal_moves if m.to_square == square]
        if not capturers:
            continue
        defended = bool(board.attackers(color, square))
        cheapest = min(capturers, key=lambda sq: PIECE_VALUE[board.piece_type_at(sq)] or 50)
        cheapest_type = board.piece_type_at(cheapest)
        if defended and PIECE_VALUE[cheapest_type] >= PIECE_VALUE[piece.piece_type]:
            continue
        found.append(
            {
                "square": chess.square_name(square),
                "piece": PIECE_NAME[piece.piece_type],
                "value": PIECE_VALUE[piece.piece_type],
                "defended": defended,
                "attacker": PIECE_NAME[cheapest_type],
                "attacker_square": chess.square_name(cheapest),
            }
        )
    return sorted(found, key=lambda item: -item["value"])


def attacked_targets(board: chess.Board, square: chess.Square) -> list[dict]:
    """Enemy pieces worth attacking that the piece on `square` hits."""
    piece = board.piece_at(square)
    if piece is None:
        return []
    targets = []
    for target in board.attacks(square):
        victim = board.piece_at(target)
        if victim is None or victim.color == piece.color:
            continue
        undefended = not board.attackers(victim.color, target)
        valuable = PIECE_VALUE[victim.piece_type] > PIECE_VALUE[piece.piece_type]
        if victim.piece_type == chess.KING or valuable or (undefended and PIECE_VALUE[victim.piece_type] >= 3):
            targets.append(
                {
                    "square": chess.square_name(target),
                    "piece": PIECE_NAME[victim.piece_type],
                    "value": 100 if victim.piece_type == chess.KING else PIECE_VALUE[victim.piece_type],
                }
            )
    return sorted(targets, key=lambda item: -item["value"])


def fork_targets(board: chess.Board, square: chess.Square) -> list[dict]:
    targets = attacked_targets(board, square)
    return targets if len(targets) >= 2 else []


def is_back_rank_mate(board: chess.Board) -> bool:
    if not board.is_checkmate():
        return False
    king = board.king(board.turn)
    back_rank = 0 if board.turn == chess.WHITE else 7
    if king is None or chess.square_rank(king) != back_rank:
        return False
    return any(
        board.piece_type_at(sq) in (chess.ROOK, chess.QUEEN) and chess.square_rank(sq) == back_rank
        for sq in board.checkers()
    )


def play_line(board: chess.Board, line: list[chess.Move], max_plies: int) -> tuple[chess.Board, list[str]]:
    """Play up to `max_plies` legal moves of `line`; return the board and the SAN list."""
    board = board.copy()
    sans: list[str] = []
    for move in line[:max_plies]:
        if move not in board.legal_moves:
            break
        sans.append(board.san(move))
        board.push(move)
    return board, sans


def material_swing(board: chess.Board, line: list[chess.Move], color: chess.Color, max_plies: int = 8) -> int:
    """How much `color`'s material balance changes along `line`.

    Stops at the last point (within `max_plies`) where the line's next move is not a
    capture, so an exchange is never cut in half.
    """
    start = material_balance(board, color)
    work = board.copy()
    balances = [start]
    is_capture: list[bool] = []
    for move in line[:max_plies]:
        if move not in work.legal_moves:
            break
        is_capture.append(work.is_capture(move))
        work.push(move)
        balances.append(material_balance(work, color))
    played = len(is_capture)
    if played == 0:
        return 0

    def quiet_after(plies: int) -> bool:
        if plies < played:
            return not is_capture[plies]
        if plies < len(line) and line[plies] in work.legal_moves:
            return not work.is_capture(line[plies])
        return True

    for plies in range(played, -1, -1):
        if quiet_after(plies):
            return balances[plies] - start
    return 0  # every visible move is a capture: claim nothing rather than half an exchange


def opening_habits(game: chess.pgn.Game, color: chess.Color) -> dict:
    """Simple, checkable opening habits for the student's side."""
    board = game.board()
    if board.board_fen() != chess.Board().board_fen():
        return {}
    castled_on = None
    early_queen_moves = 0
    developed = None
    last_number = 1
    for move in game.mainline_moves():
        mover, number = board.turn, board.fullmove_number
        if mover == color:
            if board.is_castling(move) and castled_on is None:
                castled_on = number
            if board.piece_type_at(move.from_square) == chess.QUEEN and number <= 8:
                early_queen_moves += 1
        board.push(move)
        last_number = number
        if mover == color and number == 10 and developed is None:
            developed = _developed_minors(board, color)
    if developed is None:
        developed = _developed_minors(board, color)
    return {
        "castled_on_move": castled_on,
        "early_queen_moves": early_queen_moves,
        "minors_developed_by_move_10": developed,
        "moves_played": last_number,
    }


def _developed_minors(board: chess.Board, color: chess.Color) -> int:
    return sum(
        1
        for square, piece_type in STARTING_MINORS[color].items()
        if board.piece_type_at(square) != piece_type or board.color_at(square) != color
    )


def habit_sentences(habits: dict) -> list[str]:
    if not habits:
        return []
    sentences = []
    if habits.get("castled_on_move"):
        sentences.append(f"The student castled on move {habits['castled_on_move']}.")
    elif habits.get("moves_played", 0) >= 15:
        sentences.append("The student never castled.")
    if habits.get("early_queen_moves", 0) >= 2:
        sentences.append(f"The student moved the queen {habits['early_queen_moves']} times in the first 8 moves.")
    if habits.get("moves_played", 0) >= 10:
        sentences.append(
            f"The student developed {habits['minors_developed_by_move_10']} of 4 knights and bishops by move 10."
        )
    return sentences
