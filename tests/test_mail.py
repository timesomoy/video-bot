"""Mock test for the temp-mail helper (no network): mailbox creation, placeholders, link/code extraction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import avx_mail as m

store = {"msgs": []}
def fake_http(method, url, body=None, token=None, timeout=20):
    if url.endswith("/domains"):
        return {"hydra:member": [{"domain": "priv.example", "isActive": True, "isPrivate": True}, {"domain": "mail.example", "isActive": True, "isPrivate": False}]}
    if url.endswith("/accounts"):
        assert body["address"].endswith("@mail.example") and len(body["password"]) >= 8
        return {"id": "1", "address": body["address"]}
    if url.endswith("/token"):
        return {"token": "T"}
    if url.endswith("/messages"):
        assert token == "T"
        return {"hydra:member": [{"id": x["id"], "subject": x["subject"]} for x in store["msgs"]]}
    if "/messages/" in url:
        return next(x for x in store["msgs"] if url.endswith(x["id"]))
    raise AssertionError(url)

t = {"now": 0.0}
def now(): return t["now"]
def sleep(s):
    t["now"] += s
    if t["now"] >= 6 and not store["msgs"]:           # the mail arrives after 6 "seconds"
        store["msgs"].append({"id": "m1", "subject": "Your verification code is 482913", "from": {"address": "no-reply@app.example"},
            "text": "Hi! Confirm: https://app.example/verify?token=abc123&x=1\nOr use code 482913.\nUnsubscribe https://app.example/unsubscribe",
            "html": ['<a href="https://app.example/verify?token=abc123&amp;x=1">Confirm</a> <a href="https://facebook.com/app">fb</a>']})

box = m.TempMail(http=fake_http, sleep=sleep, now=now)
state = {}
addr = box.fill("{email}", state)
assert addr.endswith("@mail.example") and box.fill("{email}", state) == addr          # same mailbox every time
assert box.fill("{password}", state) == box.password
msg = box.wait_message(timeout=30, poll=3)
assert msg and msg["code"] == "482913", msg
assert msg["link"] == "https://app.example/verify?token=abc123&x=1", msg["link"]      # verify link, not facebook / unsubscribe
assert box.wait_message(timeout=6, poll=3) is None                                    # nothing new: returns None, no crash
assert m.pick_code("Welcome", "your pin: 7788") == "7788"
assert m.pick_link("see https://a.com/logo.png and https://a.com/unsubscribe", "") is None
st2 = {"last": msg}
assert box.fill("code {code}", st2) == "code 482913"
print("temp-mail tests OK")
