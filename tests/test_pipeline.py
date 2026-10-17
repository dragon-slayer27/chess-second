import io

import chess
import chess.pgn

from conftest import FRIED_LIVER, SCHOLARS_MATE, needs_stockfish, read
from second.config import load_settings
from second.facts import build_moment, select_good_moment, select_moments
from second.llm import LLMError, NoModelClient
from second.report import render_standalone
from second.review import review_game
from second.verify import verify_moment

pytestmark = needs_stockfish


class ScriptedClient:
    """Plays back canned model replies in order, then repeats the last one."""

    label = "scripted test model"
    local = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat_json(self, system, user, schema, temperature=0.4):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(user)
        return reply


def settings():
    return load_settings().with_overrides(max_moments=3)


def test_scholars_mate_blunder_facts(analyzer):
    analysis = analyzer.analyse_game(read(SCHOLARS_MATE))
    [blunder] = select_moments(analysis, chess.BLACK, 3)
    moment = build_moment(blunder).to_dict()
    assert moment["label"] == "3... Nf6"
    assert moment["judgement"] == "blunder"
    assert "allowed checkmate" in moment["themes"]
    assert moment["mates"] == [1]
    assert "Qxf7" in moment["allowed_sans"]
    good = select_good_moment(analysis, chess.WHITE)
    assert good is not None and good.delivered_mate


def test_fork_is_explained(analyzer):
    analysis = analyzer.analyse_game(read(FRIED_LIVER))
    moments = [build_moment(m).to_dict() for m in select_moments(analysis, chess.WHITE, 3)]
    a3 = next(m for m in moments if m["played"] == "a3")
    assert "fork" in a3["themes"]
    assert any("king on e1" in s and "rook on a1" in s for s in a3["sentences"])


def test_template_notes_always_pass_the_verifier(analyzer):
    review = review_game(
        read(FRIED_LIVER), settings=settings(), llm=NoModelClient(), color=chess.WHITE, analyzer=analyzer
    )
    assert review["stats"]["template_notes"] == len(review["moments"]) + bool(review["good_moment"]) + 1
    for moment in review["moments"]:
        assert verify_moment(moment["note"], moment) == []


def test_hallucination_is_caught_and_retried(analyzer):
    bad = {"headline": "Oops", "explanation": "Nc6 was better. It was mate in 3.", "question": "Why?", "tip": "Think."}
    good = {
        "headline": "The f7 square was weak",
        "explanation": "After Nf6, your opponent has Qxf7# straight away.",
        "question": "What was the queen attacking?",
        "tip": "Look at your opponent's checks first.",
    }
    other = {
        "headline": "Keep going",
        "explanation": "Good effort here.",
        "question": "What did you notice?",
        "tip": "Take your time.",
    }
    summary = {
        "summary": "[STUDENT] lost quickly.",
        "strengths": ["Developed a knight."],
        "focus": ["Look for checks."],
        "homework": "Solve mate in 1 puzzles.",
        "parent_note": "[STUDENT] is learning to spot threats.",
    }
    nf6_calls = []

    def reply(user):
        if "FACTS about the whole game" in user:
            return summary
        if "3... Nf6" in user:
            nf6_calls.append(user)
            return bad if len(nf6_calls) == 1 else good
        return other

    review = review_game(
        read(SCHOLARS_MATE),
        settings=settings(),
        llm=ScriptedClient([reply]),
        color=chess.BLACK,
        student_name="Riya",
        analyzer=analyzer,
    )
    moment = next(m for m in review["moments"] if m["played"] == "Nf6")
    assert moment["note_source"] == "model"
    assert moment["attempts"] == 2
    assert moment["hallucinations_caught"] == 2  # the invented move and the wrong "mate in 3"
    assert "broke the rules" in nf6_calls[1]  # the retry tells the model what was wrong
    assert review["summary"]["parent_note"] == "Riya is learning to spot threats."


def test_model_errors_fall_back_to_templates(analyzer):
    client = ScriptedClient([LLMError("couldn't reach Ollama")])
    review = review_game(read(SCHOLARS_MATE), settings=settings(), llm=client, color=chess.BLACK, analyzer=analyzer)
    assert all(m["note_source"] == "template" for m in review["moments"])
    notes = len(review["moments"]) + bool(review["good_moment"]) + 1
    assert client.calls == notes  # connection errors are not retried


def test_report_and_annotated_pgn(analyzer):
    review = review_game(
        read(SCHOLARS_MATE), settings=settings(), llm=NoModelClient(), color=chess.BLACK, analyzer=analyzer
    )
    html = render_standalone(review)
    assert "Note for parents" in html and "<svg" in html
    node = chess.pgn.read_game(io.StringIO(review["annotated_pgn"]))
    for _ in range(6):
        node = node.next()
    assert node.san() == "Nf6"
    assert chess.pgn.NAG_BLUNDER in node.nags
    assert node.comment
    assert len(node.parent.variations) == 2  # the game move plus the better move
