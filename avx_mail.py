"""
avx_mail.py - a throw-away mailbox for sign-up demos (mail.tm public API, no key needed).

The robot types the address into the website's sign-up form with the REAL keyboard; this module only creates the
mailbox and reads the inbox through the API, so the video shows a real sign-up without scraping a temp-mail website.

Placeholders usable in  [type field | text]  lines:   {email}   {password}   {code}   {name}
Action  [verify]  waits for the confirmation e-mail and opens its link.

Use only for demos of services that allow it. Nothing here bypasses captchas or phone checks.
"""
import json
import random
import re
import string
import time
import urllib.error
import urllib.request

API = "https://api.mail.tm"
LINK_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
CODE_RE = re.compile(r"(?<![\w.])(\d{4,8})(?![\w.])")
GOOD_LINK = re.compile(r"verif|confirm|activate|validate|magic|token|signin|login|auth|click|redirect|u/", re.I)
BAD_LINK = re.compile(r"unsubscribe|privacy|terms|\.(png|jpe?g|gif|svg|css|ico)(\?|$)|facebook\.com|twitter\.com|x\.com/|instagram\.com|linkedin\.com|youtube\.com", re.I)


def _http(method, url, body=None, token=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "autovideo"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8") or "{}"
    return json.loads(raw)


def strip_html(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"[ \t]+", " ", re.sub(r"&nbsp;", " ", html)).strip()


def pick_link(text, html=""):
    """The most likely confirmation link: prefer verify/confirm words, skip social/unsubscribe/images."""
    hrefs = re.findall(r"""href=["']([^"']+)["']""", html or "", re.I)
    links = [h.replace("&amp;", "&") for h in hrefs if h.lower().startswith("http")] + LINK_RE.findall(text or "")
    links = [u.rstrip(".,;") for u in links if not BAD_LINK.search(u)]
    good = [u for u in links if GOOD_LINK.search(u)]
    return (good or links or [None])[0]


def pick_code(subject, text):
    """A 4-8 digit one-time code. Subject first, then lines that mention code/verify/otp, then any standalone number."""
    for chunk in (subject or "",):
        m = CODE_RE.search(chunk)
        if m:
            return m.group(1)
    for ln in (text or "").splitlines():
        if re.search(r"code|verif|otp|pin|confirm", ln, re.I):
            m = CODE_RE.search(ln)
            if m:
                return m.group(1)
    m = CODE_RE.search(text or "")
    return m.group(1) if m else None


class TempMail:
    """One mailbox for one video. Created lazily the first time {email} is needed."""

    def __init__(self, http=_http, sleep=time.sleep, now=time.time):
        self.http, self.sleep, self.now = http, sleep, now
        self.address = self.password = self.token = None
        self.seen = set()

    def create(self):
        if self.address:
            return self.address
        doms = self.http("GET", API + "/domains")
        members = doms.get("hydra:member", doms if isinstance(doms, list) else [])
        domains = [d["domain"] for d in members if d.get("isActive", True) and not d.get("isPrivate", False)]
        if not domains:
            raise RuntimeError("the temp-mail service returned no domains")
        alpha = string.ascii_lowercase + string.digits
        pw = "".join(random.choice(string.ascii_letters) for _ in range(6)) + "".join(random.choice(string.digits) for _ in range(3)) + "!Aa"
        last = None
        for _ in range(4):
            addr = "".join(random.choice(string.ascii_lowercase) for _ in range(6)) + "".join(random.choice(alpha) for _ in range(4)) + "@" + random.choice(domains)
            try:
                self.http("POST", API + "/accounts", {"address": addr, "password": pw})
                self.token = self.http("POST", API + "/token", {"address": addr, "password": pw})["token"]
                self.address, self.password = addr, pw
                return addr
            except Exception as e:                       # address taken / rate limit: try another
                last = e
                self.sleep(1.0)
        raise RuntimeError(f"could not create a temp mailbox: {last}")

    def inbox(self):
        r = self.http("GET", API + "/messages", token=self.token)
        return r.get("hydra:member", r if isinstance(r, list) else [])

    def wait_message(self, timeout=90, poll=3.0):
        """The newest message we have not returned yet, as {'subject','text','html','link','code','from'} (or None)."""
        end = self.now() + timeout
        while self.now() < end:
            try:
                for m in self.inbox():
                    if m["id"] in self.seen:
                        continue
                    full = self.http("GET", f"{API}/messages/{m['id']}", token=self.token)
                    self.seen.add(m["id"])
                    html = "".join(full.get("html") or []) if isinstance(full.get("html"), list) else (full.get("html") or "")
                    text = full.get("text") or strip_html(html)
                    subj = full.get("subject") or m.get("subject") or ""
                    return {"subject": subj, "text": text, "html": html, "from": (full.get("from") or {}).get("address", ""),
                            "link": pick_link(text, html), "code": pick_code(subj, text)}
            except Exception:
                pass
            self.sleep(poll)
        return None

    def fill(self, text, state=None):
        """Resolve {email} {password} {code} {name} inside text typed by the robot."""
        state = state if state is not None else {}
        if "{email}" in text:
            text = text.replace("{email}", self.create())
        if "{password}" in text:
            self.create()
            text = text.replace("{password}", self.password)
        if "{name}" in text:
            text = text.replace("{name}", state.setdefault("name", random.choice(["Alex", "Sam", "Jordan", "Taylor", "Riley", "Casey"]) + " " + random.choice(["Lee", "Parker", "Reed", "Brooks", "Kim", "Hart"])))
        if "{code}" in text:
            msg = state.get("last") or self.wait_message()
            if not msg or not msg.get("code"):
                raise RuntimeError("no verification code arrived in the temp inbox")
            state["last"] = msg
            text = text.replace("{code}", msg["code"])
        return text
