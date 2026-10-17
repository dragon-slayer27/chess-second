"""Prompts for the coach's notes. The model only ever sees verified facts."""

from __future__ import annotations

MOMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "explanation": {"type": "string"},
        "question": {"type": "string"},
        "tip": {"type": "string"},
    },
    "required": ["headline", "explanation", "question", "tip"],
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "focus": {"type": "array", "items": {"type": "string"}},
        "homework": {"type": "string"},
        "parent_note": {"type": "string"},
    },
    "required": ["summary", "strengths", "focus", "homework", "parent_note"],
}

LEVELS = {
    "beginner": "a young beginner (about 7 to 12 years old) who knows how the pieces move. "
    "Use very simple words and short sentences.",
    "intermediate": "a club player rated roughly 1000 to 1600. Be clear and practical.",
    "advanced": "a strong tournament player. Be concise and concrete.",
}

LANGUAGE_HINTS = {
    "hindi": "Hindi, in Devanagari script",
    "hinglish": "Hinglish (Hindi written in English letters, like a friendly WhatsApp message)",
    "marathi": "Marathi, in Devanagari script",
    "tamil": "Tamil, in Tamil script",
    "telugu": "Telugu, in Telugu script",
    "kannada": "Kannada, in Kannada script",
    "bengali": "Bengali, in Bengali script",
    "gujarati": "Gujarati, in Gujarati script",
}

JUDGEMENT_WORDS = {
    "blunder": "a blunder, a big mistake",
    "mistake": "a mistake",
    "inaccuracy": "an inaccuracy, a small mistake",
}

SYSTEM_PROMPT = """You are Second, the assistant of a chess coach. You write short coaching notes about a student's game.
You are given FACTS that were computed by a chess engine and checked by code. They are correct.

Rules:
1. Use only the FACTS. Do not add any other moves, squares, pieces, evaluations or numbers.
2. Write moves exactly as they appear in the FACTS (for example Nf6, Bxe5, O-O).
3. Talk to the student as "you". Be kind, honest and specific, like a good coach.
4. Never mention engines, computers, Stockfish or AI.
5. Reply with one JSON object and nothing else.

The student is {level}"""


def system_prompt(level: str) -> str:
    return SYSTEM_PROMPT.format(level=LEVELS.get(level, LEVELS["beginner"]))


def language_hint(language: str) -> str:
    return LANGUAGE_HINTS.get(language.strip().lower(), language.strip() or "English")


# For each theme, a phrase that marks the sentence carrying the main lesson.
KEY_FACT_MARKERS = (
    ("allowed checkmate", "forced checkmate in"),
    ("missed checkmate", "You had a forced checkmate"),
    ("fork", "(a fork)"),
    ("missed fork", "(a fork)"),
    ("hanging piece", "nothing defends it"),
    ("hanging piece", "which is worth less"),
    ("free piece", "for free"),
    ("loses material", "you lose about"),
    ("missed win of material", "you would win about"),
)


def key_fact(moment: dict) -> str:
    """The one sentence a coach would lead with for this moment."""
    for theme, marker in KEY_FACT_MARKERS:
        if theme in moment["themes"]:
            for sentence in moment["sentences"]:
                if marker in sentence:
                    return sentence
    sentences = moment["sentences"]
    return sentences[1] if len(sentences) > 1 else sentences[0]


def _line(moves: list[str]) -> str:
    return ", ".join(moves) if moves else "(none)"


def moment_prompt(moment: dict) -> str:
    facts = "\n".join(f"- {sentence}" for sentence in moment["sentences"])
    color = moment["color"].capitalize()
    if moment["kind"] == "good":
        return f"""FACTS about a good moment in the game (the student played {color}):
- Move played: {moment["label"]}
{facts}

Write a JSON object with these keys:
"headline": praise for this specific move in at most 7 words.
"explanation": 2 short sentences about why {moment["played"]} was strong. Use only the FACTS.
"question": one question that makes the student explain the idea behind {moment["played"]}.
"tip": one short rule of thumb the student can remember. No moves or squares in the tip."""

    judgement = JUDGEMENT_WORDS.get(moment["judgement"] or "", "not the best move")
    best = moment["best"] or "the better move"
    return f"""FACTS about one moment in the game (the student played {color}):
- Move played: {moment["label"]} ({judgement})
- Better move: {moment["best"] or "(none)"}
- Best line after the better move: {_line(moment["best_line"][:6])}
- Opponent's best reply to the move played: {_line(moment["reply_line"][:6])}
{facts}

KEY FACT (the main lesson): {key_fact(moment)}

Write a JSON object with these keys:
"headline": at most 7 words that name this specific idea, like "Watch the knight fork" or "A free bishop to take". Not a general warning.
"explanation": 2 or 3 short sentences. First say what went wrong after {moment["played"]}, using the KEY FACT. Then say what {best} would have done, using the FACTS about it.
"question": one question that helps the student find the idea in this position by themselves. Do not give the answer away.
"tip": one short rule of thumb the student can remember. No moves or squares in the tip."""


def summary_prompt(context: dict, language: str) -> str:
    lines = [
        f"- The student played {context['color']} and {context['outcome']}.",
        f"- The student's accuracy was {context['accuracy']}%. The opponent's accuracy was {context['opponent_accuracy']}%.",
        f"- The student made {context['counts']['blunder']} blunders, {context['counts']['mistake']} mistakes "
        f"and {context['counts']['inaccuracy']} inaccuracies.",
    ]
    for moment in context["moments"]:
        lines.append(f"- Key moment {moment['label']}: {', '.join(moment['themes'])}. {key_fact(moment)}")
    if context.get("good"):
        good = context["good"]
        lines.append(f"- Good moment {good['label']}: {good['sentences'][0]}")
    lines.extend(f"- {sentence}" for sentence in context["habits"])
    facts = "\n".join(lines)
    return f"""FACTS about the whole game:
{facts}

Write a JSON object with these keys:
"summary": 2 sentences about how the game went, using only the FACTS above. Do not mention any moves.
"strengths": a list of 1 or 2 short points the student did well, taken only from the FACTS. If there is nothing specific, praise their fighting spirit.
"focus": a list of 1 or 2 short points to work on, based on the key moments.
"homework": one practice task for this week in one sentence. No moves.
"parent_note": a warm message of 2 or 3 sentences for the student's parent, written in {language_hint(language)}. Write to the parent, and talk about [STUDENT] in the third person. Say one thing [STUDENT] did well and the one thing to practise this week, in plain words. No chess notation and no move numbers."""
