"""Run YOUR system.py on about 1 minute of set 1 (3 clips) to check it works. Budget $3.
No scores here: it only proves the code runs and shows what it outputs.

  python3 smoke.py"""
import os
os.environ.setdefault("VLM_WINDOW", "full")
import importlib.util
import json
import sys
from pathlib import Path

KIT = Path(os.environ["EVO5_KIT"])
sys.path.insert(0, str(KIT))
import tools                      # noqa: E402
from evaluate import check_code, clean   # noqa: E402

here = Path.cwd()
problems = check_code((here / "system.py").read_text())
if problems:
    sys.exit("REJECTED before running:\n  " + "\n  ".join(problems))
spec = importlib.util.spec_from_file_location("system", here / "system.py")
system = importlib.util.module_from_spec(spec)
spec.loader.exec_module(system)
m = tools.Match((1100.0, 1160.0), budget=3.0)
evs = clean(system.analyse(m), *m.window)
for e in evs:
    print(f"  {e['t']:8.2f}  {e['type']:<8} {e['team']:<6} {e['number']}")
print(f"{len(evs)} events from {len(m.clips)} clips; cost ${m.cost:.3f} (new ${m.new_spend:.3f}), "
      f"{m.calls} calls, {m.cache_hits} cached")
