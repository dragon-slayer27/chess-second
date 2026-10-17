# Evaluation: does Second stop Gemma from inventing chess?

- Model: gemma4:e4b-it-qat via Ollama on this computer
- Engine: Stockfish 19, depth 14
- Data: 16 rated blitz/classical games between 1000-1700 players from the CC0 [Lichess database](https://database.lichess.org) (January 2013), 29 blunders and mistakes.
- Hardware: Intel Core Ultra 5 125H laptop, 16 GB RAM, Intel Arc iGPU via Vulkan
- Run on 2026-10-17, total time 19.9 minutes.

| | Plain Gemma (moves + "explain this mistake") | Gemma + engine facts (first answer) | Second (facts + verifier + retries) |
|---|---|---|---|
| Notes that suggest a concrete move | 14/29 (48%) | 29/29 (100%) | 29/29 (100%) |
| ...and it is Stockfish's better move | 0/29 (0%) | 29/29 (100%) | 29/29 (100%) |
| Notes with a piece move that isn't even legal | 7/29 (24%) | 0/29 (0%) | 0/29 (0%) |
| Notes with a chess claim the engine didn't confirm | 18/29 (62%) | 0/29 (0%) | 0/29 (0%) |
| Median time per note | 11.9s | 12.2s | 12.2s |

Second needed a retry for 0/29 (0%) of notes and fell back to the plain template for 0/29 (0%).
With the facts in the prompt, Gemma's first answer passed the verifier every time in this run, so the verifier never had to step in. It is there for the times grounding isn't enough; `tests/test_verify.py` shows what it catches.

Kinds of unconfirmed claims (number of notes):

| Kind | Plain Gemma | Gemma + facts |
|---|---|---|
| fabricated move | 14 | 0 |
| unknown square | 4 | 0 |
| wrong piece | 1 | 0 |

## Examples

**34. b7** (blunder, [game](https://lichess.org/96xfi0hj)). Stockfish's better move: **Ke2**.

- Plain Gemma: "Pushing the pawn to b7 lets Black win the exchange after ...Rxb7. A better move would have been to improve your pieces instead, like Rc1." (not legal on the board: Rc1)
- Second: "After you played b7, your rook on a7 was attacked by the bishop on d4 and had no defense. Playing Ke2 would have been a much better move for you."

**34... b5** (blunder, [game](https://lichess.org/x3v33r24)). Stockfish's better move: **Kf7**.

- Plain Gemma: "Black's move 34... b5 opens up the queenside for White's passed pawn. Instead, Black should have played something like 34... Rd2 to challenge White's position." (not legal on the board: Rd2)
- Second: "After you played b5, your opponent found a line where you would lose about 3 points of material. Playing Kf7 instead would have been a much better move for you."

**14. g4** (blunder, [game](https://lichess.org/o09d3jdb)). Stockfish's better move: **Nxh6**.

- Plain Gemma: "Moving your pawn to g4 weakens your king's safety and gives Black an easy target. A better move would have been to play 14. Nf7, putting more pressure on Black's position." (not legal on the board: Nf7)
- Second: "After your move g4, the game became bad for you. If you had played Nxh6 instead, you would have won about 2 points of material."


"Unconfirmed" means the note mentions a move, square, piece, mate-in-N, move number or evaluation that is not
in the engine facts for that moment. A plain chatbot can occasionally suggest a reasonable move the engine
didn't list, so the stricter row is the one about moves that are not legal on the board at all.
By construction, nothing unconfirmed reaches a student in Second: failed notes are retried, then replaced by a template.

Every note and score is in `results.json`.
