"""Loading games: pasted PGN, uploaded files, Lichess and Chess.com."""

from __future__ import annotations

import io
import re

import chess
import chess.pgn
import httpx

USER_AGENT = "Second/0.1 (chess coach review assistant; +https://github.com/dragon-slayer27/chess-second)"
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,29}$")
LICHESS_PERF_TYPES = "ultraBullet,bullet,blitz,rapid,classical,correspondence"


class GameSourceError(ValueError):
    """Raised when games can't be loaded from the given source."""


def parse_pgn(text: str, limit: int | None = None) -> list[chess.pgn.Game]:
    """Parse every game in a PGN string, skipping empty or unreadable ones."""
    games: list[chess.pgn.Game] = []
    stream = io.StringIO(text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if sum(1 for _ in game.mainline_moves()) < 2:
            continue
        games.append(game)
        if limit is not None and len(games) >= limit:
            break
    return games


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True)


def _check_username(username: str) -> str:
    username = username.strip().lstrip("@")
    if not USERNAME_RE.match(username):
        raise GameSourceError("That username doesn't look right.")
    return username


def lichess_game_id(url_or_id: str) -> str:
    text = url_or_id.strip()
    match = re.search(r"lichess\.org/(?:embed/(?:game/)?)?([A-Za-z0-9]{8})(?![A-Za-z0-9]{1,3}\b)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{8}(?:[A-Za-z0-9]{4})?", text):
        return text[:8]
    raise GameSourceError("That doesn't look like a Lichess game link (e.g. https://lichess.org/AbCdEfGh).")


def fetch_lichess_game(url_or_id: str) -> str:
    game_id = lichess_game_id(url_or_id)
    with _client() as client:
        response = client.get(
            f"https://lichess.org/game/export/{game_id}",
            params={"clocks": "false", "evals": "false", "opening": "true"},
            headers={"Accept": "application/x-chess-pgn"},
        )
    if response.status_code == 404:
        raise GameSourceError(f"Lichess has no game with id {game_id}.")
    response.raise_for_status()
    return response.text


def fetch_lichess_user_games(username: str, max_games: int = 5) -> str:
    username = _check_username(username)
    with _client() as client:
        response = client.get(
            f"https://lichess.org/api/games/user/{username}",
            params={
                "max": max_games,
                "clocks": "false",
                "evals": "false",
                "opening": "true",
                "perfType": LICHESS_PERF_TYPES,
            },
            headers={"Accept": "application/x-chess-pgn"},
        )
    if response.status_code == 404:
        raise GameSourceError(f"There is no Lichess user called {username}.")
    response.raise_for_status()
    if not response.text.strip():
        raise GameSourceError(f"{username} has no standard chess games on Lichess yet.")
    return response.text


def fetch_chesscom_user_games(username: str, max_games: int = 5) -> str:
    username = _check_username(username).lower()
    pgns: list[str] = []
    with _client() as client:
        response = client.get(f"https://api.chess.com/pub/player/{username}/games/archives")
        if response.status_code == 404:
            raise GameSourceError(f"There is no Chess.com user called {username}.")
        response.raise_for_status()
        for archive_url in reversed(response.json().get("archives", [])):
            month = client.get(archive_url)
            month.raise_for_status()
            games = [g for g in month.json().get("games", []) if g.get("rules") == "chess" and g.get("pgn")]
            for game in reversed(games):
                pgns.append(game["pgn"])
                if len(pgns) >= max_games:
                    break
            if len(pgns) >= max_games:
                break
    if not pgns:
        raise GameSourceError(f"{username} has no standard chess games on Chess.com yet.")
    return "\n\n".join(pgns)


def player_color(game: chess.pgn.Game, name: str) -> chess.Color | None:
    """Which side `name` played in `game`, if it can be told from the headers."""
    needle = name.strip().lower()
    if not needle:
        return None
    white = game.headers.get("White", "").strip().lower()
    black = game.headers.get("Black", "").strip().lower()
    if needle == white:
        return chess.WHITE
    if needle == black:
        return chess.BLACK
    if needle in white and needle not in black:
        return chess.WHITE
    if needle in black and needle not in white:
        return chess.BLACK
    return None
