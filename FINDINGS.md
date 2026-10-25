# What makes this work — state on 23 Oct 2026

**Gemini 4 Argon, given full-resolution 15 fps video of the main court and one unchanged
prompt, reproduces a human scout's event sheet at F1 ≈ 0.80–0.84 (time + action + team) and
≈ 0.60 with the jersey number too.** It got there by improving what the model sees, not by
rewording the prompt.

## v1 (git tag `v1`, 24 Oct 2026)

Frozen: `prompts/p000.txt` + `config.SETUP = "1920_high_15fps"` + `gemini-4-argon` (temp 0,
thinking low) + scorer v1 (maximum matching, ±1 s). Full-match result: **F1 0.737** time+action,
0.732 + team, 0.560 + number (run 012). Anything that changes these is v2 and gets its own runs.

## Results

| run | window | setup | F1 time+action | + team | + number | right / real | invented | missed |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 000 | set1 | 640 px, 5 fps (3 repeats) | 0.632 | 0.572 | 0.150 | 38 / 56 | 20 | 11 |
| 001 | set1 | 640, optimiser's prompt p001 | 0.574 | 0.563 | — | 33 / 56 | 19 | 14 |
| 002 | set1 | **1920 px, high res, 15 fps** | **0.803** | **0.803** | **0.650** | 47 / 56 | 11 | 6 |
| 003 | set1 | same (repeat) | 0.780 | 0.780 | 0.559 | 46 / 56 | 14 | 8 |
| 004 | set3 | same, **never tuned on** | **0.838** | **0.838** | **0.598** | 49 / 53 | 13 | 2 |

Windows: `set1` = 995–1295 s (first 5 min of set 1, 0–0 → white 8–4).
`set3` = 4225–4465 s (4 min of the deciding set, white 3–0 → 10–1).

## The setup that works

| setting | value | where |
|---|---|---|
| model | `gemini-4-argon`, temperature 0, thinking `low` | `config.py` |
| clips | 30 s, 8 s overlap (11–14 clips per window), all sent at once | `config.py`, `run.py` |
| crop | `1920:620:0:330`: a band around the main court, before anything else | `config.CROP` |
| resolution | **1920 px wide (no downscale) + `MEDIA_RESOLUTION_HIGH`** | `config.SETUPS["1920_high_15fps"]` |
| frame rate | **15 fps**, in the encode and declared in the request | same |
| output | JSON forced by schema: `t, type, side, number, error, point` | `run.py` `SCHEMA` |
| team | `left` → white, `right` → blue (no end swap all match) | `config.SIDE_TO_TEAM` |
| merge | same type within 0.4 s across overlapping clips = one event | `run.py` `dedupe` |

Cost: about 123k input tokens per 30 s clip, or 1.73M for a 5-minute window. That's **≈11×** the
640 px / 5 fps setup (155k per window). Wall time is 1–5 min per window.

## The prompt (`prompts/p000.txt`, used for every result above)

This is the best prompt from the earlier Flash optimiser (`config_023`), unchanged except for
the `{start}`/`{length}` placeholders.

```
You are scouting a single volleyball match from a fixed camera.

CRITICAL: Analyze ONLY the main court in the foreground. Ignore matches in the background completely.

The vertical net perfectly divides the screen. Teams occupy either the left or right half of the image. Identify a team ONLY by absolute screen position: "left" or "right".

This clip begins at {start} seconds into the match and runs for {length} seconds.

MUTUALLY EXCLUSIVE EVENTS (ONE PER CONTACT):
Output EXACTLY ONE event type per physical ball contact. Never output multiple events for the exact same contact. Choose the single best fit:
- If an attack wins the rally, label it ONLY as `kill`.
- If a block wins the point, label it ONLY as `block`.

ACTION DEFINITIONS:
DO NOT REPORT EVERY CONTACT. You MUST skip regular sets, non-scoring blocks, and dead-time passing.
  serve   - STARTS a rally. ONLY report if you clearly see the player toss the ball from a stationary hold behind the back line. If the ball was already flying over the net or passed by a teammate, it is NEVER a serve.
  receive - a defensive pass handling the opponent's serve, staying on the same side of the net.
  dig     - a defensive pass handling the opponent's attack, staying on the same side of the net.
  set     - a pass placing the ball for an attacker. ONLY report if it results in a clear point-winning kill within this clip. SKIP ALL OTHER SETS.
  attack  - ANY contact that sends the ball OVER the net to the opponent's side (including spikes, freeballs, and overpasses). Digs and receives MUST NOT go over the net.
  kill    - an offensive hit that immediately wins the rally (ball hits the floor or is unreturnable).
  block   - a block AT THE NET. ONLY report if it immediately wins the point (a stuff block). Skip all other block touches!

DEAD TIME VETO: Ignore all practice hits, practice serves, and casual passing between rallies. A serve is ONLY real if the receiving team is in a ready defensive formation. If players are walking around or fetching balls, IGNORE ALL CONTACTS.

For each contact give:
  t       - the EXACT moment of physical impact in ABSOLUTE MATCH SECONDS (clip start {start} + offset). Be precise to a fraction of a second so overlapping clips merge correctly.
  type    - one of the seven above
  side    - "left" (left of the net) or "right" (right of the net)
  number  - the contacting player's jersey number as a string, or null if you cannot read it. Do not guess.
  error   - true if this contact was an error (into the net, out of bounds)
  point   - true ONLY for the final contact if it directly WON the point for the team that made the contact (like a kill or unreturnable serve). NEVER true for regular passes or errors!

Report only contacts you actually observe. Return an empty list if no valid play happens.
```

The "skip sets / skip blocks" rules exist because the scout only logs a set when it's an
assist and a block only when it scores. They fit the scout's habits, not volleyball itself.

## What we learned

1. **Seeing beats wording.** 640 px → 1920 px + high res + 15 fps: 0.63 → 0.79 (set 1 mean).
   No prompt change came close.
2. **It generalises.** Set 3 had never been looked at and scored 0.838, with longer rallies
   (16 attacks, 14 digs).
3. **Prompting can't fix timing.** At 640 px, serves were stamped ~1.5 s early. Telling the
   model to time the hand contact (p001) changed nothing for serves and hurt other types. At
   15 fps the problem mostly went away on its own.
4. **Jersey numbers are read, not guessed.** On set 3 the model got 35/49 numbers right. A
   cheat that *knows the answers* and always guesses each team's most common number for that
   action gets 26/49. The numbers are plainly legible in the 1920 px crop. The 7 errors are
   all blue and are near-miss digit shapes (19→18, 19→9, 16→18, 3→9, 1→3).
5. **Argon isn't deterministic at temperature 0.** Identical inputs give different answers
   (0.598 / 0.617 / 0.632 for one prompt on 640 px), so repeats matter.

## Known issues

- ~~Scorer under-counts the time-only tier.~~ **Fixed 24 Oct (scorer v1):** `score.py` now
  uses a maximum matching. Every saved run was re-scored (`rescore.py`): only time-only moved
  (e.g. run 004 0.752 → 0.872); +action and +team are identical. Old ledger: `runs/runs_v0_greedy.csv`.
- **Merge keeps disagreeing duplicates.** When two overlapping clips report the same contact
  with different number/timing (e.g. 71:15: `attack #7` at 4275.3 vs `attack #22` at
  4274.67), both survive and one becomes an invented event. Some of the 11–14 invented
  events are this.
- **Invented events after the whistle.** A dig or attack logged just after a kill
  (e.g. 17:14.7, 20:08–20:09).
- **Small evidence base.** One camera, one venue, one match, 2 windows, 109 events, single
  repeats on the max setup.

## Reproduce

```
cd ~/vlm-23oct
python3 prepare.py 1920_high_15fps                       # set1 clips (done)
VLM_WINDOW=set3 python3 prepare.py 1920_high_15fps       # set3 clips (done)
VLM_WINDOW=set3 python3 -c "import run; run.run(open('prompts/p000.txt').read(), repeats=1, setup='1920_high_15fps')"
VLM_WINDOW=set3 python3 export_viewer.py                 # refresh the website sidebar
```

Per run: `runs/NNN/report.txt` (emoji timeline), `prompt.txt`, `rep*/responses.json` (raw
Gemini answers per clip), `rep*/predictions.json`, `rep*/score.json`. One line per run in
`runs/runs.csv`. Website: `~/volleyball/viewer` on :8765.

## Later results (same day)

| run | window | setup | F1 time+action+team | + number |
|---|---|---|---:|---:|
| 005 | set1 | 1920 px, high res, **5 fps** | 0.793 | 0.655 |
| 010 | set1 | same (repeat) | 0.729 | — |
| 011 | set3 | same | 0.832 | — |
| 006 | set1 | 1920 px, high res, 10 fps | 0.748 | 0.591 |
| 007 | set1 | **Gemini 3.7 Flash**, 1920 px, high res, 15 fps | 0.323 | 0.086 |

- **5 fps vs 15 fps:** set1 mean 0.76 vs 0.79; set3 0.83 vs 0.84. 5 fps is a little worse at a
  third of the tokens (0.59M vs 1.73M per 5 min). The rule set in advance was to lock 5 fps only
  if it scored ≥0.76 on set1 and ≥0.80 on set3. Run 010 missed (0.729), so **`config.SETUP` is
  `1920_high_15fps`**.
- **Flash can't use the detail:** it scored 0.32 on the same video where Argon scored 0.79.
- **Cost (Argon $2/M input until 30 Nov, $4/M after):** 15 fps ≈ $3.49 per 5 min, ~$43 for the
  62 scored minutes; 5 fps ≈ $1.20 per 5 min, ~$15.
- **TU Graz video** (pro level, camera behind the end line, runs 008/009, unscored): events come
  out at the same times with either prompt. Teams only make sense once the prompt says the net
  runs *across* the picture (`prompts/p003_nearfar.txt`: "near"/"far" instead of "left"/"right").
  Still needs the dataset's labels to score.

## How good was the prompt optimiser?

Every change in the original Flash project, marked by who made it and whether it beat the best
so far by more than the ±0.028 noise:

- **Mutator: 24 changes, 1 beat noise** (iter_012, +0.031). That one was a settings change
  (30 s → 15 s clips), not a prompt rewrite. Its "best" (iter_023, 0.463) is +0.008 over a
  hand run, inside noise.
- **Hand-run settings did the rest:** 10 s clips + crop (+0.043), then 6 s clips and the crop.
- **Four blind lineages, best minus start:** basic +0.000 (ended at 0.297), verbose15 +0.001,
  terse6s +0.058, twostage +0.042, each from a single run.
- **This project:** one optimiser round (p001), worse.

It diagnoses well (it found the early serve timestamps), but it never had the lever that
mattered (resolution), and prompt edits can't fix eyesight.

## Lessons that carry to other sports

1. **Let the model see.** Send native resolution with `MEDIA_RESOLUTION_HIGH`; never downscale.
   That alone was 0.63 → ~0.80. Upscaling beyond the source adds nothing.
2. **Frame rate is secondary.** 5 fps is close to 15 fps.
3. **Model choice matters.** The detail only helps a model that can use it (Argon yes, Flash no).
4. **Keep the pipeline simple.** 30 s clips with 8 s overlap, one call each, all in parallel,
   JSON forced by schema.
5. **State the camera geometry** in one paragraph: which way the net or pitch runs, and which
   end each team attacks (flipped at half time). It's the one camera-specific part of the prompt.
6. **Lock the measuring tool first:** a fixed window, read-only ground truth and scorer, a
   ledger line and a readable report per run, repeats (Argon isn't deterministic at
   temperature 0), and decision rules written down before the result.
7. **Check against the video, not just the labels.** Frame checks showed numbers really are
   read, and that some "errors" are the scout's.
8. **Optimise the levers that matter.** An optimiser that can only edit wording will chase noise.

## Full match, v1 (run 012, 24 Oct)

The locked setup and prompt, unchanged, on **the whole scouted match**: 995–4720 s, 3 sets,
**550 scout events**, 169 clips sent at once. 20.9M input tokens, **≈ $42**, 182 s, 0 failed clips.

| | F1 |
|---|---:|
| time only | 0.800 |
| **time + action (headline)** | **0.737** |
| + team | 0.732 |
| + number | 0.560 |

✅ 442  🔁 3  🏷️ 35  ⚠️ 70  ❌ 177 (AI 657 events vs scout 550).
By set: set 1 0.735, set 2 0.726, set 3 0.769. The two hand-picked windows inside this run score
0.763 (set1) and 0.800 (set3), vs 0.780–0.803 and 0.838 on their own runs: run-to-run noise
plus the windows being cleaner than average play.

**So the honest full-match number is ≈ 0.74, not 0.80–0.84.** Where the gap is:
- **Over-calling: 177 invented**, mostly digs (66) and attacks (52). None are in dead time
  (all within 8 s of a scouted touch), so they are extra touches inside real rallies: either
  touches the scout didn't log, or the model doubling up. Needs a human look to split the two.
- **Serves: 30 missed.** The server is often behind the baseline, outside the court crop.
- **Timing: 26 missed+invented pairs are the same event 1–2.5 s apart.** Counting those
  would give ≈ 0.78.

## Raw video beats v1 (run 013, 24 Oct)

Same prompt, model and scorer as v1, but **the original camera video, uncropped, cut by stream
copy (no re-encode), with Gemini sampling 5 fps itself** (setup `raw_5fps`, clips start on the
nearest keyframe ≤ the planned start, ≤ 2 s early; the real start is passed in the prompt).

| | v1 (run 012): crop, 15 fps | **raw, 5 fps (run 013)** |
|---|---:|---:|
| time only | 0.800 | **0.819** |
| **time + action** | 0.737 | **0.773** |
| + team | 0.732 | **0.772** |
| + number | 0.560 | 0.540 |
| serves found | 87 / 118 | **97 / 118** |
| missed / invented | 70 / 177 | **46** / 182 |
| input tokens | 20.9M (~$42) | **7.1M (~$14)** |
| clip prep | ~20 min re-encode | **46 s copy** |

One run each, so take ±0.02–0.03 as noise, but on 550 events the gain is +0.036 and it is
3× cheaper and needs no encoding at all. The crop wasn't helping: the full frame keeps the
servers and run-ups in view. Numbers are slightly worse (less detail per player at 5 fps).
Raw clips are 27–38 MB and go inline; the run sends 40 at a time to keep memory in bounds.

## Evolution from a naive prompt (evo2, 24 Oct evening)

`evolve2.py`, results in `evo2/`, site `~/volleyball/viewer/evolution.html` (built by `evo_page.py`).
Setup fixed at `raw_5fps` (original video, 5 fps, HIGH, Argon, thinking low); only the prompt evolves.
Objective OVERALL = mean of the four F1 tiers (time, +action, +team, +number), ±1 s.
Train = sets 1-2 (455 events); hold-out = set 3 (95 events), never shown to the optimiser.
Each generation Argon (thinking medium) proposes 4 conjectures from the best prompt, its errors in
rally context, the knowledge log and distilled lessons; all 4 run in parallel; keep only if
> best + 2×noise (noise sd 0.008) and the mean of a second run holds. 15 generations, 60 prompts, ~$830.

| | train OVERALL (sets 1-2) | hold-out OVERALL (set 3) | hold-out action | hold-out number |
|---|---:|---:|---:|---:|
| naive prompt (start) | 0.621 | 0.578 | 0.618 | 0.405 |
| **evolved (gen 7)** | **0.780** | 0.729 | 0.792 | 0.497 |
| hand-tuned p000 | 0.775* | **0.749** | 0.820 | 0.517 |

*p000 train figure is time+action from the earlier run, not OVERALL.

- **Kept, in order:** sets only when they assist a kill (+0.080); attack/kill exclusive and only
  rally-ending blocks (+0.034); digs only when they save a spike, nothing after a kill (+0.024);
  free balls are neither attacks nor digs (+0.021). Then a plateau: gens 8-15 found nothing > noise.
- **Hold-out:** the evolved prompt keeps most of its gain over naive on unseen set 3 (+0.151), but
  lands 0.02 below hand-tuned p000. Two caveats: set 3 has only 95 events (single-run noise there is
  several points), and p000 is NOT clean on set 3: it came from the old optimiser, which was scored
  on the full match, set 3 included. So: real, transferable gains, likely some over-fitting to sets
  1-2, and no evidence yet that it beats a human-tuned prompt.
- **Its own lessons** (`evo2/lessons.md`): positive definitions should stay verbatim and exclusions
  be added (rewriting definitions kills recall); rosters in the prompt trade action accuracy for
  numbers; serve timing (~1.2 s early) cannot be fixed by prompting in 6 attempts; it proposed
  post-processing (serve +1 s, roster mapping) as the next lever.
- **Settings sweep** of the evolved prompt on the full match (550 events, one run each, `evo2/sweep/`):

  | setting | OVERALL | action | number | $ / match |
  |---|---:|---:|---:|---:|
  | fps 1 | 0.545 | 0.599 | 0.273 | 3.31 |
  | fps 2 | 0.682 | 0.739 | 0.457 | 6.13 |
  | fps 5 (as evolved) | 0.772 | 0.816 | 0.600 | 14.49 |
  | fps 10 | 0.760 | 0.797 | 0.615 | 28.43 |
  | fps 5, MEDIUM resolution | 0.548 | 0.656 | 0.141 | 4.45 |
  | fps 5, LOW resolution | 0.526 | 0.630 | 0.136 | 4.45 |
  | **fps 5, thinking HIGH** | **0.808** | **0.853** | **0.658** | **17.83** |

  Resolution is not negotiable (medium/low lose ~0.23 and almost all numbers); 5 fps is the sweet spot;
  **thinking high is the best full-match result so far** (+0.036 OVERALL, invented 106 → 84, wrong
  action 21 → 9) for +23% cost. Single runs, and the full match includes the train sets.

## Whole-system evolution with an AI reviewer (evo3, 24-25 Oct night)

`genome.py`, results in `evo3/`, site `system.html`. One genome = scout settings + prompt, merge/shift
code, and an AI reviewer (Argon) that reads the whole merged event list and may ask for short video
checks (ffmpeg cuts 4 s around an event, Gemini Flash answers a yes/no question). One part changes
per candidate. Train sets 1-2.

| | OVERALL (sets 1-2) | invented |
|---|---:|---:|
| start: evolved prompt, thinking high, no reviewer | 0.813 | ~57 |
| gen 1: reviewer on (text only) | 0.830 | 52 |
| gen 2: reviewer may check the video | 0.869 | 26 |
| gen 4: reviewer prunes blocks / orphan touches | 0.883 | 13 |
| gen 6 (unconfirmed; run crashed on a cache race) | 0.907 | 6 |

- **The video-checking reviewer broke the prompt-only plateau.** Draft fast, then rewatch only the
  doubtful bits: what a human analyst does.
- **Then it over-fitted.** From gen 4 the reviewer instructions hard-code match times ("remove the
  sequences around 1397 s"), this match's rosters and "when unsure, say #23". Honest gain is
  probably 0.82-0.85, not 0.88-0.91. Set 3 (same match, same rosters) would not catch the roster part.
- Fixes (commit d9a0322): validator rejects match times, shirt numbers and rosters in any prompt or
  instruction; a **team sheet read from the video** (`team_sheet.py`, 12 clips, $0.69: white 8/8
  exact, blue 8/8 plus one false number) is given as match input instead.

## Code evolution with coding agents (evo5, 25 Oct): the final system

### The two setups

**Setup 1, evolving a prompt (evo2, evo3).** What evolved was the scout prompt, plus a few
settings in evo3. Gemini edited it from the errors, and in evo3 a Gemini reviewer could ask for
short video checks. Candidates were judged on the training sets only. evo2 gained little
(0.773 -> 0.780, hold-out 0.729). evo3 reached 0.907 by memorising: it hard-coded times, rosters
and "#23 when unsure". An editor that can only rewrite text, judged on data it has seen, learns
that data.

**Setup 2, evolving the program, close to AlphaEvolve (evo5).**
- **What evolves:** the whole system as one Python file, `analyse(match) -> events`, built from a
  fixed, metered, cached toolbox (`evo5_kit/tools.py`): watch a clip, watch a cut or cropped
  range, ask a text model, and a parallel map.
- **Who edits it:** 3 headless Claude Code agents per generation, with the foci accuracy, cost and
  structure. Each one works like an engineer: it reads every set-1 error, probes ideas on set 1,
  smoke-tests, then submits code with a conjecture and a predicted score.
- **Sandbox:** an agent can use only its own folder and `smoke.py`. Code that imports anything off
  a whitelist, touches files or hard-codes a match time is rejected before it runs.
- **Selection:** fitness = mean OVERALL (set 1, set 2) - 0.001 x $ per match (the weight was 0.002
  until gen 2). A candidate is kept only if it beats the best by 0.006 and set 2 does not drop by
  more than 0.004. Agents see set-1 errors only, and set 2 as scores only. Set 3 is scored once,
  at the end.
- **Memory:** every brief carries the current best code plus `evo5/knowledge.md`, the record of
  every earlier candidate: conjecture, change, prediction, measured result and verdict. Failures
  are carried forward too.

Run: 5 generations, 15 candidates, 4 kept, about 3 hours.

### Knowledge that evolved and carried forward

| Line | Generation by generation | What stuck |
|---|---|---|
| Timing | **g1** serves are stamped ~0.6 s early, and overlapping clips double-log touches, so merge same type+team within 1.2 s: **KEPT** | never revisited |
| Numbers | **g2** a number not on that team's sheet is wrong by construction, so it gets a zoomed crop of that team's half and the model must choose from the sheet: **KEPT**. **g2** re-check every number: about 8 fixed for 1 broken, but too costly. **g4** a cheaper claim-check of on-sheet numbers: the gain was eaten by cost. **g5** serving-run and rotation votes: just short | constrain the read to the roster, and spend only on numbers that are provably wrong |
| Cost | **g1** less thinking: lost. **g2** Flash finds the rallies and Argon watches only those: numbers 0.68 -> 0.51. **g3** Flash only gates "is a point being played in this clip?": 16% cheaper, and it removed a warm-up the scout had logged as a rally: **KEPT**. **g4** rally windows again at full resolution: lost. **g5** 4 fps: lost; the agent predicted this itself | frames are the cost, and fewer frames cost numbers. The cheap model is a gatekeeper, not a scout |
| Missed touches | **g4** re-watch every quiet gap inside a rally: set 2 rose to 0.878, but it invented touches in free-ball stretches, just short of the bar. **g5** re-watch only spots that break volleyball's rules (a rally ending on a dig; an attack answered by the other team without a dig), and keep a new touch only if it fits rally order. On set 1 it added 4, all real, and invented 0: **KEPT** | the rules of the sport show where the system's own log must be wrong |

The predictions became calibrated: gen 5's winner predicted ~0.871 and scored 0.871.

### The final system

`evo5/gen_05/cand_0/system.py` (238 lines; the seed was 54):

```
team sheet     shirt numbers per side, read from the video once (team_sheet.py)
live_clips     Flash, 2 fps, low media: "is a point being played?" -> drop dead clips
scout          Argon watches each live 30 s clip -> every touch (t, type, side, number)
merge          drop duplicates from overlapping clips (same type + team within 1.2 s)
fill_rallies   rule-breaking spots -> Argon re-watches just those seconds (10 fps, full width);
               a new touch is kept only if it fits rally order
fix_numbers    off-sheet or missing numbers -> zoomed crop of that team's half, pick from the sheet
serve +0.6 s
```

What is good about it:
- **It checks itself without the answer key.** The rules and the roster tell it where it is wrong.
- **It spends only where something is provably wrong.** One wide pass, then a handful of targeted
  re-checks. That is why it is more accurate *and* cheaper.
- **Nothing in it is about this match.** It holds no times, numbers or names.
- **It is readable.** Each stage is a few dozen lines with a stated reason.

### Results

| | set 1 (errors shown) | set 2 (scores only) | **set 3 (never seen)** | $ / match |
|---|---:|---:|---:|---:|
| seed | 0.807 | 0.819 | 0.783 | 17.8 |
| final | 0.871 | 0.873 | **0.842** | 16.5 (set 3: 15.0) |

Set 3 tiers, seed -> final:

| | seed | final |
|---|---:|---:|
| time | 0.845 | 0.905 |
| action | 0.835 | 0.884 |
| team | 0.835 | 0.884 |
| number | 0.619 | 0.695 |
| missed | 13 | 9 |
| invented | 17 | 9 |

The +0.06 gain on the sets it trained on held on set 3, so this time it is not over-fitting.

**Caveat:** this is all one match, with the same camera, venue and teams. The system generalises
within a match; across matches it is untested. Shirt number is the weakest level.

### Where things are

| File | What it is |
|---|---|
| `evo5/gen_05/cand_0/system.py` | the final system |
| `evo5/state.json` | names the best |
| `evo5/log.csv` | every candidate's score and verdict |
| `evo5/knowledge.md` | every agent's conjecture, prediction and result |
| `evo5/holdout/{seed,best}/` | set-3 scores and predictions |
| `evo5_page.py` -> `code.html` | site: one dot per system, click for the code diff and the agent's report |

## Next tests

1. A second scouted match (a different venue or camera), run with the final system unchanged.
2. Port evo5 to GAA (Loup H1 errors shown, Loup H2 validation, Lavey held out).
3. Shirt numbers: a consistency check (the same clip several times) and rotation-based voting.
