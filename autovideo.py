#!/usr/bin/env python3
"""
autovideo.py (v4)  -  scripts in, finished narrated screen-demo videos out (reel + Instagram), optionally from Telegram.   WINDOWS.

Real session (nothing simulated): a real Chrome/Brave/Edge window with a throw-away profile, the REAL mouse pointer and
keyboard, the REAL screen recorded. The profile is deleted after every session.

One recording -> several formats, plus the transcript:
    <name>_vertical.mp4    1080x1920 reel: badges + title on top, the video in the middle, word-highlight subtitles below
    <name>_instagram.mp4   1080x1350 (4:5) full screen, no subtitles
    <name>_transcript.txt  what the voice says, with timestamps

Commands (run from this folder):
    python autovideo.py check                     # 10-second self-test of the controlled environment
    python autovideo.py queue [--female|--male]   # make ALL scripts in scripts.txt / jobs\\*.txt, one by one, unattended
    python autovideo.py bot [--female|--male]     # listen to a Telegram group topic; paste a script there -> video comes back
    python autovideo.py bot-setup                 # find your Telegram chat / topic / user ids (needs only the bot token)
    python autovideo.py voice-profile <video>     # measure the voice of a reference video
    python autovideo.py voice-lab                 # pick the closest male and female voices to that reference
    python autovideo.py plan | make | finish | all   # single video from brief.txt (finish = resume without re-recording)

While recording, do not touch the mouse or keyboard. Slam the mouse into a screen corner to abort.
"""
import asyncio
import bisect
import ctypes
import hashlib
import json
import math
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import queue
import uuid
from pathlib import Path

# Make this process DPI-aware BEFORE anything reads screen coordinates (Windows display scaling).
if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import cv2
import numpy as np

try:                                                   # Bangla etc. must print without crashing
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ----------------------------------------------------------------------------
# SETTINGS  (edit these)
# ----------------------------------------------------------------------------
BROWSER_PATH = ""                 # leave empty to auto-detect Chrome, then Brave, then Edge
PLANNER = "auto"                  # "auto" = AI editor if you set a key in .env, else built-in | "builtin" | "opencode"
DEFAULT_GENDER = "male"          # "male" | "female"  (switch per run with --female, per script with "Voice: female")
VOICE_RATE = "+6%"                # base speaking speed; `voice-lab` tunes it to match your reference video
WORDS_PER_SEC = 2.6               # only used to decide how much spare footage to record per scene
FPS = 30
CAPTURE = "gdigrab"               # "gdigrab" or "ddagrab" (ffmpeg 6+, handles display scaling better)
STYLE = "recordly"                # "recordly" = zoom + rounded window on a background | "plain" = raw real footage
ZOOM = 1.25                       # zoom on clicks / typing / pointer tours (1.0 = none)
PUSH_IN = 0.05                    # gentle "breathing" zoom during every scene so no shot is ever dead (0 = off)
PAGE_ZOOM = 1.25                  # browser zoom while recording, so text is readable in 1080p (1.0 = off)
CURSOR_SCALE = 1.0                # size of the drawn cursor (1.0 = about 46 px tall on a 1080p video)
OUT_W, OUT_H = 1920, 1080
WINDOW_SCALE = 0.92
CORNER_RADIUS = 26
BACKGROUND_IMAGE = "background.jpg"   # optional wallpaper next to this script
LEAD = 0.20                       # seconds between a scene starting and its narration starting (brisk reel pace)
TAIL = 0.30                       # pause after narration before the next scene
RIPPLE = True                     # click ripple highlight
CAPTIONS = True                   # burned-in captions (Bangla needs the Nirmala UI font, present on Windows)
MUSIC_FILE = "music.mp3"          # optional: put a royalty-free track next to this script
MUSIC_VOLUME = 0.10               # music level under the voice (it also ducks while the voice speaks)
LOUDNORM = True                   # normalise voice loudness to -16 LUFS (social-media standard)
FADE_IN, FADE_OUT = 0.35, 0.8
GAP_BETWEEN_JOBS = 8              # seconds between videos in the queue
KEEP_TEMP = False                 # True keeps output\_work for debugging
OUTPUTS = ["vertical", "instagram"]   # any of: "vertical" (reel layout) | "instagram" (4:5 full screen) | "landscape"
VERT_SIZE = (1080, 1920)          # 9:16 reel canvas: title on top, video in the middle, subtitles below
VERT_WINDOW = (960, 640)          # the video window inside the reel canvas
VERT_ZOOM = 1.15                  # base zoom inside that window so text stays readable on a phone
IG_SIZE = (1080, 1350)            # Instagram feed 4:5 (1080 wide x 1350 tall). 3:4 grid-friendly alternative: (1080, 1440)
DEFAULT_TEMPLATE = "clean-light"      # see `python avx_templates.py preview sheet.png`; per video: "Template: neon" or the bot button
CAPTION_WORDS = 4                 # words per subtitle page (the spoken word is highlighted)
BOT_START_DELAY = 15              # seconds the bot waits (after warning you) before it takes over the mouse
SYNC_OFFSET = 0.0                 # +x delays zooms/ripples by x seconds (fine-tune)

# Speed per kind of moment. BASE = normal edit speed, CAP = the most it may be sped up to fit the narration.
BASE = {"move": 1.0, "click": 1.0, "hold": 1.0, "type": 1.6, "load": 6.0, "wait": 6.0,
        "scroll": 1.0, "settle": 1.2, "idle": 2.0, "dwell": 1.0}
CAP = {"move": 1.0, "click": 1.0, "hold": 1.6, "type": 3.2, "load": 20.0, "wait": 20.0,
       "scroll": 1.7, "settle": 3.0, "idle": 6.0, "dwell": 1.0}

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
WORK = OUT / "_work"
PLANS = OUT / "plans"
BRIEF = ROOT / "brief.txt"
PLAN = ROOT / "plan.json"
PROMPT = ROOT / "plan_prompt.txt"
SCRIPTS = ROOT / "scripts.txt"
JOBS_DIR = ROOT / "jobs"
STATE = OUT / "queue_state.json"
LOG = OUT / "queue_log.txt"


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def media_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


def video_size(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(path)])
    w, h = r.stdout.strip().split(",")[:2]
    return int(w), int(h)


def ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def smoother(u):
    u = min(1.0, max(0.0, u))
    return u * u * u * (u * (u * 6 - 15) + 10)


IS_WIN = os.name == "nt"
_PG = None


def _pg():
    """Real OS input. Windows: pyautogui. Linux (a real desktop or Xvfb): xinput_linux (XTEST via ctypes)."""
    global _PG
    if _PG is None:
        if IS_WIN:
            import pyautogui
            pyautogui.PAUSE = 0
            pyautogui.FAILSAFE = True          # slam the mouse into a screen corner to abort
            _PG = pyautogui
        else:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from xinput_linux import PG
            _PG = PG()
    return _PG


def keep_awake(on=True):
    if os.name == "nt":
        flags = 0x80000000 | 0x00000001 | 0x00000002 if on else 0x80000000
        ctypes.windll.kernel32.SetThreadExecutionState(flags)


def work_area():
    """Primary monitor minus the taskbar, in physical pixels: (x, y, w, h), even sizes."""
    if not IS_WIN:
        d = _pg().d
        return 0, 0, d.width // 2 * 2, d.height // 2 * 2         # the whole X screen (Xvfb: the virtual display)
    from ctypes import wintypes
    r = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
    return r.left, r.top, (r.right - r.left) // 2 * 2, (r.bottom - r.top) // 2 * 2


def find_browser():
    if BROWSER_PATH and Path(BROWSER_PATH).exists():
        return BROWSER_PATH
    bases = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    rels = [r"Google\Chrome\Application\chrome.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Microsoft\Edge\Application\msedge.exe"]
    for rel in rels:
        for b in bases:
            if b and (Path(b) / rel).exists():
                return str(Path(b) / rel)
    for n in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser", "brave", "msedge"):
        w = shutil.which(n)
        if w:
            return w
    import glob                                                  # Playwright's own Chromium (Linux / CI)
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), str(Path.home() / ".cache" / "ms-playwright"), "/opt/pw-browsers"]
    for r in roots:
        for pat in ("chromium-*/chrome-linux*/chrome", "chromium-*/chrome-linux*/headless_shell"):
            hits = sorted(glob.glob(os.path.join(r, pat))) if r else []
            if hits:
                return hits[-1]
    sys.exit("No Chrome/Brave/Edge found. Set BROWSER_PATH at the top of autovideo.py.")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def log(msg):
    print(msg)
    try:
        OUT.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# JOBS  (one video = one job; every job has its own plan, work folder and output)
# ----------------------------------------------------------------------------
class Job:
    def __init__(self, name, brief_text=None, brief=None, plan=None, prompt=None, work=None, final=None):
        self.name = name
        self.brief_text = brief_text
        # the key changes when the script text changes, so an edited script never reuses an old plan or recording
        self.key = hashlib.sha1(brief_text.encode("utf-8")).hexdigest()[:10] if brief_text else name
        tag = f"{name}.{self.key[:6]}" if brief_text else name
        self.brief = Path(brief) if brief else PLANS / f"{tag}_brief.txt"
        self.plan = Path(plan) if plan else PLANS / f"{tag}.json"
        self.prompt = Path(prompt) if prompt else PLANS / f"{tag}_prompt.txt"
        self.work = Path(work) if work else WORK / tag
        self.outs = {t: OUT / f"{name}_{t}.mp4" for t in OUTPUTS}           # one video per format
        self.out_dir = OUT
        self.final = Path(final) if final else next(iter(self.outs.values()))
        self.transcript = OUT / f"{name}_transcript.txt"                     # the voice transcript
        self.force_gender = None                                              # from --female / --male or the bot's /voice
        self.meta = {}
        self.assets = []                                                      # image files sent by the user (for [upload ...])
        self.options = {}                                                     # template, depth, outputs ... (see avx_options)

    def set_options(self, opts):
        """Per-video options (template, outputs, captions, depth ...). Anything unknown is ignored."""
        self.options = {k: v for k, v in (opts or {}).items() if v not in (None, "")}
        outs = self.options.get("outputs")
        if outs:
            outs = [o for o in outs if o in ("vertical", "instagram", "landscape")] or list(OUTPUTS)
            self.outs = {t: self.out_dir / f"{self.name}_{t}.mp4" for t in outs}
            self.final = next(iter(self.outs.values()))
        return self

    def opt(self, key, default=None):
        return self.options.get(key, default)

    def text(self):
        if self.brief_text is None:
            if not self.brief.exists():
                sys.exit(f"{self.brief.name} not found. Write your brief script there first.")
            self.brief_text = self.brief.read_text(encoding="utf-8")
        return self.brief_text

    @staticmethod
    def default():
        return Job("final", brief=BRIEF, plan=PLAN, prompt=PROMPT, work=WORK)


def slug(text, idx):
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    first = re.sub(r"^\s*(video|title)\s*:\s*", "", first, flags=re.I)
    s = re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-")[:40]
    return f"{idx:02d}_{s}" if s else f"video_{idx:02d}"


def split_scripts(text):
    """Scripts are separated by a line with --- and/or simply by the next 'Video:' line."""
    out = []
    for part in re.split(r"(?m)^\s*---+\s*$", text):
        cur, has_video = [], False
        for ln in part.splitlines():
            is_video = bool(re.match(r"(?i)^\s*video\s*:", ln))
            if is_video and has_video:
                if any(x.strip() for x in cur):
                    out.append("\n".join(cur).strip())
                cur = []
            cur.append(ln)
            has_video = has_video or is_video
        if any(x.strip() for x in cur):
            out.append("\n".join(cur).strip())
    return [t for t in out if t]


def collect_jobs():
    """Scripts come from scripts.txt (many scripts) and/or jobs\\*.txt (one per file)."""
    texts = []
    if SCRIPTS.exists():
        texts += split_scripts(SCRIPTS.read_text(encoding="utf-8"))
    if JOBS_DIR.exists():
        for f in sorted(JOBS_DIR.glob("*.txt")):
            texts += split_scripts(f.read_text(encoding="utf-8"))
    return [Job(slug(t, i), brief_text=t) for i, t in enumerate(texts, 1)]


# ----------------------------------------------------------------------------
# PLAN  (script -> plan json via opencode)
# ----------------------------------------------------------------------------
PLAN_INSTRUCTIONS = """You are planning a narrated screen-demo video. A robot will use a REAL browser with a REAL mouse and keyboard,
like a person would. Read the BRIEF below and produce ONE JSON object and nothing else, exactly in this shape:

{
  "title": "short title",
  "voice": "",
  "scenes": [
    { "say": "1-2 sentence narration for this scene (max 25 words)",
      "do": [ {"goto": "https://example.com"}, {"scroll": 800}, {"click": "visible link or button text"} ] }
  ]
}

Allowed actions inside "do":
  {"goto": "<full url>"}                          typed into the address bar and Enter (like a person)
  {"click": "<visible text>"}                     move the pointer to it and click
  {"hover": "<visible text>"}                     move the pointer onto it
  {"type": ["<placeholder or label>", "<text>"]}  click an input and type
  {"press": "enter"}                              press a key (enter, tab, esc, down, up, pagedown ...)
  {"scroll": <pixels>}                            mouse-wheel scroll, positive = down, negative = up
  {"wait": <seconds>}

Rules:
- The narration must describe what is on screen during that scene, in the same order as the actions.
- At most 4 actions per scene. Use the exact visible text from PAGE HINTS when available.
- Do not invent buttons that are not in PAGE HINTS. If a cookie banner is likely, add a click for its Accept button.
- Do not scroll back to the top unless the brief says so. Keep scrolls short (400-900 pixels each).
- Narration language = the language of the BRIEF. Leave "voice" empty unless the brief names one.
- Save the JSON to the file {SAVE_TO}. Output nothing else.
"""


SCOUT_JS = """() => {
  const vw = innerWidth, vh = innerHeight, seen = new Set(), texts = [];
  const add = t => { t = (t || '').trim().replace(/\\s+/g, ' '); if (t.length > 1 && t.length < 60 && !seen.has(t)) { seen.add(t); texts.push(t); } };
  for (const e of document.querySelectorAll('a,button,[role=button],[role=link],[role=tab],[role=menuitem],summary,label,h1,h2,h3,input,textarea')) {
    if (e.offsetParent === null && getComputedStyle(e).position !== 'fixed') continue;
    add(e.innerText || e.placeholder || e.getAttribute('aria-label') || e.title);
  }
  for (const e of document.querySelectorAll('span,div,li,p')) {
    if (e.childElementCount === 0 && e.offsetParent !== null) add(e.innerText);
    if (texts.length > 260) break;
  }
  const se = document.scrollingElement || document.documentElement;
  let room = se.scrollHeight - vh;
  for (const e of document.querySelectorAll('div,main,section,ul')) {
    const cs = getComputedStyle(e);
    if (/(auto|scroll)/.test(cs.overflowY) && e.clientHeight > vh * 0.3 && e.scrollHeight - e.clientHeight > room) room = e.scrollHeight - e.clientHeight;
  }
  return {texts: texts.slice(0, 260), scroll: Math.round(room)};
}"""


def _texts(v):
    return v["texts"] if isinstance(v, dict) else list(v)


def collect_page_hints(urls):
    """The built-in 'scout': load each page headless (not recorded) and note its real button/link/heading texts and
    how far it can scroll. {url: {"texts": [...], "scroll": px}}.  (Same idea as the accessibility snapshots that
    Playwright MCP gives an AI agent, but done directly so no AI client is needed.)"""
    from playwright.sync_api import sync_playwright
    hints = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=find_browser(), headless=True)
        pg = b.new_page(viewport={"width": 1500, "height": 820})
        for u in urls[:6]:
            try:
                pg.goto(u, wait_until="domcontentloaded", timeout=30000)
                pg.wait_for_timeout(2000)
                hints[u] = pg.evaluate(SCOUT_JS)
            except Exception as e:
                print(f"    (could not read {u}: {type(e).__name__})")
                hints[u] = {"texts": [], "scroll": None}
        b.close()
    return hints


def validate_plan(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    sc = plan.get("scenes")
    if not sc or not all(isinstance(s.get("say"), str) and s["say"].strip() for s in sc):
        raise ValueError("plan has no scenes, or a scene without narration ('say')")
    return plan


# ---- built-in planner: no AI, no network, no opencode ----------------------
URL_RE = re.compile(r"https?://[^\s)\"'<>]*[^\s)\"'<>.,;:!?]")
TAG_RE = re.compile(r"\[(goto|click|hover|type|scroll|wait|press|explore|upload|verify)\b\s*([^\]]*)\]", re.I)
META_RE = re.compile(r"^\s*(video|title|tone|style|language|voice|gender|music|note|notes|tag|category|part|brand|template|depth|outputs|captions|frame)\s*:\s*(.*)$", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u0980-\u09FF\"\u201c])")
CLAUSE_SPLIT = re.compile(r"\s*(?:,\s*)?(?:and\s+)?then\s+|,\s+(?=(?:click|press|pick|choose|select|open|scroll|type|search|hover)\b)"
                          r"|\s+and\s+(?=(?:click|press|pick|choose|select|scroll|type|search|hover|go to|navigate|visit)\b)", re.I)
IMPERATIVES = {"open", "go", "visit", "show", "scroll", "click", "pick", "choose", "select", "type", "search", "hover",
               "press", "look", "take", "see", "check", "start", "try", "navigate", "enter", "explore", "browse", "view",
               "watch", "notice", "point", "highlight", "demonstrate", "use", "head", "load", "launch", "keep", "continue"}
LEADS = ["Next, let's", "Now let's", "Then, let's", "Let's"]
PRONOUNS = {"it", "that", "this", "them", "one", "there", "here", "those", "these"}


def domain_of(url):
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]


def cap(t):
    t = t.strip()
    return (t[:1].upper() + t[1:]) if t else t


def parse_tags(line):
    """Exact control: [click Linux Mint] [scroll 800] [type Search | mint] [hover X] [wait 2] [goto url] [press enter]."""
    acts = []
    for m in TAG_RE.finditer(line):
        k, v = m.group(1).lower(), m.group(2).strip().strip("\"\u201c\u201d'")
        if k == "goto":
            acts.append({"goto": v})
        elif k in ("click", "hover"):
            acts.append({k: v})
        elif k == "type":
            f, _, t = v.partition("|")
            acts.append({"type": [f.strip() or "Search", t.strip()]})
        elif k == "scroll":
            try:
                acts.append({"scroll": int(float(v))})
            except ValueError:
                acts.append({"scroll": 800})
        elif k == "wait":
            try:
                acts.append({"wait": float(v or 2)})
            except ValueError:
                acts.append({"wait": 2})
        elif k == "press":
            acts.append({"press": v or "enter"})
        elif k == "explore":
            acts.append({"explore": int(float(v)) if re.fullmatch(r"\d+(\.\d+)?", v or "") else 3})
        elif k == "upload":                                   # [upload Upload photo]  or  [upload Upload photo | 2]
            f, _, which = v.partition("|")
            acts.append({"upload": [f.strip() or "Upload", which.strip()]})
        elif k == "verify":                                   # wait for the temp-mail message and open its link
            acts.append({"verify": v.strip() or "link"})
    return acts, re.sub(r"\s+", " ", TAG_RE.sub("", line)).strip()


def resolve_target(phrase, hints):
    """Turn 'the newest Cinnamon option' into a real on-page label such as 'Cinnamon' when the page has one."""
    quoted = bool(re.search("[\"\u201c\u201d]", phrase))
    p = phrase.strip()
    p = re.sub(r"(?i)^(?:on\s+)?(?:the|a|an|that|this)\s+", "", p)
    p = re.sub(r"(?i)\s+(?:button|link|option|tab|menu|card|item|icon|page|section)s?$", "", p)
    if not quoted:
        p = re.split(r"(?i)\s+(?:in order to|so that|which|from|for|to)\s+", p)[0]
    p = p.strip(" ,.;\"\u201c\u201d'")
    if not p or p.lower() in PRONOUNS or p.lower().startswith("and "):
        return None
    words = set(re.findall(r"\w+", p.lower()))
    best, score = None, 0.0
    for h in hints:
        hw = set(re.findall(r"\w+", h.lower()))
        if not hw:
            continue
        sc = len(words & hw) / len(words | hw)
        if p.lower() in h.lower() or h.lower() in p.lower():
            sc = max(sc, 0.8)
        if sc > score:
            best, score = h, sc
    if best and score >= 0.34:
        return best
    wl = re.findall(r"\w+", p.lower())
    for i in range(1, len(wl)):                       # drop leading adjectives: "newest Cinnamon" -> "Cinnamon"
        sub = " ".join(wl[i:])
        for h in hints:
            if sub and sub in h.lower():
                return h
    return p


def clause_actions(c, hints):
    c = re.sub(r"(?i)^(?:and|then|also|slowly|gently|just)\s+", "", c.strip(" ,.;"))
    if not c:
        return []
    m = re.match(r"(?i)scroll(?:ing)?\b(.*)", c)
    if m:
        rest = m.group(1).lower()
        amt = 2500 if re.search(r"bottom|\bend\b|footer|all the way", rest) else 350 if re.search(r"a bit|a little|slightly|\blittle\b", rest) \
            else 1400 if re.search(r"\blong\b|far", rest) else 800
        return [{"scroll": -amt if re.search(r"\bup\b|\btop\b", rest) else amt}]
    if re.match(r"(?i)(?:explore|look around|take a look around|tour|point out|highlight|move (?:the )?(?:mouse|pointer|cursor)|show (?:off )?the (?:features|interface|layout))\b", c):
        return [{"explore": 3}]
    m = re.match(r"(?i)press\s+(enter|return|tab|esc|escape|space|down|up|pagedown|pageup)\b", c)
    if m:
        return [{"press": m.group(1).lower()}]
    # --- upload / sign-up demo actions written in plain English --------------------------------------------------
    if re.match(r"(?i)(?:upload|attach|drop in|drag in|add|choose|select|pick)\s+(?:a|an|the|your|some)?\s*(?:own\s+)?(?:photo|picture|image|file|selfie|screenshot|logo|sample photo)s?\b", c) \
            or re.match(r"(?i)upload\b", c):
        label = next((t for t in hints if re.search(r"(?i)upload|choose (?:a )?file|browse|drop|add (?:a )?(?:photo|image)|select (?:a )?(?:photo|image|file)", t)), "Upload")
        return [{"upload": [label, ""]}]
    if re.match(r"(?i)(?:verify|confirm)\b.*(?:e-?mail|inbox|address|account)|(?:open|click|follow)\s+(?:the\s+)?(?:verification|confirmation|magic|activation)\s+(?:link|e-?mail)|check\s+(?:the\s+)?(?:temp(?:orary)?\s+)?(?:inbox|e-?mail)", c):
        return [{"verify": "link"}]
    if re.match(r"(?i)(?:type|enter|fill in|use|put in)\s+(?:a\s+|an\s+|the\s+|your\s+)?(?:temp(?:orary)?|throw-?away|disposable|fake|new|test)?\s*e-?mail(?:\s+address)?\b", c):
        return [{"type": ["Email", "{email}"]}]
    if re.match(r"(?i)(?:type|enter|fill in|use|put in)\s+(?:a\s+|the\s+|your\s+)?(?:new\s+|strong\s+)?password\b", c):
        return [{"type": ["Password", "{password}"]}]
    if re.match(r"(?i)(?:type|enter|fill in|put in)\s+(?:the\s+|your\s+)?(?:verification|confirmation|one-time|login|security)?\s*code\b", c):
        return [{"type": ["Code", "{code}"]}]
    m = re.match(r"(?i)(type|enter|write|search(?:\s+for)?)\s+(.+)", c)
    if m:
        mm = re.match(r"(?i)[\"\u201c']?(.+?)[\"\u201d']?(?:\s+(?:in|into)\s+(?:the\s+)?(.+))?$", m.group(2).strip())
        field = re.sub(r"(?i)\s+(?:box|field|bar|input)$", "", (mm.group(2) or "Search")).strip() or "Search"
        acts = [{"type": [field, mm.group(1).strip()]}]
        if m.group(1).lower().startswith("search"):
            acts.append({"press": "enter"})
        return acts
    m = re.match(r"(?i)hover(?:ing)?(?:\s+(?:over|on))?\s+(.+)", c)
    if m:
        t = resolve_target(m.group(1), hints)
        return [{"hover": t}] if t else []
    if re.match(r"(?i)(?:wait|pause)\b", c):
        return [{"wait": 2}]
    m = re.match(r"(?i)(?:click|press|tap|hit|pick|choose|select|open|go to|navigate to|visit|start|try|launch)\s+(?:on\s+)?(.+)", c)
    if m:
        t = resolve_target(m.group(1), hints)
        return [{"click": t}] if t else []
    return []


def parse_actions(sentence, hints):
    acts = []
    urls = URL_RE.findall(sentence)
    s = sentence
    if urls:
        acts.append({"goto": urls[0]})
        s = re.sub(r"(?i)\b(?:open|go to|visit|navigate to|load|head to)\s+(?:the\s+(?:site|page|website)\s+)?" + re.escape(urls[0]), " ", s)
        s = s.replace(urls[0], " ")
    s = s.split(":")[0]                                           # text after a colon is a description, not an action
    for c in CLAUSE_SPLIT.split(s):
        acts += clause_actions(c, hints)
    return acts


def make_say(sentence, idx, total):
    text = re.sub(r"\s+", " ", URL_RE.sub(lambda m: domain_of(m.group(0)), sentence)).strip()
    letters = [ch for ch in text if ch.isalpha()]
    if letters and sum(ord(ch) > 127 for ch in letters) / len(letters) > 0.3:      # Bangla etc.: use the line as written
        return text
    m = re.search(r"(?i)\b(?:tell|telling|ask|asking|invite|inviting|encourage|encouraging|urge|urging)\s+(?:the\s+)?(?:people|viewers|everyone|users|them)\s+(?:to\s+)?(.+?)[.!]?$", text)
    if m:
        return cap(m.group(1)) + "."
    m = re.search(r"(?i)\b(?:saying|explaining|mentioning|noting|adding)\s+(?:in one sentence\s+)?(?:that\s+)?(.+?)[.!]?$", text) or \
        re.match(r"(?i)^(?:say|tell|explain|mention|narrate|note)\b(?:\s+in (?:one|a few) sentences?)?(?:\s+(?:that|how))?\s+(.+?)[.!]?$", text)
    if m:
        return cap(m.group(1)) + "."
    body = re.sub(r"(?i)^(?:then|next|now|finally|first|also|and)\b[, ]*", "", text.rstrip(".!")).strip()
    first = re.match(r"[A-Za-z']+", body)
    if first and first.group(0).lower() in IMPERATIVES:
        lead = "Let's" if idx == 0 else ("Finally, let's" if idx == total - 1 and total > 2 else LEADS[idx % len(LEADS)])
        return f"{lead} {body[0].lower() + body[1:]}."
    return cap(body) + "."


def plan_builtin(brief, hints_by_url):
    """Script -> plan without any AI: one scene per sentence, narration written from the line, actions read from it."""
    hints = [t for v in hints_by_url.values() for t in _texts(v)]
    title, voice, gender, tag, part, locked, lines = "", "", "", "", "", False, []
    meta = {}
    for raw in brief.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = META_RE.match(raw)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k == "video" and not locked:
                title = v
            elif k == "title":
                title, locked = v, True
            elif k in ("voice", "gender"):
                if v.lower() in ("male", "female"):
                    gender = v.lower()
                elif re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}-\w+", v):
                    voice = v
            elif k in ("tag", "category"):
                tag = v
            elif k == "part":
                part = v
            elif k == "language" and re.search(r"(?i)bangla|bengali|\bbn\b", v):
                voice = voice or "bn-BD-NabanitaNeural"
            elif k in ("template", "depth", "outputs", "captions", "frame"):
                meta[k] = v
            continue
        if "||" in raw:                                           # "actions || exact narration": one scene, never split
            lines.append(raw)
        else:
            lines += [x.strip() for x in SENT_SPLIT.split(raw) if x.strip()]
    scenes = []
    for i, ln in enumerate(lines):
        custom = None
        if "||" in ln:
            ln, custom = [x.strip() for x in ln.split("||", 1)]
        tag_acts, clean = parse_tags(ln)
        acts = tag_acts if tag_acts else parse_actions(clean, hints)
        if custom:                                                # the author wrote the narration: use it as is
            scenes.append({"say": re.sub(r"\s+", " ", URL_RE.sub(lambda m: domain_of(m.group(0)), custom)), "do": acts})
            continue
        if not clean:                                             # a line with only [tags]: attach to the previous scene
            if scenes:
                scenes[-1]["do"] += acts
            continue
        scenes.append({"say": make_say(clean, i, len(lines)), "do": acts})
    first_url = next(iter(URL_RE.findall(brief)), None)
    if scenes and first_url and not any("goto" in a for sc in scenes for a in sc["do"]):
        scenes[0]["do"].insert(0, {"goto": first_url})
    return {"title": title or "Video", "title_locked": locked, "voice": voice, "gender": gender, "tag": tag, "part": part,
            "meta": meta, "scenes": scenes}


def repair_plan(plan, hints_by_url):
    """Use what the scout learned: scrolling on a page that cannot scroll becomes a pointer tour, and clicks on text the
    page does not contain are reported (they are handled live too: a missing target becomes a pointer tour)."""
    notes, cur = [], None
    for i, sc in enumerate(plan["scenes"], 1):
        new = []
        for a in sc["do"]:
            if "goto" in a:
                cur = a["goto"]
                new.append(a)
                continue
            info = hints_by_url.get(cur) if cur else None
            if "scroll" in a and isinstance(info, dict) and info.get("scroll") is not None and info["scroll"] < 120:
                notes.append(f"scene {i}: {domain_of(cur)} does not scroll -> using a pointer tour instead")
                new.append({"explore": 3})
                continue
            key = "click" if "click" in a else "hover" if "hover" in a else None
            if key and isinstance(info, dict) and info["texts"]:
                tl_ = a[key].lower()
                if not any(tl_ in t.lower() or t.lower() in tl_ for t in info["texts"]):
                    notes.append(f"scene {i}: '{a[key]}' was not found on {domain_of(cur)} (will tour the page if still missing)")
            new.append(a)
            if "click" in a:
                cur = None                                        # the page may have changed
        sc["do"] = new
    return notes


def preview_plan(plan):
    for i, sc in enumerate(plan["scenes"], 1):
        acts = ", ".join(next(iter(a.items()))[0] + ":" + str(next(iter(a.values()))) for a in sc["do"]) or "(no actions)"
        print(f"    {i}. \"{sc['say'][:70]}\"  ->  {acts[:90]}")


# ---- optional: opencode planner ----------------------------------------------
def find_opencode():
    for n in ("opencode", "opencode.cmd", "opencode.exe"):
        w = shutil.which(n)
        if w:
            return w
    home = Path.home()
    for c in (Path(os.environ.get("APPDATA", "")) / "npm" / "opencode.cmd", home / ".opencode" / "bin" / "opencode.exe",
              home / ".bun" / "bin" / "opencode.exe", home / "scoop" / "shims" / "opencode.exe",
              Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "opencode" / "opencode.exe"):
        if c.exists():
            return str(c)
    return None


def extract_json(text):
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    depth, start = 0, None
    for k, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = k
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    json.loads(text[start:k + 1])
                    return text[start:k + 1]
                except ValueError:
                    start = None
    return None


def plan_with_opencode(job, brief, hints):
    exe = find_opencode()
    if not exe:
        print("  opencode not found - using the built-in planner instead.")
        return False
    lines = "\n".join(f"{u}\n  " + " | ".join(_texts(t)[:80]) for u, t in hints.items())
    save_to = job.plan.relative_to(ROOT).as_posix() if job.plan.is_relative_to(ROOT) else str(job.plan)
    prompt_rel = job.prompt.relative_to(ROOT).as_posix() if job.prompt.is_relative_to(ROOT) else str(job.prompt)
    job.prompt.parent.mkdir(parents=True, exist_ok=True)
    job.prompt.write_text(PLAN_INSTRUCTIONS.replace("{SAVE_TO}", save_to) +
                          "If you cannot write files, print ONLY the JSON.\n" +
                          f"\nBRIEF:\n{brief}\n\nPAGE HINTS:\n{lines or '(none)'}\n", encoding="utf-8")
    print("  asking opencode to write the plan ...")
    try:
        r = subprocess.run([exe, "run", f"Read {prompt_rel} and follow it exactly. Save the result as {save_to}."], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except Exception as e:
        print(f"  opencode failed ({type(e).__name__}) - using the built-in planner instead.")
        return False
    if not job.plan.exists():
        js = extract_json(r.stdout or "")
        if js:
            job.plan.write_text(js, encoding="utf-8")
    try:
        validate_plan(job.plan)
        return True
    except Exception:
        print("  opencode did not produce a usable plan - using the built-in planner instead.")
        job.plan.unlink(missing_ok=True)
        return False


def plan_job(job):
    """Script -> plan json. Works by itself (built-in planner). If you put an AI key in .env, an AI editor then polishes the
    narration and checks every action against what the page really contains today. opencode is an optional alternative."""
    brief = job.text()
    urls = URL_RE.findall(brief)
    hints = {}
    if urls:
        print("  scouting the pages in the script (real button names, how far each page scrolls) ...")
        try:
            hints = collect_page_hints(urls)
        except Exception as e:
            print(f"  (could not read the pages: {type(e).__name__}; continuing without)")
    job.plan.parent.mkdir(parents=True, exist_ok=True)
    job.plan.unlink(missing_ok=True)
    if PLANNER == "opencode":
        plan_with_opencode(job, brief, hints)
    if not job.plan.exists():
        built = plan_builtin(brief, hints)
        notes = repair_plan(built, hints)
        if PLANNER in ("auto", "api") and ai_configured():
            try:
                built = ai_refine_plan(built, brief, hints)
                notes = repair_plan(built, hints)
                print("  AI editor: narration polished and actions checked against the scouted pages.")
            except Exception as e:
                print(f"  (AI editor skipped: {str(e)[:120]}; using the built-in plan)")
        job.plan.write_text(json.dumps(built, ensure_ascii=False, indent=2), encoding="utf-8")
        for n in notes:
            print(f"  ! {n}")
    try:
        plan = validate_plan(job.plan)
    except Exception:
        job.plan.unlink(missing_ok=True)                          # do not leave an unusable plan behind
        raise
    preview_plan(plan)


# ----------------------------------------------------------------------------
# REAL MOUSE / KEYBOARD
# ----------------------------------------------------------------------------
def human_path(p0, p1):
    """Curved, slightly bent path between two points (cubic bezier). Returns (f(u)->(x,y), distance)."""
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / dist, dx / dist
    bend = random.uniform(-0.16, 0.16) * dist
    c1 = (x0 + dx * 0.30 + nx * bend, y0 + dy * 0.30 + ny * bend)
    c2 = (x0 + dx * 0.72 + nx * bend * 0.6, y0 + dy * 0.72 + ny * bend * 0.6)

    def f(u):
        a, b, c, d = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u ** 2, u ** 3
        return a * x0 + b * c1[0] + c * c2[0] + d * x1, a * y0 + b * c1[1] + c * c2[1] + d * y1
    return f, dist


def mouse_move(x, y, dur=None):
    pg = _pg()
    p0 = tuple(pg.position())
    f, dist = human_path(p0, (x, y))
    dur = dur or min(1.3, max(0.45, 0.35 + dist / 1800))
    t0 = time.perf_counter()
    while True:
        u = (time.perf_counter() - t0) / dur
        if u >= 1:
            break
        px, py = f(smoother(u))
        pg.moveTo(round(px), round(py))
        time.sleep(0.004)
    pg.moveTo(round(x), round(y))


def mouse_click():
    pg = _pg()
    pg.mouseDown()
    time.sleep(random.uniform(0.05, 0.11))
    pg.mouseUp()


def wheel(notches):
    """Real mouse-wheel scrolling. Positive = down. One notch is about 100 px in Chrome."""
    pg = _pg()
    d = -1 if notches > 0 else 1                 # pyautogui: positive scrolls UP
    if not IS_WIN:                               # X11: one wheel click is about 96 px in Chrome
        for _ in range(abs(int(notches))):
            pg.scroll(d)
            time.sleep(random.uniform(0.06, 0.12))
        return
    for _ in range(abs(int(notches))):
        for _ in range(3):
            pg.scroll(d * 40)
            time.sleep(0.016)
        time.sleep(random.uniform(0.05, 0.10))


def drift(clock, seconds):
    """Keep the pointer alive: a slow, tiny sway around where it is. The pointer is never frozen."""
    pg = _pg()
    x0, y0 = pg.position()
    rx, ry = random.uniform(7, 13), random.uniform(4, 8)
    ph = random.uniform(0, 6.28)
    end = clock() + seconds
    t0 = time.perf_counter()
    while clock() < end:
        t = time.perf_counter() - t0
        pg.moveTo(round(x0 + rx * math.sin(t * 0.8 + ph) - rx * math.sin(ph)),
                  round(y0 + ry * math.sin(t * 0.55 + ph * 0.5) - ry * math.sin(ph * 0.5)))
        time.sleep(0.02)


# ----------------------------------------------------------------------------
# CONTROLLED SESSION  (fresh profile, real window, cleaned afterwards)
# ----------------------------------------------------------------------------
MOUSE_JS = ("(() => { if (window.__avmm_on) return; window.__avmm_on = true;"
            " addEventListener('mousemove', e => { window.__mm = [e.clientX, e.clientY, e.screenX, e.screenY]; }, true); })()")


SCROLL_JS = """(() => { const m = window.__mm; const se = document.scrollingElement || document.documentElement;
  let pos = se.scrollTop, room = Math.max(0, se.scrollHeight - se.clientHeight - se.scrollTop);
  let el = m ? document.elementFromPoint(m[0], m[1]) : null;
  while (el && el !== document.body && el !== document.documentElement) {
    const cs = getComputedStyle(el);
    if (/(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 4) {
      pos += el.scrollTop; room += Math.max(0, el.scrollHeight - el.clientHeight - el.scrollTop); break; }
    el = el.parentElement; }
  return [pos, room]; })()"""

EXPLORE_JS = """(() => { const vw = innerWidth, vh = innerHeight, out = [];
  for (const e of document.querySelectorAll('a,button,[role=button],input,textarea,select,summary,h1,h2,h3')) {
    const r = e.getBoundingClientRect();
    if (r.width < 40 || r.height < 16 || r.width * r.height > vw * vh * 0.5) continue;
    if (r.bottom < 60 || r.top > vh - 30 || r.right < 0 || r.left > vw) continue;
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
    const inter = /^(A|BUTTON|INPUT|TEXTAREA|SELECT|SUMMARY)$/.test(e.tagName) || e.getAttribute('role') === 'button';
    out.push({x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height, inter: inter}); }
  return out; })()"""


def choose_tour(cands, n, min_gap=170, avoid=()):
    """Pick up to n well-spread, interesting on-page targets for a pointer tour (interactive, mid-sized first).
    Places listed in `avoid` (already visited on this page) are skipped when there is anything else to show."""
    def score(c):
        area = c["w"] * c["h"]
        return (0 if c["inter"] else 1, 0 if 1500 < area < 120000 else 1, abs(c["y"] - 380))
    fresh = [c for c in cands if all(math.hypot(c["x"] - a[0], c["y"] - a[1]) > 90 for a in avoid)]
    if len(fresh) >= 1:
        cands = fresh
    picked = []
    for c in sorted(cands, key=score):
        if all(math.hypot(c["x"] - p["x"], c["y"] - p["y"]) >= min_gap for p in picked):
            picked.append(c)
        if len(picked) >= n:
            break
    return sorted(picked, key=lambda c: (round(c["y"] / 120), c["x"]))


class Session:
    """Starts a throw-away browser. Playwright is attached ONLY to read element positions and to verify results;
    every move, click, key and scroll is done by the real OS mouse and keyboard."""

    def __init__(self, assets=None):
        self.region = work_area()
        self.assets = list(assets or [])      # images the user sent (or a generated sample) for [upload ...]
        self.upload_file = None               # file the next native file-chooser should receive
        self.mail, self.mail_state = None, {}
        self.profile = Path(tempfile.mkdtemp(prefix="autovideo_profile_"))
        self.port = free_port()
        self.proc = self.pw = self.browser = self.ctx = self.page = None
        self.ax = self.ay = self.b0 = self.dpr0 = None   # page px -> physical screen px:  screen = a + b * client
        self.clock = None            # set to the recorder clock once recording starts
        self.marks = []              # (time, kind): what kind of moment starts now (drives the speed edit)
        self.visited = []            # pointer-tour spots already shown on the current page
        self.focus = []              # [t0, t1, x, y]: moments the camera should look at the address bar

    def mark(self, kind):
        if self.clock:
            self.marks.append((self.clock(), kind))

    def __enter__(self):
        try:
            self._start()
        except BaseException:
            self.cleanup()
            raise
        return self

    def __exit__(self, *exc):
        self.cleanup()
        return False

    def _start(self):
        from playwright.sync_api import sync_playwright
        args = [find_browser(), f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}",
                "--remote-allow-origins=*", "--no-first-run", "--no-default-browser-check", "--start-maximized",
                "--disable-sync", "--disable-extensions", "--disable-notifications", "--password-store=basic",
                "--disable-session-crashed-bubble", "--hide-crash-restore-bubble", "--lang=en-US",
                "--disable-features=Translate,TranslateUI,OptimizationHints,PrivacySandboxSettings4", "about:blank"]
        if not IS_WIN:                                           # Linux / Xvfb / containers
            x, y, w, h = self.region
            args[1:1] = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--force-device-scale-factor=1",
                         f"--window-position={x},{y}", f"--window-size={w},{h}", "--disable-infobars",
                         "--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=not IS_WIN)
        for _ in range(80):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1).read()
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("The browser did not start (remote debugging port never opened).")
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.ctx = self.browser.contexts[0]
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.ctx.add_init_script(MOUSE_JS)
        self._hook_pages()
        self.page.evaluate(MOUSE_JS)
        self.page.bring_to_front()
        time.sleep(1.0)
        self.calibrate()

    def _hook_pages(self):
        """Native file dialogs cannot be driven by a mouse on a server: Playwright just hands the chosen file to the
        chooser that the REAL click opened (the click itself, the pointer and the timing stay real)."""
        def on_chooser(fc):
            f = self.upload_file or (self.assets[0] if self.assets else None)
            if f:
                try:
                    fc.set_files(str(f))
                    self.uploaded = True
                except Exception as e:
                    print(f"    ! the file chooser refused the file: {e}")
        self.uploaded = False
        for pg_ in self.ctx.pages:
            pg_.on("filechooser", on_chooser)
        self.ctx.on("page", lambda pg_: pg_.on("filechooser", on_chooser))

    def mailbox(self):
        if self.mail is None:
            from avx_mail import TempMail
            self.mail = TempMail()
        return self.mail

    def fill(self, text):
        """Placeholders {email} {password} {code} {name} -> real values from the throw-away mailbox."""
        if "{" not in text:
            return text
        return self.mailbox().fill(text, self.mail_state)

    def cleanup(self):
        """Kill the browser and delete the whole profile: history, cookies, cache, session."""
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass
        if self.proc:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                try:
                    os.killpg(os.getpgid(self.proc.pid), 9)          # the whole browser process tree
                except Exception:
                    self.proc.kill()
        for _ in range(20):
            try:
                shutil.rmtree(self.profile)
                break
            except FileNotFoundError:
                break
            except Exception:
                time.sleep(0.5)
        if self.profile.exists():
            print(f"  ! could not fully delete the temp profile: {self.profile}")

    # -- coordinates -------------------------------------------------------
    def calibrate(self):
        """Fit  screen = a + b * client  from two real mouse moves. Only uses positions we sent and positions the page
        reported, so it does not depend on display scaling, browser flags or zoom."""
        pg = _pg()
        x, y, w, h = self.region
        pts = [(x + int(w * .35), y + int(h * .55)), (x + int(w * .65), y + int(h * .75))]
        got = []
        for px, py in pts:
            pg.moveTo(px, py)
            time.sleep(0.2)
            pg.moveTo(px + 1, py + 1)
            time.sleep(0.25)
            mm = self.page.evaluate("window.__mm")
            if not mm:
                raise RuntimeError("Calibration failed: the page did not receive the real mouse. Is another window covering the browser?")
            got.append((px + 1, py + 1, mm))
        (p1x, p1y, m1), (p2x, p2y, m2) = got
        bx, by = (p2x - p1x) / (m2[0] - m1[0]), (p2y - p1y) / (m2[1] - m1[1])
        self.b0 = (bx + by) / 2
        self.ax, self.ay = p1x - bx * m1[0], p1y - by * m1[1]
        self.dpr0 = float(self.page.evaluate("window.devicePixelRatio"))

    def b_now(self):
        """Physical pixels per page pixel right now (changes when the page is zoomed)."""
        try:
            return self.b0 * float(self.page.evaluate("window.devicePixelRatio")) / self.dpr0
        except Exception:
            return self.b0

    def to_screen(self, cx, cy):
        b = self.b_now()
        return self.ax + b * cx, self.ay + b * cy

    def point_at(self, cx, cy):
        """Move the real pointer to page coords (cx, cy) and verify it landed there."""
        sx, sy = self.to_screen(cx, cy)
        mouse_move(sx, sy)
        time.sleep(0.12)
        try:
            mm = self.page.evaluate("window.__mm")
            ex, ey = cx - mm[0], cy - mm[1]
            if abs(ex) > 2 or abs(ey) > 2:                   # tiny correction, like a human nudge
                b = self.b_now()
                _pg().moveRel(round(ex * b), round(ey * b))
                sx, sy = self.to_screen(cx, cy)
        except Exception:
            pass
        return sx, sy

    def ensure_zoom(self):
        """Browser zoom (real Ctrl+= presses) so text is readable in a 1080p video. Zoom is remembered per site."""
        if PAGE_ZOOM <= 1.0:
            return
        pg = _pg()
        for _ in range(5):
            try:
                r = float(self.page.evaluate("window.devicePixelRatio")) / self.dpr0
            except Exception:
                return
            if r >= PAGE_ZOOM - 0.03:
                return
            pg.hotkey("ctrl", "=")
            time.sleep(0.3)

    def content_center(self):
        x, y, w, h = self.region
        return x + w * 0.5, y + h * 0.6

    # -- finding things ------------------------------------------------------
    def find(self, text):
        pg = self.page
        for loc in (pg.get_by_role("link", name=text), pg.get_by_role("button", name=text),
                    pg.get_by_text(text), pg.get_by_placeholder(text), pg.get_by_label(text)):
            try:
                for i in range(min(loc.count(), 6)):
                    el = loc.nth(i)
                    if el.is_visible():
                        return el
            except Exception:
                continue
        return None

    def target_field(self, label):
        """When a label is not found, fall back to the first visible text box / search box / chat box on the page."""
        if not re.search(r"(?i)search|message|chat|prompt|ask|question|query|e-?mail|password|code|name|type|text|input", label or ""):
            return None
        for sel in ("textarea", "input[type=search]", "input[type=email]", "input[type=password]", "input[type=text]", "input:not([type])",
                    "[contenteditable=true]", "[role=textbox]"):
            try:
                loc = self.page.locator(sel)
                for i in range(min(loc.count(), 6)):
                    el = loc.nth(i)
                    if el.is_visible():
                        b = el.bounding_box()
                        if b and b["width"] > 40:
                            print(f"    (no field called '{label}': using the first visible {sel})")
                            return self.target_el(el)
            except Exception:
                continue
        return None

    def viewport(self):
        return self.page.evaluate("[innerWidth, innerHeight]")

    def target(self, text):
        el = self.find(text)
        if el is None:
            print(f"    ! could not find '{text}' on the page - skipped")
            return None
        return self.target_el(el, text)

    def target_el(self, el, text="field"):
        vw, vh = self.viewport()
        prev = None
        for _ in range(14):                                  # bring it into view with REAL wheel scrolling
            try:
                b = el.bounding_box()
            except Exception:
                return None
            if not b:
                return None
            cy = b["y"] + b["height"] / 2
            if 110 < cy < vh - 110:
                break
            if prev is not None and abs(cy - prev) < 2:      # scrolling does nothing: stop trying
                break
            prev = cy
            self.park_in_page()
            self.mark("scroll")
            wheel(max(1, round(abs(cy - vh / 2) / 100 * 0.85)) * (1 if cy > vh / 2 else -1))
            self.mark("settle")
            time.sleep(0.4)
        self.mark("move")
        b = el.bounding_box()
        if not b or not (0 < b["y"] + b["height"] / 2 < vh):
            print(f"    ! '{text}' is not reachable on screen - skipped")
            return None
        return (b["x"] + b["width"] * random.uniform(0.4, 0.6), b["y"] + b["height"] * random.uniform(0.4, 0.6))

    def park_in_page(self, force=False):
        """Wheel events go to whatever is under the pointer, so make sure it is over the page."""
        px, py = _pg().position()
        x, y, w, h = self.region
        top = self.ay + 24
        if force or not (x + 20 < px < x + w - 20 and top < py < y + h - 20):
            mouse_move(x + w * random.uniform(0.35, 0.65), top + (y + h - top) * random.uniform(0.35, 0.75), 0.5)

    def scroll_state(self):
        try:
            return self.page.evaluate(SCROLL_JS)
        except Exception:
            return [0, 0]

    def scroll_by(self, px):
        """A real wheel scroll that is VERIFIED. If nothing moved: try another spot, then the PageDown key.
        Returns how many pixels the page really scrolled (0 = this page does not scroll)."""
        sign = 1 if px > 0 else -1
        notches = max(1, round(abs(px) / 100))
        for attempt in range(3):
            self.park_in_page(force=attempt > 0)
            before = self.scroll_state()
            self.mark("scroll")
            if attempt < 2:
                wheel(sign * notches)
            else:
                _pg().press("pagedown" if sign > 0 else "pageup")
            self.mark("settle")
            time.sleep(0.7)
            moved = abs(self.scroll_state()[0] - before[0])
            if moved >= 25:
                return moved
        return 0


class CursorLogger(threading.Thread):
    """Logs the REAL pointer position and left-button state ~60 times a second. The edit draws a large, smooth cursor
    from this telemetry (the same way screen-recording apps do), so the cursor is always visible and never tiny."""

    def __init__(self, clock, region):
        super().__init__(daemon=True)
        self.clock, self.rx, self.ry = clock, region[0], region[1]
        self.samples, self._halt = [], threading.Event()

    def run(self):
        if not IS_WIN:
            d = _pg().d
            while not self._halt.is_set():
                x, y, down = d.position()
                self.samples.append((round(self.clock(), 4), x - self.rx, y - self.ry, 1 if down else 0))
                time.sleep(0.008)
            return
        from ctypes import wintypes
        pt = wintypes.POINT()
        get_pos, get_key = ctypes.windll.user32.GetCursorPos, ctypes.windll.user32.GetAsyncKeyState
        while not self._halt.is_set():
            get_pos(ctypes.byref(pt))
            self.samples.append((round(self.clock(), 4), pt.x - self.rx, pt.y - self.ry, 1 if get_key(0x01) & 0x8000 else 0))
            time.sleep(0.008)

    def stop(self):
        self._halt.set()
        self.join(1.0)


class Recorder:
    """Records the real screen region with ffmpeg. The system pointer is NOT recorded (draw_mouse 0): the edit draws a
    proper large cursor from the logged real pointer path instead."""

    def __init__(self, region, out_path, draw_mouse=False):
        self.region, self.out, self.t0, self.draw_mouse = region, out_path, None, draw_mouse
        self.proc, self.ready = None, threading.Event()

    def start(self):
        x, y, w, h = self.region
        dm = 1 if self.draw_mouse else 0
        if not IS_WIN:
            disp = os.environ.get("DISPLAY", ":0")
            src = ["-f", "x11grab", "-framerate", str(FPS), "-draw_mouse", str(dm), "-video_size", f"{w}x{h}",
                   "-i", f"{disp}+{x},{y}"]
        elif CAPTURE == "ddagrab":
            src = ["-f", "lavfi", "-i", f"ddagrab=framerate={FPS}:draw_mouse={dm}:offset_x={x}:offset_y={y}:video_size={w}x{h},hwdownload,format=bgra"]
        else:
            src = ["-f", "gdigrab", "-framerate", str(FPS), "-offset_x", str(x), "-offset_y", str(y),
                   "-video_size", f"{w}x{h}", "-draw_mouse", str(dm), "-i", "desktop"]
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *src, "-c:v", "libx264", "-preset", "ultrafast",
               "-crf", "14", "-pix_fmt", "yuv420p", "-progress", "pipe:1", "-stats_period", "0.05", str(self.out)]
        env = dict(os.environ, __COMPAT_LAYER="HIGHDPIAWARE") if IS_WIN else dict(os.environ)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, env=env)
        threading.Thread(target=self._read, daemon=True).start()
        if not self.ready.wait(10):
            err = ""
            if self.proc.poll() is not None:
                err = self.proc.stderr.read()[-800:]
            raise RuntimeError(f"Screen recording did not start. {err}")

    def _read(self):
        for line in self.proc.stdout:
            if not self.ready.is_set() and line.startswith("out_time_us="):
                try:
                    v = int(line.split("=")[1])
                except ValueError:
                    continue
                if v >= 0:
                    self.t0 = time.time() - v / 1e6              # wall-clock moment of the first captured frame
                    self.ready.set()

    def clock(self):
        return time.time() - self.t0

    def stop(self):
        try:
            self.proc.stdin.write("q")
            self.proc.stdin.flush()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=20)
        except Exception:
            self.proc.kill()


# ----------------------------------------------------------------------------
# PERFORM THE PLAN LIVE  (real input, real recording)
# ----------------------------------------------------------------------------
def type_text(sess, s):
    pg = _pg()
    for ch in s:
        if ord(ch) < 128:
            pg.write(ch)
        else:
            sess.page.keyboard.insert_text(ch)                   # non-ASCII fallback (Bangla etc.)
        time.sleep(random.uniform(0.045, 0.12) + (random.uniform(0.15, 0.3) if random.random() < 0.05 else 0))


def wait_loaded(sess):
    time.sleep(0.8)
    try:
        sess.page.wait_for_load_state("load", timeout=20000)
    except Exception:
        pass
    sess.ensure_zoom()                                           # readable text: real Ctrl+= presses
    sess.visited = []                                            # new page: tours may show its spots again
    time.sleep(1.2)                                              # let page animations settle


def explore(sess, rec, events, n=3):
    """A pointer tour of the page: the pointer visits the most interesting buttons/inputs/headings in view.
    Used when a page cannot scroll, and for narration-only scenes, so something real always happens on screen."""
    sess.mark("move")
    try:
        cands = sess.page.evaluate(EXPLORE_JS)
    except Exception:
        cands = []
    tour = choose_tour(cands, n, avoid=sess.visited)
    sess.visited += [(c["x"], c["y"]) for c in tour]
    if not tour:
        sess.mark("hold")
        drift(rec.clock, 1.2)
        return
    for c in tour:
        sess.mark("move")
        sx, sy = sess.point_at(c["x"], c["y"])
        events.append((rec.clock(), sx - sess.region[0], sy - sess.region[1], "look"))
        sess.mark("hold")
        drift(rec.clock, random.uniform(0.6, 0.9))


def do_action(sess, a, rec, events):
    pg = _pg()
    rx, ry = sess.region[0], sess.region[1]

    def ev(kind, sx, sy):                                        # zoom/ripple target, relative to the recorded region
        events.append((rec.clock(), sx - rx, sy - ry, kind))

    if "goto" in a:
        sess.mark("type")
        fx, fy = 420.0, max(40.0, (sess.ay - ry) - 28 * sess.dpr0)   # about where the address bar text is, in the video
        t_focus = rec.clock()
        events.append((t_focus, fx, fy, "type"))                     # zoom in on the address bar while the URL is typed
        pg.hotkey("ctrl", "l")
        time.sleep(0.4)
        type_text(sess, re.sub(r"^https?://", "", a["goto"]))
        time.sleep(0.25)
        pg.press("enter")
        sess.focus.append([t_focus, rec.clock(), fx, fy])
        sess.mark("load")
        wait_loaded(sess)
    elif "wait" in a:
        sess.mark("wait")
        time.sleep(float(a["wait"]))
    elif "press" in a:
        sess.mark("click")
        pg.press(a["press"])
        sess.mark("settle")
        time.sleep(0.4)
    elif "explore" in a:
        explore(sess, rec, events, int(a["explore"] or 3))
    elif "scroll" in a:
        px = float(a["scroll"])
        sess.mark("move")
        total = 0.0
        long_scroll = abs(px) >= 2000                            # "to the bottom": go in chunks until nothing moves
        for _ in range(3 if long_scroll else 1):
            moved = sess.scroll_by(px / 3 if long_scroll else px)
            total += moved
            if moved < 25:
                break
        if total < 25:
            print("    ! this page does not scroll - touring the page with the pointer instead")
            explore(sess, rec, events, 3)
        else:
            print(f"    scrolled {total:.0f}px")
    elif "hover" in a:
        sess.mark("move")
        t = sess.target(a["hover"])
        if t:
            ev("hover", *sess.point_at(*t))
            sess.mark("hold")
            time.sleep(0.6)
        else:
            explore(sess, rec, events, 1)
    elif "click" in a:
        sess.mark("move")
        t = sess.target(a["click"])
        if t:
            before = len(sess.ctx.pages)
            ev("click", *sess.point_at(*t))
            sess.mark("click")
            time.sleep(0.15)
            mouse_click()
            sess.mark("settle")
            time.sleep(0.7)
            if len(sess.ctx.pages) > before:                     # link opened a new tab: follow it
                sess.page = sess.ctx.pages[-1]
                sess.page.bring_to_front()
                sess.page.evaluate(MOUSE_JS)
            sess.mark("load")
            wait_loaded(sess)
        else:
            explore(sess, rec, events, 1)
    elif "type" in a:
        label, text = a["type"]
        sess.mark("move")
        t = sess.target(label) or sess.target_field(label)
        if t:
            ev("type", *sess.point_at(*t))
            sess.mark("click")
            time.sleep(0.15)
            mouse_click()
            time.sleep(0.3)
            sess.mark("type")
            type_text(sess, sess.fill(text))
            sess.mark("settle")
            time.sleep(0.4)
    elif "upload" in a:
        label, which = a["upload"]
        sess.mark("move")
        t = sess.target(label)
        if t:
            pick = None
            if which and which.isdigit() and 0 < int(which) <= len(sess.assets):
                pick = sess.assets[int(which) - 1]
            elif which:
                pick = next((x for x in sess.assets if which.lower() in Path(x).name.lower()), None)
            sess.upload_file = pick or (sess.assets[0] if sess.assets else None)
            sess.uploaded = False
            ev("click", *sess.point_at(*t))
            sess.mark("click")
            time.sleep(0.15)
            mouse_click()
            for _ in range(20):                                  # wait for the chooser to be answered
                if sess.uploaded:
                    break
                time.sleep(0.1)
            if not sess.uploaded:                                # a hidden <input type=file> that never opened a chooser
                try:
                    sess.page.locator("input[type=file]").first.set_input_files(str(sess.upload_file))
                    sess.uploaded = True
                except Exception:
                    print("    ! no file input found on this page")
            sess.mark("settle")
            time.sleep(1.2)                                       # let the preview appear
            sess.mark("load")
            wait_loaded(sess)
        else:
            explore(sess, rec, events, 1)
    elif "verify" in a:
        sess.mark("wait")
        last = sess.mail_state.get("last")                       # a {code} lookup may already have read the message
        msg = last if (last and last.get("link") and not last.get("opened")) else sess.mailbox().wait_message(timeout=100)
        if msg:
            msg["opened"] = True
        sess.mail_state["last"] = msg
        if not msg or not msg.get("link"):
            print("    ! no confirmation e-mail with a link arrived - continuing")
            return
        sess.mark("type")
        fx, fy = 420.0, max(40.0, (sess.ay - ry) - 28 * sess.dpr0)
        t_focus = rec.clock()
        events.append((t_focus, fx, fy, "type"))
        pg.hotkey("ctrl", "l")
        time.sleep(0.3)
        for ch in re.sub(r"^https?://", "", msg["link"]):          # a long link: typed fast, the edit speeds it up
            pg.write(ch) if ord(ch) < 128 else None
            time.sleep(0.006)
        pg.press("enter")
        sess.focus.append([t_focus, rec.clock(), fx, fy])
        sess.mark("load")
        wait_loaded(sess)


def perform(sess, rec, plan):
    """Run every scene live at a natural pace. Spare footage (a drifting-pointer 'dwell') is recorded at the end of
    each scene, so the edit can TRIM to the narration length instead of ever freezing a frame."""
    sess.clock = rec.clock
    logger = CursorLogger(rec.clock, sess.region)
    logger.start()
    starts, events = [], []
    try:
        sess.mark("idle")
        mouse_move(*sess.content_center(), 0.6)
        time.sleep(0.6)
        for i, sc in enumerate(plan["scenes"]):
            print(f"  scene {i + 1}/{len(plan['scenes'])}: {sc['say'][:60]}")
            s0 = rec.clock()
            starts.append(s0)
            est = len(sc["say"].split()) / WORDS_PER_SEC + 0.6
            sess.mark("hold")
            acts = sc.get("do", [])
            for a in acts:
                try:
                    do_action(sess, a, rec, events)
                except Exception as e:
                    if type(e).__name__ == "FailSafeException":
                        raise
                    print(f"    ! action {a} failed: {e}")
                sess.mark("hold")
                drift(rec.clock, random.uniform(0.35, 0.6))      # a natural beat between actions
            if not acts:                                         # narration-only scene: point at something on the page
                try:
                    explore(sess, rec, events, 1)
                except Exception as e:
                    if type(e).__name__ == "FailSafeException":
                        raise
            spent = rec.clock() - s0
            dwell = min(14.0, max(1.2, est * 1.25 + LEAD + TAIL - spent * 0.5))
            sess.mark("dwell")
            drift(rec.clock, dwell)
        time.sleep(0.2)
    finally:
        logger.stop()
    return {"marks": sess.marks, "starts": starts, "events": events, "total": rec.clock(), "cursor": logger.samples,
            "focus": sess.focus}


# ----------------------------------------------------------------------------
# VOICE (after the video)
# ----------------------------------------------------------------------------
# ---- voice: choose, analyse, synthesise (with exact word timings for the subtitles) -----------------------------
VOICES = {                     # defaults until you run `voice-lab` (it measures voices against your reference video)
    "en": {"male": "en-US-AndrewNeural", "female": "en-US-AvaNeural"},
    "bn": {"male": "bn-BD-PradeepNeural", "female": "bn-BD-NabanitaNeural"},
}
VOICE_CANDIDATES = {
    "male": ["en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-AndrewNeural", "en-US-BrianNeural",
             "en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-EricNeural", "en-US-SteffanNeural", "en-US-RogerNeural"],
    "female": ["en-US-AvaMultilingualNeural", "en-US-EmmaMultilingualNeural", "en-US-AvaNeural", "en-US-EmmaNeural",
               "en-US-JennyNeural", "en-US-AriaNeural", "en-US-MichelleNeural", "en-US-AnaNeural"],
}
LAB_SENTENCE = ("Here is a quick way to try any Linux distro right in your browser. Scroll down, pick the one you like, "
                "and it starts in seconds with nothing to install.")
PROFILE_FILE = ROOT / "voice_profile.json"
# Measured on the reference video with analyze_voice() (same function `voice-profile` runs on any file):
REFERENCE_VOICE = {"f0_median": 175.8, "f0_p25": 145.5, "f0_p75": 219.2, "rate": 8.77}
FORCE_GENDER = None            # set by --male / --female / --voice on the command line, or by /voice in the bot


def is_bengali(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum("\u0980" <= c <= "\u09ff" for c in letters) / len(letters) > 0.3


def fmt_rate(pct):
    return f"{int(round(pct)):+d}%"


def fmt_pitch(hz):
    return f"{int(round(hz)):+d}Hz"


USE_VOICE_PROFILE = False      # True = old behaviour: use the voice `voice-lab` matched to the reference speaker (that one is HIGH, ~176 Hz)


def resolve_voice(plan, force=None, depth=None):
    """-> {"voice","rate","pitch","gender","depth"}. Priority: a voice named in the script > --male/--female (or the bot) > default.
    `depth` (0 natural, 1 warm, 2 deep, 3 very deep) picks a naturally deep base voice, lowers its pitch and drives the
    post-processing in avx_voice.deepen()."""
    import avx_voice as vv
    texts = " ".join(sc["say"] for sc in plan["scenes"])
    lang = "bn" if is_bengali(texts) else "en"
    gender = (plan.get("gender") or force or FORCE_GENDER or DEFAULT_GENDER or "male").lower()
    if gender not in ("male", "female"):
        gender = "male"
    if depth is None:
        depth = (plan.get("meta") or {}).get("depth")
    has = depth is not None and str(depth).strip() != ""
    depth = vv.clamp_depth(depth if has else (vv.DEFAULT_DEPTH if gender == "male" else 1))
    v = (plan.get("voice") or "").strip()
    if re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}-\w+", v):                      # a voice named in the script
        return {"voice": v, "rate": VOICE_RATE, "pitch": vv.tts_pitch(depth), "gender": None, "depth": depth}
    prof = {}
    if lang == "en" and USE_VOICE_PROFILE:
        try:
            prof = json.loads(PROFILE_FILE.read_text(encoding="utf-8")).get(gender, {})
        except Exception:
            prof = {}
    if prof:
        return {"voice": prof.get("voice") or VOICES[lang][gender], "rate": prof.get("rate", VOICE_RATE),
                "pitch": prof.get("pitch", "+0Hz"), "gender": gender, "depth": depth}
    if lang == "en" and gender == "male":
        base = {0: "en-US-AndrewNeural", 1: "en-US-ChristopherNeural", 2: "en-US-ChristopherNeural", 3: "en-US-EricNeural"}[depth]
    else:
        base = VOICES[lang][gender]
    return {"voice": base, "rate": VOICE_RATE, "pitch": vv.tts_pitch(depth) if lang == "en" else "+0Hz", "gender": gender, "depth": depth}


# -- measuring a voice (numpy only) --------------------------------------------------------------------------------
def load_pcm(path, sr=16000):
    p = Path(str(path).strip().strip('"'))
    if not p.exists() and (ROOT / p).exists():                   # also look next to autovideo.py
        p = ROOT / p
    if not p.exists():
        raise FileNotFoundError(f"Cannot find '{path}'. Put the file in {ROOT} or give its full path in quotes.")
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                "-of", "csv=p=0", str(p)], capture_output=True, text=True)
        if not probe.stdout.strip():
            raise RuntimeError(f"'{p}' has no audio track. Use the video that contains the voice.")
        err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"ffmpeg could not read audio from '{p}': " + (err[-1] if err else "unknown error"))
    return np.frombuffer(r.stdout, np.float32), sr


def analyze_voice(path):
    """Pitch (median / quartiles), speaking-rate proxy and energy of a recording. The SAME numbers are computed for the
    reference and for every candidate voice, so they can be compared directly."""
    x, sr = load_pcm(path)
    if len(x) < sr:
        raise RuntimeError(f"only {len(x) / sr:.1f}s of audio found - need at least 1 second of speech to analyse")
    x = x / (np.percentile(np.abs(x), 99.5) + 1e-9) * 0.3                    # level-independent thresholds
    n, h = int(0.04 * sr), int(0.01 * sr)
    win = np.hanning(n)
    lo, hi = int(sr / 300), int(sr / 75)
    f0s, rms = [], []
    for i in range(0, len(x) - n, h):
        s = x[i:i + n] * win
        e = float(np.sqrt(np.mean(s ** 2)))
        rms.append(e)
        if e < 0.02:
            continue
        ac = np.correlate(s, s, "full")[n - 1:]
        ac = ac / (ac[0] + 1e-12)
        seg = ac[lo:hi]
        k = int(seg.argmax())
        if seg[k] > 0.6:
            f0s.append(sr / (k + lo))
    rms = np.array(rms)
    f0s = np.array(f0s)
    speech = rms > 0.02
    env = np.convolve(rms, np.ones(5) / 5, "same")
    thr = max(0.015, 0.5 * float(np.median(env[speech]))) if speech.any() else 0.015
    peaks = int(((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > thr)).sum())
    speech_s = max(float(speech.sum()) * 0.01, 1e-6)
    return {"f0_median": float(np.median(f0s)) if len(f0s) else 0.0,
            "f0_p25": float(np.percentile(f0s, 25)) if len(f0s) else 0.0,
            "f0_p75": float(np.percentile(f0s, 75)) if len(f0s) else 0.0,
            "rate": peaks / speech_s, "speech_s": speech_s}


# -- speaking with edge-tts, keeping the word timings -------------------------------------------------------------
def words_path(audio):
    return Path(audio).with_name(Path(audio).stem + ".words.json")      # scene_00.mp3 -> scene_00.words.json


async def _tts_stream(text, vcfg, path):
    import edge_tts
    kw = dict(rate=vcfg["rate"], pitch=vcfg["pitch"])
    try:
        comm = edge_tts.Communicate(text, vcfg["voice"], boundary="WordBoundary", **kw)
    except TypeError:                                          # older edge-tts: no boundary option
        comm = edge_tts.Communicate(text, vcfg["voice"], **kw)
    audio, words = bytearray(), []
    async for ch in comm.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append((ch["text"], ch["offset"] / 1e7, ch["duration"] / 1e7))
    if not audio:
        raise RuntimeError("No audio was received")
    Path(path).write_bytes(bytes(audio))
    return words


def sapi_voice(text, path):
    """Last-resort offline voice (built into Windows). Robotic, but it never fails because of the network."""
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$s.SetOutputToWaveFile($env:AV_OUT); $s.Speak($env:AV_TEXT); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   env=dict(os.environ, AV_OUT=str(path), AV_TEXT=text), capture_output=True)


def fake_tts(text, path):
    """TEST ONLY (AUTOVIDEO_FAKE_TTS=1): a synthetic buzzing 'voice' so the whole pipeline can run offline."""
    import wave
    toks = text.split() or ["x"]
    sr, f0 = 24000, 105.0
    words, sig, t = [], [], 0.0
    for w in toks:
        d = 0.12 + 0.055 * len(w)
        n = int(d * sr)
        tt = np.arange(n) / sr
        saw = sum(np.sin(2 * np.pi * f0 * k * tt) / k for k in range(1, 12))
        env = np.minimum(1, np.minimum(tt / 0.02, (d - tt) / 0.03)) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * tt) ** 2)
        sig.append(0.25 * saw * env)
        sig.append(np.zeros(int(0.05 * sr)))
        words.append([w, round(t, 3), round(d, 3)])
        t += d + 0.05
    x = (np.concatenate(sig) * 32000).astype(np.int16)
    wav = Path(path).with_suffix(".wav")
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr); f.writeframes(x.tobytes())
    words_path(wav).write_text(json.dumps(words), encoding="utf-8")
    return wav


def espeak_voice(text, wav):
    """Offline fallback on Linux (sudo apt install espeak-ng). Robotic, but the video still finishes."""
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        return None
    subprocess.run([exe, "-v", "en-us+m3", "-p", "20", "-s", "165", "-w", str(wav), text], capture_output=True, timeout=120)
    return wav if wav.exists() and wav.stat().st_size > 1000 else None


def tts_one(text, vcfg, path):
    """edge-tts is an online service and sometimes returns no audio: retry with a growing pause, then fall back."""
    if os.environ.get("AUTOVIDEO_FAKE_TTS"):
        return fake_tts(text, path)
    last = None
    for attempt in range(4):
        try:
            words = asyncio.run(_tts_stream(text, vcfg, path))
            if path.exists() and path.stat().st_size > 1000:
                words_path(path).write_text(json.dumps(words), encoding="utf-8")
                return path
        except Exception as e:
            last = e
        print(f"    voice attempt {attempt + 1} failed ({type(last).__name__ if last else 'empty audio'}), retrying ...")
        time.sleep(1.5 * (attempt + 1))
    if os.name == "nt":
        wav = path.with_suffix(".wav")
        print("    ! online voice unavailable, using the offline Windows voice for this scene")
        sapi_voice(text, wav)
        return wav
    if os.name != "nt":
        wav = path.with_suffix(".wav")
        if espeak_voice(text, wav):
            print("    ! online voice unavailable, using the offline espeak voice for this scene")
            return wav
    raise RuntimeError(f"Voice generation failed: {last}")


def make_voice(work, scenes, vcfg):
    import avx_voice as vv
    d = work / "voice"
    d.mkdir(parents=True, exist_ok=True)
    files = []
    depth = vv.clamp_depth(vcfg.get("depth", 0))
    print(f"  voice: {vcfg['voice']}  rate {vcfg['rate']}  pitch {vcfg['pitch']}  depth {depth} ({vv.LEVEL_NAMES[depth]})")
    for i, sc in enumerate(scenes):
        f = d / f"scene_{i:02d}.mp3"
        w = f.with_suffix(".wav")
        print(f"  voice {i + 1}/{len(scenes)}")
        if f.exists() and f.stat().st_size > 1000:          # already made (resume after a failure)
            raw = f
        elif w.exists() and w.stat().st_size > 1000:
            raw = w
        else:
            raw = tts_one(sc["say"], vcfg, f)
            time.sleep(0.5)                                  # be gentle with the online service
        if depth > 0 and not str(raw).endswith(".deep.wav"):
            out = d / f"scene_{i:02d}.deep.wav"
            vv.deepen(raw, out, depth)                       # same duration, so the word timings stay exact
            wj = words_path(raw)
            if wj.exists():
                words_path(out).write_text(wj.read_text(encoding="utf-8"), encoding="utf-8")
            raw = out
        files.append(raw)
    return files


def load_words(audio, text, dur):
    """[(word, start, duration)] for one scene: the real timings from the voice service, or an estimate."""
    try:
        w = json.loads(words_path(audio).read_text(encoding="utf-8"))
        if w:
            return [(a, float(b), float(c)) for a, b, c in w]
    except Exception:
        pass
    toks = text.split()
    if not toks:
        return []
    lens = np.array([len(t) + 1 for t in toks], float)
    edges = dur * 0.96 * np.concatenate([[0], np.cumsum(lens)]) / lens.sum()
    return [(toks[i], float(edges[i]), float(edges[i + 1] - edges[i])) for i in range(len(toks))]


# -- voice-profile / voice-lab commands ----------------------------------------------------------------------------
def cmd_voice_profile(path):
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH. Install: winget install Gyan.FFmpeg   (then reopen the terminal)")
    try:
        a = analyze_voice(path)
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(f"voice-profile: {e}")
    print(json.dumps({k: round(v, 2) for k, v in a.items()}, indent=1))
    prof = {}
    try:
        prof = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    prof["reference"] = {"f0_median": round(a["f0_median"], 1), "f0_p25": round(a["f0_p25"], 1),
                         "f0_p75": round(a["f0_p75"], 1), "rate": round(a["rate"], 2)}
    PROFILE_FILE.write_text(json.dumps(prof, indent=1), encoding="utf-8")
    print(f"Saved as the reference in {PROFILE_FILE.name}. Now run:  python autovideo.py voice-lab")


def cmd_voice_lab():
    """Speak the same sentence with every candidate voice, measure each one against the reference, and save the closest
    male voice and the closest female voice (with the rate/pitch that bring them nearest) to voice_profile.json."""
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH.")
    try:
        prof = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        prof = {}
    ref = prof.get("reference") or REFERENCE_VOICE
    lab = OUT / "voice_lab"
    lab.mkdir(parents=True, exist_ok=True)
    print(f"Reference voice: pitch median {ref['f0_median']:.0f} Hz (middle half {ref['f0_p25']:.0f}-{ref['f0_p75']:.0f} Hz), "
          f"pace {ref['rate']:.1f}\n")
    ref_spread = (ref["f0_p75"] - ref["f0_p25"]) / max(ref["f0_median"], 1)
    for gender, cands in VOICE_CANDIDATES.items():
        rows = []
        for v in cands:
            p = lab / f"{gender}_{v}.mp3"
            try:
                asyncio.run(_tts_stream(LAB_SENTENCE, {"voice": v, "rate": "+0%", "pitch": "+0Hz"}, p))
                a = analyze_voice(p)
            except Exception as e:
                print(f"  {v:36} skipped ({type(e).__name__})")
                continue
            spread = (a["f0_p75"] - a["f0_p25"]) / max(a["f0_median"], 1)
            pitch_err = abs(a["f0_median"] - ref["f0_median"]) / ref["f0_median"] if gender == "male" else 0.0
            score = pitch_err + 0.5 * abs(spread - ref_spread)
            rows.append((score, v, a))
            print(f"  {v:36} pitch {a['f0_median']:5.0f} Hz  spread {spread:4.2f}  pace {a['rate']:4.1f}  score {score:4.2f}")
        if not rows:
            print(f"  no {gender} voice could be measured (is the internet on?)\n")
            continue
        score, v, a = min(rows, key=lambda r: r[0])
        rate = max(-15, min(25, (ref["rate"] / max(a["rate"], 1e-6) - 1) * 100))
        pitch = max(-10, min(25, ref["f0_median"] - a["f0_median"])) if gender == "male" else 0
        prof[gender] = {"voice": v, "rate": fmt_rate(rate), "pitch": fmt_pitch(pitch)}
        p = lab / f"BEST_{gender}.mp3"
        try:
            asyncio.run(_tts_stream(LAB_SENTENCE, {"voice": v, "rate": prof[gender]["rate"], "pitch": prof[gender]["pitch"]}, p))
            b = analyze_voice(p)
            print(f"  -> {gender.upper()}: {v}  rate {prof[gender]['rate']}  pitch {prof[gender]['pitch']}   "
                  f"(now pitch {b['f0_median']:.0f} Hz, pace {b['rate']:.1f})   listen: {p}\n")
        except Exception:
            print(f"  -> {gender.upper()}: {v}  rate {prof[gender]['rate']}  pitch {prof[gender]['pitch']}\n")
    PROFILE_FILE.write_text(json.dumps(prof, indent=1), encoding="utf-8")
    print(f"Saved to {PROFILE_FILE.name}. Videos now use these. Add --female (or 'Voice: female' in a script) for the female voice.")



# ----------------------------------------------------------------------------
# THE SPEED EDIT  (what to speed up, what to keep, how to fit the narration)
# ----------------------------------------------------------------------------
def scene_intervals(marks, a, b):
    """Split the recording between a and b into (t0, t1, kind) pieces using the live 'mark' log."""
    marks = sorted(marks)
    ts = [m[0] for m in marks]
    i = bisect.bisect_right(ts, a) - 1
    kind = marks[i][1] if i >= 0 else "idle"
    out, cur = [], a
    for t, k in marks[i + 1:]:
        if t >= b:
            break
        if t > cur:
            out.append((cur, t, kind))
            cur = t
        kind = k
    if b > cur:
        out.append((cur, b, kind))
    return out


def plan_scene(ints, D):
    """Decide the speed of every piece so the scene lasts exactly as long as its narration needs.
    Returns (kept [(t0, t1, speed)], atempo for the voice, frames to hold (only a rare last resort))."""
    T = D + LEAD + TAIL
    nd = [(a, b, k) for a, b, k in ints if k != "dwell"]
    dwell = sum(b - a for a, b, k in ints if k == "dwell")

    def tot(m):
        return sum((b - a) / min(CAP[k], BASE[k] * m) for a, b, k in nd)

    m, use_dw = 1.0, 0.0
    S0 = tot(1.0)
    if S0 > T:                                            # too long: speed up the boring parts (never moves/clicks)
        if tot(40.0) > T:
            m = 40.0
        else:
            lo, hi = 1.0, 40.0
            for _ in range(40):
                mid = (lo + hi) / 2
                if tot(mid) <= T:
                    hi = mid
                else:
                    lo = mid
            m = hi
    else:                                                 # too short: use spare footage (pointer drifting), trimmed
        use_dw = min(dwell, T - S0)
    V = tot(m) + use_dw
    atempo, hold = 1.0, 0
    if V < T - 0.05:                                      # narration longer than the footage: speak a touch faster
        avail = V - LEAD - TAIL
        atempo = min(1.15, max(1.0, D / avail)) if avail > 0.3 else 1.15
        hold = max(0, round((D / atempo + LEAD + TAIL - V) * FPS))
    kept, left = [], use_dw
    for a, b, k in ints:
        if k == "dwell":
            take = min(b - a, left)
            if take > 0.03:
                kept.append((a, a + take, 1.0))
                left -= take
        else:
            kept.append((a, b, min(CAP[k], BASE[k] * m)))
    return kept, atempo, hold


def smooth(x, sigma):
    r = max(1, int(sigma * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(x, (r, r), mode="edge"), k, mode="valid")


def build_timeline(sj, durs):
    """Whole-video time map. Returns dict with: src (source frame for each kept frame), pos (output frame position),
    n_out, outs (output start time of each scene), atempos, to_out(t_src)."""
    starts, marks, total = sj["starts"], [tuple(m) for m in sj["marks"]], sj["total"]
    n = len(starts)
    bounds = [(max(0.0, starts[0] - 0.3) if i == 0 else starts[i], starts[i + 1] if i + 1 < n else total) for i in range(n)]
    src, spd, first, atempos = [], [], [], []
    for i, (a, b) in enumerate(bounds):
        kept, at, hold = plan_scene(scene_intervals(marks, a, b), durs[i])
        first.append(sum(len(s) for s in src))
        for t0, t1, s in kept:
            n0 = int(round(t0 * FPS))
            n1 = max(n0 + 1, int(round(t1 * FPS)))
            src.append(np.arange(n0, n1))
            spd.append(np.full(n1 - n0, s, np.float64))
        if hold:                                          # last resort only; normally never happens
            src.append(np.full(hold, src[-1][-1]))
            spd.append(np.ones(hold))
        atempos.append(at)
    src, spd = np.concatenate(src), np.concatenate(spd)
    spd_s = np.clip(smooth(spd, 0.18 * FPS), 0.5, 40.0)   # soft speed ramps instead of hard jumps
    dt = 1.0 / spd_s
    edges = first + [len(src)]
    for i in range(len(first)):                           # smoothing must not change a scene's planned length
        lo, hi = edges[i], edges[i + 1]
        if hi > lo and dt[lo:hi].sum() > 0:
            dt[lo:hi] *= (1.0 / spd[lo:hi]).sum() / dt[lo:hi].sum()
    pos = np.concatenate([[0.0], np.cumsum(dt)[:-1]])
    n_out = int(math.ceil(pos[-1] + dt[-1]))

    def to_out(t):
        j = min(int(np.searchsorted(src, t * FPS)), len(src) - 1)
        return pos[j] / FPS

    return dict(src=src, pos=pos, n_out=n_out, outs=[pos[f] / FPS for f in first], atempos=atempos, to_out=to_out)


def build_audio_track(work, files, tl, durs, out_wav):
    """Voice placed on the output timeline: scene i speaks from LEAD seconds after the scene starts."""
    d = work / "voice"
    total = tl["n_out"] / FPS
    parts = []
    for i, f in enumerate(files):
        o0 = tl["outs"][i]
        o1 = tl["outs"][i + 1] if i + 1 < len(files) else total
        L = o1 - o0
        if durs[i] / tl["atempos"][i] + LEAD > L + 0.05:
            print(f"    ! scene {i + 1}: narration is {durs[i] / tl['atempos'][i] + LEAD - L:.2f}s longer than its footage")
        flt = (f"atempo={tl['atempos'][i]:.4f}," if abs(tl["atempos"][i] - 1) > 1e-3 else "") + \
              f"adelay={int(LEAD * 1000)}:all=1,apad=whole_dur={L:.3f},atrim=0:{L:.3f}"
        p = d / f"seg_{i:02d}.wav"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(f), "-af", flt, "-ar", "44100", "-ac", "2", str(p)])
        parts.append(p)
    lst = d / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", str(out_wav)])


# ----------------------------------------------------------------------------
# RENDER  (zoom, click ripples, window frame, captions, audio polish)
# ----------------------------------------------------------------------------
def build_camera(events, sw, sh):
    kf = [(0.0, 1.0, sw / 2, sh / 2)]

    def add(t, z, cx, cy):
        kf.append((max(t, kf[-1][0] + 0.04), z, cx, cy))

    for i, (t, x, y) in enumerate(events):
        add(t - 0.9, kf[-1][1], kf[-1][2], kf[-1][3])
        add(t - 0.25, ZOOM, x, y)
        add(t + 1.2, ZOOM, x, y)
        nxt = events[i + 1][0] if i + 1 < len(events) else None
        if nxt is None or nxt - 0.9 > kf[-1][0] + 1.0:
            add(kf[-1][0] + 0.8, 1.0, sw / 2, sh / 2)
    return kf


def camera_at(kf, times, t):
    i = bisect.bisect_right(times, t) - 1
    if i < 0:
        return kf[0][1:]
    if i >= len(kf) - 1:
        return kf[-1][1:]
    (t0, z0, x0, y0), (t1, z1, x1, y1) = kf[i], kf[i + 1]
    e = ease((t - t0) / (t1 - t0))
    return z0 + (z1 - z0) * e, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e


def cover_resize(img, w, h):
    ih, iw = img.shape[:2]
    k = max(w / iw, h / ih)
    r = cv2.resize(img, (int(math.ceil(iw * k)), int(math.ceil(ih * k))),
                   interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]


def make_background(w, h):
    """Your wallpaper (background.jpg) cropped to fill the canvas without stretching, or a soft gradient."""
    p = ROOT / BACKGROUND_IMAGE
    if p.exists():
        img = cv2.imread(str(p))
        if img is not None:
            return cover_resize(img, w, h)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = (xx / w * 0.5 + yy / h * 0.5)[..., None]
    a, b = np.array([60, 30, 20], np.float32), np.array([190, 90, 60], np.float32)
    return (a + (b - a) * t).astype(np.uint8)


def rounded_alpha(iw, ih, radius):
    yy, xx = np.mgrid[0:ih, 0:iw].astype(np.float32)
    qx = np.abs(xx - iw / 2) - (iw / 2 - radius)
    qy = np.abs(yy - ih / 2) - (ih / 2 - radius)
    d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - radius
    return np.clip(0.5 - d, 0, 1)[..., None].astype(np.float32)


def window_base(W, H, iw, ih, x0, y0, radius):
    """Background + soft shadow under a rounded window. Returns (base, window alpha)."""
    alpha = rounded_alpha(iw, ih, radius)
    bg = make_background(W, H).astype(np.float32)
    shadow = np.zeros((H, W), np.float32)
    ye = min(H, y0 + 22 + ih)
    shadow[y0 + 22:ye, x0:x0 + iw] = alpha[:ye - y0 - 22, :, 0]
    shadow = cv2.GaussianBlur(shadow, (0, 0), 32)[..., None]
    return (bg * (1 - 0.55 * shadow)).astype(np.uint8), alpha


def caption_font(text, size):
    from PIL import ImageFont
    bengali = any("\u0980" <= c <= "\u09ff" for c in text)
    names = (["Nirmala.ttc", "Nirmala.ttf", "NirmalaB.ttf", "vrinda.ttf", "NotoSansBengali-Bold.ttf",
              "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf", "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf"]
             if bengali else []) + \
            [str(Path(__file__).resolve().parent / "fonts" / "caption.ttf"),
             "segoeuib.ttf", "arialbd.ttf", "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
             "/usr/share/fonts/opentype/inter/Inter-Bold.otf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_lines(draw, words, font, max_w):
    lines, cur = [], []
    for w in words:
        t = " ".join(cur + [w])
        if cur and draw.textlength(t, font=font) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    lines.append(cur)
    return lines


def vertical_base(plan, W, H, iw, ih, x0, y0, template=None, frame=None):
    """The reel layout from the chosen template: badges + big title on top, framed video window, room for subtitles."""
    import avx_templates as tp
    return tp.render_base(plan, template or DEFAULT_TEMPLATE, W, H, (x0, y0, iw, ih), frame=frame,
                          photo_loader=lambda w, h: cover_resize(cv2.imread(str(ROOT / BACKGROUND_IMAGE)), w, h)
                          if (ROOT / BACKGROUND_IMAGE).exists() and cv2.imread(str(ROOT / BACKGROUND_IMAGE)) is not None else None)


def build_targets(job, plan, sw, sh):
    """One dict per output: canvas size, the video window inside it, the static background layer, caption style."""
    import avx_templates as tp
    targets = []
    template = job.opt("template") or plan.get("template") or DEFAULT_TEMPLATE
    cap_style, cap_cs, accent = tp.caption_style_for(template, job.opt("captions"))
    for name in job.outs:
        capx = {"style": cap_style, "cs": cap_cs, "accent": accent}
        if name == "vertical":
            W, H = VERT_SIZE
            iw, ih = VERT_WINDOW
            x0, y0 = (W - iw) // 2, int(H * 0.335)
            base, alpha = vertical_base(plan, W, H, iw, ih, x0, y0, template, job.opt("frame"))
            cap = {"size": int(W * 0.076), "max_w": int(W * 0.9), "cy": int(H * 0.80), **capx}
            zoom = VERT_ZOOM
        elif name == "instagram":
            W, H = IG_SIZE
            iw, ih, x0, y0, base, alpha, cap = W, H, 0, 0, None, None, None       # full screen, no subtitles
            zoom = 1.0
        else:                                                                      # landscape
            if STYLE == "recordly":
                W, H = OUT_W, OUT_H
                k = min(W * WINDOW_SCALE / sw, H * WINDOW_SCALE / sh)
                iw, ih = int(sw * k) // 2 * 2, int(sh * k) // 2 * 2
                x0, y0 = (W - iw) // 2, (H - ih) // 2
                base, alpha = window_base(W, H, iw, ih, x0, y0, CORNER_RADIUS)
            else:
                W, H, iw, ih, x0, y0, base, alpha = sw, sh, sw, sh, 0, 0, None, None
            zoom = 1.0
            size = int(W * 0.027)
            cap = {"size": size, "max_w": int(W * 0.8), "cy": H - int(H * 0.085) - size, **capx} if CAPTIONS else None
            if cap:
                cap["cs"] = dict(cap_cs, fg=(255, 255, 255), stroke=(0, 0, 0))     # landscape sits on a dark wallpaper
        targets.append({"name": name, "W": W, "H": H, "iw": iw, "ih": ih, "x0": x0, "y0": y0, "base": base,
                        "alpha": alpha, "aspect": iw / ih, "cap": cap, "zoom": zoom, "path": job.outs[name]})
    return targets


# ---- word-highlight subtitles ---------------------------------------------------------------------------------------
def caption_pages(words, t0, atempo, per=None, fits=None):
    """Group a scene's words into short ONE-LINE pages; each word knows when it is spoken."""
    import avx_templates as tp
    return tp.split_pages(words, t0, atempo, per or CAPTION_WORDS, fits or (lambda ws: True))


def render_cap_variant(texts, active, cap):
    import avx_templates as tp
    return tp.render_caption(texts, active, cap["size"], cap["max_w"], cap["style"], cap["cs"], cap["accent"])


def make_cursor_sprites(size):
    """A large, crisp arrow cursor (white fill, dark outline, soft shadow) as premultiplied float sprites.
    Returns {"normal": (premult_bgr, alpha, hotspot), "down": ...}; the tip of the arrow is the hotspot."""
    S, pad = 4, int(size * 0.35)

    def build(scale):
        H = int((size + 2 * pad) * S)
        pts = np.array([(0, 0), (0, 0.86), (0.20, 0.68), (0.33, 1.0), (0.47, 0.93), (0.34, 0.64), (0.64, 0.64)], np.float32)
        poly = (pts * size * S * scale + pad * S).astype(np.int32)
        body = np.zeros((H, H, 4), np.uint8)
        cv2.fillPoly(body, [poly], (255, 255, 255, 255), cv2.LINE_AA)
        cv2.polylines(body, [poly], True, (18, 18, 18, 255), max(2, int(size * S * 0.085)), cv2.LINE_AA)
        shadow = np.zeros((H, H), np.uint8)
        cv2.fillPoly(shadow, [poly + int(size * S * 0.07)], 255, cv2.LINE_AA)
        shadow = cv2.GaussianBlur(shadow, (0, 0), size * S * 0.06).astype(np.float32) / 255.0 * 0.45
        a_body = body[..., 3].astype(np.float32) / 255.0
        rgb = body[..., :3].astype(np.float32)
        alpha = a_body + shadow * (1 - a_body)
        premult = rgb * a_body[..., None]
        k = H // S
        premult = cv2.resize(premult, (k, k), interpolation=cv2.INTER_AREA)
        alpha = cv2.resize(alpha, (k, k), interpolation=cv2.INTER_AREA)[..., None]
        return premult.astype(np.float32), alpha.astype(np.float32), pad

    return {"normal": build(1.0), "down": build(0.86)}


def blit_cursor(frame, sprite, x, y):
    pm, al, hot = sprite
    h, w = al.shape[:2]
    x0, y0 = int(round(x - hot)), int(round(y - hot))
    fx0, fy0 = max(0, x0), max(0, y0)
    fx1, fy1 = min(frame.shape[1], x0 + w), min(frame.shape[0], y0 + h)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    sx0, sy0 = fx0 - x0, fy0 - y0
    roi = frame[fy0:fy1, fx0:fx1]
    a = al[sy0:sy0 + (fy1 - fy0), sx0:sx0 + (fx1 - fx0)]
    roi[:] = (roi * (1 - a) + pm[sy0:sy0 + (fy1 - fy0), sx0:sx0 + (fx1 - fx0)]).astype(np.uint8)


def cursor_arrays(cursor, t_src):
    """Real pointer telemetry -> position / button state at each output frame's source time (lightly smoothed)."""
    arr = np.asarray(cursor, float)
    arr = arr[np.argsort(arr[:, 0], kind="stable")]
    ct, cd = arr[:, 0], arr[:, 3]
    cx, cy = smooth(arr[:, 1], 1.5), smooth(arr[:, 2], 1.5)
    return np.interp(t_src, ct, cx), np.interp(t_src, ct, cy), np.interp(t_src, ct, cd) > 0.5, (ct, cd, cx, cy)


def camera_path(z_arr, tx, ty, sw, sh, aspect):
    """Camera centre follows the target (the real pointer, or the address bar while a URL is typed) but only once it leaves
    the middle of the view (a dead zone), and it glides. `aspect` is the shape of the output window."""
    bw, bh = (sh * aspect, float(sh)) if sh * aspect <= sw else (float(sw), sw / aspect)
    n = len(z_arr)
    cam = np.zeros((n, 2))
    c = np.array([sw / 2.0, sh / 2.0])
    for k in range(n):
        half = np.array([bw / z_arr[k], bh / z_arr[k]]) / 2.0
        d = np.array([tx[k], ty[k]]) - c
        lim = half * 0.45
        c = c + np.where(np.abs(d) > lim, d - np.sign(d) * lim, 0.0) * 0.10
        c = np.clip(c, half, np.array([sw, sh]) - half)
        cam[k] = c
    return cam, bw, bh


def build_final_audio(wav, total, out):
    """Voice (+ optional music that ducks under it): loudness-normalised, faded out."""
    music = ROOT / MUSIC_FILE
    fo = f"afade=t=out:st={max(0, total - FADE_OUT):.3f}:d={FADE_OUT}"
    chain = ("loudnorm=I=-16:TP=-1.5:LRA=11," if LOUDNORM else "") + "aresample=44100"
    if music.exists():
        fc = (f"[0:a]{chain},asplit[vc1][vc2];[1:a]volume={MUSIC_VOLUME}[m];"
              f"[m][vc1]sidechaincompress=threshold=0.02:ratio=10:attack=30:release=500[md];"
              f"[md][vc2]amix=inputs=2:duration=longest:dropout_transition=0,volume=2,{fo}[a]")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-stream_loop", "-1", "-i", str(music), "-filter_complex", fc,
             "-map", "[a]", "-t", f"{total:.3f}", str(out)])
    else:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-af", f"{chain},{fo}", "-t", f"{total:.3f}", str(out)])


def mmss(t):
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def write_transcript(job, plan, tl, durs):
    """The voice transcript as a .txt: one timed line per scene, then the whole text as one paragraph."""
    lines = [str(plan.get("title") or job.name), ""]
    for i, sc in enumerate(plan["scenes"]):
        lines.append(f"[{mmss(tl['outs'][i] + LEAD)}] {sc['say']}")
    lines += ["", "FULL TEXT", " ".join(sc["say"] for sc in plan["scenes"]), ""]
    job.transcript.write_text("\n".join(lines), encoding="utf-8")


def render_video(job, sj, plan, voice_files, durs):
    work, raw = job.work, job.work / "raw.mp4"
    sw, sh = video_size(raw)
    tl = build_timeline(sj, durs)
    n_out, total = tl["n_out"], tl["n_out"] / FPS

    print("  building voice track ...")
    wav = work / "voice" / "track.wav"
    build_audio_track(work, voice_files, tl, durs, wav)
    mix = work / "voice" / "mix.wav"
    build_final_audio(wav, total, mix)
    write_transcript(job, plan, tl, durs)

    frame_idx = tl["src"][np.clip(np.searchsorted(tl["pos"], np.arange(n_out), side="right") - 1, 0, len(tl["src"]) - 1)]
    t_src = frame_idx / FPS
    ev = [(tl["to_out"](t) + SYNC_OFFSET, x, y, k) for t, x, y, k in sj["events"]]
    zoom_ev = [(t, x, y) for t, x, y, k in ev if k in ("click", "type", "look")]

    # --- the real pointer: telemetry -> large smooth cursor, click ripples ---------------------------------------
    cursor = sj.get("cursor")
    have_cursor = bool(cursor) and len(cursor) > 10
    if have_cursor:
        cur_x, cur_y, cur_down, (ct, cd, cxs, cys) = cursor_arrays(cursor, t_src)
        press = [i for i in range(1, len(cd)) if cd[i] > 0.5 >= cd[i - 1]]
        ripples = [(tl["to_out"](ct[i]) + SYNC_OFFSET, cxs[i], cys[i]) for i in press] if RIPPLE else []
        sprites = make_cursor_sprites(max(18, int(sw * 0.024 * CURSOR_SCALE)))
    else:
        cur_x, cur_y, cur_down = np.full(n_out, sw / 2.0), np.full(n_out, sh / 2.0), np.zeros(n_out, bool)
        ripples = [(t + 0.15, x, y) for t, x, y, k in ev if k == "click"] if RIPPLE else []
        sprites = None

    # --- camera: zoom on actions + breathing per scene; it follows the pointer, or the address bar while typing a URL
    kf = build_camera(zoom_ev, sw, sh)
    times = [k[0] for k in kf]
    z_zoom = np.array([camera_at(kf, times, k / FPS)[0] for k in range(n_out)])
    z_base = np.ones(n_out)
    edges = list(tl["outs"]) + [total]
    for i in range(len(edges) - 1):
        lo, hi = int(edges[i] * FPS), min(n_out, int(edges[i + 1] * FPS))
        if hi > lo:
            z_base[lo:hi] = 1.0 + PUSH_IN * np.sin(np.pi * np.linspace(0, 1, hi - lo, endpoint=False)) ** 2
    z_arr = np.maximum(z_zoom, z_base)
    tx, ty = cur_x.copy(), cur_y.copy()
    for f0, f1, fx, fy in sj.get("focus", []):                    # typing a URL: look at the address bar, not the pointer
        a, b = int((tl["to_out"](f0) - 0.3) * FPS), int((tl["to_out"](f1) + 0.6) * FPS)
        tx[max(0, a):b], ty[max(0, a):b] = fx, fy
    if not have_cursor and zoom_ev:
        for k in range(n_out):
            tx[k], ty[k] = camera_at(kf, times, k / FPS)[1:]

    targets = build_targets(job, plan, sw, sh)
    for T in targets:
        T["cam"], T["bw"], T["bh"] = camera_path(z_arr * T["zoom"], tx, ty, sw, sh, T["aspect"])

    # --- subtitles: real word timings -> pages -----------------------------------------------------------------------
    pages = []
    cap_targets = [T for T in targets if T["cap"]]
    if cap_targets:
        import avx_templates as tp
        narrow = min(cap_targets, key=lambda T: T["cap"]["max_w"] / max(1, T["cap"]["size"]))["cap"]     # tightest one-line budget
        fits = lambda ws: tp.line_width(ws, narrow["size"], narrow["style"]) <= narrow["max_w"]
        for i, sc in enumerate(plan["scenes"]):
            words = load_words(voice_files[i], sc["say"], durs[i])
            pages += caption_pages(words, tl["outs"][i] + LEAD, tl["atempos"][i], job.opt("caption_words") or CAPTION_WORDS, fits)
        pages.sort(key=lambda p: p["t0"])
    page_starts = [p["t0"] for p in pages]

    fade = f"fade=t=in:st=0:d={FADE_IN},fade=t=out:st={max(0, total - FADE_OUT):.3f}:d={FADE_OUT}"
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(raw), "-vf", f"fps={FPS}", "-f", "rawvideo",
                            "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for T in targets:
        T["enc"] = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{T['W']}x{T['H']}", "-r", str(FPS),
             "-i", "-", "-i", str(mix), "-vf", fade, "-map", "0:v", "-map", "1:a", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(T["path"])], stdin=subprocess.PIPE)

    fsize, cur, frame = sw * sh * 3, -1, None
    capcache, cap_page = {}, -1
    print(f"  rendering {n_out} frames ({total:.1f}s) x {len(targets)} format(s): {', '.join(T['name'] for T in targets)} ...")
    for k in range(n_out):
        f = int(frame_idx[k])
        while cur < f:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                break
            frame, cur = np.frombuffer(buf, np.uint8).reshape(sh, sw, 3), cur + 1
        if frame is None:
            raise RuntimeError("The recording contains no frames.")
        t = k / FPS
        src_frame = frame.copy() if (sprites or ripples) else frame
        for rt, rx_, ry_ in ripples:                              # click ripple, drawn on the page so it zooms with it
            u = (t - rt) / 0.5
            if 0 <= u < 1:
                ov = src_frame.copy()
                rad = int(14 + 52 * ease(u))
                cv2.circle(ov, (int(rx_), int(ry_)), rad, (25, 25, 25), 9, cv2.LINE_AA)
                cv2.circle(ov, (int(rx_), int(ry_)), rad, (255, 255, 255), 4, cv2.LINE_AA)
                src_frame = cv2.addWeighted(ov, 0.9 * (1 - u), src_frame, 1 - 0.9 * (1 - u), 0)
        if sprites:                                               # the large cursor, from the real pointer path
            blit_cursor(src_frame, sprites["down" if cur_down[k] else "normal"], cur_x[k], cur_y[k])
        pi = bisect.bisect_right(page_starts, t) - 1 if pages else -1
        page = pages[pi] if 0 <= pi and t < pages[pi]["t1"] + 0.05 else None
        if pi != cap_page:
            capcache.clear()
            cap_page = pi
        for T in targets:
            z = z_arr[k] * T["zoom"]
            cx_, cy_ = T["cam"][k]
            cwid, chei = T["bw"] / z, T["bh"] / z
            sx, sy = min(max(cx_ - cwid / 2, 0), sw - cwid), min(max(cy_ - chei / 2, 0), sh - chei)
            s = T["iw"] / cwid
            if s < 0.85:                                          # shrinking: area-average for crisp small text
                xi, yi = int(round(sx)), int(round(sy))
                wi, hi = int(round(cwid)), int(round(chei))
                xi, yi = min(xi, sw - wi), min(yi, sh - hi)
                inner = cv2.resize(src_frame[yi:yi + hi, xi:xi + wi], (T["iw"], T["ih"]), interpolation=cv2.INTER_AREA)
            else:
                inner = cv2.warpAffine(src_frame, np.float32([[s, 0, -sx * s], [0, s, -sy * s]]), (T["iw"], T["ih"]),
                                       flags=cv2.INTER_CUBIC)
            if T["base"] is not None:
                out = T["base"].copy()
                roi = out[T["y0"]:T["y0"] + T["ih"], T["x0"]:T["x0"] + T["iw"]]
                roi[:] = (inner * T["alpha"] + roi * (1 - T["alpha"])).astype(np.uint8)
            else:
                out = inner
            if page and T["cap"]:
                act = max([i for i, w in enumerate(page["words"]) if t >= w[1] - 0.02] or [0])
                key = (T["name"], act)
                if key not in capcache:
                    capcache[key] = render_cap_variant([w[0] for w in page["words"]], act, T["cap"])
                bgr, al = capcache[key]
                h_, w_ = bgr.shape[:2]
                cxp, cyp = (T["W"] - w_) // 2, T["cap"]["cy"] - h_ // 2
                a_ = al * min(1.0, (t - page["t0"] + 0.02) / 0.08, (page["t1"] + 0.05 - t) / 0.08)
                r = out[cyp:cyp + h_, cxp:cxp + w_]
                r[:] = (bgr * a_ + r * (1 - a_)).astype(np.uint8)
            T["enc"].stdin.write(out.tobytes())
    for T in targets:
        T["enc"].stdin.close()
    for T in targets:
        T["enc"].wait()
    dec.terminate()
    if any(T["enc"].returncode != 0 for T in targets):
        raise RuntimeError("ffmpeg encode failed")


# ----------------------------------------------------------------------------
# ONE VIDEO, START TO FINISH
# ----------------------------------------------------------------------------
def preflight():
    if not IS_WIN and not os.environ.get("DISPLAY"):
        sys.exit("No DISPLAY. On a server run it inside a virtual screen:  xvfb-run -a -s '-screen 0 1920x1080x24' python3 autovideo.py ...")
    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            sys.exit(f"{exe} not found on PATH. Windows: winget install Gyan.FFmpeg   Linux: sudo apt install ffmpeg")


def countdown(n=5, what="The browser will open"):
    print(f"\n{what} and take over the mouse and keyboard. Do not touch them. To abort: slam the mouse into a screen corner.")
    for i in range(n, 0, -1):
        print(f"  starting in {i} ...", end="\r")
        time.sleep(1)
    print(" " * 30)


def ensure_assets(job):
    """Images a script may upload: the ones the user sent, else one generated sample photo."""
    files = [Path(p) for p in getattr(job, "assets", []) if Path(p).exists()]
    if not files:
        from avx_templates import sample_photo
        d = job.work if job.work.exists() else job.work.parent
        d.mkdir(parents=True, exist_ok=True)
        files = [sample_photo(d / "sample_photo.jpg")]
    return files


def record_job(job, plan):
    shutil.rmtree(job.work, ignore_errors=True)
    job.work.mkdir(parents=True)
    try:
        with Session(assets=ensure_assets(job)) as sess:
            rec = Recorder(sess.region, job.work / "raw.mp4")
            rec.start()
            try:
                data = perform(sess, rec, plan)
            finally:
                rec.stop()
        (job.work / "session.json").write_text(json.dumps(data), encoding="utf-8")
    except BaseException:
        shutil.rmtree(job.work, ignore_errors=True)               # a failed/aborted recording is not worth keeping
        raise
    print("    session closed, browser profile deleted. Recording saved until the video is finished.")


def finish_job(job, plan):
    """Voice (after the video), speed edit, render. The recording is kept until the video exists."""
    raw, sj_path = job.work / "raw.mp4", job.work / "session.json"
    if not raw.exists() or not sj_path.exists():
        raise RuntimeError("No saved recording found for this video. Run 'make' (or 'queue') again.")
    sj = json.loads(sj_path.read_text(encoding="utf-8"))
    try:
        print("2/3 generating AI voice (after the video) ...")
        vcfg = resolve_voice(plan, job.force_gender, job.opt("depth"))
        voice_files = make_voice(job.work, plan["scenes"], vcfg)
        durs = [media_duration(f) for f in voice_files]
        print("3/3 editing (speed ramps, zoom, subtitles, audio) and exporting every format ...")
        OUT.mkdir(exist_ok=True)
        render_video(job, sj, plan, voice_files, durs)
    except BaseException:
        print(f"\nThe recording is KEPT in {job.work}. Fix the problem, then resume without re-recording.")
        raise
    print("\nDone:")
    for p in [*job.outs.values(), job.transcript]:
        print(f"  {p}")
    if not KEEP_TEMP:
        shutil.rmtree(job.work, ignore_errors=True)


def apply_plan_meta(job, plan):
    """Lines like  Template: neon / Depth: 2 / Outputs: vertical, instagram / Captions: box  inside a script win over the
    bot's saved defaults for that one video."""
    m = plan.get("meta") or {}
    o = dict(job.options)
    if m.get("template"):
        import avx_templates as tp
        o["template"] = tp.get_template(m["template"])
    if m.get("frame"):
        o["frame"] = m["frame"].strip().lower()
    if m.get("captions"):
        o["captions"] = m["captions"].strip().lower()
    if m.get("depth", "").strip().isdigit():
        o["depth"] = max(0, min(3, int(m["depth"])))
    if m.get("outputs"):
        o["outputs"] = [x.strip().lower() for x in re.split(r"[,\s]+", m["outputs"]) if x.strip()]
    job.set_options(o)


def run_job(job):
    """plan (if needed) -> record (if needed) -> voice + edit."""
    if not job.plan.exists():
        print("1/3 planning ...")
        plan_job(job)
    plan = validate_plan(job.plan)
    apply_plan_meta(job, plan)
    if not (job.work / "session.json").exists():
        print("    recording the real session ...")
        record_job(job, plan)
    else:
        print("    found a saved recording, skipping the live session.")
    finish_job(job, plan)


# ---- optional AI editor for scripts (needs your own API key; everything works without it) --------------------------
def load_env():
    """Read KEY=VALUE lines from .env next to this script (secrets stay out of the code)."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def ai_configured():
    return bool(os.environ.get("AUTOVIDEO_AI_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def http_json(url, body=None, headers=None, method=None, timeout=120):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json", "User-Agent": "autovideo", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def ai_complete(system, user, max_tokens=3500):
    """One call to an AI provider: 'openai' (also works with Gemini/Groq/OpenRouter/... compatible endpoints) or 'anthropic'."""
    provider = os.environ.get("AUTOVIDEO_AI_PROVIDER", "openai").strip().lower()
    key, model = os.environ.get("AUTOVIDEO_AI_KEY", ""), os.environ.get("AUTOVIDEO_AI_MODEL", "")
    base = os.environ.get("AUTOVIDEO_AI_BASE", "").strip()
    if provider in ("google", "gemini") or "gemini" in base.lower() or os.environ.get("GEMINI_API_KEY"):
        import avx_gemini                                    # native Gemini API (model names are normalised, with fallbacks)
        return avx_gemini.complete(system, user, max_tokens=max_tokens, temperature=0.4)
    if provider == "anthropic":
        d = http_json((base or "https://api.anthropic.com").rstrip("/") + "/v1/messages",
                      {"model": model or "claude-sonnet-5-5", "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user}]},
                      {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    d = http_json((base or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                  {"model": model or "gpt-4o-mini", "temperature": 0.4, "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                  {"Authorization": f"Bearer {key}"})
    return d["choices"][0]["message"]["content"]


AI_SYSTEM = """You are the script editor for automated screen-demo videos in the style of fast, punchy tech-tips reels.
A robot uses a REAL browser with a real mouse and keyboard; an AI narrator reads your narration while the robot acts.

You receive: the author's brief, a draft plan (JSON) and a scout report of what each page REALLY contains today
(visible button/link texts, and how far the page can scroll). Return ONE improved plan as JSON and nothing else:
{"title": "...", "tag": "...", "part": "...", "scenes": [{"say": "...", "do": [ ...actions... ]}]}

Narration rules: energetic, confident, conversational narrator, brisk pace, short punchy sentences, a strong hook in the
first scene, no filler or hype, present tense, 8 to 20 words per scene, total 85 to 140 words (about 35 to 55 seconds).
Each scene describes exactly what is on screen while its actions happen. Keep the author's language and facts.
"title" is a short punchy on-screen headline (max 6 words). "tag" is a 1-3 word category. Keep "part" if given.

Allowed actions: {"goto": "https://..."}, {"click": "exact visible text"}, {"hover": "exact visible text"},
{"type": ["field placeholder or label", "text"]}, {"scroll": 800} (pixels, negative = up), {"wait": 1.5}, {"press": "enter"},
{"explore": 3} (the pointer visits the main buttons on screen). At most 4 actions per scene.
Action rules: click/hover ONLY texts that appear in the scout report for that page. Use scroll ONLY on pages whose scout
"scroll_px" is above 300; on single-screen pages use explore. The first scene must goto the first page. Never invent buttons."""


def ai_refine_plan(plan, brief, hints):
    """Ask the AI to polish narration and fix actions using the scout report; sanitise the answer; return it (or raise)."""
    scout = {u: {"buttons_and_links": _texts(v)[:70], "scroll_px": v.get("scroll") if isinstance(v, dict) else None}
             for u, v in hints.items()}
    txt = ai_complete(AI_SYSTEM, json.dumps({"brief": brief, "draft_plan": plan, "scout_report": scout}, ensure_ascii=False))
    js = extract_json(txt)
    if not js:
        raise ValueError("the AI answer contained no JSON")
    new = json.loads(js)
    allowed = {"goto", "click", "hover", "type", "scroll", "wait", "press", "explore", "upload", "verify"}
    scenes = []
    for sc in new.get("scenes", []):
        say = " ".join(str(sc.get("say", "")).split())
        if not say:
            continue
        acts = []
        for a in sc.get("do", []) if isinstance(sc.get("do"), list) else []:
            if isinstance(a, dict) and len(a) == 1 and next(iter(a)) in allowed:
                acts.append(a)
        scenes.append({"say": say, "do": acts[:4]})
    if not 2 <= len(scenes) <= 14:
        raise ValueError(f"the AI returned {len(scenes)} scenes")
    out = dict(plan)
    out["scenes"] = scenes
    for k in ("title", "tag", "part"):
        if new.get(k) and not plan.get(k if k != "title" else "title_locked"):
            out[k] = str(new[k]).strip()
    return out


# ---- Telegram bot + storage ---------------------------------------------------------------------------------------
def tg_base():
    return os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")


def multipart(fields, files):
    b = uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
    for k, (fname, data, ctype) in files.items():
        out += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                f'Content-Type: {ctype}\r\n\r\n').encode("utf-8") + data + b"\r\n"
    out += f"--{b}--\r\n".encode()
    return b, bytes(out)


def tg_call(method, params=None, files=None, timeout=70):
    url = f"{tg_base()}/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"
    if files:
        b, body = multipart({k: str(v) for k, v in (params or {}).items()}, files)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(params or {}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    if not d.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {d}")
    return d["result"]


def tg_say(chat, thread, text):
    p = {"chat_id": chat, "text": text[:3900]}
    if thread:
        p["message_thread_id"] = thread
    try:
        tg_call("sendMessage", p)
    except Exception as e:
        print(f"  (telegram message failed: {type(e).__name__})")


def shrink_for_telegram(path, limit=49 * 1024 * 1024):
    """Telegram bots can send files up to 50 MB: re-encode a smaller copy when needed."""
    if path.stat().st_size <= limit:
        return path
    small = path.with_name(path.stem + "_tg.mp4")
    for crf in (26, 30, 34):
        run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(small)])
        if small.stat().st_size <= limit:
            return small
    return None


def tg_send_file(chat, thread, path, caption=""):
    is_video = path.suffix.lower() == ".mp4"
    if is_video:
        path = shrink_for_telegram(path)
        if path is None:
            return False
    p = {"chat_id": chat, "caption": caption[:900]}
    if thread:
        p["message_thread_id"] = thread
    if is_video:
        p["supports_streaming"] = "true"
    tg_call("sendVideo" if is_video else "sendDocument", p,
            files={"video" if is_video else "document": (path.name, path.read_bytes(),
                                                          "video/mp4" if is_video else "text/plain")}, timeout=300)
    return True


def github_upload(files):
    """Upload files as assets of a monthly GitHub Release (free; each file up to 2 GiB, no total/bandwidth limit).
    Returns {file name: download url}. Needs GITHUB_TOKEN and GITHUB_REPO (owner/name)."""
    repo, token = os.environ["GITHUB_REPO"], os.environ["GITHUB_TOKEN"]
    api = os.environ.get("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
    up = os.environ.get("GITHUB_UPLOAD_BASE", "https://uploads.github.com").rstrip("/")
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tag = time.strftime("videos-%Y-%m")
    try:
        rel = http_json(f"{api}/repos/{repo}/releases/tags/{tag}", headers=hdr)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        rel = http_json(f"{api}/repos/{repo}/releases",
                        {"tag_name": tag, "name": time.strftime("Videos %Y-%m"), "body": "Made by autovideo",
                         "draft": False, "prerelease": False}, hdr)
    urls = {}
    for f in files:
        name = f.name
        for attempt in range(2):
            req = urllib.request.Request(f"{up}/repos/{repo}/releases/{rel['id']}/assets?name={urllib.parse.quote(name)}",
                                         data=f.read_bytes(), method="POST",
                                         headers={**hdr, "Content-Type": "video/mp4" if f.suffix == ".mp4" else "text/plain"})
            try:
                with urllib.request.urlopen(req, timeout=900) as r:
                    urls[f.name] = json.loads(r.read().decode("utf-8")).get("browser_download_url", "")
                break
            except urllib.error.HTTPError as e:
                if e.code == 422 and attempt == 0:                   # a file with that name already exists
                    name = f"{f.stem}_{time.strftime('%H%M%S')}{f.suffix}"
                    continue
                raise
    return urls


BOT = {"gender": None, "current": None, "queue": None}


def bot_config():
    load_env()
    need = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ALLOWED_USERS"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        sys.exit("Missing in .env: " + ", ".join(miss) + "\nSee SETUP_TELEGRAM_GITHUB.txt (copy .env.example to .env).")
    return {"chat": int(os.environ["TELEGRAM_CHAT_ID"]),
            "topic": int(os.environ["TELEGRAM_TOPIC_ID"]) if os.environ.get("TELEGRAM_TOPIC_ID") else None,
            "users": {int(x) for x in os.environ["TELEGRAM_ALLOWED_USERS"].replace(" ", "").split(",") if x}}


HELP_TEXT = ("Paste a script here and I will make the video.\n\n"
             "Format: first line  Video: <title>  then one line per scene  <what to do> || <what the voice says>\n"
             "Several scripts in one message: separate them with a line containing ---\n"
             "Optional lines: Voice: female   Tag: Windows Tips   Part: 1\n\n"
             "Commands: /voice male|female  (voice for the next videos)   /status   /id   /help")


def bot_handle(msg, cfg, q):
    """One incoming Telegram message -> a reply and/or queued jobs. Returns a short note (used by tests/logs)."""
    chat, thread = msg["chat"]["id"], msg.get("message_thread_id")
    uid = (msg.get("from") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if text.split("@")[0] == "/id":
        tg_say(chat, thread, f"chat id: {chat}\ntopic id: {thread or '(none)'}\nyour user id: {uid}")
        return "id"
    if chat != cfg["chat"] or (cfg["topic"] and thread != cfg["topic"]) or not text:
        return "ignored"
    if uid not in cfg["users"]:
        tg_say(chat, thread, "Sorry, you are not on the allowed list for this bot.")
        return "denied"
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if cmd in ("/help", "/start"):
        tg_say(chat, thread, HELP_TEXT)
    elif cmd == "/voice":
        arg = (text.split() + [""])[1].lower()
        if arg in ("male", "female"):
            BOT["gender"] = arg
            tg_say(chat, thread, f"OK: next videos use the {arg} voice.")
        else:
            tg_say(chat, thread, f"Current voice: {BOT['gender'] or DEFAULT_GENDER}. Use /voice male or /voice female.")
    elif cmd == "/status":
        cur = BOT["current"]
        tg_say(chat, thread, f"Working on: {cur or 'nothing'}\nWaiting: {q.qsize()}\nVoice: {BOT['gender'] or DEFAULT_GENDER}")
    elif cmd:
        tg_say(chat, thread, "Unknown command. /help")
    else:
        scripts = split_scripts(text)
        if not scripts or not (URL_RE.search(text) or re.search(r"(?i)^\s*video\s*:", text, re.M)):
            tg_say(chat, thread, "I could not find a script. Send it starting with  Video: <title>  (see /help).")
            return "no-script"
        for i, sc in enumerate(scripts, 1):
            job = Job(f"tg{msg['message_id']}_{slug(sc, i)[3:] or i}", brief_text=sc)
            job.force_gender = BOT["gender"]
            job.meta = {"chat": chat, "thread": thread}
            q.put(job)
        tg_say(chat, thread, f"Queued {len(scripts)} video(s). {q.qsize()} waiting. When recording starts I will tell you "
                             f"- please do not touch the PC's mouse/keyboard until I say it is done.")
        return "queued"
    return cmd or "ok"


def bot_deliver(job, meta):
    files = [p for p in [job.transcript, *job.outs.values()] if p.exists()]
    chat, thread = meta["chat"], meta["thread"]
    for p in files:
        try:
            ok = tg_send_file(chat, thread, p, caption=f"{p.stem}")
            if not ok:
                tg_say(chat, thread, f"{p.name} is too big for Telegram - see the GitHub link.")
        except Exception as e:
            tg_say(chat, thread, f"Could not send {p.name}: {type(e).__name__}")
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPO"):
        try:
            urls = github_upload(files)
            tg_say(chat, thread, "Stored on GitHub:\n" + "\n".join(f"{n}: {u}" for n, u in urls.items()))
        except Exception as e:
            tg_say(chat, thread, f"GitHub upload failed ({type(e).__name__}); the files are still on the PC in {OUT}")


def bot_worker(q):
    while True:
        job = q.get()
        meta = getattr(job, "meta", {})
        BOT["current"] = job.name
        try:
            tg_say(meta["chat"], meta["thread"], f"Starting {job.name} in {BOT_START_DELAY}s. Hands off the mouse and keyboard now.")
            time.sleep(BOT_START_DELAY)
            run_job(job)
            tg_say(meta["chat"], meta["thread"], "Done. You can use the PC again. Sending the files ...")
            bot_deliver(job, meta)
        except BaseException as e:
            tg_say(meta.get("chat"), meta.get("thread"), f"Failed: {str(e)[:500] or type(e).__name__}")
            log(f"[{job.name}] FAILED: {e}")
            if type(e).__name__ == "FailSafeException":
                tg_say(meta.get("chat"), meta.get("thread"), "Stopped by the screen-corner failsafe.")
        finally:
            BOT["current"] = None
            q.task_done()


def cmd_bot_setup():
    """Find the ids you need for .env: send /id in your group topic (and to the bot) and it answers."""
    load_env()
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        sys.exit("Put TELEGRAM_BOT_TOKEN=... in .env first (copy .env.example to .env).")
    print("Setup mode: in your Telegram group topic send   /id   - I will reply with the ids. Press Ctrl+C when done.")
    cfg, offset = {"chat": 0, "topic": None, "users": set()}, None
    while True:
        try:
            ups = tg_call("getUpdates", {"timeout": 50, "offset": offset, "allowed_updates": ["message"]}, timeout=70)
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"  (poll problem: {type(e).__name__}; retrying)")
            time.sleep(5)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            if u.get("message"):
                if bot_handle(u["message"], cfg, queue.Queue()) == "id":
                    m = u["message"]
                    print(f"  chat id {m['chat']['id']}  topic id {m.get('message_thread_id')}  user id {m['from']['id']}")


def cmd_bot():
    preflight()
    cfg = bot_config()
    q = queue.Queue()
    BOT["queue"] = q
    threading.Thread(target=bot_worker, args=(q,), daemon=True).start()
    keep_awake(True)
    print(f"Bot is running. Listening in chat {cfg['chat']}" + (f", topic {cfg['topic']}" if cfg["topic"] else "") +
          f". Allowed users: {sorted(cfg['users'])}. Press Ctrl+C to stop.")
    offset = None
    try:
        while True:
            try:
                ups = tg_call("getUpdates", {"timeout": 50, "offset": offset, "allowed_updates": ["message"]}, timeout=70)
            except Exception as e:
                print(f"  (telegram poll problem: {type(e).__name__}; retrying)")
                time.sleep(5)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                if u.get("message"):
                    try:
                        bot_handle(u["message"], cfg, q)
                    except Exception as e:
                        print(f"  (could not handle a message: {e})")
    finally:
        keep_awake(False)


# ----------------------------------------------------------------------------
# COMMANDS
# ----------------------------------------------------------------------------
def cmd_check():
    preflight()
    OUT.mkdir(exist_ok=True)
    work = WORK / "_check"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    x, y, w, h = work_area()
    print(f"Browser : {find_browser()}")
    print(f"Capture : {w}x{h} at ({x},{y})  (screen minus taskbar)")
    countdown(3)
    try:
        with Session() as s:
            print(f"Calibration: {s.b0:.3f} screen px per page px, page origin at ({s.ax:.0f},{s.ay:.0f})")
            rec = Recorder(s.region, work / "check_raw.mp4", draw_mouse=True)
            rec.start()
            s.clock = rec.clock
            errs = []
            vw, vh = s.viewport()
            for fx, fy in ((.2, .3), (.8, .3), (.8, .8), (.2, .8), (.5, .5)):
                s.point_at(vw * fx, vh * fy)
                mm = s.page.evaluate("window.__mm")
                errs.append(max(abs(vw * fx - mm[0]), abs(vh * fy - mm[1])))
                time.sleep(0.3)
            print("Pointer accuracy (px error at 5 points):", [round(e, 1) for e in errs])
            do_action(s, {"goto": "example.com"}, rec, [])
            time.sleep(0.5)
            rec.stop()
        final = OUT / "check.mp4"
        shutil.copy(work / "check_raw.mp4", final)
        print(f"\nRecorded {video_size(final)} -> {final}")
        print("Open check.mp4: you should see the REAL pointer moving on the full browser window,")
        print("the URL being typed, and example.com loading. If the picture is cropped or shifted, set")
        print('CAPTURE = "ddagrab" at the top of autovideo.py, or set Windows display scale to 100%.')
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print("Temp profile and work files deleted.")


def cmd_plan():
    job = Job.default()
    plan_job(job)
    print("plan.json is ready. Review it (fix wrong button names), then run:  python autovideo.py make")


def cmd_make():
    preflight()
    job = Job.default()
    if not job.plan.exists():
        sys.exit("plan.json not found. Run:  python autovideo.py plan")
    plan = validate_plan(job.plan)
    OUT.mkdir(exist_ok=True)
    countdown(5)
    print("1/3 recording the real session ...")
    record_job(job, plan)
    finish_job(job, plan)


def cmd_finish():
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH.")
    job = Job.default()
    finish_job(job, validate_plan(job.plan))


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    OUT.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def cmd_queue():
    preflight()
    jobs = collect_jobs()
    if not jobs:
        sys.exit("No scripts found. Put your scripts in scripts.txt (separate them with a line containing only ---)\n"
                 "or put one .txt file per script in the jobs folder.")
    OUT.mkdir(exist_ok=True)
    PLANS.mkdir(parents=True, exist_ok=True)
    st = load_state()
    todo = [j for j in jobs if not (st.get(j.key, {}).get("status") == "done" and all(p.exists() for p in j.outs.values()))]
    log(f"Queue: {len(jobs)} script(s), {len(todo)} to make, {len(jobs) - len(todo)} already done.")
    for j in todo:
        print(f"  - {j.name}")
    if not todo:
        return
    print("\nPlanning all scripts first (the mouse is not used yet, you can keep working) ...")
    ready = []
    for j in todo:
        try:
            if not j.plan.exists():
                print(f"[{j.name}] planning ...")
                plan_job(j)
            validate_plan(j.plan)
            ready.append(j)
        except Exception as e:
            st[j.key] = {"name": j.name, "status": "failed", "error": str(e)[-400:]}
            log(f"[{j.name}] PLANNING FAILED: {e}")
    save_state(st)
    todo = ready
    if not todo:
        print("Nothing could be planned. See the messages above.")
        return
    print(f"\nPlans are saved in {PLANS} (you can edit them before recording starts: close this window and re-run).")
    print("\nThe computer will be busy (real mouse + keyboard) until the queue ends. Keep it plugged in.")
    countdown(10, "The queue will start; the browser will open")
    keep_awake(True)
    results = []
    try:
        for n, job in enumerate(todo, 1):
            log(f"=== [{n}/{len(todo)}] {job.name} ===")
            t0 = time.time()
            try:
                run_job(job)
                st[job.key] = {"name": job.name, "status": "done", "file": str(job.final)}
                results.append((job.name, "done", f"{time.time() - t0:.0f}s"))
                log(f"[{job.name}] finished in {time.time() - t0:.0f}s -> {job.final}")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if type(e).__name__ == "FailSafeException":
                    log("Aborted by the corner failsafe. Queue stopped.")
                    raise
                st[job.key] = {"name": job.name, "status": "failed", "error": str(e)[-400:]}
                results.append((job.name, "FAILED", str(e).splitlines()[0][:70] if str(e) else type(e).__name__))
                log(f"[{job.name}] FAILED: {e}\n{traceback.format_exc()[-1200:]}")
            save_state(st)
            if n < len(todo):
                time.sleep(GAP_BETWEEN_JOBS)
    finally:
        keep_awake(False)
        save_state(st)
        print("\n================ QUEUE SUMMARY ================")
        for name, status, info in results:
            print(f"  {status:7} {name}   {info}")
        print(f"Videos are in {OUT}. Failed ones are retried when you run 'queue' again. Log: {LOG}")


def main():
    global FORCE_GENDER
    load_env()
    args = sys.argv[1:]
    for i, a in enumerate(list(args)):                            # --female / --male / --voice female
        low = a.lower()
        if low in ("--female", "--male"):
            FORCE_GENDER = low[2:]
        elif low.startswith("--voice="):
            FORCE_GENDER = low.split("=", 1)[1]
        elif low == "--voice" and i + 1 < len(args):
            FORCE_GENDER = args[i + 1].lower()
    args = [a for i, a in enumerate(args) if not a.startswith("--") and not (i > 0 and args[i - 1].lower() == "--voice")]   # (--enc is read from sys.argv)
    if FORCE_GENDER and FORCE_GENDER not in ("male", "female"):
        sys.exit("Use --male or --female.")
    cmd = args[0] if args else ""
    if cmd == "check":
        cmd_check()
    elif cmd == "queue":
        cmd_queue()
    elif cmd == "job" and len(args) > 1:
        import avx_job
        avx_job.cmd_job(args[1], encrypted="--enc" in sys.argv)
    elif cmd == "templates":
        import avx_templates
        print(avx_templates.preview(args[1] if len(args) > 1 else "templates.png"))
    elif cmd == "bot":
        cmd_bot()
    elif cmd == "bot-setup":
        cmd_bot_setup()
    elif cmd == "voice-profile" and len(args) > 1:
        cmd_voice_profile(args[1])
    elif cmd == "voice-lab":
        cmd_voice_lab()
    elif cmd == "plan":
        cmd_plan()
    elif cmd == "make":
        cmd_make()
    elif cmd == "finish":
        cmd_finish()
    elif cmd == "all":
        cmd_plan()
        cmd_make()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
