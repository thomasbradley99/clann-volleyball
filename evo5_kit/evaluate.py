"""Harness side: run one candidate's system.py on match windows and score it against the scout.

  python3 evaluate.py <cand_dir> set1 set2     # writes <cand_dir>/result.json
Candidates never run this; they only see the numbers (and set-1 errors) in the next brief."""
import os
os.environ.setdefault("VLM_WINDOW", "full")
import ast
import importlib.util
import json
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent
ROOT = KIT.parent
sys.path[:0] = [str(KIT), str(ROOT)]
import tools                      # noqa: E402  (the harness's copy, never the candidate's)
from score import score           # noqa: E402

WINDOWS = {"set1": (995.0, 2270.0), "set2": (2270.0, 4030.0), "set3": (4030.0, 4720.0)}
GT = json.load(open(ROOT / "data" / "ground_truth_full.json"))
FULL_CLIPS = len(json.load(open(tools.CLIPDIR / "uploads.json")))
BUDGET = {"set1": 40.0, "set2": 50.0, "set3": 25.0}
ALLOWED_IMPORTS = {"tools", "json", "math", "re", "statistics", "collections", "itertools", "functools",
                   "dataclasses", "typing", "copy", "bisect", "heapq", "string"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "input",
                "breakpoint", "setattr", "delattr", "memoryview"}
BANNED_ATTRS = {"ROOT", "CACHE", "CLIPDIR", "VIDEO", "os", "subprocess", "tempfile", "Path", "genai", "types",
                "read_text", "read_bytes", "write_text", "write_bytes", "open", "glob", "rglob", "iterdir",
                "unlink", "system", "popen", "budget", "cost", "new_spend"}


def check_code(src):
    """Problems that stop a candidate before it costs anything."""
    problems = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"syntax error: {e}"]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import {m} not allowed (allowed: {sorted(ALLOWED_IMPORTS)})")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            problems.append(f"{node.id} not allowed")
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in BANNED_ATTRS):
            if not (node.attr == "cost" and isinstance(node.ctx, ast.Load)):
                problems.append(f"attribute .{node.attr} not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool) \
                and 990 <= node.value <= 4800:
            problems.append(f"constant {node.value} looks like a match time: rules must work on any match")
    if "def analyse" not in src:
        problems.append("no analyse(match)")
    return sorted(set(problems))


def add_objective(s, pred, gt):
    from score import match
    n = len(match(pred, gt, lambda p, g: p["type"] == g["type"] and p["team"] == g["team"]
                  and str(p.get("number") or "") == str(g["number"])))
    s["f1_number"] = round(2 * n / (len(pred) + len(gt)), 4) if pred or gt else 0.0
    s["objective"] = round((s["f1_time_only"] + s["f1"] + s["f1_with_team"] + s["f1_number"]) / 4, 4)
    return s


def clean(evs, lo, hi):
    out = []
    for e in evs:
        try:
            t = float(e["t"])
        except (KeyError, TypeError, ValueError):
            continue
        if lo <= t < hi and e.get("type") in tools.TYPES and e.get("team") in ("white", "blue"):
            n = e.get("number")
            out.append({"t": t, "type": e["type"], "team": e["team"], "number": None if n in (None, "") else str(n)})
    return sorted(out, key=lambda e: e["t"])


def run_part(cand, part):
    spec = importlib.util.spec_from_file_location("system", cand / "system.py")
    system = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(system)
    lo, hi = WINDOWS[part]
    m = tools.Match((lo, hi), budget=BUDGET[part])
    t0 = time.time()
    evs = clean(system.analyse(m), lo, hi)
    gt = [g for g in GT if lo <= g["t"] < hi]
    s = add_objective(score(evs, gt), evs, gt)
    s.update(cost=round(m.cost, 3), new_spend=round(m.new_spend, 3), calls=m.calls, cache_hits=m.cache_hits,
             clips=len(m.clips), seconds=round(time.time() - t0))
    return s, evs


def main():
    cand, parts = Path(sys.argv[1]), sys.argv[2:]
    problems = check_code((cand / "system.py").read_text())
    res = {"problems": problems, "parts": {}}
    if not problems:
        for part in parts:
            try:
                s, evs = run_part(cand, part)
                json.dump(evs, open(cand / f"predictions_{part}.json", "w"))
                json.dump(s, open(cand / f"score_{part}.json", "w"))
                res["parts"][part] = {k: s[k] for k in ("objective", "f1_time_only", "f1", "f1_with_team", "f1_number",
                                                        "cost", "new_spend", "calls", "clips", "seconds", "counts")}
            except Exception as e:
                res["error"] = f"{part}: {type(e).__name__}: {str(e)[:400]}"
                break
        ok = [p for p in res["parts"].values()]
        if ok and "error" not in res:
            res["cost_per_match"] = round(sum(p["cost"] for p in ok) / sum(p["clips"] for p in ok) * FULL_CLIPS, 2)
    json.dump(res, open(cand / "result.json", "w"), indent=1)
    print(json.dumps(res)[:600])


if __name__ == "__main__":
    main()
