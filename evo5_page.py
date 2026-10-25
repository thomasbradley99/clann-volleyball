"""Website for the code-evolution run (evo5): same graph and run pages as evolution.html.

  python3 evo5_page.py      # writes ~/volleyball/viewer/code.html + evo5data/

Each dot is one system.py written by a coding agent; its score is the mean of set 1 (errors shown to
the agents) and set 2 (validation, scores only). The run page shows the agent's conjecture, the code
diff against its parent, per-set results and the errors on both sets."""
import csv
import difflib
import json
import os
import shutil

from evo_page import ROOT, VIDEO, VIEW, compact_events, page

EVO = ROOT / "evo5"
OUT = VIEW / "evo5data"


def mean_tiers(d):
    s = [json.load(open(d / f"score_{p}.json")) for p in ("set1", "set2")]
    t = {k: round(sum(x[f] for x in s) / 2, 4) for k, f in (("overall", "objective"), ("time", "f1_time_only"),
                                                          ("action", "f1"), ("team", "f1_with_team"), ("number", "f1_number"))}
    counts = {k: s[0]["counts"][k] + s[1]["counts"][k] for k in s[0]["counts"]}
    per_type = {ty: {k: s[0]["per_type"][ty][k] + s[1]["per_type"][ty][k] for k in ("real", "predicted", "matched")}
                for ty in s[0]["per_type"]}
    events = compact_events(s[0]) + compact_events(s[1])
    return s, t, counts, per_type, events


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (OUT / "match.mp4").exists():
        try:
            os.link(VIDEO, OUT / "match.mp4")
        except OSError:
            (OUT / "match.mp4").symlink_to(VIDEO)
    st = json.load(open(EVO / "state.json"))
    rows = list(csv.DictReader(open(EVO / "log.csv"))) if (EVO / "log.csv").exists() else []
    verdict = {(int(r["gen"]), int(r["cand"])): r["verdict"] for r in rows}
    nodes, code, spent = [], {}, 0.0

    def add(nid, d, gen, k, v, parent, label=""):
        nonlocal spent
        s, t, counts, per_type, events = mean_tiers(d)
        res = json.load(open(d / "result.json"))
        idea = json.load(open(d / "idea.json")) if (d / "idea.json").exists() else {}
        agent = json.load(open(d / "agent.json")) if (d / "agent.json").exists() else {}
        spent += sum(p.get("new_spend", 0) for p in res["parts"].values()) + (agent.get("total_cost_usd") or 0)
        src = (d / "system.py").read_text()
        code[nid] = src
        par = next((n for n in nodes if n["id"] == parent), None)
        diff = ([[l[0], l[2:]] for l in difflib.ndiff(code[parent].splitlines(), src.splitlines()) if l[:1] in "+- "]
                if par else [[" ", l] for l in src.splitlines()])
        p1, p2 = res["parts"]["set1"], res["parts"]["set2"]
        measured = (f"Measured: set 1 {p1['objective']:.3f} (number {p1['f1_number']:.3f}), set 2 (unseen) "
                    f"{p2['objective']:.3f} (number {p2['f1_number']:.3f}), ${res['cost_per_match']}/match")
        focus = d.name and next((r["focus"] for r in rows if (int(r["gen"]), int(r["cand"])) == (gen, k)), None)
        node = {"id": nid, "gen": gen, "k": k, "verdict": v, "parent": parent, "label": label, "tiers": t,
                "counts": counts, "predicted": s[0]["predicted"] + s[1]["predicted"], "real": s[0]["real"] + s[1]["real"],
                "confirm": None, "part": (focus or "").lower() or None, "cost_match": res["cost_per_match"],
                "change": idea.get("change", label)}
        input_name = None
        if (d / "BRIEF.md").exists():
            input_name = f"evo5data/brief_{nid.replace('/', '_')}.txt"
            shutil.copy(d / "BRIEF.md", VIEW / input_name)
        detail = {"id": nid, "prompt": src, "diff": diff, "diff_label": "Code (system.py)", "per_type": per_type,
                  "events": events, "conjecture": idea.get("conjecture", ""),
                  "prediction": (idea.get("prediction", "") + "\n" + measured).strip(), "lessons": None,
                  "parent_tiers": par["tiers"] if par else None, "parent_counts": par["counts"] if par else None,
                  "checks": [f"agent worked {agent.get('minutes', '?')} min, {agent.get('num_turns', '?')} steps: "
                             + (agent.get("result") or "")[:1500]] if agent else [],
                  "input": input_name}
        nodes.append(node)
        json.dump(detail, open(OUT / f"run_{nid.replace('/', '_')}.json", "w"))

    add("seed", EVO / "seed", 0, 0, "start", None, label="seed: evo2 prompt, Argon thinking high, merge only")
    parent = "seed"
    for gd in sorted(EVO.glob("gen_*")):
        g = int(gd.name.split("_")[1])
        kept = None
        for cd in sorted(gd.glob("cand_*")):
            k = int(cd.name.split("_")[1])
            if not (cd / "score_set2.json").exists() or not (cd / "result.json").exists():
                continue
            v = verdict.get((g, k), "scoring")
            add(f"gen_{g:02d}/cand_{k}", cd, g, k, v, parent)
            if v == "KEPT":
                kept = f"gen_{g:02d}/cand_{k}"
        if kept:
            parent = kept
    best = st["best"]["dir"] if st["best"]["dir"] != "seed" else "seed"
    bn = next(n for n in nodes if n["id"] == best)
    index = {"nodes": nodes, "best": best, "best_overall": bn["tiers"]["overall"], "spent": round(spent, 2),
             "start_overall": nodes[0]["tiers"]["overall"]}
    json.dump(index, open(OUT / "index.json", "w"))
    html = page("evo5data", "Full evolutionary system",
                "Each dot is one version of the whole system as code, rewritten by a coding agent from the errors "
                "of the one before, then scored against a human scout: set 1 (errors shown) and set 2 (never "
                "shown). Click any dot.")
    html = html.replace("Video checks the reviewer asked for", "What the agent reported") \
               .replace("Exactly what Argon saw before proposing this", "Exactly what the agent was briefed with") \
               .replace("start (naive prompt)", "start (seed system)")
    (VIEW / "code.html").write_text(html)
    print(f"{len(nodes)} runs -> {OUT}")


if __name__ == "__main__":
    main()
