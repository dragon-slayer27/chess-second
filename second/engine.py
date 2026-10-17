"""Stockfish analysis: per-move evaluations, win chances and judgements."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import chess
import chess.engine
import chess.pgn

MATE_CP = 1000

# Lichess flags a move when the mover's winning chances (on a -1..1 scale) drop by
# 0.1 / 0.2 / 0.3. On the 0-100 win% scale used here that is 5 / 10 / 15 points.
JUDGEMENT_THRESHOLDS = ((15.0, "blunder"), (10.0, "mistake"), (5.0, "inaccuracy"))


def score_to_cp(score: chess.engine.Score) -> int:
    if score.is_mate():
        mate = score.mate()
        winning = (mate is not None and mate > 0) or score == chess.engine.MateGiven
        return MATE_CP if winning else -MATE_CP
    cp = score.score() or 0
    return max(-MATE_CP, min(MATE_CP, cp))


def win_percent(cp: int) -> float:
    """Lichess's centipawn -> win% curve."""
    cp = max(-MATE_CP, min(MATE_CP, cp))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def move_accuracy(win_before: float, win_after: float) -> float:
    """Lichess's per-move accuracy formula."""
    drop = max(0.0, win_before - win_after)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


def judge(win_drop: float) -> str | None:
    for threshold, label in JUDGEMENT_THRESHOLDS:
        if win_drop >= threshold:
            return label
    return None


@dataclass
class Line:
    score: chess.engine.Score  # relative to the side to move
    pv: list[chess.Move]

    @property
    def cp(self) -> int:
        return score_to_cp(self.score)

    @property
    def mate(self) -> int | None:
        return self.score.mate() if self.score.is_mate() else None


@dataclass
class PositionEval:
    lines: list[Line]
    terminal: str | None = None  # "checkmate", "stalemate" or "draw"

    @property
    def best(self) -> Line | None:
        return self.lines[0] if self.lines else None

    @property
    def cp(self) -> int:
        """Score for the side to move, capped at +-MATE_CP."""
        if self.terminal == "checkmate":
            return -MATE_CP
        if self.terminal is not None or not self.lines:
            return 0
        return self.lines[0].cp


@dataclass
class MoveEval:
    ply: int
    move_number: int
    color: chess.Color
    move: chess.Move
    san: str
    board_before: chess.Board
    before: PositionEval
    after: PositionEval
    cp_before: int
    cp_after: int
    win_before: float
    win_after: float
    accuracy: float
    judgement: str | None
    best_move: chess.Move | None
    best_pv: list[chess.Move] = field(default_factory=list)
    second_cp: int | None = None
    mate_before: int | None = None  # >0: the mover could force mate in n; <0: the mover was getting mated
    mate_after: int | None = None  # the same, after the move, still from the mover's point of view
    delivered_mate: bool = False

    @property
    def win_drop(self) -> float:
        return self.win_before - self.win_after

    @property
    def is_best(self) -> bool:
        return self.best_move is not None and self.move == self.best_move

    @property
    def board_after(self) -> chess.Board:
        board = self.board_before.copy()
        board.push(self.move)
        return board

    @property
    def label(self) -> str:
        dots = "." if self.color == chess.WHITE else "..."
        return f"{self.move_number}{dots} {self.san}"

    @property
    def missed_mate(self) -> bool:
        if self.mate_before is None or not 0 < self.mate_before <= 3 or self.delivered_mate:
            return False
        return not (self.mate_after is not None and self.mate_after > 0)


@dataclass
class GameAnalysis:
    moves: list[MoveEval]
    engine_name: str
    depth: int
    seconds: float

    def accuracy(self, color: chess.Color) -> float | None:
        values = [m.accuracy for m in self.moves if m.color == color]
        return round(sum(values) / len(values), 1) if values else None

    def counts(self, color: chess.Color) -> dict[str, int]:
        counts = {"blunder": 0, "mistake": 0, "inaccuracy": 0}
        for move in self.moves:
            if move.color == color and move.judgement:
                counts[move.judgement] += 1
        return counts


class Analyzer:
    """Runs Stockfish over every position of a game."""

    def __init__(
        self,
        stockfish_path: str | None,
        depth: int = 14,
        threads: int = 2,
        hash_mb: int = 64,
        max_time: float = 1.0,
        multipv: int = 2,
    ):
        if not stockfish_path:
            raise FileNotFoundError("Stockfish not found. Install it, put it in ./bin or set STOCKFISH_PATH.")
        self.path = stockfish_path
        self.depth = depth
        self.threads = threads
        self.hash_mb = hash_mb
        self.max_time = max_time
        self.multipv = multipv
        self.engine: chess.engine.SimpleEngine | None = None
        self.name = "Stockfish"

    def __enter__(self) -> Analyzer:
        self.engine = chess.engine.SimpleEngine.popen_uci(self.path)
        self.engine.configure({"Threads": self.threads, "Hash": self.hash_mb})
        self.name = self.engine.id.get("name", "Stockfish")
        return self

    def __exit__(self, *exc) -> None:
        if self.engine is not None:
            self.engine.quit()
            self.engine = None

    def evaluate(self, board: chess.Board) -> PositionEval:
        if board.is_checkmate():
            return PositionEval([], "checkmate")
        if board.is_game_over(claim_draw=False):
            return PositionEval([], "stalemate" if board.is_stalemate() else "draw")
        assert self.engine is not None, "use Analyzer as a context manager"
        infos = self.engine.analyse(
            board,
            chess.engine.Limit(depth=self.depth, time=self.max_time),
            multipv=self.multipv,
        )
        lines = [Line(info["score"].relative, list(info.get("pv", []))) for info in infos if "score" in info]
        return PositionEval(lines)

    def analyse_game(
        self,
        game: chess.pgn.Game,
        progress: Callable[[int, int], None] | None = None,
    ) -> GameAnalysis:
        start = time.perf_counter()
        board = game.board()
        moves = list(game.mainline_moves())
        boards = [board.copy()]
        evals = [self.evaluate(board)]
        for index, move in enumerate(moves, 1):
            board.push(move)
            boards.append(board.copy())
            evals.append(self.evaluate(board))
            if progress:
                progress(index, len(moves))

        results: list[MoveEval] = []
        for index, move in enumerate(moves):
            before_board = boards[index]
            before, after = evals[index], evals[index + 1]
            cp_before = before.cp
            cp_after = -after.cp
            win_before, win_after = win_percent(cp_before), win_percent(cp_after)
            best = before.best
            best_move = best.pv[0] if best and best.pv else None
            delivered = after.terminal == "checkmate"
            mate_after = -after.best.mate if after.best and after.best.mate is not None else None
            judgement = None
            if not delivered and move != best_move:
                judgement = judge(win_before - win_after)
            results.append(
                MoveEval(
                    ply=index,
                    move_number=before_board.fullmove_number,
                    color=before_board.turn,
                    move=move,
                    san=before_board.san(move),
                    board_before=before_board,
                    before=before,
                    after=after,
                    cp_before=cp_before,
                    cp_after=cp_after,
                    win_before=win_before,
                    win_after=win_after,
                    accuracy=move_accuracy(win_before, win_after),
                    judgement=judgement,
                    best_move=best_move,
                    best_pv=list(best.pv) if best else [],
                    second_cp=before.lines[1].cp if len(before.lines) > 1 else None,
                    mate_before=best.mate if best else None,
                    mate_after=mate_after,
                    delivered_mate=delivered,
                )
            )
        return GameAnalysis(results, self.name, self.depth, time.perf_counter() - start)
