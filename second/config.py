"""Runtime settings, read from environment variables."""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def find_stockfish() -> str | None:
    """Locate a Stockfish binary: env var, PATH, ./bin, then common install paths."""
    explicit = os.environ.get("STOCKFISH_PATH")
    if explicit:
        return explicit
    on_path = shutil.which("stockfish")
    if on_path:
        return on_path
    for pattern in ("bin/stockfish*", "bin/*/stockfish*"):
        for candidate in sorted(glob.glob(str(PROJECT_ROOT / pattern))):
            if os.path.isfile(candidate) and (candidate.endswith(".exe") or os.access(candidate, os.X_OK)):
                return candidate
    for candidate in (
        "/usr/games/stockfish",
        "/usr/bin/stockfish",
        "/usr/local/bin/stockfish",
        "/opt/homebrew/bin/stockfish",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass(frozen=True)
class Settings:
    stockfish_path: str | None
    engine_depth: int
    engine_threads: int
    engine_hash_mb: int
    engine_max_time: float
    llm_backend: str
    ollama_url: str
    ollama_model: str
    ollama_api_key: str | None
    gemini_api_key: str | None
    gemini_model: str
    data_dir: Path
    samples_dir: Path
    public_demo: bool
    max_moments: int
    max_games: int

    def with_overrides(self, **changes) -> Settings:
        return replace(self, **{k: v for k, v in changes.items() if v is not None})


def load_settings() -> Settings:
    public_demo = _env_bool("SECOND_PUBLIC_DEMO")
    cpu = os.cpu_count() or 2
    return Settings(
        stockfish_path=find_stockfish(),
        engine_depth=_env_int("SECOND_ENGINE_DEPTH", 10 if public_demo else 14),
        engine_threads=_env_int("SECOND_ENGINE_THREADS", 1 if public_demo else max(1, min(4, cpu // 2))),
        engine_hash_mb=_env_int("SECOND_ENGINE_HASH_MB", 16 if public_demo else 64),
        engine_max_time=_env_float("SECOND_ENGINE_MAX_TIME", 2.0 if public_demo else 1.0),
        llm_backend=os.environ.get("SECOND_LLM_BACKEND", "ollama").strip().lower(),
        ollama_url=os.environ.get("SECOND_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.environ.get("SECOND_OLLAMA_MODEL", "gemma4:e4b-it-qat"),
        ollama_api_key=os.environ.get("OLLAMA_API_KEY") or None,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None,
        gemini_model=os.environ.get("SECOND_GEMINI_MODEL", "gemma-4-26b-a4b-it"),
        data_dir=Path(os.environ.get("SECOND_DATA_DIR", PROJECT_ROOT / "data")),
        samples_dir=Path(os.environ.get("SECOND_SAMPLES_DIR", PROJECT_ROOT / "samples")),
        public_demo=public_demo,
        max_moments=_env_int("SECOND_MAX_MOMENTS", 3 if public_demo else 4),
        max_games=_env_int("SECOND_MAX_GAMES", 1 if public_demo else 10),
    )
