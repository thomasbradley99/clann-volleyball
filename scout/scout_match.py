"""Video in, scouting sheet out, with the evolved system (system.py).

    GEMINI_API_KEY=... python3 scout_match.py match.mp4 [--window 1100 1220] [--out sheet.json]

The video can be a local path or an http(s) URL (e.g. a presigned S3 URL). Assumes a fixed side-on
camera with each team on one side of the net for the whole video. Output:
    {"events": [{"t", "type", "side", "team", "number"}], "team_sheet", "colours", "cost_usd", "seconds"}
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tools                                   # noqa: E402  (system.py does `import tools`)
import system                                  # noqa: E402

TEAM_TO_SIDE = {"white": "left", "blue": "right"}


def run(video, window=None, team_sheet=None, budget=float("inf"), log=print):
    t0 = time.time()
    match = tools.Match(video, window=window, team_sheet=team_sheet, budget=budget, log=log)
    events = system.analyse(match)
    lo, hi = match.window
    colours = getattr(match, "colours", {})
    out = [{"t": round(e["t"], 2), "type": e["type"], "side": TEAM_TO_SIDE.get(e["team"]),
            "team": colours.get(TEAM_TO_SIDE.get(e["team"])) or e["team"], "number": e.get("number")}
           for e in sorted(events, key=lambda e: e["t"]) if lo <= e["t"] <= hi]
    return {"events": out, "team_sheet": match.team_sheet, "colours": colours,
            "cost_usd": round(match.cost, 2), "calls": match.calls, "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--window", nargs=2, type=float)
    ap.add_argument("--out")
    a = ap.parse_args()
    res = run(a.video, window=a.window, log=lambda m: print(m, file=sys.stderr))
    text = json.dumps(res, indent=1)
    Path(a.out).write_text(text) if a.out else print(text)
    print(f"{len(res['events'])} events, ${res['cost_usd']}, {res['seconds']}s", file=sys.stderr)
