# Self-checking volleyball scouting, evolved by coding agents

## ▶ [Open the interactive evolution site](https://thomasbradley99.github.io/clann-volleyball/evolve.html#1)

A volleyball scout tags every touch of a match by hand: the time, the action, the team and the
shirt number. That takes hours per match. This system watches the match video with Gemini 4 Argon
and produces the same sheet. It was then improved by an evolutionary loop in which coding agents
rewrite the whole system and only changes that hold on unseen play are kept.

## Results (scored against a human scout, one full match)

Score = the mean of four F1 tiers: touch found within ±1 s, + right action, + right team,
+ right shirt number.

| | set 1 (errors shown to agents) | set 2 (scores only) | **set 3 (never seen)** |
|---|---:|---:|---:|
| starting system | 0.807 | 0.819 | 0.783 |
| evolved system | 0.871 | 0.873 | **0.842** |

On set 3:
- **Time:** 0.905.
- **Action:** 0.884.
- **Team:** 0.884.
- **Number:** 0.695.
- **Missed touches:** 13 down to 9.
- **Invented touches:** 17 down to 9.

The evolved system is also cheaper to run than the one it started from. The gain on the training
sets held on set 3.

## How the evolution works

1. **The genome is a program.** The whole system is one Python file, `analyse(match) -> events`,
   built from a fixed toolbox: watch a clip, watch a cropped few seconds, ask a question. Every
   call is metered.
2. **Coding agents do the mutation.** Each generation, three agents (focused on accuracy, cost
   and structure) each take a copy. Each reads the errors, tests ideas, edits the code and submits
   it with a hypothesis and a predicted score.
3. **Selection only counts unseen play.** Agents see the errors from set 1. Set 2 is a gate they
   only see as a score: a change is kept only if it improves overall and set 2 does not drop.
   Set 3 is used once, at the end. Code that hard-codes match times, or reaches outside its
   sandbox, is rejected before it runs.
4. **Knowledge carries forward.** Every agent is briefed with every earlier attempt: its
   hypothesis, its change, its prediction, its result and its verdict. Later agents build on what
   worked and avoid what failed.

An earlier version evolved only a prompt and was judged on training data. It reached 0.907 by
memorising this match: it hard-coded timestamps and shirt numbers. That failure is why the
current loop has held-out gates and code checks.

## What the agents discovered

- **The rules of volleyball show where the system is wrong.** A rally cannot end on a dig, and an
  attack cannot be answered by the other team without a dig. The system finds such spots in its
  own output and re-watches only those seconds.
- **A shirt number that is not on the team sheet is wrong for certain.** The team sheet is read
  from the video first. A number that is not on it gets a zoomed re-read that must choose from
  the sheet.
- **Use a cheap model as a gatekeeper, not a scout.** The cheap model is good at "is a point
  being played?", so breaks and warm-ups are skipped. Every attempt to let it find the rallies
  lost accuracy.
- **Frames are both the cost and the accuracy.** Cutting frames or thinking always cost shirt
  numbers. Re-checking everything cost more than it gained. Only targeted re-checks paid off.

## The final system

```
team sheet     shirt numbers per side, read from the video once
live_clips     cheap model drops clips with no play
scout          Argon watches each clip and logs every touch
merge          removes duplicates from overlapping clips
fill_rallies   finds rule-breaking spots, re-watches just those seconds
fix_numbers    off-sheet numbers get a zoomed re-read, chosen from the team sheet
```

One wide pass, then the system checks its own output against the rules and the roster, and spends
more only where something is provably wrong. Nothing in it is specific to this match.

**Limits:** it is validated on one match so far (one camera, one venue, one pair of teams).
Shirt number is the weakest tier.

## Setup

```
pip install -U google-genai          # plus ffmpeg on PATH
echo "GEMINI_API_KEY=..." > .env
python3 team_sheet.py                # read shirt numbers per side from the video
python3 evo5_kit/evaluate.py         # score a system.py against the scout sheet
python3 evo5_kit/code_evolve.py --gens 5   # run the evolution (needs Claude Code for the agents)
```

The match video and the scout's sheet are not included in the repo.

## Repo

| Path | What it is |
|---|---|
| `scout/` | **run it**: standalone `scout_match.py` (video in, sheet out), Lambda handler, Dockerfile, `HANDOFF.md` |
| `final_system.py` | the evolved system |
| `results/` | every candidate's score and verdict, the agents' notes, set-3 hold-out scores |
| `evo5_kit/` | the evolution loop (`code_evolve.py`), the toolbox, the evaluator, the sandbox smoke test |
| `evo5_page.py` | builds the evolution site: one dot per system, click for the code diff and the agent's report |
| `team_sheet.py` | reads the shirt numbers per side from the video |
| `score.py` | the scorer: maximum matching against the scout's sheet |

Next: a second match with a different venue and camera, then the same loop on Gaelic football.
