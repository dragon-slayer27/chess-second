"""Rendering: board diagrams, the evaluation graph, annotated PGN and HTML pages."""

from __future__ import annotations

from pathlib import Path

import chess
import chess.pgn
import chess.svg
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
ARROW_COLORS = {"played": "#d64545cc", "best": "#2e9e5bd9", "threat": "#f08c00d9"}
NAGS = {
    "blunder": chess.pgn.NAG_BLUNDER,
    "mistake": chess.pgn.NAG_MISTAKE,
    "inaccuracy": chess.pgn.NAG_DUBIOUS_MOVE,
}
REPO_URL = "https://github.com/dragon-slayer27/chess-second"


def _arrow(uci: str, kind: str) -> chess.svg.Arrow:
    move = chess.Move.from_uci(uci)
    return chess.svg.Arrow(move.from_square, move.to_square, color=ARROW_COLORS[kind])


def _orientation(moment: dict) -> chess.Color:
    return chess.WHITE if moment["color"] == "white" else chess.BLACK


def board_before_svg(moment: dict, size: int = 300) -> Markup:
    board = chess.Board(moment["fen_before"])
    arrows = [_arrow(moment["played_uci"], "best" if moment["kind"] == "good" else "played")]
    if moment["kind"] != "good" and moment.get("best_uci"):
        arrows.append(_arrow(moment["best_uci"], "best"))
    svg = chess.svg.board(board, arrows=arrows, orientation=_orientation(moment), size=size)
    return Markup(svg)


def board_after_svg(moment: dict, size: int = 300) -> Markup | None:
    if moment["kind"] == "good" or not moment.get("reply_uci"):
        return None
    board = chess.Board(moment["fen_after"])
    fill = {chess.parse_square(square): "#f2c94c99" for square in moment.get("highlight", [])}
    svg = chess.svg.board(
        board,
        lastmove=chess.Move.from_uci(moment["played_uci"]),
        arrows=[_arrow(moment["reply_uci"], "threat")],
        fill=fill,
        check=board.king(board.turn) if board.is_check() else None,
        orientation=_orientation(moment),
        size=size,
    )
    return Markup(svg)


def eval_graph_svg(review: dict, width: int = 900, height: int = 110) -> Markup:
    """Area chart of the student's winning chances, with the key moments marked."""
    series = review.get("win_series") or []
    if len(series) < 2:
        return Markup("")
    step = width / (len(series) - 1)
    points = [(i * step, height - value / 100 * height) for i, value in enumerate(series)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    marks = []
    for moment in review.get("moments", []):
        index = moment["ply"] + 1
        if index < len(points):
            x, y = points[index]
            marks.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="mark-bad"><title>{moment["label"]}</title></circle>'
            )
    good = review.get("good_moment")
    if good and good["ply"] + 1 < len(points):
        x, y = points[good["ply"] + 1]
        marks.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="mark-good"><title>{good["label"]}</title></circle>'
        )
    svg = (
        f'<svg viewBox="0 0 {width} {height}" class="graph" role="img" '
        f'aria-label="The student\'s winning chances during the game">'
        f'<line x1="0" y1="{height / 2}" x2="{width}" y2="{height / 2}" class="mid"/>'
        f'<polygon points="0,{height} {line} {width},{height}" class="area"/>'
        f'<polyline points="{line}" class="line"/>{"".join(marks)}</svg>'
    )
    return Markup(svg)


def annotated_pgn(game: chess.pgn.Game, review: dict) -> str:
    """The game with Second's notes as PGN comments and the better moves as variations."""
    by_ply = {moment["ply"]: moment for moment in review.get("moments", [])}
    good = review.get("good_moment")
    if good:
        by_ply.setdefault(good["ply"], good)
    out = chess.pgn.Game()
    for key, value in game.headers.items():
        out.headers[key] = value
    out.headers["Annotator"] = "Second (Stockfish + Gemma)"
    start = game.board()
    if start.fen() != chess.STARTING_FEN:
        out.setup(start)
    node: chess.pgn.GameNode = out
    for ply, move in enumerate(game.mainline_moves()):
        parent = node
        node = parent.add_variation(move)
        moment = by_ply.get(ply)
        if not moment:
            continue
        note = moment.get("note") or {}
        if moment["kind"] == "good":
            node.nags.add(chess.pgn.NAG_GOOD_MOVE)
        elif moment.get("judgement") in NAGS:
            node.nags.add(NAGS[moment["judgement"]])
        node.comment = " ".join(part for part in (note.get("headline"), note.get("explanation")) if part)
        if moment["kind"] != "good" and moment.get("best_uci"):
            board = parent.board()
            best = chess.Move.from_uci(moment["best_uci"])
            if best in board.legal_moves:
                variation = parent.add_variation(best)
                board.push(best)
                for san in moment.get("best_line", [])[1:6]:
                    try:
                        follow = board.parse_san(san)
                    except ValueError:
                        break
                    variation = variation.add_variation(follow)
                    board.push(follow)
    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return out.accept(exporter)


def fmt_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(round(seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


_ENV: Environment | None = None


def environment() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
        _ENV.globals.update(
            board_before_svg=board_before_svg,
            board_after_svg=board_after_svg,
            eval_graph_svg=eval_graph_svg,
            fmt_seconds=fmt_seconds,
            repo_url=REPO_URL,
        )
    return _ENV


def render(template: str, **context) -> str:
    context.setdefault("standalone", False)
    return environment().get_template(template).render(**context)


def render_standalone(review: dict) -> str:
    """A single self-contained HTML file a coach can save, print or send to a parent."""
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    return render("review.html", review=review, standalone=True, inline_css=Markup(css))
