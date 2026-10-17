"""Checks that model output only uses engine-verified facts.

The model is given facts about one moment of a game. Anything chess-specific it
writes (moves, squares, pieces it says were won or lost, "mate in N", move
numbers, evaluations) must appear in those facts. Anything else is flagged.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

SAN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    r"O-O-O|O-O|0-0-0|0-0"
    r"|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?"
    r"|[a-h]x[a-h][1-8](?:=[QRBN])?"
    r"|[a-h][1-8](?:=[QRBN])?"
    r")[+#]?(?![A-Za-z0-9])"
)
PIECE_CLAIM_RE = re.compile(
    r"\b(?:lose|loses|losing|lost|drop|drops|dropping|dropped|hang|hangs|hanging|hung|"
    r"blunder(?:s|ed|ing)?|give away|gives away|giving away|gave away|"
    r"win|wins|winning|won|capture|captures|capturing|captured|take|takes|taking|took|taken|"
    r"grab|grabs|grabbing|grabbed|trap|traps|trapped|fork|forks|forked|forking)"
    r"\s+(?:[\w']+\s+){0,2}?(king|queen|rook|bishop|knight|pawn)s?\b",
    re.I,
)
# "the knight on f4 is hanging", "your rook was lost": the piece's fate stated after it.
STATE_CLAIM_RE = re.compile(
    r"\b(queen|rook|bishop|knight|pawn)s?(?:\s+on\s+([a-h][1-8]))?\s+"
    r"(?:is|was|were|can be|could be|gets|got|will be|would be|became)\s+(?:\w+\s+)?"
    r"(?:hanging|undefended|unprotected|loose|free|lost|captured|taken|trapped|won|en prise)\b",
    re.I,
)
MATERIAL_FACT_RE = re.compile(r"nothing defends it|worth less|captures|for free|can be taken", re.I)
SQUARE_RE = re.compile(r"(?<![A-Za-z0-9])[a-h][1-8](?![A-Za-z0-9])")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
MATE_RE = re.compile(r"\b(?:check)?mate[- ]in[- ](\d+|one|two|three|four|five|six)\b", re.I)
MOVE_NUMBER_RE = re.compile(r"\bmove (?:number )?(\d+)\b", re.I)
EVAL_NUMBER_RE = re.compile(r"(?<![\w.])[+-]\d+(?:\.\d+)?(?![\w.])|(?<![\w.])\d+\.\d+(?![\w.])")
ENGINE_RE = re.compile(r"\b(?:stockfish|engine|computer|artificial intelligence)\b", re.I)
AI_RE = re.compile(r"\bAI\b")
SQUARE_ONLY_RE = re.compile(r"[a-h][1-8]")
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
# Named tactics a note may only use when the engine facts mention them.
TACTIC_RE = re.compile(
    r"\b(back[- ]rank|fork(?:s|ed|ing)?|pin(?:s|ned|ning)?|skewer\w*|discovered (?:attack|check)\w*|"
    r"sacrific\w*|smothered|stalemate\w*|en passant|zwischenzug|deflect\w*|decoy\w*|overload\w*|x-ray)\b",
    re.I,
)
TACTIC_ROOTS = (
    ("back", "back-rank"),
    ("fork", "fork"),
    ("pin", "pin"),
    ("skewer", "skewer"),
    ("discovered", "discovered"),
    ("sacrific", "sacrific"),
    ("smothered", "smothered"),
    ("stalemate", "stalemate"),
    ("en passant", "en passant"),
    ("zwischenzug", "zwischenzug"),
    ("deflect", "deflect"),
    ("decoy", "decoy"),
    ("overload", "overload"),
    ("x-ray", "x-ray"),
)
MATE_WORD_RE = re.compile(r"\b(?:check)?mat(?:e|es|ed|ing)\b", re.I)

HALLUCINATION_KINDS = {
    "fabricated_move",
    "unknown_square",
    "wrong_piece",
    "wrong_mate",
    "wrong_move_number",
    "invented_number",
    "wrong_tactic",
}

# Scripts we can check for parent notes written in non-Latin languages.
LANGUAGE_SCRIPTS = {
    "hindi": "DEVANAGARI",
    "marathi": "DEVANAGARI",
    "nepali": "DEVANAGARI",
    "bengali": "BENGALI",
    "tamil": "TAMIL",
    "telugu": "TELUGU",
    "kannada": "KANNADA",
    "malayalam": "MALAYALAM",
    "gujarati": "GUJARATI",
    "punjabi": "GURMUKHI",
    "odia": "ORIYA",
    "urdu": "ARABIC",
    "arabic": "ARABIC",
    "russian": "CYRILLIC",
}


@dataclass(frozen=True)
class Issue:
    kind: str
    detail: str
    where: str = ""  # the note field the problem is in

    def __str__(self) -> str:
        return f"{self.kind.replace('_', ' ')}: {self.detail}"

    @property
    def is_hallucination(self) -> bool:
        return self.kind in HALLUCINATION_KINDS


@dataclass
class Allowed:
    sans: set[str]
    squares: set[str]
    pieces: set[str]
    mates: set[int]
    move_numbers: set[int]
    facts_text: str = ""
    material_squares: set[str] = field(default_factory=set)
    numbers: set[str] = field(default_factory=set)

    def with_facts(self, text: str) -> Allowed:
        """Also allow the numbers, move numbers and words in a block of extra facts."""
        self.facts_text += " " + text.lower()
        self.numbers |= set(NUMBER_RE.findall(text))
        self.move_numbers |= {int(n) for n in MOVE_NUMBER_RE.findall(text)}
        return self

    @classmethod
    def from_moment(cls, moment: dict) -> Allowed:
        sentences = moment.get("sentences", [])
        material_squares = set(moment.get("highlight", []))
        for sentence in sentences:
            if MATERIAL_FACT_RE.search(sentence):
                material_squares.update(SQUARE_RE.findall(sentence))
        return cls(
            sans=set(moment["allowed_sans"]),
            squares=set(moment["allowed_squares"]),
            pieces=set(moment["allowed_pieces"]),
            mates=set(moment["mates"]),
            move_numbers=set(range(moment["min_move_number"], moment["max_move_number"] + 1)),
            facts_text=" ".join([*sentences, *moment.get("themes", [])]).lower(),
            material_squares=material_squares,
        )

    @classmethod
    def union(cls, moments: Iterable[dict]) -> Allowed:
        allowed = cls(set(), set(), {"king"}, set(), set())
        for moment in moments:
            one = cls.from_moment(moment)
            allowed.sans |= one.sans
            allowed.squares |= one.squares
            allowed.pieces |= one.pieces
            allowed.mates |= one.mates
            allowed.move_numbers |= one.move_numbers
            allowed.facts_text += " " + one.facts_text
            allowed.material_squares |= one.material_squares
        return allowed

    @property
    def has_mate(self) -> bool:
        return bool(self.mates) or bool(MATE_WORD_RE.search(self.facts_text))

    def mentions(self, root: str) -> bool:
        text = self.facts_text.replace("back rank", "back-rank")
        return re.search(r"\b" + re.escape(root), text) is not None


def normalize_san(token: str) -> str:
    if token.startswith("0"):
        token = token.replace("0", "O")
    return token.rstrip("+#")


def notation_tokens(text: str) -> list[str]:
    return [normalize_san(match.group(1)) for match in SAN_TOKEN_RE.finditer(text)]


def check_text(text: str, allowed: Allowed, claims_mate: bool = False, where: str = "") -> list[Issue]:
    """Flag chess claims in `text` that are not in the facts.

    `claims_mate` also flags any mention of checkmate when the facts have none; use it for
    headlines and explanations, where "checkmate" is a claim rather than general advice.
    """
    issues: list[Issue] = []
    for token in notation_tokens(text):
        if SQUARE_ONLY_RE.fullmatch(token):
            if token not in allowed.squares and token not in allowed.sans:
                issues.append(Issue("unknown_square", token))
        elif token not in allowed.sans:
            issues.append(Issue("fabricated_move", token))
    for match in PIECE_CLAIM_RE.finditer(text):
        if match.group(1).lower() not in allowed.pieces:
            issues.append(Issue("wrong_piece", match.group(0)))
    for match in STATE_CLAIM_RE.finditer(text):
        piece, square = match.group(1).lower(), match.group(2)
        if piece not in allowed.pieces or (square and square not in allowed.material_squares):
            issues.append(Issue("wrong_piece", match.group(0)))
    for match in MATE_RE.finditer(text):
        raw = match.group(1).lower()
        number = WORD_NUMBERS.get(raw) or int(raw)
        if number not in allowed.mates:
            issues.append(Issue("wrong_mate", match.group(0)))
    for match in MOVE_NUMBER_RE.finditer(text):
        if int(match.group(1)) not in allowed.move_numbers:
            issues.append(Issue("wrong_move_number", match.group(0)))
    for match in EVAL_NUMBER_RE.finditer(text):
        if match.group(0).lstrip("+-") not in allowed.numbers:
            issues.append(Issue("invented_number", match.group(0)))
    for match in TACTIC_RE.finditer(text):
        word = match.group(1).lower()
        root = next(root for prefix, root in TACTIC_ROOTS if word.startswith(prefix))
        if not allowed.mentions(root):
            issues.append(Issue("wrong_tactic", match.group(0)))
    if claims_mate and not allowed.has_mate:
        found = MATE_WORD_RE.search(text)
        if found:
            issues.append(Issue("wrong_tactic", found.group(0)))
    found = ENGINE_RE.search(text) or AI_RE.search(text)
    if found:
        issues.append(Issue("mentions_engine", found.group(0)))
    return _dedupe([Issue(issue.kind, issue.detail, where) for issue in issues])


def _dedupe(issues: list[Issue]) -> list[Issue]:
    seen, unique = set(), []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            unique.append(issue)
    return unique


def _text_field(data: dict, key: str, issues: list[Issue], max_chars: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(Issue("missing_field", key, key))
        return ""
    if len(value) > max_chars:
        issues.append(Issue("too_long", key, key))
    return value


def _list_field(data: dict, key: str, issues: list[Issue]) -> list[str]:
    value = data.get(key)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        issues.append(Issue("missing_field", key, key))
        return []
    return value


def verify_moment(data: dict, moment: dict) -> list[Issue]:
    allowed = Allowed.from_moment(moment)
    issues: list[Issue] = []
    limits = {"headline": 90, "explanation": 650, "question": 250, "tip": 200}
    for key, limit in limits.items():
        text = _text_field(data, key, issues, limit)
        issues.extend(check_text(text, allowed, claims_mate=key in ("headline", "explanation"), where=key))
    return _dedupe(issues)


def script_share(text: str, script: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if script in unicodedata.name(c, "")) / len(letters)


def verify_summary(data: dict, moments: list[dict], language: str, facts_text: str = "") -> list[Issue]:
    """Check the game summary against every moment's facts plus the summary's own fact sheet."""
    allowed = Allowed.union(moments).with_facts(facts_text)
    issues: list[Issue] = []
    summary = _text_field(data, "summary", issues, 500)
    issues.extend(check_text(summary, allowed, claims_mate=True, where="summary"))
    homework = _text_field(data, "homework", issues, 300)
    # "Solve ten mate-in-1 puzzles" is advice, not a claim about the game.
    issues.extend(i for i in check_text(homework, allowed, where="homework") if i.kind != "wrong_mate")
    for key in ("strengths", "focus"):
        for item in _list_field(data, key, issues):
            issues.extend(check_text(item, allowed, where=key))
    note = _text_field(data, "parent_note", issues, 700)
    if note:
        tokens = notation_tokens(note)
        if tokens:
            issues.append(Issue("notation_in_parent_note", ", ".join(tokens), "parent_note"))
        issues.extend(i for i in check_text(note, allowed, where="parent_note") if i.kind != "unknown_square")
        script = LANGUAGE_SCRIPTS.get(language.strip().lower())
        if script and script_share(note, script) < 0.5:
            issues.append(Issue("wrong_language", f"parent note is not in {language}", "parent_note"))
    return _dedupe(issues)
