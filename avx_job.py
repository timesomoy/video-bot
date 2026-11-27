"""
avx_job.py - ONE video, start to finish, inside a throw-away sandbox.

    python autovideo.py job payload.json          (this is what the GitHub Actions workflow / the Docker image runs)

payload.json (written by the Telegram front end, see worker/worker.js):
{
  "id": "job-123", "chat_id": 123456, "thread_id": null, "user": "alice",
  "mode": "idea" | "script",
  "text": "plain-language idea, or a full script",
  "options": {"template":"neon","depth":2,"outputs":["vertical","instagram"],"captions":"pill","frame":"laptop",
              "video_type":"fast tips for beginners, friendly","language":"English","seconds":40,"gender":"male"},
  "files": [{"file_id":"...","name":"photo.jpg"}]        # images the member sent, for [upload ...]
}

Sandbox guarantees (the point of this file):
  * everything lives in ONE temp directory + one private browser profile + one private virtual screen;
  * the temp directory, the profile, the downloaded images, the recordings and the browser are deleted in a `finally`;
  * a hard time limit kills a stuck job;
  * the result is sent to Telegram and nothing is kept (on GitHub Actions the whole machine is destroyed afterwards as well).
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

JOB_TIMEOUT = int(os.environ.get("AUTOVIDEO_JOB_TIMEOUT", "1500"))        # seconds
SCREEN = os.environ.get("AUTOVIDEO_SCREEN", "1920x1080x24")
IMG_OK = {".jpg", ".jpeg", ".png", ".webp"}


def redact(text):
    t = str(text)
    for k in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "AUTOVIDEO_AI_KEY", "GITHUB_TOKEN"):
        v = os.environ.get(k)
        if v:
            t = t.replace(v, "***")
    return re.sub(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b", "***", t)


class Sandbox:
    """Private temp dir + (on Linux without a display) a private Xvfb virtual screen. Everything is removed on exit."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="avjob_"))
        self.xvfb = None
        self.wm = None

    def __enter__(self):
        if os.name != "nt" and not os.environ.get("DISPLAY"):
            for n in range(90, 140):
                if not Path(f"/tmp/.X11-unix/X{n}").exists():
                    self.xvfb = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", SCREEN, "-nolisten", "tcp", "-ac"],
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    os.environ["DISPLAY"] = f":{n}"
                    for _ in range(50):
                        if Path(f"/tmp/.X11-unix/X{n}").exists():
                            break
                        time.sleep(0.1)
                    break
            if shutil.which("openbox") and self.xvfb:
                self.wm = subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                time.sleep(0.8)
        return self

    def __exit__(self, *exc):
        for p in (self.wm, self.xvfb):
            if p:
                try:
                    os.killpg(os.getpgid(p.pid), 9)
                except Exception:
                    pass
        if self.xvfb:
            os.environ.pop("DISPLAY", None)
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def _download_files(av, files, dest):
    """Images the member sent in Telegram -> re-encoded JPEGs (no metadata, max 1920 px). Anything else is ignored."""
    out = []
    for i, f in enumerate(files or []):
        try:
            info = av.tg_call("getFile", {"file_id": f["file_id"]})
            if int(info.get("file_size") or 0) > 10_000_000:
                continue
            ext = Path(info["file_path"]).suffix.lower()
            if ext not in IMG_OK:
                continue
            url = f"{av.tg_base()}/file/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{info['file_path']}"
            raw = dest / f"in_{i}{ext}"
            with urllib.request.urlopen(url, timeout=60) as r:
                raw.write_bytes(r.read(10_000_001))
            from PIL import Image
            im = Image.open(raw).convert("RGB")
            im.thumbnail((1920, 1920))
            clean = dest / f"photo_{i + 1}.jpg"
            im.save(clean, "JPEG", quality=92)
            raw.unlink(missing_ok=True)
            out.append(clean)
        except Exception as e:
            print(f"  (could not use image {i + 1}: {type(e).__name__})")
    return out


def _say(av, payload, text):
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not payload.get("chat_id"):
        print("  >>", text)
        return
    av.tg_say(payload["chat_id"], payload.get("thread_id"), text)


def run_payload(payload, send=True):
    import autovideo as av
    import avx_gemini
    import avx_safety
    av.load_env()
    opts = dict(payload.get("options") or {})
    started = time.time()
    if payload.get("chat_id") and not os.environ.get("TELEGRAM_BOT_TOKEN"):
        # without the token nothing can be delivered: fail loudly instead of building a video that is thrown away
        print("JOB FAILED: TELEGRAM_BOT_TOKEN is empty - add it as a GitHub *secret* (Settings > Secrets and variables > Actions > Secrets).")
        return False
    with Sandbox() as sb:
        av.OUT = sb.dir / "out"
        av.WORK = av.OUT / "_work"
        av.PLANS = av.OUT / "plans"
        for d in (av.OUT, av.WORK, av.PLANS):
            d.mkdir(parents=True, exist_ok=True)

        def on_alarm(signum, frame):
            raise TimeoutError(f"the job took longer than {JOB_TIMEOUT // 60} minutes and was stopped")
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, on_alarm)
            signal.alarm(JOB_TIMEOUT)
        try:
            # 1. the script: written by Gemini first (idea mode), or taken as it is
            text = (payload.get("text") or "").strip()
            if payload.get("mode", "script") == "idea" or (avx_gemini.configured() and not avx_gemini.looks_like_script(text) and text):
                if avx_gemini.configured():
                    _say(av, payload, "🧠 Writing the script with Gemini ...")
                    try:
                        text = avx_gemini.generate_script(
                            text, style=opts.get("video_type", ""), language=opts.get("language") or "English",
                            seconds=int(opts.get("seconds") or 40), uploads=len(payload.get("files") or []))
                    except Exception as e:
                        raise RuntimeError("Gemini could not write the script: " + redact(e)[:300])
                    _say(av, payload, "📝 Script:\n" + text[:3300])
                elif not avx_gemini.looks_like_script(text):
                    raise RuntimeError("That looks like an idea, but no Gemini key is configured in the back end. Send a full script instead, or ask the admin to add GEMINI_API_KEY.")
            # 2. safety checks on whatever script we now have
            problems = avx_safety.validate_script(text)
            if problems:
                raise RuntimeError("I can't run that script:\n- " + "\n- ".join(problems))
            # 3. the video
            job = av.Job("video", brief_text=text)
            job.force_gender = (opts.get("gender") or "").lower() or None
            job.set_options({k: v for k, v in opts.items() if k in ("template", "depth", "outputs", "captions", "frame", "caption_words")})
            job.assets = _download_files(av, payload.get("files"), sb.dir) if os.environ.get("TELEGRAM_BOT_TOKEN") else \
                [Path(p) for p in payload.get("local_files", [])]
            _say(av, payload, "🎬 Recording in a fresh private browser (about 3-6 minutes) ...")
            av.preflight()
            av.run_job(job)
            # 4. deliver
            files = [p for p in job.outs.values() if p.exists()] + ([job.transcript] if job.transcript.exists() else [])
            if send and os.environ.get("TELEGRAM_BOT_TOKEN") and payload.get("chat_id"):
                big = []
                for p in files:
                    try:
                        if not av.tg_send_file(payload["chat_id"], payload.get("thread_id"), p, caption=p.stem.replace("video_", "")):
                            big.append(p)
                    except Exception as e:
                        print(f"  (could not send {p.name}: {redact(e)[:120]})")
                        big.append(p)
                if big:
                    _say(av, payload, "Some files were too big for Telegram and could not be sent: " + ", ".join(x.name for x in big))
            else:
                keep = Path(payload.get("keep_dir") or "out_video")
                keep.mkdir(parents=True, exist_ok=True)
                for p in files:
                    shutil.copy(p, keep / p.name)
                print("  results copied to", keep)
            _say(av, payload, f"✅ Done in {int(time.time() - started)} s. 🧹 This session is closed and everything from it was deleted.")
            return True
        except BaseException as e:
            msg = redact(e)
            print("JOB FAILED:", msg)
            _say(av, payload, "❌ " + msg[:900] + "\n🧹 Session closed and deleted.")
            return False
        finally:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
    # leaving the with-block removed the temp dir, the profile, the virtual screen


def decrypt_payload(b64, key_b64):
    """AES-256-GCM, layout iv(12) + ciphertext + tag, exactly what worker.js (WebCrypto) produces."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(b64.strip())
    return json.loads(AESGCM(base64.b64decode(key_b64.strip())).decrypt(raw[:12], raw[12:], None).decode("utf-8"))


def cmd_job(path, encrypted=False):
    if encrypted:                                           # GitHub Actions: payload arrives encrypted (the repo may be public)
        payload = decrypt_payload(Path(path).read_text(encoding="utf-8"), os.environ["PAYLOAD_KEY"])
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    ok = run_payload(payload)
    if payload.get("uid") and os.environ.get("DONE_URL") and os.environ.get("DONE_SECRET"):
        try:                                                # tell the front end this member's job is over (frees their slot)
            req = urllib.request.Request(os.environ["DONE_URL"], data=json.dumps({"uid": payload["uid"]}).encode(), method="POST",
                                         headers={"content-type": "application/json", "x-done-secret": os.environ["DONE_SECRET"],
                                                  "user-agent": "videobot-runner/1.0 (+github-actions)"})   # Python's default UA is often blocked by Cloudflare (error 1010)
            urllib.request.urlopen(req, timeout=20).read()
            print("  (told the front end this job is over)")
        except Exception as e:
            print(f"  ! could not call DONE_URL: {redact(e)[:160]} (the front end frees the slot by itself after a minute or two)")
    sys.exit(0 if ok else 1)
