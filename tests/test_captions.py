"""Fuzz test: subtitle pages must keep every word, in order, with monotone times, and always fit ONE line."""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import avx_templates as tp

W, SIZE = 1080, int(1080 * 0.076)
MAX_W = int(W * 0.9)
rng = random.Random(1)
vocab = ["a", "it", "Windows", "settings", "Change", "extraordinarily", "supercalifragilisticexpialidocious", "AI", "free,", "now.", "tips!",
         "browser?", "Let's", "open", "ChatGPT", "background", "remove", "no", "sign-up", "photos"]
bad = 0
for trial in range(400):
    n = rng.randint(1, 30)
    words, t = [], 0.0
    for _ in range(n):
        w = rng.choice(vocab); d = rng.uniform(0.1, 0.6)
        words.append((w, t, d)); t += d + rng.uniform(0, 0.1)
    for style in ("pill", "box", "text", "underline"):
        fits = lambda ws, st=style: tp.line_width(ws, SIZE, st) <= MAX_W
        pages = tp.split_pages(words, 5.0, 1.07, rng.choice([3, 4, 5]), fits)
        flat = [w[0] for p in pages for w in p["words"]]
        assert flat == [w[0] for w in words], ("words lost/reordered", trial, style)
        assert all(p["words"] for p in pages), "empty page"
        ts = [p["t0"] for p in pages]
        assert ts == sorted(ts), "pages out of order"
        for p in pages:
            ws = [w[0] for w in p["words"]]
            # a single word wider than the line is allowed: render_caption shrinks the font for it
            assert len(ws) == 1 or fits(ws), ("page does not fit one line", ws, style)
            assert p["t1"] >= p["words"][-1][2] - 1e-9
            img, al = tp.render_caption(ws, len(ws) - 1, SIZE, MAX_W, style)
            assert img.shape[1] <= MAX_W + 16, ("rendered caption wider than the line", img.shape, ws, style)
            assert img.shape[0] < SIZE * 1.6, ("caption is more than one line tall", img.shape, ws)
print("caption fuzz test OK (400 scripts x 4 styles)")
