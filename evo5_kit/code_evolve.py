"""Code evolution (evo5): the whole system is one Python file, and coding agents (Claude Code, headless)
rewrite it the way a human engineer would: read the errors, form a conjecture, change the code, smoke-test.

  nohup python3 evo5_kit/code_evolve.py --gens 6 > evo5_stdout.log 2>&1 &     # resumes from evo5/
  touch evo5/STOP                                                            # stop after this generation

Each generation: POP agents start from the best system.py, each in its own sandbox folder (it can
read/write only there and run only smoke.py). They see set 1 errors in full; set 2 is validation,
shown as numbers only, so a change that memorises set 1 does not survive. Set 3 is held out.
Fitness = mean OVERALL (set 1, set 2) - COST_W * $ per match. Kept if fitness beats the best by
MARGIN and set 2 does not drop."""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent
ROOT = KIT.parent
EVO = ROOT / "evo5"
POP = 3
COST_W = 0.001          # $10 per match costs 0.01 OVERALL (was 0.002 until gen 2)
MARGIN = 0.006
SET2_SLACK = 0.004      # set 2 may not drop by more than this
AGENT_MINUTES = 30
GT = json.load(open(ROOT / "data" / "ground_truth_full.json"))
SET1 = (995.0, 2270.0)

FOCUS = [
    "ACCURACY: fix the biggest class of missed, invented or mislabelled events.",
    "COST: keep accuracy and cut the $ per match (cheaper model or settings for some of the work, fewer frames, fewer calls).",
    "STRUCTURE: add or replace a stage. Ideas: find rallies first with a cheap model and scout whole rallies; "
    "an AI reviewer that reads the whole event list and asks for short video checks; precise timing checks "
    "at high fps; zoomed checks of shirt numbers against the team sheet. Pick the one you think is worth most.",
]

BRIEF = """# Your job

You are improving a volleyball event-detection system. The whole system is `system.py` in this
folder: `analyse(match)` takes a match and returns events (time, type, team, shirt number). The
toolbox it may use is `tools.py` (read its docstring: watch a clip, watch a cut range of the video,
ask a text model, run in parallel; every call is cached and metered). A human scout's sheet is the
truth. Work like a careful engineer: study the errors, form ONE conjecture about a class of errors
(or cost), change the code to fix it, run `python3 smoke.py` to make sure it runs, iterate if it
crashes, then stop.

## Your focus this time
{focus}

## How it is judged (by the harness, after you stop)
- Run on set 1 (you can see its errors below and in the files) and set 2 (validation: you only see
  its scores). OVERALL = mean of four F1 levels: time (within 1 s), + action type, + team, + shirt
  number.
- Fitness = mean OVERALL of sets 1 and 2 - {cost_w} x ($ per match). Kept only if fitness beats the
  best by {margin} AND set 2 does not drop. So a change that only fits set 1's particular events
  will fail. Make changes that would work on any volleyball match.
- Rejected before running: hard-coded match times, file access, imports other than the allowed
  ones (see the harness check printed by smoke.py), touching tools internals.
- Cost per match counts cache hits at their original price. Re-watching all clips with a new scout
  prompt costs about $18 per match with Argon at thinking high.

## The current best ({best_name})
set 1: {s1}
set 2: {s2}
cost per match: ${cost}   fitness {fitness:.4f}

Per type on set 1 (scout / system / matched):
{per_type}

## Files here
- `system.py`: the current best system. Edit this.
- `tools.py`: the toolbox (reference copy; the harness uses its own).
- `errors_set1.md`: every set-1 error in context (what the system said vs the scout within 3 s).
- `set1_scout.json`: the scout's sheet for set 1. `set1_system.json`: the system's output on set 1.
- `knowledge.md`: every earlier attempt in this run: idea, result, verdict. Do not repeat failures.

## Before you stop
Write `idea.json`: {{"conjecture": "...", "change": "...", "prediction": "numbers you expect on set 1 / set 2 / cost"}}.
Keep `analyse(match)` working. Do not stop with a crashing system.py.
"""


def log(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    with open(EVO / "progress.txt", "a") as fh:
        fh.write(line + "\n")


def evaluate(cand, parts=("set1", "set2")):
    env = dict(os.environ, VLM_WINDOW="full")
    subprocess.run(["python3", str(KIT / "evaluate.py"), str(cand), *parts], env=env, timeout=3600,
                   stdout=open(cand / "eval.log", "w"), stderr=subprocess.STDOUT)
    return json.load(open(cand / "result.json"))


def fitness(res):
    p = res["parts"]
    return (p["set1"]["objective"] + p["set2"]["objective"]) / 2 - COST_W * res["cost_per_match"]


def fmt(p):
    c = p["counts"]
    return (f"OVERALL {p['objective']:.3f} (time {p['f1_time_only']:.3f}, action {p['f1']:.3f}, team "
            f"{p['f1_with_team']:.3f}, number {p['f1_number']:.3f}); missed {c['missed']}, invented {c['invented']}, "
            f"wrong action {c['wrong_action']}, wrong team {c['wrong_team']}")


def errors_md(best_dir):
    s = json.load(open(best_dir / "score_set1.json"))
    pred = json.load(open(best_dir / "predictions_set1.json"))
    gt = [g for g in GT if SET1[0] <= g["t"] < SET1[1]]
    f = lambda e: f"{e['t']:.2f} {e['type']} {e['team']} #{e.get('number') or '-'}"
    out = []
    for kind in ("missed", "invented", "wrong_action", "wrong_team"):
        evs = [e for e in s["events"] if e["verdict"] == kind]
        out.append(f"\n## {kind} ({len(evs)})\n")
        for e in evs:
            t = (e["gt"] or e["pred"])["t"]
            out.append(f"- {kind.upper()} at {t:.2f}: " + (f"scout {f(e['gt'])}" if e["gt"] else "") +
                       (f" / system {f(e['pred'])}" if e["pred"] else "") +
                       f"\n    system nearby: {'; '.join(f(p) for p in pred if abs(p['t'] - t) <= 3) or '-'}"
                       f"\n    scout nearby:  {'; '.join(f(g) for g in gt if abs(g['t'] - t) <= 3) or '-'}")
    wrong_num = [e for e in s["events"] if e["verdict"] == "ok" and str(e["pred"].get("number") or "") != str(e["gt"]["number"])]
    out.append(f"\n## right event, wrong or missing shirt number ({len(wrong_num)})\n")
    out += [f"- {e['gt']['t']:.2f} {e['gt']['type']} {e['gt']['team']}: scout #{e['gt']['number']}, system "
            f"#{e['pred'].get('number') or '-'}" for e in wrong_num]
    return "\n".join(out)


def prepare(cd, st, k):
    best = EVO / st["best"]["dir"]
    cd.mkdir(parents=True, exist_ok=True)
    shutil.copy(best / "system.py", cd / "system.py")
    shutil.copy(KIT / "tools.py", cd / "tools.py")
    shutil.copy(KIT / "smoke.py", cd / "smoke.py")
    (cd / "errors_set1.md").write_text(errors_md(best))
    json.dump([g for g in GT if SET1[0] <= g["t"] < SET1[1]], open(cd / "set1_scout.json", "w"), indent=0)
    shutil.copy(best / "predictions_set1.json", cd / "set1_system.json")
    shutil.copy(EVO / "knowledge.md", cd / "knowledge.md")
    s1 = json.load(open(best / "score_set1.json"))
    r = st["best"]["result"]
    per_type = "\n".join(f"  {ty:<8} {v['real']:>4} {v['predicted']:>5} {v['matched']:>5}" for ty, v in s1["per_type"].items())
    (cd / "BRIEF.md").write_text(BRIEF.format(
        focus=FOCUS[k % len(FOCUS)], cost_w=COST_W, margin=MARGIN, best_name=st["best"]["dir"],
        s1=fmt(r["parts"]["set1"]), s2=fmt(r["parts"]["set2"]), cost=r["cost_per_match"], fitness=st["best"]["fitness"],
        per_type=per_type))


def agent(cd):
    env = dict(os.environ, EVO5_KIT=str(KIT), VLM_WINDOW="full")
    t0 = time.time()
    try:
        p = subprocess.run(
            ["claude", "-p", "Read BRIEF.md in this folder and do the job it describes.",
             "--permission-mode", "acceptEdits", "--allowedTools", "Bash(python3 smoke.py)",
             "--disallowedTools", "WebFetch", "WebSearch", "Agent", "--max-turns", "80", "--output-format", "json"],
            cwd=cd, env=env, capture_output=True, text=True, timeout=AGENT_MINUTES * 60)
        out = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {"result": p.stdout[-2000:]}
    except subprocess.TimeoutExpired:
        out = {"result": f"agent timed out after {AGENT_MINUTES} min"}
    out["minutes"] = round((time.time() - t0) / 60, 1)
    json.dump(out, open(cd / "agent.json", "w"), indent=1)
    return out


def ledger(row):
    p = EVO / "log.csv"
    new = not p.exists()
    with open(p, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=6)
    a = ap.parse_args()
    EVO.mkdir(exist_ok=True)
    sp = EVO / "state.json"
    if sp.exists():
        st = json.load(open(sp))
        st["max_gens"] = a.gens
        st["best"]["fitness"] = fitness(st["best"]["result"])      # COST_W may have changed
        log(f"resuming after gen {st['gen']}; best {st['best']['dir']} fitness {st['best']['fitness']:.4f} (COST_W {COST_W})")
    else:
        seed = EVO / "seed"
        seed.mkdir(exist_ok=True)
        shutil.copy(KIT / "seed_system.py", seed / "system.py")
        res = evaluate(seed)
        st = {"gen": 0, "max_gens": a.gens, "best": {"dir": "seed", "result": res, "fitness": fitness(res)}}
        (EVO / "knowledge.md").write_text(f"# Knowledge log\n\nseed (evo2 prompt, Argon thinking high, merge only): set 1 "
                                          f"{fmt(res['parts']['set1'])}; set 2 {fmt(res['parts']['set2'])}; "
                                          f"${res['cost_per_match']}/match; fitness {fitness(res):.4f}\n")
        json.dump(st, open(sp, "w"), indent=1)
        log(f"seed fitness {fitness(res):.4f}")

    while st["gen"] < st["max_gens"] and not (EVO / "STOP").exists():
        g = st["gen"] + 1
        gd = EVO / f"gen_{g:02d}"
        log(f"=== gen {g}  best {st['best']['dir']} fitness {st['best']['fitness']:.4f}")
        cds = [gd / f"cand_{k}" for k in range(POP)]
        for k, cd in enumerate(cds):
            prepare(cd, st, k)

        def one(k):
            cd = cds[k]
            out = agent(cd)
            log(f"  [{k}] agent done in {out['minutes']} min (${out.get('total_cost_usd', 0) or 0:.2f}); evaluating")
            res = evaluate(cd)
            return k, out, res
        with cf.ThreadPoolExecutor(POP) as ex:
            results = list(ex.map(one, range(POP)))

        best_f, verdicts = st["best"]["fitness"], {}
        b2 = st["best"]["result"]["parts"]["set2"]["objective"]
        scored = []
        for k, out, res in results:
            if res.get("problems") or res.get("error") or "cost_per_match" not in res:
                verdicts[k] = "broken"
            else:
                verdicts[k] = "rejected"
                scored.append((fitness(res), k, res))
        win = max(scored) if scored else None
        if win and win[0] > best_f + MARGIN and win[2]["parts"]["set2"]["objective"] >= b2 - SET2_SLACK:
            verdicts[win[1]] = "KEPT"
            st["best"] = {"dir": f"gen_{g:02d}/cand_{win[1]}", "result": win[2], "fitness": win[0]}

        with open(EVO / "knowledge.md", "a") as fh:
            fh.write(f"\n## generation {g}\n")
            for k, out, res in results:
                idea = json.load(open(cds[k] / "idea.json")) if (cds[k] / "idea.json").exists() else {}
                if verdicts[k] == "broken":
                    r = f"BROKEN: {'; '.join(res.get('problems') or []) or res.get('error', 'no result')}"[:400]
                else:
                    r = (f"set 1 {fmt(res['parts']['set1'])}; set 2 {fmt(res['parts']['set2'])}; "
                         f"${res['cost_per_match']}/match; fitness {fitness(res):.4f}")
                fh.write(f"- candidate {k} [{FOCUS[k % len(FOCUS)].split(':')[0]}] [{verdicts[k]}] {r}\n"
                         f"  conjecture: {idea.get('conjecture', '')}\n  change: {idea.get('change', '')}\n"
                         f"  predicted: {idea.get('prediction', '')}\n")
            fh.write(f"  best after generation {g}: {st['best']['dir']} fitness {st['best']['fitness']:.4f}\n")
        for k, out, res in results:
            p = res.get("parts", {})
            ledger({"gen": g, "cand": k, "focus": FOCUS[k % len(FOCUS)].split(":")[0], "verdict": verdicts[k],
                    "set1": p.get("set1", {}).get("objective", ""), "set2": p.get("set2", {}).get("objective", ""),
                    "cost_per_match": res.get("cost_per_match", ""),
                    "fitness": round(fitness(res), 4) if verdicts[k] != "broken" else "",
                    "agent_min": out.get("minutes"), "agent_usd": out.get("total_cost_usd"),
                    "gemini_new_usd": round(sum(x.get("new_spend", 0) for x in p.values()), 2),
                    "best_after": st["best"]["dir"]})
            log(f"  [{k}] {verdicts[k]}: " + (f"set1 {p['set1']['objective']:.3f} set2 {p['set2']['objective']:.3f} "
                                              f"${res['cost_per_match']}/match fitness {fitness(res):.4f}"
                                              if verdicts[k] != "broken" else str(res.get("problems") or res.get("error"))[:200]))
        st["gen"] = g
        json.dump(st, open(sp, "w"), indent=1)
        log(f"  -> best {st['best']['dir']} fitness {st['best']['fitness']:.4f}")

    if not (EVO / "holdout").exists():
        log("hold-out set 3: seed vs best")
        for name, src in (("seed", EVO / "seed"), ("best", EVO / st["best"]["dir"])):
            d = EVO / "holdout" / name
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy(src / "system.py", d / "system.py")
            res = evaluate(d, ("set3",))
            p = res.get("parts", {}).get("set3")
            log(f"  {name}: {fmt(p) if p else res}  ${res.get('cost_per_match')}/match")
    log("done")


if __name__ == "__main__":
    main()
