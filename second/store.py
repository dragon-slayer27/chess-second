"""Saving and loading reviews as JSON files."""

from __future__ import annotations

import json
import re
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def card(review: dict) -> dict:
    """The few fields needed to list a review."""
    student = review["student"]
    return {
        "id": review["id"],
        "student": student.get("name") or student["color"].capitalize(),
        "color": student["color"],
        "white": review["game"]["white"],
        "black": review["game"]["black"],
        "result": review["game"]["result"],
        "outcome": review["outcome"],
        "accuracy": review["accuracy"]["student"],
        "moments": len(review["moments"]),
        "created_at": review["created_at"],
        "model": review["model"]["label"],
        "title": review.get("sample_title"),
        "blurb": review.get("sample_blurb"),
    }


class ReviewStore:
    def __init__(self, root: Path, read_only: bool = False):
        self.root = Path(root)
        self.read_only = read_only
        if not read_only:
            self.root.mkdir(parents=True, exist_ok=True)

    def path(self, review_id: str) -> Path | None:
        if not ID_RE.match(review_id):
            return None
        return self.root / f"{review_id}.json"

    def save(self, review: dict) -> str:
        if self.read_only:
            raise PermissionError("this review store is read-only")
        path = self.path(review["id"])
        if path is None:
            raise ValueError(f"bad review id: {review['id']}")
        path.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
        return review["id"]

    def load(self, review_id: str) -> dict | None:
        path = self.path(review_id)
        if path is None or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self, limit: int = 50, newest_first: bool = True) -> list[dict]:
        if not self.root.is_dir():
            return []
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime if newest_first else p.name)
        if newest_first:
            files.reverse()
        cards = []
        for file in files[:limit]:
            try:
                cards.append(card(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError):
                continue
        return cards
