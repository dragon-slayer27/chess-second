import pytest

from second.verify import Allowed, check_text, verify_moment, verify_summary

MOMENT = {
    "kind": "mistake",
    "allowed_sans": ["Nf6", "Qxf7", "g6", "Qf3", "Qe7"],
    "allowed_squares": ["e1", "f6", "f7", "g6", "g7", "g8", "h5"],
    "allowed_pieces": ["king", "knight", "pawn", "queen"],
    "mates": [1],
    "min_move_number": 2,
    "max_move_number": 6,
}

GOOD_NOTE = {
    "headline": "Watch the f7 square",
    "explanation": "After Nf6, your opponent plays Qxf7# and it is checkmate. g6 would have blocked the queen on h5.",
    "question": "What was the queen on h5 attacking?",
    "tip": "Always look at your opponent's checks.",
}


def kinds(issues):
    return {issue.kind for issue in issues}


def test_clean_note_passes():
    assert verify_moment(GOOD_NOTE, MOMENT) == []


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Nc6 was a better move.", "fabricated_move"),
        ("Your bishop on b5 was loose.", "unknown_square"),
        ("After that you lose your rook.", "wrong_piece"),
        ("White had mate in 2.", "wrong_mate"),
        ("On move 14 things went wrong.", "wrong_move_number"),
        ("The position is +3.5 for White.", "invented_number"),
        ("Stockfish says this is bad.", "mentions_engine"),
        ("Avoid the back-rank trap.", "wrong_tactic"),
        ("The queen sacrifice worked.", "wrong_tactic"),
        ("Your knight was pinned.", "wrong_tactic"),
        ("Watch out for a discovered attack.", "wrong_tactic"),
    ],
)
def test_hallucinations_are_caught(text, kind):
    assert kind in kinds(check_text(text, Allowed.from_moment(MOMENT)))


def test_tactic_words_are_allowed_when_the_facts_have_them():
    moment = {**MOMENT, "sentences": ["Nf6 allows a fork."], "themes": ["fork"]}
    assert check_text("Your opponent had a fork.", Allowed.from_moment(moment)) == []


def test_checkmate_claims_need_a_mate_in_the_facts():
    no_mate = {
        **MOMENT,
        "mates": [],
        "sentences": ["You lose about 3 points of material."],
        "themes": ["loses material"],
    }
    allowed = Allowed.from_moment(no_mate)
    assert "wrong_tactic" in kinds(check_text("This move allowed checkmate.", allowed, claims_mate=True))
    assert check_text("Always look for checkmate threats.", allowed) == []  # advice, not a claim


def test_castling_written_with_zeros_is_normalised():
    allowed = Allowed.from_moment({**MOMENT, "allowed_sans": [*MOMENT["allowed_sans"], "O-O"]})
    assert check_text("Castle with 0-0 first.", allowed) == []


def test_missing_and_overlong_fields():
    note = {**GOOD_NOTE, "tip": "", "explanation": "x" * 800}
    assert {"missing_field", "too_long"} <= kinds(verify_moment(note, MOMENT))


SUMMARY = {
    "summary": "[STUDENT] attacked fast but missed a threat to the king.",
    "strengths": ["Brought the queen out with a clear plan."],
    "focus": ["Check every capture your opponent can make."],
    "homework": "Solve 10 mate in 1 puzzles.",
    "parent_note": "[STUDENT] played bravely today and is learning to spot threats.",
}


def test_summary_passes_and_list_fields_accept_strings():
    assert verify_summary({**SUMMARY, "focus": "Check captures."}, [MOMENT], "English") == []


def test_parent_note_must_not_contain_notation():
    note = {**SUMMARY, "parent_note": "[STUDENT] should have played g6."}
    assert "notation_in_parent_note" in kinds(verify_summary(note, [MOMENT], "English"))


def test_parent_note_language_script_is_checked():
    english = verify_summary(SUMMARY, [MOMENT], "Hindi")
    hindi = verify_summary(
        {**SUMMARY, "parent_note": "[STUDENT] ने आज बहुत अच्छा खेला और खतरों को पहचानना सीख रहा है।"},
        [MOMENT],
        "Hindi",
    )
    assert "wrong_language" in kinds(english)
    assert hindi == []
