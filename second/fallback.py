"""Deterministic notes used when the model's output can't be verified.

These are less charming than Gemma's notes but always correct, because they are
built straight from the engine facts.
"""

from __future__ import annotations

HEADLINES = {
    "allowed checkmate": "Watch out for checkmate threats",
    "missed checkmate": "There was a checkmate here",
    "back-rank mate": "Watch your back rank",
    "hanging piece": "A piece was left undefended",
    "fork": "Your opponent had a fork",
    "missed fork": "You had a fork",
    "free piece": "A free piece was waiting",
    "loses material": "This move loses material",
    "missed win of material": "You could have won material",
    "better move available": "There was a better move",
}

QUESTIONS = {
    "allowed checkmate": "What was your opponent threatening against your king?",
    "missed checkmate": "Can you find a checkmate in this position?",
    "back-rank mate": "Does your king have an escape square?",
    "hanging piece": "After your move, which of your pieces can be captured?",
    "fork": "Which of your opponent's pieces could attack two things at once?",
    "missed fork": "Is there a move that attacks two pieces at the same time?",
    "free piece": "Is any of your opponent's pieces undefended?",
    "loses material": "What is your opponent's best reply to this move?",
    "missed win of material": "Which captures or checks do you have here?",
    "better move available": "What does your opponent want to do next?",
}

TIPS = {
    "allowed checkmate": "Before every move, look at all of your opponent's checks.",
    "missed checkmate": "Always look at every check you can give. One of them might be mate.",
    "back-rank mate": "After you castle, a little pawn move gives your king some air.",
    "hanging piece": "Before you move, ask: is every one of my pieces still protected?",
    "fork": "Knights love forks. Look at every square they can jump to.",
    "missed fork": "Look for moves that attack two things at once.",
    "free piece": "Always ask: can I capture something for free?",
    "loses material": "Count attackers and defenders before you move.",
    "missed win of material": "Checks, captures and threats: look at them first.",
    "better move available": "Before every move, ask: what does my opponent want?",
}

HOMEWORK = {
    "allowed checkmate": "Solve 10 'mate in 1' puzzles and say the threat out loud before each move in your next games.",
    "missed checkmate": "Solve 10 'mate in 1' and 'mate in 2' puzzles this week.",
    "back-rank mate": "Solve 5 back-rank checkmate puzzles this week.",
    "hanging piece": "Before every move this week, touch-check each of your pieces in your head: is it protected?",
    "fork": "Solve 10 knight-fork puzzles this week.",
    "missed fork": "Solve 10 fork puzzles this week.",
    "free piece": "Solve 10 'win a free piece' puzzles this week.",
    "loses material": "Play 3 slow games this week and ask 'what is my opponent's best reply?' before each move.",
    "missed win of material": "Solve 10 tactics puzzles this week, looking at checks and captures first.",
    "better move available": "Play 3 slow games this week and write down your opponent's threat before each move.",
}


def _main_theme(themes: list[str]) -> str:
    for theme in themes:
        if theme in HEADLINES:
            return theme
    return "better move available"


def moment_note(moment: dict) -> dict:
    if moment["kind"] == "good":
        return {
            "headline": "Strong move!",
            "explanation": " ".join(moment["sentences"][:2]),
            "question": f"What was your idea behind {moment['played']}?",
            "tip": "When you find a strong move, check it once more and then play it with confidence.",
        }
    theme = _main_theme(moment["themes"])
    body = moment["sentences"][1:3] or moment["sentences"][:1]
    return {
        "headline": HEADLINES[theme],
        "explanation": " ".join(body),
        "question": QUESTIONS[theme],
        "tip": TIPS[theme],
    }


def summary_note(context: dict) -> dict:
    themes = [theme for moment in context["moments"] for theme in moment["themes"]]
    theme = _main_theme(themes) if themes else "better move available"
    habits = context.get("habit_facts", {})
    strengths = []
    if context.get("good"):
        strengths.append(f"Found a strong move: {context['good']['label']}.")
    if habits.get("castled_on_move") and habits["castled_on_move"] <= 10:
        strengths.append("Castled early to keep the king safe.")
    if habits.get("minors_developed_by_move_10", 0) >= 3:
        strengths.append("Brought the knights and bishops out quickly.")
    if not strengths:
        strengths.append("Kept fighting all the way through the game.")
    focus = [TIPS[theme]]
    count = len(context["moments"])
    return {
        "summary": f"[STUDENT] played {context['color']} and {context['outcome']}. "
        f"We picked out {count} key moment{'s' if count != 1 else ''} to learn from.",
        "strengths": strengths[:2],
        "focus": focus,
        "homework": HOMEWORK[theme],
        "parent_note": f"[STUDENT] played a fighting game this week. We found {count} key "
        f"moment{'s' if count != 1 else ''} to learn from, mostly about one idea: "
        f"{HEADLINES[theme].lower()}. A few puzzles at home on this will really help!",
    }
