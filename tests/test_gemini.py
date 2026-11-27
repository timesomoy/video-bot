"""Mock tests for avx_gemini: response shapes, model fallback, 429 retry, key never leaked, script cleaning."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import avx_gemini as g

os.environ["GEMINI_API_KEY"] = "SECRETKEY123"
os.environ.pop("GEMINI_MODEL", None); os.environ.pop("AUTOVIDEO_AI_MODEL", None)

# 1. model normalisation (the user's .env had the display name "Gemini 4 Hydrogen")
assert g.normalize_model("Gemini 4 Hydrogen") == "gemini-4-hydrogen"
assert g.normalize_model("models/gemini-3.8-flash") == "gemini-3.8-flash"
assert g.model_list()[0] == "gemini-4-hydrogen"
os.environ["AUTOVIDEO_AI_MODEL"] = "  Gemini 4 Hydrogen"
assert g.model_list()[0] == "gemini-4-hydrogen"
os.environ.pop("AUTOVIDEO_AI_MODEL")

# 2. three response shapes
gc = {"candidates": [{"content": {"parts": [{"text": "hello "}, {"text": "world"}]}}]}
st = {"id": "x", "steps": [{"type": "model_output", "content": [{"type": "text", "text": "from steps"}]}]}
ou = {"id": "x", "outputs": [{"type": "text", "text": "from outputs"}]}
assert g.extract_text(gc) == "hello world" and g.extract_text(st) == "from steps" and g.extract_text(ou) == "from outputs"

# 3. fallback: first model 404 -> second model answers; header key is sent, URL has no key
calls = []
def post_fallback(url, body, key, timeout=90):
    calls.append(url)
    assert key == "SECRETKEY123" and "SECRETKEY123" not in url
    if "gemini-4-hydrogen" in url:
        e = g.GeminiError("HTTP 404: model not found"); e.code = 404; raise e
    return gc
assert g.complete("s", "u", post=post_fallback, sleep=lambda s: None) == "hello world"
assert len(calls) == 2, calls

# 4. 429 once -> wait -> succeed on the same model
state = {"n": 0}; waited = []
def post_429(url, body, key, timeout=90):
    state["n"] += 1
    if state["n"] == 1:
        e = g.GeminiError("HTTP 429"); e.code = 429; raise e
    return gc
assert g.complete("s", "u", post=post_429, sleep=waited.append) == "hello world" and waited == [20]

# 5. everything fails -> one clear error, key never inside the message
def post_fail(url, body, key, timeout=90):
    e = g.GeminiError(f"HTTP 403: denied {key}".replace(key, "***")); e.code = 403; raise e
try:
    g.complete("s", "u", post=post_fail, sleep=lambda s: None); raise SystemExit("should have failed")
except g.GeminiError as e:
    assert "SECRETKEY123" not in str(e)

# 6. script cleaning + generation with a fake model
messy = "```text\nHere is your script:\n**Video: Remove a background**\n1. Open https://example.com || A hook.\n- Click Try || Next.\n|| Try it free.\n```"
c = g.clean_script(messy)
assert c.splitlines()[0].lower().startswith("video:"), c
good = "Video: Test\nOpen https://example.com || Hook line here.\nClick Try || Second.\n|| Call to action."
answers = iter(["just some prose without the format", good])
out = g.generate_script("remove a background", style="fast tips", complete_fn=lambda s, u: next(answers))
assert out.startswith("Video: Test") and g.script_ok(out)
assert "fast tips" in g.build_system("fast tips") and "Narration language: Bangla" in g.build_system(language="Bangla")
assert "{email}" in g.build_system() and "<<" not in g.build_system()
assert g.looks_like_script(good) and not g.looks_like_script("how to remove a background free")
print("gemini tests OK")
