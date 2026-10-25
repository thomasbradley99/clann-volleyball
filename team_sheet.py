"""Team sheet from the video, before scouting: which shirt numbers play on each side, and the liberos.

  python3 team_sheet.py        # 12 clips spread over the match at 2 fps, ~$1; writes data/team_sheet.json + .txt

A human analyst knows the rosters before scouting; this reads them off the footage instead (never
from the scout sheet), so the system can be given them as match input on any new match. A number
counts if it is read in at least MIN_CLIPS clips; rarer ones are listed as "seen once"."""
import os
os.environ.setdefault("VLM_WINDOW", "full")
import concurrent.futures as cf
import json
from collections import Counter

import evolve2 as E2
import genome as G
from config import ROOT

N_CLIPS = 12
MIN_CLIPS = 2
OUT = ROOT / "data" / "team_sheet"

ASK = """This is a 30-second clip of a volleyball match, fixed side-on camera. List every player whose
shirt number you can read clearly. For each: the side of the net they are on ("left" or "right"), the
number, the shirt colour, and whether they are a libero (the libero wears a different-coloured shirt
from their team-mates). Only list numbers you can actually read; do not guess."""

SCHEMA = {"type": "OBJECT", "properties": {"players": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "side": {"type": "STRING", "enum": ["left", "right"]}, "number": {"type": "INTEGER"},
    "colour": {"type": "STRING"}, "libero": {"type": "BOOLEAN"}}, "required": ["side", "number", "libero"]}}},
    "required": ["players"]}


def main():
    names = sorted((n for n in E2.INDEX if n in E2.UPLOADS), key=E2.INDEX.get)
    pick = [names[round(i * (len(names) - 1) / (N_CLIPS - 1))] for i in range(N_CLIPS)]
    st = {"spent": 0.0}

    def one(n):
        return n, G.ask(E2.run.MODEL, ASK, SCHEMA, "high", st, file_uri=E2.UPLOADS[n]["uri"], fps=2)
    with cf.ThreadPoolExecutor(N_CLIPS) as ex:
        answers = dict(ex.map(one, pick))
    seen, libero, colour = Counter(), Counter(), {"left": Counter(), "right": Counter()}
    for n, a in answers.items():
        for side, num in {(p["side"], p["number"]) for p in a.get("players", [])}:
            seen[side, num] += 1
        for p in a.get("players", []):
            if p.get("libero"):
                libero[p["side"], p["number"]] += 1
            elif p.get("colour"):
                colour[p["side"]][p["colour"].lower()] += 1
    sheet = {}
    for side in ("left", "right"):
        nums = sorted((num for (s, num), k in seen.items() if s == side), key=lambda x: -seen[side, x])
        sheet[side] = {"colour": colour[side].most_common(1)[0][0] if colour[side] else None,
                       "players": [x for x in nums if seen[side, x] >= MIN_CLIPS],
                       "seen_once": [x for x in nums if seen[side, x] < MIN_CLIPS],
                       "liberos": sorted(x for (s, x), k in libero.items() if s == side and k >= MIN_CLIPS)}
    lines = [f"{side} team ({v['colour'] or '?'}): {', '.join(map(str, v['players'])) or '-'}"
             + (f"; libero {', '.join(map(str, v['liberos']))}" if v["liberos"] else "")
             + (f"; also seen once: {', '.join(map(str, v['seen_once']))}" if v["seen_once"] else "")
             for side, v in sheet.items()]
    text = ("Read from the video before scouting (may miss substitutes; a number not listed is possible):\n"
            + "\n".join(lines))
    json.dump({"sheet": sheet, "clips": pick, "answers": answers, "cost_usd": round(st["spent"], 2)},
              open(OUT.with_suffix(".json"), "w"), indent=1)
    OUT.with_suffix(".txt").write_text(text + "\n")
    print(text, f"\n${st['spent']:.2f}")


if __name__ == "__main__":
    main()
