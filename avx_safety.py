"""
avx_safety.py - checks applied to every script BEFORE a browser is opened, because group members (not only the owner)
can now send scripts and ideas. The browser itself runs in a throw-away machine, but these rules also stop scripts that
try to reach internal addresses, local files or credential-looking input.
"""
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

MAX_CHARS = 4500
MAX_SCENES = 14
MAX_ACTIONS_PER_SCENE = 5
URL_RE = re.compile(r"(?:https?|file|ftp|javascript|data|chrome|about|view-source)\s*:[^\s)\"'<>\]]+", re.I)
BARE_RE = re.compile(r"\[goto\s+([^\]\s]+)", re.I)
DEFAULT_BLOCKED = ("localhost", "metadata.google.internal", "169.254.169.254", "instance-data", "kubernetes.default",
                   "internal", "local", "lan", "intranet", "corp", "home.arpa")
SECRETISH = re.compile(r"(?i)(\bAQ\.[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,}|\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b|"
                       r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,}|\b(?:\d[ -]*?){15,16}\b)")


def _blocked_extra():
    extra = [x.strip().lower() for x in (os.environ.get("AUTOVIDEO_BLOCKED_HOSTS") or "").split(",") if x.strip()]
    return DEFAULT_BLOCKED + tuple(extra)


def host_problem(url, resolve=True):
    """None if the URL is fine, else a short reason."""
    if os.environ.get("AUTOVIDEO_ALLOW_LOCAL") == "1":      # tests only: lets the offline test site on 127.0.0.1 through
        return None
    u = url.strip()
    if not re.match(r"(?i)^[a-z][a-z0-9+.\-]*:", u):
        u = "https://" + u
    p = urlparse(u)
    if p.scheme.lower() not in ("http", "https"):
        return f"scheme '{p.scheme}:' is not allowed"
    host = (p.hostname or "").lower().strip(".")
    if not host:
        return "no host in the address"
    if p.username or p.password:
        return "addresses with a user name/password are not allowed"
    for b in _blocked_extra():
        if host == b or host.endswith("." + b) or (b in ("internal", "local", "lan", "corp") and host.endswith(b)):
            return f"'{host}' is an internal or blocked address"
    try:
        ip = ipaddress.ip_address(host)
        ips = [ip]
    except ValueError:
        ips = []
        if resolve:
            try:
                ips = [ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, None)]
            except Exception:
                ips = []                                   # cannot resolve here: the browser will simply fail to load it
        if "." not in host:
            return f"'{host}' is not a public website name"
    for ip in ips:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return f"'{host}' points to a private/internal network address"
    return None


def validate_script(text, resolve=True):
    """-> list of problems (empty = OK)."""
    problems = []
    t = text or ""
    if len(t) > MAX_CHARS:
        problems.append(f"script is too long ({len(t)} characters, max {MAX_CHARS})")
    if SECRETISH.search(t):
        problems.append("the text looks like it contains a password, API key, token or card number - remove it")
    lines = [l for l in t.splitlines() if l.strip() and not re.match(r"(?i)^\s*(video|title|tag|part|voice|language|template|depth|outputs|captions|frame|brand|music|style|tone|note|notes|gender|category)\s*:", l)]
    if len(lines) > MAX_SCENES + 2:
        problems.append(f"too many scene lines ({len(lines)}, max {MAX_SCENES})")
    for ln in lines:
        if len(re.findall(r"\[[a-z]+\b", ln, re.I)) > MAX_ACTIONS_PER_SCENE:
            problems.append(f"too many actions in one line: {ln[:60]}")
            break
    seen = set()
    for m in list(URL_RE.findall(t)) + ["https://" + x if not re.match(r"(?i)^[a-z]+:", x) else x for x in BARE_RE.findall(t)]:
        m = m.rstrip(".,;:!?")
        if m in seen:
            continue
        seen.add(m)
        why = host_problem(m, resolve)
        if why:
            problems.append(f"{m[:60]}: {why}")
    return problems[:6]
