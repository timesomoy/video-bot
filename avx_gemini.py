"""
avx_gemini.py - the Gemini API key lives in the BACK END (an environment variable / GitHub secret / .env), never in the
Telegram chat. It does two jobs:

  1. generate_script(): a plain-language idea ("show how to remove a photo background for free") + the saved "video type"
     ("fast tips for beginners, friendly, about 40 seconds") -> a full script in the format autovideo.py understands.
     The script is written FIRST; the rest of the pipeline (scout pages, record, voice, edit) continues from it.
  2. complete(): the generic text call used by the optional AI editor (ai_refine_plan).

Environment (any one of the key names):   GEMINI_API_KEY | GOOGLE_API_KEY | AUTOVIDEO_AI_KEY
Optional:                                 GEMINI_MODEL   (a model ID such as gemini-4-hydrogen; display names are normalised)

Model names and free-tier limits change often. The default is tried first, then the fallbacks; a 404/400 "unknown model"
moves to the next one, a 429 waits once and moves on. Check your own key's limits at https://aistudio.google.com/rate-limit
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-4-hydrogen"
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


class GeminiError(RuntimeError):
    pass


def normalize_model(name):
    """'Gemini 4 Hydrogen' -> 'gemini-4-hydrogen' ; 'models/gemini-3.8-flash' -> 'gemini-3.8-flash'."""
    n = (name or "").strip().lower()
    n = re.sub(r"^models/", "", n)
    n = re.sub(r"[\s_]+", "-", n)
    return re.sub(r"[^a-z0-9.\-]", "", n)


def get_key():
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AUTOVIDEO_AI_KEY"):
        v = (os.environ.get(k) or "").strip().strip("\"'")
        if v:
            return v
    return ""


def configured():
    return bool(get_key())


def model_list():
    first = normalize_model(os.environ.get("GEMINI_MODEL") or (os.environ.get("AUTOVIDEO_AI_MODEL") if "gemini" in (os.environ.get("AUTOVIDEO_AI_MODEL") or "").lower() else "")) or DEFAULT_MODEL
    out = [first]
    for m in FALLBACK_MODELS:
        if m not in out:
            out.append(m)
    return out


def _post(url, body, key, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key, "User-Agent": "autovideo"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        err = GeminiError(f"HTTP {e.code}: {body_txt}".replace(key, "***"))
        err.code = e.code
        raise err


def extract_text(resp):
    """Text from a generateContent answer, or from an Interactions answer (either the 'steps' or the older 'outputs' shape)."""
    out = []
    for c in resp.get("candidates") or []:
        for p in (c.get("content") or {}).get("parts") or []:
            if p.get("text") and not p.get("thought"):
                out.append(p["text"])
        if out:
            break
    if not out:
        for st in resp.get("steps") or []:
            if st.get("type") in ("model_output", "output", None):
                for c in st.get("content") or []:
                    if c.get("type") == "text" and c.get("text"):
                        out.append(c["text"])
    if not out:
        for o in resp.get("outputs") or []:
            if o.get("type") == "text" and o.get("text"):
                out.append(o["text"])
    return "".join(out).strip()


def complete(system, user, max_tokens=2500, temperature=0.8, post=_post, sleep=time.sleep):
    key = get_key()
    if not key:
        raise GeminiError("no Gemini key configured (set GEMINI_API_KEY in the back end)")
    errors = []
    for model in model_list():
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        for attempt in range(2):
            try:
                txt = extract_text(post(f"{BASE}/models/{model}:generateContent", body, key))
                if txt:
                    return txt
                errors.append(f"{model}: empty answer")
                break
            except GeminiError as e:
                code = getattr(e, "code", 0)
                if code == 429 and attempt == 0:
                    sleep(20)                                   # per-minute limit: wait once
                    continue
                errors.append(f"{model}: {str(e)[:160]}")
                break
            except Exception as e:                              # network problem
                errors.append(f"{model}: {type(e).__name__}")
                break
        else:
            continue
    # last resort: the Interactions endpoint (newer API shape)
    try:
        r = post(f"{BASE}/interactions", {"model": model_list()[0], "input": f"{system}\n\n{user}"}, key)
        txt = extract_text(r)
        if txt:
            return txt
    except Exception as e:
        errors.append(f"interactions: {str(e)[:120]}")
    raise GeminiError("Gemini did not answer: " + " | ".join(errors)[:600])


# ------------------------------------------------------------------------------------------------------------------
# the script writer
# ------------------------------------------------------------------------------------------------------------------
SCRIPT_RULES = """You write scripts for automated screen-demo videos. A robot opens a REAL web browser, moves the mouse, clicks, types and scrolls like a person; an AI voice reads your narration. Write in EXACTLY this format.

OUTPUT: only the script as plain text. No explanations, no markdown, no numbering, no bullets, no code fences.
First lines (Video is required, the rest optional):
Video: <short title>
Title: <punchy on-screen headline, max 6 words>
Tag: <1-3 word category>
Part: <number, only for a series>
Then ONE LINE PER SCENE:   <what the robot does> || <what the voice says: 1-2 short sentences>

What the robot can do (left of ||, plain English or tags):
- Open <full https URL>                     [goto https://...]
- Scroll down / Scroll down a bit / Scroll down to the bottom / Scroll up   [scroll 800]
- Click <exact visible text of a button or link>     [click Text]
- Hover over <exact visible text>           [hover Text]
- Type "<text>" in the <field name>         [type Field | text]   (add [press enter] to submit)
- Upload a photo                            [upload Upload photo]   (uses the image the user sent, or a built-in sample)
- Look around                               [explore 3]   (pointer visits the main controls; use on single-screen pages)
- Wait                                      [wait 2]
Chat boxes: to show a chat app, use [type Message | your question] then [press enter].
Sign-up demos (ONLY for services that allow throw-away e-mail, no captcha/phone/payment): [type Email | {email}] [type Password | {password}] then click the sign-up button, then [verify] opens the confirmation link from the temp inbox, or [type Code | {code}] types a one-time code. Never invent other credentials.

Rules:
1. Scene 1 opens the website. At most 3 actions per scene, in the same order as the narration.
2. Use only real, public pages. If you are not sure a button exists, use Look around instead of Click. Single-screen pages cannot scroll: do not use Scroll there.
3. Narration: energetic, confident tech-tips reel, strong hook in the first scene, present tense, short punchy sentences, 8-20 words per scene, no emojis, do not read URLs aloud, no claims the video cannot show.
4. Total about <<SECONDS>> seconds = <<SCENES>> scenes. The last scene is a call to action with an empty left part (start the line with ||).
5. Narration language: <<LANGUAGE>>. If it is not English, write only the part after || in that language (and add the line "Language: Bangla" at the top for Bangla).
"""


def build_system(style="", language="English", seconds=40, uploads=0):
    scenes = "5 to 7" if seconds <= 45 else "7 to 9"
    s = SCRIPT_RULES.replace("<<SECONDS>>", str(seconds)).replace("<<SCENES>>", scenes).replace("<<LANGUAGE>>", language or "English")
    if uploads:
        s += f"\nThe user attached {uploads} image(s): you may use [upload ...] where it makes sense.\n"
    if (style or "").strip():
        s += ("\nVIDEO TYPE chosen by the user (obey it for tone, pace, audience and structure until they change it):\n"
              + style.strip()[:600] + "\n")
    return s


def clean_script(text):
    """Strip code fences / markdown, keep only script lines, make sure it starts with a Video: line."""
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t, flags=re.M).strip()
    lines = []
    for ln in t.splitlines():
        ln = ln.rstrip()
        ln = re.sub(r"^\s*[-*\u2022]\s+", "", ln)                    # bullets
        ln = re.sub(r"^\s*\d+[.)]\s+(?=\S)", "", ln) if "||" in ln else ln
        ln = ln.replace("**", "").replace("`", "")
        if ln.strip():
            lines.append(ln)
    if not lines:
        return ""
    if not re.match(r"(?i)^\s*video\s*:", lines[0]):
        first = next((l for l in lines if re.match(r"(?i)^\s*video\s*:", l)), None)
        if first:
            lines = lines[lines.index(first):]
        else:
            lines.insert(0, "Video: Quick demo")
    return "\n".join(lines[:60])


def looks_like_script(text):
    t = text or ""
    return bool(re.search(r"(?im)^\s*video\s*:", t) or "||" in t or re.search(r"(?m)\[(goto|click|type|scroll|upload|verify|explore)\b", t))


def script_ok(text):
    """At least a title line and 2 scene lines (a line with || or a URL or a tag)."""
    scenes = [l for l in (text or "").splitlines() if "||" in l or re.search(r"https?://", l) or re.search(r"\[(goto|click|type|upload)\b", l)]
    return bool(re.search(r"(?im)^\s*video\s*:", text or "")) and len(scenes) >= 2


def generate_script(idea, style="", language="English", seconds=40, uploads=0, complete_fn=None):
    complete_fn = complete_fn or complete
    system = build_system(style, language, seconds, uploads)
    user = f"Write the script for this video idea:\n{idea.strip()[:1200]}"
    last = ""
    for attempt in range(2):
        raw = complete_fn(system, user if attempt == 0 else user + "\n\nYour last answer did not follow the format. Output ONLY the script lines.")
        last = clean_script(raw)
        if script_ok(last):
            return last
    raise GeminiError("the generated script was not in the expected format:\n" + last[:300])
