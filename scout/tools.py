"""Production toolbox for the evolved system (system.py): the same interface as the evolution harness's
evo5_kit/tools.py, without the cache, the scorer or any local data paths.

    match = Match("match.mp4")                  # local path or http(s) URL (e.g. a presigned S3 URL)
    events = system.analyse(match)

On construction the video is cut into 30 s clips (8 s overlap) with ffmpeg and the clips are uploaded
to the Gemini Files API. watch_range() cuts short pieces straight from the original video, so a URL
works without downloading the whole file. The key comes from the GEMINI_API_KEY environment variable."""
import concurrent.futures as cf
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from google import genai
from google.genai import types

ARGON, FLASH = "gemini-4-argon", "gemini-3.8-flash"
PRICES = {ARGON: (2.0, 10.0), FLASH: (0.5, 3.0)}
TYPES = ["serve", "receive", "set", "dig", "attack", "kill", "block"]
MEDIA = {"low": "MEDIA_RESOLUTION_LOW", "medium": "MEDIA_RESOLUTION_MEDIUM", "high": "MEDIA_RESOLUTION_HIGH"}
EVENTS = {"type": "OBJECT", "properties": {"events": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "t": {"type": "NUMBER"}, "type": {"type": "STRING", "enum": TYPES},
    "side": {"type": "STRING", "enum": ["left", "right"]}, "number": {"type": "STRING", "nullable": True},
    "error": {"type": "BOOLEAN"}, "point": {"type": "BOOLEAN"}},
    "required": ["t", "type", "side", "number", "error", "point"]}}}, "required": ["events"]}
CLIP_LEN, CLIP_STEP = 30.0, 22.0


class BudgetExceeded(Exception):
    pass


def duration(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(video)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


class Match:
    def __init__(self, video, window=None, team_sheet=None, budget=float("inf"), work_dir=None,
                 cut_workers=os.cpu_count() or 4, upload_workers=16, log=print):
        self.video = str(video)
        lo, hi = window or (0.0, duration(self.video))
        self.window = (float(lo), float(hi))
        self.budget, self.cost, self.calls = budget, 0.0, 0
        self.log = log
        self._lock = threading.Lock()
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._dir = Path(work_dir or tempfile.mkdtemp(prefix="scout_"))
        self._dir.mkdir(parents=True, exist_ok=True)
        starts, s = [], self.window[0]
        while s < self.window[1]:
            starts.append(round(s, 3))
            if s + CLIP_LEN >= self.window[1]:
                break
            s += CLIP_STEP
        self.clips = [(f"clip_{i:03d}", st, CLIP_LEN) for i, st in enumerate(starts)]
        t0 = time.time()
        paths = self.map(self._cut_clip, self.clips, workers=cut_workers)
        self.log(f"cut {len(paths)} clips in {time.time() - t0:.0f}s")
        t0 = time.time()
        self._uri = dict(zip([c[0] for c in self.clips], self.map(self._upload, paths, workers=upload_workers)))
        self.log(f"uploaded {len(paths)} clips in {time.time() - t0:.0f}s")
        self.team_sheet = team_sheet if team_sheet is not None else read_team_sheet(self)

    # ---- setup ----
    def _cut_clip(self, clip):
        # 10 fps is enough: whole clips are only ever watched at 5 fps or less; the 10 fps re-watches
        # (watch_range) cut from the original video
        name, start, length = clip
        out = self._dir / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", self.video,
                        "-t", f"{length:g}", "-an", "-vf", "fps=10", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        str(out)], check=True)
        return out

    def _upload(self, path):
        for attempt in range(5):
            try:
                f = self._client.files.upload(file=str(path), config={"mime_type": "video/mp4",
                                                                      "display_name": path.name})
                while f.state.name == "PROCESSING":
                    time.sleep(3)
                    f = self._client.files.get(name=f.name)
                if f.state.name != "ACTIVE":
                    raise RuntimeError(f"{path.name}: {f.state.name}")
                return f.uri
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(5 * 2 ** attempt)

    # ---- metering ----
    def _call(self, model, contents, schema, thinking, media):
        if model not in PRICES:
            raise ValueError(f"unknown model {model}")
        cfg = types.GenerateContentConfig(
            temperature=0.0, response_mime_type="application/json" if schema else None, response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=thinking),
            media_resolution=MEDIA[media] if media else None)
        last = None
        for attempt in range(6):
            try:
                r = self._client.models.generate_content(model=model, contents=contents, config=cfg)
                u = r.usage_metadata
                pin, pout = PRICES[model]
                usd = ((u.prompt_token_count or 0) * pin + ((u.candidates_token_count or 0)
                       + (u.thoughts_token_count or 0)) * pout) / 1e6
                with self._lock:
                    self.cost += usd
                    self.calls += 1
                    if self.cost > self.budget:
                        raise BudgetExceeded(f"${self.cost:.2f} > budget ${self.budget:.2f}")
                return json.loads(r.text) if schema else r.text
            except BudgetExceeded:
                raise
            except Exception as e:
                last = e
                time.sleep(min(60, 5 * 2 ** attempt))
        raise RuntimeError(f"{model} failed 6 times: {type(last).__name__}: {str(last)[:150]}")

    # ---- the tools system.py uses ----
    def watch(self, clip, prompt, fps=5, media="high", thinking="high", schema=EVENTS, model=ARGON):
        part = types.Part(file_data=types.FileData(file_uri=self._uri[clip], mime_type="video/mp4"),
                          video_metadata=types.VideoMetadata(fps=fps))
        return self._call(model, [part, prompt], schema, thinking, media)

    def watch_range(self, t0, t1, prompt, fps=10, width=1280, crop=None, model=FLASH, thinking="low",
                    schema=None, media="high"):
        t0, t1 = round(max(0.0, float(t0)), 2), round(float(t1), 2)
        if not 0 < t1 - t0 <= 20:
            raise ValueError("watch_range: 0 < t1 - t0 <= 20 s")
        vf = (f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}," if crop else "") + f"scale={int(width)}:-2"
        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=self._dir) as f:
            subprocess.run(["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-ss", f"{t0:.2f}", "-i", self.video,
                            "-t", f"{t1 - t0:.2f}", "-an", "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
                            "-crf", "20", f.name], check=True)
            part = types.Part(inline_data=types.Blob(mime_type="video/mp4", data=Path(f.name).read_bytes()),
                              video_metadata=types.VideoMetadata(fps=fps))
            return self._call(model, [part, prompt], schema, thinking, media)

    def ask(self, text, model=ARGON, thinking="medium", schema=None):
        return self._call(model, [text], schema, thinking, None)

    def map(self, fn, items, workers=32):
        with cf.ThreadPoolExecutor(min(64, max(1, workers))) as ex:
            return list(ex.map(fn, items))


TEAM_ASK = """This is a 30-second clip of a volleyball match, fixed side-on camera. List every player whose
shirt number you can read clearly. For each: the side of the net they are on ("left" or "right"), the
number, the shirt colour, and whether they are a libero (the libero wears a different-coloured shirt
from their team-mates). Only list numbers you can actually read; do not guess."""
TEAM_SCHEMA = {"type": "OBJECT", "properties": {"players": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "side": {"type": "STRING", "enum": ["left", "right"]}, "number": {"type": "INTEGER"},
    "colour": {"type": "STRING"}, "libero": {"type": "BOOLEAN"}}, "required": ["side", "number", "libero"]}}},
    "required": ["players"]}


def read_team_sheet(match, n_clips=12, min_clips=2):
    """Shirt numbers per side read from clips spread over the match (a number counts if read in at least
    min_clips clips). The system names the left team "white" and the right team "blue" whatever their
    real colours; the colours read here are returned in match.colours."""
    from collections import Counter
    names = [c[0] for c in match.clips]
    k = min(n_clips, len(names))
    pick = [names[round(i * (len(names) - 1) / max(1, k - 1))] for i in range(k)]
    answers = match.map(lambda n: match.watch(n, TEAM_ASK, fps=2, media=None, thinking="high", schema=TEAM_SCHEMA),
                        sorted(set(pick)))
    seen, libero, colour = Counter(), Counter(), {"left": Counter(), "right": Counter()}
    for a in answers:
        for side, num in {(p["side"], p["number"]) for p in a.get("players", [])}:
            seen[side, num] += 1
        for p in a.get("players", []):
            if p.get("libero"):
                libero[p["side"], p["number"]] += 1
            elif p.get("colour"):
                colour[p["side"]][p["colour"].lower()] += 1
    need = min(min_clips, len(answers))
    match.colours = {s: (colour[s].most_common(1)[0][0] if colour[s] else None) for s in ("left", "right")}
    lines = []
    for side, label in (("left", "white"), ("right", "blue")):
        nums = sorted((n for (s, n) in seen if s == side), key=lambda x: -seen[side, x])
        players = [n for n in nums if seen[side, n] >= need]
        once = [n for n in nums if seen[side, n] < need]
        libs = sorted(n for (s, n), c in libero.items() if s == side and c >= need)
        lines.append(f"{side} team ({label}): {', '.join(map(str, players)) or '-'}"
                     + (f"; libero {', '.join(map(str, libs))}" if libs else "")
                     + (f"; also seen once: {', '.join(map(str, once))}" if once else ""))
    return ("Read from the video before scouting (may miss substitutes; a number not listed is possible):\n"
            + "\n".join(lines))
