"""The review pipeline: Stockfish -> verified facts -> Gemma -> verifier -> review."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime

import chess
import chess.pgn

from . import fallback
from .config import Settings
from .engine import Analyzer, GameAnalysis
from .facts import build_moment, select_good_moment, select_moments
from .llm import LLMError
from .motifs import color_name, habit_sentences, opening_habits
from .prompts import MOMENT_SCHEMA, SUMMARY_SCHEMA, moment_prompt, summary_facts, summary_prompt, system_prompt
from .report import annotated_pgn
from .verify import HALLUCINATION_KINDS, Issue, verify_moment, verify_summary

Progress = Callable[[str, float], None]
MAX_ATTEMPTS = 3
FATAL_ERRORS = (
    "couldn't reach",
    "no language model",
    "quota",
    "not set",
    "was rejected",
    "returned 401",
    "returned 403",
)


def new_review_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


def _feedback(issues: list[Issue]) -> str:
    listed = "; ".join(str(issue) for issue in issues[:6])
    return (
        f"\n\nYour previous answer broke the rules ({listed}). Write it again using only the FACTS above. "
        "Only mention moves, squares and pieces that appear in the FACTS."
    )


def _clean(data: dict, schema: dict) -> dict:
    cleaned = {}
    for key, spec in schema["properties"].items():
        value = data.get(key)
        if spec["type"] == "array":
            items = [value] if isinstance(value, str) else value or []
            cleaned[key] = [str(item).strip() for item in items if str(item).strip()]
        else:
            cleaned[key] = str(value or "").strip()
    return cleaned


def write_note(
    llm,
    system: str,
    prompt: str,
    schema: dict,
    check: Callable[[dict], list[Issue]],
    fallback_note: Callable[[], dict],
) -> dict:
    """Ask the model, verify, retry with feedback, and fall back to a template if needed.

    If the last answer still has problems, only the fields with problems are replaced by the
    template; fields that passed (say, a correct parent note in Hindi) are kept.
    """
    caught: list[str] = []
    hallucinations = 0
    errors: list[str] = []
    feedback = ""
    attempts = 0
    last: tuple[dict, list[Issue]] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            data = llm.chat_json(system, prompt + feedback, schema)
        except LLMError as exc:
            errors.append(str(exc))
            if any(marker in str(exc) for marker in FATAL_ERRORS):
                break
            continue
        issues = check(data)
        if not issues:
            return {
                "note": _clean(data, schema),
                "source": "model",
                "attempts": attempt,
                "caught": caught,
                "hallucinations_caught": hallucinations,
                "errors": errors,
            }
        last = (data, issues)
        caught.extend(str(issue) for issue in issues)
        hallucinations += sum(1 for issue in issues if issue.kind in HALLUCINATION_KINDS)
        feedback = _feedback(issues)

    note, source = fallback_note(), "template"
    if last is not None:
        data, issues = last
        failed = {issue.where for issue in issues}
        if "" not in failed:
            kept = {key: value for key, value in _clean(data, schema).items() if key not in failed and value}
            if kept:
                note, source = {**note, **kept}, "partial"
    return {
        "note": note,
        "source": source,
        "attempts": attempts,
        "caught": caught,
        "hallucinations_caught": hallucinations,
        "errors": errors,
    }


def outcome(game: chess.pgn.Game, color: chess.Color) -> str:
    result = game.headers.get("Result", "*")
    if result == "*":
        final = game.end().board()
        if final.is_checkmate():
            result = "0-1" if final.turn == chess.WHITE else "1-0"
    if result == "1/2-1/2":
        return "drew the game"
    if result in ("1-0", "0-1"):
        won = (result == "1-0") == (color == chess.WHITE)
        return "won the game" if won else "lost the game"
    return "the game was not finished"


def win_series(analysis: GameAnalysis, color: chess.Color) -> list[float]:
    if not analysis.moves:
        return []
    first = analysis.moves[0]
    start = first.win_before if first.color == color else 100 - first.win_before
    series = [round(start, 1)]
    for move in analysis.moves:
        value = move.win_after if move.color == color else 100 - move.win_after
        series.append(round(value, 1))
    return series


def personalize(text: str, name: str, fallback_name: str) -> str:
    return text.replace("[STUDENT]", name.strip() or fallback_name)


def _usage(llm) -> dict:
    stats = getattr(llm, "stats", None)
    return {
        "model_calls": getattr(stats, "calls", 0),
        "prompt_tokens": getattr(stats, "prompt_tokens", 0),
        "output_tokens": getattr(stats, "output_tokens", 0),
    }


def review_game(
    game: chess.pgn.Game,
    *,
    settings: Settings,
    llm,
    color: chess.Color,
    student_name: str = "",
    level: str = "beginner",
    language: str = "English",
    analyzer: Analyzer | None = None,
    progress: Progress | None = None,
) -> dict:
    progress = progress or (lambda message, fraction: None)
    started = time.perf_counter()

    def on_move(index: int, total: int) -> None:
        progress(f"Stockfish is checking move {index} of {total}", 0.02 + 0.48 * index / max(total, 1))

    progress("Starting Stockfish", 0.01)
    if analyzer is None:
        with Analyzer(
            settings.stockfish_path,
            depth=settings.engine_depth,
            threads=settings.engine_threads,
            hash_mb=settings.engine_hash_mb,
            max_time=settings.engine_max_time,
        ) as engine:
            analysis = engine.analyse_game(game, on_move)
    else:
        analysis = analyzer.analyse_game(game, on_move)
    engine_seconds = time.perf_counter() - started

    moments = [build_moment(m).to_dict() for m in select_moments(analysis, color, settings.max_moments)]
    good_eval = select_good_moment(analysis, color)
    good = build_moment(good_eval, "good").to_dict() if good_eval else None
    all_moments = [*moments, *([good] if good else [])]

    system = system_prompt(level)
    model_started = time.perf_counter()
    calls_before = _usage(llm)
    total_notes = len(all_moments) + 1
    stats = {"model_notes": 0, "partial_notes": 0, "template_notes": 0, "retries": 0, "hallucinations_caught": 0}

    def record(target: dict, result: dict) -> None:
        target["note_source"] = result["source"]
        target["attempts"] = result["attempts"]
        target["caught"] = result["caught"]
        target["hallucinations_caught"] = result["hallucinations_caught"]
        stats[f"{result['source']}_notes"] += 1
        stats["retries"] += max(0, result["attempts"] - 1)
        stats["hallucinations_caught"] += result["hallucinations_caught"]

    for done, moment in enumerate(all_moments):
        progress(f"Gemma is writing note {done + 1} of {total_notes}", 0.52 + 0.44 * done / total_notes)
        result = write_note(
            llm,
            system,
            moment_prompt(moment),
            MOMENT_SCHEMA,
            lambda data, m=moment: verify_moment(data, m),
            lambda m=moment: fallback.moment_note(m),
        )
        moment["note"] = result["note"]
        record(moment, result)

    habits = opening_habits(game, color)
    context = {
        "color": color_name(color),
        "outcome": outcome(game, color),
        "accuracy": analysis.accuracy(color),
        "opponent_accuracy": analysis.accuracy(not color),
        "counts": analysis.counts(color),
        "moments": moments,
        "good": good,
        "habits": habit_sentences(habits),
        "habit_facts": habits,
    }
    progress("Gemma is writing the summary and the note for parents", 0.52 + 0.44 * len(all_moments) / total_notes)
    result = write_note(
        llm,
        system,
        summary_prompt(context, language),
        SUMMARY_SCHEMA,
        lambda data: verify_summary(data, all_moments, language, summary_facts(context)),
        lambda: fallback.summary_note(context),
    )
    summary = result["note"]
    summary["summary"] = personalize(summary["summary"], student_name, "The student")
    summary["parent_note"] = personalize(summary["parent_note"], student_name, "Your child")
    summary_meta: dict = {}
    record(summary_meta, result)
    model_seconds = time.perf_counter() - model_started
    usage = _usage(llm)
    stats.update({key: usage[key] - calls_before[key] for key in usage})

    headers = game.headers
    review = {
        "id": new_review_id(),
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "student": {
            "name": student_name.strip(),
            "color": color_name(color).lower(),
            "level": level,
            "language": language,
        },
        "game": {
            "white": headers.get("White", "?"),
            "black": headers.get("Black", "?"),
            "white_elo": headers.get("WhiteElo", ""),
            "black_elo": headers.get("BlackElo", ""),
            "result": headers.get("Result", "*"),
            "date": headers.get("Date", ""),
            "event": headers.get("Event", ""),
            "site": headers.get("Site", ""),
            "opening": headers.get("Opening", "") or headers.get("ECO", ""),
            "moves": analysis.moves[-1].move_number if analysis.moves else 0,
            "pgn": str(game),
        },
        "outcome": context["outcome"],
        "accuracy": {"student": context["accuracy"], "opponent": context["opponent_accuracy"]},
        "counts": context["counts"],
        "moments": moments,
        "good_moment": good,
        "habits": habits,
        "habit_sentences": context["habits"],
        "summary": summary,
        "summary_source": summary_meta["note_source"],
        "summary_caught": summary_meta["caught"],
        "win_series": win_series(analysis, color),
        "engine": {"name": analysis.engine_name, "depth": analysis.depth},
        "model": {"label": llm.label, "local": bool(getattr(llm, "local", False))},
        "timings": {
            "engine_s": round(engine_seconds, 1),
            "model_s": round(model_seconds, 1),
            "total_s": round(time.perf_counter() - started, 1),
        },
        "stats": stats,
    }
    review["annotated_pgn"] = annotated_pgn(game, review)
    progress("Done", 1.0)
    return review
