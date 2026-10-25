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
MERGE_WINDOW = 1.2     # same type + team within this many seconds = one touch (a team never repeats a
                       # touch type that fast; overlapping clips time the same touch up to ~1.1 s apart)
SERVE_LAG = 0.6        # the model stamps the serve at the toss; the scout stamps the hand-ball contact


LIVE_PROMPT = """This is a 30 second clip of a volleyball match video (fixed side-on camera).
Is any point of the match being played at any moment in this clip: a serve, or a rally in progress
(also a rally that is already under way when the clip starts, or that begins near the end)?
Answer false only if the whole clip has no match play at all: players standing or walking between
points, a timeout, a set break, warm-up or practice drills (pepper, hitting lines), or an empty court.
Reply as JSON: {"live": true/false, "what": "<one sentence>"}"""
LIVE_SCHEMA = {"type": "OBJECT", "properties": {"live": {"type": "BOOLEAN"}, "what": {"type": "STRING"}},
               "required": ["live", "what"]}


def live_clips(match):
    """Some clips hold no match play (long breaks, set breaks, warm-up between sets). The Argon scout
    costs ~$0.105 a clip and on warm-up drills it invents whole fake rallies (attack/dig chains with no
    readable numbers). A Flash look at 2 fps, low media (~$0.002 a clip) says whether any play
    happens; only those clips go to the Argon scout. Unsure answers keep the clip."""
    def one(clip):
        try:
            ans = match.watch(clip[0], LIVE_PROMPT, fps=2, media="low", thinking="low", model=tools.FLASH,
                              schema=LIVE_SCHEMA)
        except tools.BudgetExceeded:
            raise
        except Exception:
            return True
        return (ans or {}).get("live") is not False
    return [c for c, live in zip(match.clips, match.map(one, match.clips)) if live]


def scout(match):
    def one(clip):
        name, start, length = clip
        prompt = PROMPT.replace("{start}", f"{start:.2f}").replace("{length}", f"{length:g}")
        answer = match.watch(name, prompt, fps=5, media="high", thinking="high")
        return [dict(e, team=SIDE_TO_TEAM.get(e.get("side")), clip_start=start, clip_len=length)
                for e in answer.get("events", [])]
    return [e for evs in match.map(one, live_clips(match)) for e in evs]


def merge(events):
    """Overlapping clips see the same touch twice: keep the copy furthest from its clip's edge."""
    def margin(e):
        off = e["t"] - e["clip_start"]
        return min(off, e["clip_len"] - off)
    out = []
    for e in sorted(events, key=lambda x: x["t"]):
        prior = next((o for o in reversed(out) if e["t"] - o["t"] <= MERGE_WINDOW and o["type"] == e["type"]
                      and o["team"] == e["team"]), None)
        if prior is None:
            out.append(e)
        elif margin(e) > margin(prior):
            out[out.index(prior)] = e
    return out


def roster(sheet):
    """Regular shirt numbers per team from the team sheet: the list before the first ';' on each
    side's line ('also seen once' numbers are unreliable and left out)."""
    out = {}
    for line in sheet.splitlines():
        for team in ("white", "blue"):
            if f"({team})" in line and ":" in line:
                main = line.split(":", 1)[1].split(";")[0]
                nums = ["".join(c for c in tok if c.isdigit()) for tok in main.split(",")]
                out[team] = [n for n in nums if n]
    return out


NUMBER_PROMPT = """This is a side-on view of one half of a volleyball court ({side} side of the net, the {team} team).
About {at:.1f} seconds into this clip a {team} player makes a {type} (one touch of the ball).
Find that touch and read the shirt number of the player who touches the ball. Look at every frame
where the player's front or back is visible; the number is printed on the shirt.
The {team} team's shirt numbers are: {numbers}. Answer with one of these, or null if the number
cannot be read in any frame. Do not guess from position or role.
Reply as JSON: {{"number": "<number or null>", "seen": "<what you saw, brief>"}}"""
FRAME_W, FRAME_H = 16 * 120, 9 * 120   # the raw clips are 1920x1080
HALF_W = FRAME_W // 2 + 160         # one half of the court plus the net zone
CROP = {"white": (0, 0, HALF_W, FRAME_H), "blue": (FRAME_W - HALF_W, 0, HALF_W, FRAME_H)}  # white left, blue right
BEFORE, AFTER = 1.0, 1.5


def fix_numbers(match, events):
    """The clip scout reads shirt numbers from the whole 1920-wide frame and often reports a number
    that is not on either team sheet (or none). Re-read those touches from a 2.5 s cut of that
    team's half of the court, choosing from the team's sheet; keep the old number otherwise."""
    teams = roster(match.team_sheet)
    todo = [e for e in events if e["team"] in teams and teams[e["team"]]
            and str(e.get("number") or "") not in teams[e["team"]]]

    def one(e):
        side = "left" if e["team"] == "white" else "right"
        prompt = NUMBER_PROMPT.format(side=side, team=e["team"], at=BEFORE, type=e["type"],
                                      numbers=", ".join(teams[e["team"]]))
        ans = match.watch_range(e["t"] - BEFORE, e["t"] + AFTER, prompt, fps=10, width=HALF_W,
                                crop=CROP[e["team"]], model=tools.ARGON, thinking="medium",
                                schema={"type": "OBJECT", "properties": {"number": {"type": "STRING", "nullable": True},
                                        "seen": {"type": "STRING"}}, "required": ["number", "seen"]})
        n = "".join(c for c in str((ans or {}).get("number") or "") if c.isdigit())
        return n if n in teams[e["team"]] else None

    for e, n in zip(todo, match.map(one, todo)):
        if n:
            e["number"] = n
    return events


FILL_PROMPT = """This is a side-on video of a volleyball match, {length:.1f} seconds long (the white team plays on the
left of the net, the blue team on the right). A scout logged these touches in it (seconds from the start of this video):
{logged}
{why}
{task}
For each touch give:
  t      - the time in seconds from the start of this video
  type   - set, dig, attack, kill or block
  side   - "left" or "right" of the net
  number - the player's shirt number, or null
  error  - true if it was an error
  point  - true if it won the point"""
MISSING_TASK = """Watch the rally closely and list only the touches that are missing from the list above, between {lo:.1f}
and {hi:.1f} seconds. Use the scout's logging rules:
- Only log actual spikes/attack hits as attacks; never log soft free-ball passes or standing bumps sent over the net as
  attacks. If the spike wins the point, log it only as a kill.
- Only log a dig when a defender successfully keeps an opponent's attack in play.
- Do not log routine sets; only log a set if it directly precedes a point-winning kill.
- Only log a block if it is a stuff block that directly ends the rally.
If nothing is missing, return an empty list."""
AFTER_TASK = """Follow the ball after that dig, frame by frame, from {lo:.1f} to {hi:.1f} seconds, and list every touch of
the ball by either team until the ball is dead: each set, attack hit (any ball hit over the net), dig or block. Use
"kill" for an attack hit that wins the point. If the ball was in fact dead straight after the dig, return an empty list."""
RALLY_GAP = 9.0       # touches more than this far apart are not in the same rally
DIG_TAIL = 6.0         # after a rally-ending dig, look this far ahead for the touches that must follow it
ATTACK_REPLY = 7.0     # an attack answered by the other team's set/attack within this many seconds


def broken_rallies(events):
    """Spots where the logged touches break the rules of volleyball, so a touch must be missing:
    (1) a rally whose last logged touch is a dig: a logged dig kept the ball in play, so the same team
        plays it again; (2) an attack by one team followed by a set, attack or kill of the other team:
        the other team's first touch (its dig) is missing. Returns (lo, hi, why, anchor, task); times in
        match seconds. Holes that only break no rule (a quiet stretch after a receive or dig) are left
        alone: there the scout's sheet is often empty too (free balls are not logged)."""
    spots = []
    for i, e in enumerate(events):
        nxt = events[i + 1] if i + 1 < len(events) else None
        if e["type"] == "dig" and (nxt is None or nxt["type"] == "serve" or nxt["t"] - e["t"] > RALLY_GAP):
            hi = e["t"] + DIG_TAIL if nxt is None else min(e["t"] + DIG_TAIL, nxt["t"] - 1.0)
            why = (f"The {e['team']} dig at {{x:.1f}} s kept the ball in play, so the rally goes on after it, "
                   f"but no touch after it is logged.")
            spots.append((e["t"], hi, why, e["t"], AFTER_TASK))
        elif (e["type"] == "attack" and nxt is not None and nxt["team"] and nxt["team"] != e["team"]
              and nxt["type"] in ("set", "attack", "kill") and nxt["t"] - e["t"] <= ATTACK_REPLY):
            why = (f"After the {e['team']} attack at {{x:.1f}} s the next logged touch is a {nxt['team']} "
                   f"{nxt['type']}, so the {nxt['team']} team's dig of that attack (and anything between) is missing.")
            spots.append((e["t"], nxt["t"], why, e["t"], MISSING_TASK))
    return [s for s in spots if s[1] - s[0] > 0.6]


def in_order(a, before):
    """Rally order for a touch found on a re-watch: a dig or block answers the other team's attack; an
    attack, kill or set follows a touch by the same team (its own receive, dig or set)."""
    if not before:
        return False
    prev = before[-1]
    if a["type"] in ("dig", "block"):
        return prev["type"] in ("attack", "kill") and prev["team"] != a["team"]
    return prev["team"] == a["team"]


def fill_rallies(match, events):
    """Re-watch each broken spot (10 fps, full width, Argon) with the logged touches as context and
    add the missing touches it finds strictly inside the spot. Nothing is deleted or retimed."""
    spots = broken_rallies(events)

    def one(spot):
        lo, hi, why, x, task = spot
        t0, t1 = lo - 1.5, min(hi + 1.0, lo - 1.5 + 20.0)
        logged = "\n".join(f"  {e['t'] - t0:5.1f} s  {e['team']} {e['type']}" + (f" #{e['number']}" if e.get("number") else "")
                           for e in events if t0 <= e["t"] <= t1) or "  (none)"
        prompt = FILL_PROMPT.format(length=t1 - t0, logged=logged, why=why.format(x=x - t0),
                                    task=task.format(lo=lo - t0, hi=hi - t0))
        try:
            ans = match.watch_range(t0, t1, prompt, fps=10, width=FRAME_W, model=tools.ARGON, thinking="medium",
                                    schema=tools.EVENTS)
        except tools.BudgetExceeded:
            raise
        except Exception:
            return []
        found = sorted(({"t": t0 + float(a.get("t") or 0.0), "type": a.get("type"), "team": SIDE_TO_TEAM.get(a.get("side")),
                         "number": a.get("number")} for a in (ans or {}).get("events", [])), key=lambda a: a["t"])
        context = sorted([e for e in events if t0 - 3.0 <= e["t"] <= t1] + found, key=lambda a: a["t"])
        out = []
        for i, a in enumerate(found):
            if a["type"] in ("serve", "receive") or a["team"] is None or not lo + 0.3 < a["t"] < hi - 0.2:
                continue
            if a["type"] == "set" and not any(b["type"] == "kill" for b in found[i + 1:]):
                continue           # the scout logs a set only before a point-winning kill
            if not in_order(a, [c for c in context if c["t"] < a["t"] - 0.05]):
                continue
            out.append(a)
        return out

    added = []
    for found in match.map(one, spots):
        for a in found:
            if not any(o["team"] == a["team"] and abs(o["t"] - a["t"]) < 0.7 for o in events + added):
                added.append(a)
    return sorted(events + added, key=lambda e: e["t"])


def analyse(match):
    events = fix_numbers(match, fill_rallies(match, merge(scout(match))))
    return [{"t": e["t"] + (SERVE_LAG if e["type"] == "serve" else 0.0), "type": e["type"], "team": e["team"], "number": e.get("number")} for e in events]
