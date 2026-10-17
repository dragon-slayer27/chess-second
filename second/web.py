"""FastAPI web app: paste games, watch the progress, read the review."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import chess
import chess.pgn
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .games import (
    GameSourceError,
    fetch_chesscom_user_games,
    fetch_lichess_game,
    fetch_lichess_user_games,
    parse_pgn,
    player_color,
)
from .llm import LLMError, make_client
from .prompts import LEVELS
from .report import STATIC_DIR, render, render_standalone
from .review import review_game
from .store import ReviewStore

log = logging.getLogger("second")
settings = load_settings()
store = ReviewStore(settings.data_dir)
samples = ReviewStore(settings.samples_dir, read_only=True)
app = FastAPI(title="Second", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
executor = ThreadPoolExecutor(max_workers=1)

MAX_PGN_CHARS = 200_000
DEMO_JOBS_PER_HOUR = 6
DEMO_MAX_QUEUE = 3
SOURCES = {"pgn", "file", "lichess_game", "lichess_user", "chesscom_user"}


@dataclass
class Job:
    id: str
    status: str = "queued"
    message: str = "Waiting for the review before this one to finish"
    fraction: float = 0.0
    review_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()
recent_by_ip: dict[str, deque] = {}


def page(template: str, **context) -> HTMLResponse:
    return HTMLResponse(render(template, public_demo=settings.public_demo, **context))


def error_page(message: str, status: int = 400) -> HTMLResponse:
    response = page("error.html", message=message)
    response.status_code = status
    return response


def _rate_limited(ip: str) -> bool:
    now = time.time()
    history = recent_by_ip.setdefault(ip, deque())
    while history and now - history[0] > 3600:
        history.popleft()
    if len(history) >= DEMO_JOBS_PER_HOUR:
        return True
    history.append(now)
    return False


def _active_jobs() -> int:
    with jobs_lock:
        return sum(1 for job in jobs.values() if job.status in ("queued", "running"))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    recent = [] if settings.public_demo else store.list(6)
    return page("index.html", recent=recent, levels=list(LEVELS), settings=settings)


@app.get("/api/status")
def status() -> JSONResponse:
    result = {"stockfish": bool(settings.stockfish_path), "public_demo": settings.public_demo}
    try:
        client = make_client(settings)
        result["model"] = client.check()
        result["model_ok"] = True
    except LLMError as exc:
        result["model"] = str(exc)
        result["model_ok"] = False
    return JSONResponse(result)


@app.post("/review")
async def start_review(request: Request) -> Response:
    form = await request.form()

    def text(key: str, default: str = "") -> str:
        value = form.get(key)
        return value.strip() if isinstance(value, str) else default

    source = text("source", "pgn")
    if source not in SOURCES:
        return error_page("Pick where the games come from.")
    file_text = ""
    upload = form.get("pgn_file")
    if source == "file" and upload is not None and hasattr(upload, "read"):
        file_text = (await upload.read())[: MAX_PGN_CHARS * 2].decode("utf-8", errors="replace")
    try:
        games_limit = max(1, min(int(text("games", "1") or 1), settings.max_games))
    except ValueError:
        games_limit = 1
    level = text("level", "beginner")
    params = {
        "source": source,
        "pgn_text": text("pgn_text"),
        "file_text": file_text,
        "lichess_url": text("lichess_url"),
        "lichess_user": text("lichess_user"),
        "chesscom_user": text("chesscom_user"),
        "games_limit": games_limit,
        "student_name": text("student_name")[:60],
        "student_color": text("student_color", "auto"),
        "level": level if level in LEVELS else "beginner",
        "language": (text("language", "English") or "English")[:30],
    }
    if settings.public_demo:
        ip = request.client.host if request.client else "unknown"
        if _active_jobs() >= DEMO_MAX_QUEUE:
            return error_page("The public demo is busy right now. Please try again in a minute.", 429)
        if _rate_limited(ip):
            return error_page(
                "You've reached the demo limit for this hour. Run Second locally for unlimited reviews.", 429
            )
    job = Job(id=uuid.uuid4().hex[:12])
    with jobs_lock:
        jobs[job.id] = job
    executor.submit(run_job, job, params)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


def load_source(params: dict) -> str:
    source, limit = params["source"], params["games_limit"]
    if source == "lichess_game":
        return fetch_lichess_game(params["lichess_url"])
    if source == "lichess_user":
        params["username"] = params["lichess_user"]
        return fetch_lichess_user_games(params["lichess_user"], limit)
    if source == "chesscom_user":
        params["username"] = params["chesscom_user"]
        return fetch_chesscom_user_games(params["chesscom_user"], limit)
    pgn = params["file_text"] if source == "file" else params["pgn_text"]
    if not pgn.strip():
        raise GameSourceError("Paste a PGN, upload a .pgn file, or give a game link.")
    if len(pgn) > MAX_PGN_CHARS:
        raise GameSourceError("That PGN is too long. Try fewer games at once.")
    return pgn


def resolve_color(game: chess.pgn.Game, params: dict) -> chess.Color:
    choice = params["student_color"]
    if choice == "white":
        return chess.WHITE
    if choice == "black":
        return chess.BLACK
    for name in (params.get("username"), params.get("student_name")):
        if name:
            color = player_color(game, name)
            if color is not None:
                return color
    raise GameSourceError("I couldn't tell which side the student played. Choose White or Black in the form.")


def run_job(job: Job, params: dict) -> None:
    job.status = "running"
    job.message = "Loading the games"
    try:
        games = parse_pgn(load_source(params), limit=params["games_limit"])
        if not games:
            raise GameSourceError("I couldn't find any games in that PGN.")
        llm = make_client(settings)
        total = len(games)
        for number, game in enumerate(games, 1):
            color = resolve_color(game, params)

            def progress(message: str, fraction: float, number: int = number) -> None:
                prefix = f"Game {number} of {total}: " if total > 1 else ""
                job.message = prefix + message
                job.fraction = ((number - 1) + fraction) / total

            review = review_game(
                game,
                settings=settings,
                llm=llm,
                color=color,
                student_name=params["student_name"],
                level=params["level"],
                language=params["language"],
                progress=progress,
            )
            if settings.public_demo:
                review["public_demo"] = True
            store.save(review)
            job.review_ids.append(review["id"])
        job.status, job.fraction, job.message = "done", 1.0, "Done"
    except (GameSourceError, LLMError, FileNotFoundError) as exc:
        job.status, job.message = "error", str(exc)
        job.errors.append(str(exc))
    except httpx.HTTPError as exc:
        job.status, job.message = "error", "Couldn't download the games. Check the link or username and try again."
        job.errors.append(f"{exc.__class__.__name__}: {exc}")
    except Exception:
        log.exception("review job %s failed", job.id)
        job.status, job.message = "error", "Something went wrong while reviewing. Please try another game."
        job.errors.append(job.message)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str) -> HTMLResponse:
    job = jobs.get(job_id)
    if job is None:
        return error_page("That review job doesn't exist (the server may have restarted).", 404)
    return page("job.html", job=job)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404)
    return JSONResponse(
        {
            "status": job.status,
            "message": job.message,
            "fraction": round(job.fraction, 3),
            "review_ids": job.review_ids,
            "errors": job.errors,
        }
    )


def _find(review_id: str) -> dict:
    review = store.load(review_id) or samples.load(review_id)
    if review is None:
        raise HTTPException(404)
    return review


@app.get("/reviews", response_class=HTMLResponse)
def reviews_page() -> HTMLResponse:
    if settings.public_demo:
        return RedirectResponse("/samples", status_code=303)
    return page("list.html", reviews=store.list(200), heading="Your reviews", empty="No reviews yet.")


@app.get("/reviews/{review_id}", response_class=HTMLResponse)
def review_page(review_id: str) -> HTMLResponse:
    return page("review.html", review=_find(review_id))


@app.get("/reviews/{review_id}/pgn")
def review_pgn(review_id: str) -> Response:
    review = _find(review_id)
    return Response(
        review["annotated_pgn"],
        media_type="application/x-chess-pgn",
        headers={"Content-Disposition": f'attachment; filename="second-{review_id}.pgn"'},
    )


@app.get("/reviews/{review_id}/download")
def review_download(review_id: str) -> HTMLResponse:
    review = _find(review_id)
    return HTMLResponse(
        render_standalone(review),
        headers={"Content-Disposition": f'attachment; filename="second-{review_id}.html"'},
    )


@app.get("/samples", response_class=HTMLResponse)
def samples_page() -> HTMLResponse:
    return page(
        "list.html",
        reviews=samples.list(50, newest_first=False),
        heading="Sample reviews",
        intro="Real games from the open Lichess database, reviewed by Stockfish and Gemma 4 running on a laptop.",
        empty="No samples yet.",
    )


@app.get("/about", response_class=HTMLResponse)
def about_page() -> HTMLResponse:
    return page("about.html", settings=settings)


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "stockfish": bool(settings.stockfish_path), "public_demo": settings.public_demo})
