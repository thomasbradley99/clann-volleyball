"""The toolbox an evolved system.py may use. Owned by the harness: candidates cannot change it.

system.py defines   analyse(match) -> list of events   where each event is a dict
    {"t": match seconds (float), "type": one of TYPES, "team": "white" | "blue", "number": str or None}
White plays on the LEFT of the net all match, blue on the RIGHT (fixed side-on camera).

`match` gives you:
    match.window            (lo, hi) match seconds to analyse; events outside are dropped
    match.clips             [(name, start, length)] the 30 s raw clips (1920x1080) covering the window,
                            8 s overlap between neighbours; already uploaded, so watching is fast
    match.team_sheet        text: shirt numbers per side, read from the video before scouting
    match.watch(clip, prompt, fps=5, media="high", thinking="high", schema=EVENTS, model=ARGON)
                            Gemini watches one whole clip and answers `prompt` as JSON (default
                            schema: {"events": [{t, type, side, number, error, point}]})
    match.watch_range(t0, t1, prompt, fps=10, width=1280, crop=None, model=FLASH, thinking="low",
                      schema=None, media="high")
                            ffmpeg cuts t0..t1 (at most 20 s) from the original video, optionally
                            crop=(x, y, w, h) in 1920x1080 pixels, then Gemini answers about it
    match.ask(text, model=ARGON, thinking="medium", schema=None)
                            a text-only call
    match.map(fn, items, workers=32)
                            runs fn over items in parallel threads, returns results in order

Every call is cached and metered. match.cost is the deployed cost so far ($, cache hits count at
their original price): cost per match is part of fitness, so cheap models / fewer frames / fewer
calls are rewarded when accuracy holds. Prices ($/M tokens in/out): ARGON 2/10, FLASH 0.5/3.
A run that exceeds its budget raises BudgetExceeded.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
ARGON, FLASH = "gemini-4-argon", "gemini-3.8-flash"
PRICES = {ARGON: (2.0, 10.0), FLASH: (0.5, 3.0)}
TYPES = ["serve", "receive", "set", "dig", "attack", "kill", "block"]
MEDIA = {"low": "MEDIA_RESOLUTION_LOW", "medium": "MEDIA_RESOLUTION_MEDIUM", "high": "MEDIA_RESOLUTION_HIGH"}
EVENTS = {"type": "OBJECT", "properties": {"events": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "t": {"type": "NUMBER"}, "type": {"type": "STRING", "enum": TYPES},
    "side": {"type": "STRING", "enum": ["left", "right"]}, "number": {"type": "STRING", "nullable": True},
    "error": {"type": "BOOLEAN"}, "point": {"type": "BOOLEAN"}},
    "required": ["t", "type", "side", "number", "error", "point"]}}}, "required": ["events"]}
VIDEO = ROOT / "data" / "full_match.mp4"
CLIPDIR = ROOT / "data" / "clips_full" / "raw_5fps"
CACHE = ROOT / "evo5" / "cache"
CLIP_LEN = 30.0


class BudgetExceeded(Exception):
    pass


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _api_key():
    for line in open(ROOT / ".env"):
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()


class Match:
    def __init__(self, window, budget=60.0):
        index = json.load(open(CLIPDIR / "index.json"))
        uploads = json.load(open(CLIPDIR / "uploads.json"))
        lo, hi = window
        self.window = (lo, hi)
        self.clips = sorted([(n, s, CLIP_LEN) for n, s in index.items()
                             if n in uploads and s < hi and s + CLIP_LEN > lo], key=lambda c: c[1])
        self._uri = {n: uploads[n]["uri"] for n, _, _ in self.clips}
        self.team_sheet = (ROOT / "data" / "team_sheet.txt").read_text().strip()
        self.budget, self.cost, self.new_spend, self.calls, self.cache_hits = budget, 0.0, 0.0, 0, 0
        self._lock = threading.Lock()
        self._client = genai.Client(api_key=_api_key())
        CACHE.mkdir(parents=True, exist_ok=True)

    # ---- metering and caching ----
    def _charge(self, usd, new):
        with self._lock:
            self.cost += usd
            self.calls += 1
            if new:
                self.new_spend += usd
            else:
                self.cache_hits += 1
            if self.cost > self.budget:
                raise BudgetExceeded(f"deployed cost ${self.cost:.2f} > budget ${self.budget:.2f}")

    def _call(self, key, model, contents, schema, thinking, media):
        p = CACHE / f"{key}.json"
        if p.exists():
            hit = json.load(open(p))
            self._charge(hit["usd"], False)
            return hit["answer"]
        if model not in PRICES:
            raise ValueError(f"unknown model {model}; use tools.ARGON or tools.FLASH")
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
                answer = json.loads(r.text) if schema else r.text
                tmp = p.with_suffix(f".{threading.get_ident()}.tmp")
                json.dump({"usd": usd, "answer": answer}, open(tmp, "w"))
                tmp.replace(p)
                self._charge(usd, True)
                return answer
            except BudgetExceeded:
                raise
            except Exception as e:
                last = e
                time.sleep(min(60, 5 * 2 ** attempt))
        raise RuntimeError(f"{model} failed 6 times: {type(last).__name__}: {str(last)[:150]}")

    # ---- the tools ----
    def watch(self, clip, prompt, fps=5, media="high", thinking="high", schema=EVENTS, model=ARGON):
        part = types.Part(file_data=types.FileData(file_uri=self._uri[clip], mime_type="video/mp4"),
                          video_metadata=types.VideoMetadata(fps=fps))
        key = _key("watch", clip, prompt, fps, media, thinking, schema, model)
        return self._call(key, model, [part, prompt], schema, thinking, media)

    def watch_range(self, t0, t1, prompt, fps=10, width=1280, crop=None, model=FLASH, thinking="low",
                    schema=None, media="high"):
        t0, t1 = round(max(0.0, float(t0)), 2), round(float(t1), 2)
        if not 0 < t1 - t0 <= 20:
            raise ValueError("watch_range: 0 < t1 - t0 <= 20 s")
        key = _key("range", t0, t1, prompt, fps, width, crop, model, thinking, schema, media)
        if (CACHE / f"{key}.json").exists():
            return self._call(key, model, None, schema, thinking, media)
        vf = (f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}," if crop else "") + f"scale={int(width)}:-2"
        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=CACHE) as f:
            subprocess.run(["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-ss", f"{t0:.2f}", "-i", str(VIDEO),
                            "-t", f"{t1 - t0:.2f}", "-an", "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
                            "-crf", "20", f.name], check=True)
            part = types.Part(inline_data=types.Blob(mime_type="video/mp4", data=Path(f.name).read_bytes()),
                              video_metadata=types.VideoMetadata(fps=fps))
            return self._call(key, model, [part, prompt], schema, thinking, media)

    def ask(self, text, model=ARGON, thinking="medium", schema=None):
        return self._call(_key("ask", text, model, thinking, schema), model, [text], schema, thinking, None)

    def map(self, fn, items, workers=32):
        with cf.ThreadPoolExecutor(min(64, max(1, workers))) as ex:
            return list(ex.map(fn, items))


def seed_cache(prompt):
    """Answers already paid for (evo2's thinking-high sweep) become cache entries for watch()."""
    CACHE.mkdir(parents=True, exist_ok=True)
    resp = json.load(open(ROOT / "evo2" / "sweep" / "fps5_think_high" / "responses.json"))
    index = json.load(open(CLIPDIR / "index.json"))
    usd = 17.83 / len(resp)
    for n, evs in resp.items():
        if evs is None:
            continue
        filled = prompt.replace("{start}", f"{index[n]:.2f}").replace("{length}", f"{CLIP_LEN:g}")
        k = _key("watch", n, filled, 5, "high", "high", EVENTS, ARGON)
        clean = [{f: e[f] for f in ("t", "type", "side", "number", "error", "point")} for e in evs]
        json.dump({"usd": usd, "answer": {"events": clean}}, open(CACHE / f"{k}.json", "w"))
