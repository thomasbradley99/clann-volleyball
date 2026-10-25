"""Volleyball event detection: the whole system, as code. This file is what evolves.

Seed version: Gemini 4 Argon watches every 30 s clip (5 fps, high resolution, thinking high) with
the prompt evolved by evo2; overlapping clips are merged in code. No reviewer, no checks."""
import tools

PROMPT = """This is a volleyball match. This clip begins at {start} seconds into the match and runs for {length} seconds.

List every serve, receive, set, dig, attack, kill and block you see. Follow these logging rules:
- Do not log routine sets during a rally; only log a set if it directly precedes a point-winning kill.
- Only log a block if it is a stuff block that directly ends the rally; do not log block jumps or soft block deflections where play continues.
- Never log both an attack and a kill for the same hit: if the spike wins the point, log it only as a kill; otherwise log it as an attack. Only log actual spikes/attack hits; never log soft free-ball passes or standing bumps sent over the net as attacks.
- Only log a dig when a defender successfully keeps an opponent's attack in play; never log a routine free-ball pass or a failed defensive touch or shank after a point-winning kill.

For each one give:
  t      - the time in absolute match seconds (clip start {start} + offset)
  type   - serve, receive, set, dig, attack, kill or block
  side   - "left" or "right" of the net
  number - the player's shirt number, or null
  error  - true if it was an error
  point  - true if it won the point"""

SIDE_TO_TEAM = {"left": "white", "right": "blue"}
MERGE_WINDOW = 0.4     # same type within this many seconds across overlapping clips = one event


def scout(match):
    def one(clip):
        name, start, length = clip
        prompt = PROMPT.replace("{start}", f"{start:.2f}").replace("{length}", f"{length:g}")
        answer = match.watch(name, prompt, fps=5, media="high", thinking="high")
        return [dict(e, team=SIDE_TO_TEAM.get(e.get("side")), clip_start=start, clip_len=length)
                for e in answer.get("events", [])]
    return [e for evs in match.map(one, match.clips) for e in evs]


def merge(events):
    """Overlapping clips see the same touch twice: keep the copy furthest from its clip's edge."""
    def margin(e):
        off = e["t"] - e["clip_start"]
        return min(off, e["clip_len"] - off)
    out = []
    for e in sorted(events, key=lambda x: x["t"]):
        prior = next((o for o in reversed(out) if e["t"] - o["t"] <= MERGE_WINDOW and o["type"] == e["type"]), None)
        if prior is None:
            out.append(e)
        elif margin(e) > margin(prior):
            out[out.index(prior)] = e
    return out


def analyse(match):
    events = merge(scout(match))
    return [{"t": e["t"], "type": e["type"], "team": e["team"], "number": e.get("number")} for e in events]
