"""Scoring. A prediction matches a real event if it is within TOLERANCE seconds; each event is
used once, and the pairing is a maximum matching (v1; v0 was closest-first greedy).

Headline F1 = 2 * matches / (predictions + real events), where a match needs time AND type."""
import json

from config import GT_WINDOW, TOLERANCE, TYPES


def match(pred, gt, same):
    """Maximum one-to-one pairs (i, j) with |dt| <= TOLERANCE and same(p, g). Augmenting paths,
    trying nearest candidates first, so a busy rally never loses a pair that a different pairing
    would have kept (closest-first greedy did, under-counting the time-only tier)."""
    adj = [sorted((j for j, g in enumerate(gt) if abs(p["t"] - g["t"]) <= TOLERANCE and same(p, g)),
                  key=lambda j: abs(p["t"] - gt[j]["t"])) for p in pred]
    owner = {}

    def augment(i, seen):
        for j in adj[i]:
            if j not in seen:
                seen.add(j)
                if j not in owner or augment(owner[j], seen):
                    owner[j] = i
                    return True
        return False
    for i in range(len(pred)):
        augment(i, set())
    return sorted((i, j) for j, i in owner.items())


def f1(n_match, n_pred, n_gt):
    return 2 * n_match / (n_pred + n_gt) if n_pred + n_gt else 0.0


def score(pred, gt):
    by_time = match(pred, gt, lambda p, g: True)
    by_type = match(pred, gt, lambda p, g: p["type"] == g["type"])
    by_team = match(pred, gt, lambda p, g: p["type"] == g["type"] and p["team"] == g["team"])

    # Account for every event once: right type first, then the leftovers paired on time alone.
    events = []
    for i, j in by_type:
        events.append({"verdict": "ok" if pred[i]["team"] == gt[j]["team"] else "wrong_team",
                       "gt": gt[j], "pred": pred[i]})
    left_p = [i for i in range(len(pred)) if i not in {i for i, _ in by_type}]
    left_g = [j for j in range(len(gt)) if j not in {j for _, j in by_type}]
    sub = match([pred[i] for i in left_p], [gt[j] for j in left_g], lambda p, g: True)
    for a, b in sub:
        events.append({"verdict": "wrong_action", "gt": gt[left_g[b]], "pred": pred[left_p[a]]})
    events += [{"verdict": "missed", "gt": gt[left_g[b]], "pred": None}
               for b in range(len(left_g)) if b not in {b for _, b in sub}]
    events += [{"verdict": "invented", "gt": None, "pred": pred[left_p[a]]}
               for a in range(len(left_p)) if a not in {a for a, _ in sub}]
    events.sort(key=lambda e: (e["gt"] or e["pred"])["t"])

    per_type = {}
    for ty in TYPES:
        n_g = sum(g["type"] == ty for g in gt)
        n_p = sum(p["type"] == ty for p in pred)
        n_m = sum(gt[j]["type"] == ty for _, j in by_type)
        per_type[ty] = {"real": n_g, "predicted": n_p, "matched": n_m, "f1": round(f1(n_m, n_p, n_g), 3)}

    counts = {v: sum(e["verdict"] == v for e in events)
              for v in ("ok", "wrong_team", "wrong_action", "missed", "invented")}
    return {"f1": round(f1(len(by_type), len(pred), len(gt)), 4),
            "f1_time_only": round(f1(len(by_time), len(pred), len(gt)), 4),
            "f1_with_team": round(f1(len(by_team), len(pred), len(gt)), 4),
            "matched": len(by_type), "predicted": len(pred), "real": len(gt),
            "counts": counts, "per_type": per_type, "events": events}


def load_gt():
    return json.load(open(GT_WINDOW))


if __name__ == "__main__":
    gt = load_gt()
    s = score(gt, gt)
    assert s["f1"] == s["f1_time_only"] == s["f1_with_team"] == 1.0, s
    print(f"self-check: ground truth vs itself = 1.0 at every level ({len(gt)} events)  PASS")
