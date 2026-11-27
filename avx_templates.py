"""
avx_templates.py - looks for the vertical reel: backgrounds, device frames (laptop / tablet / monitor / card ...),
badges, title, and ONE-LINE word-highlight subtitles.

Everything here is pure drawing (PIL + numpy). autovideo.py calls:
    render_base(plan, template_name, W, H, win)   -> (background+frame+title as BGR, alpha mask of the video window)
    split_pages(words, fits, per)                 -> subtitle pages that always fit on ONE line
    render_caption(texts, active, size, max_w, style) -> (bgr, alpha) one-line subtitle image
    sample_photo(path)                            -> a generated photo used by the [upload ...] demo action

Preview all templates:   python avx_templates.py preview templates.png
"""
import hashlib
import math
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / "fonts"


# ------------------------------------------------------------------------------------------------------------------
# fonts
# ------------------------------------------------------------------------------------------------------------------
_FONT_CACHE = {}
_SYSTEM = ["/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "segoeuib.ttf", "arialbd.ttf",
           "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
_BENGALI = ["Nirmala.ttc", "NirmalaB.ttf", "vrinda.ttf", "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
            "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf", "/usr/share/fonts/opentype/noto/NotoSansBengali-Bold.ttf"]


def font(kind, size, text=""):
    """kind: 'sans' (Inter ExtraBold) | 'display' (Poppins Bold) | 'serif' (Lora Bold). Bengali text uses a system font."""
    from PIL import ImageFont
    bn = any("\u0980" <= c <= "\u09ff" for c in text)
    key = (kind, int(size), bn)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    f = None
    if bn:
        for n in _BENGALI:
            try:
                f = ImageFont.truetype(n, int(size))
                break
            except Exception:
                continue
    if f is None:
        local = {"sans": "Inter-ExtraBold.otf", "display": "Poppins-Bold.ttf", "serif": "Lora-Variable.ttf"}.get(kind, "Inter-ExtraBold.otf")
        try:
            f = ImageFont.truetype(str(FONT_DIR / local), int(size))
            if kind == "serif":
                try:
                    f.set_variation_by_axes([700])
                except Exception:
                    pass
        except Exception:
            for n in _SYSTEM:
                try:
                    f = ImageFont.truetype(n, int(size))
                    break
                except Exception:
                    continue
    if f is None:
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


# ------------------------------------------------------------------------------------------------------------------
# the templates.  Colours are RGB.  frame: laptop | tablet | monitor | card | glass | plain | brutal
# ------------------------------------------------------------------------------------------------------------------
TEMPLATES = {
    "clean-light": dict(label="Clean light (laptop)", bg=("gradient", (250, 247, 241), (206, 202, 196), 90), fg=(16, 16, 20),
                        accent=(31, 111, 209), tag=((14, 14, 18), (255, 255, 255)), part=(16, 16, 20), frame="laptop",
                        frame_c=(18, 20, 26), font="sans", cap=dict(style="pill", fg=(16, 16, 20), stroke=None, pill_fg=(255, 255, 255))),
    "clean-dark": dict(label="Clean dark (laptop)", bg=("gradient", (30, 32, 40), (8, 9, 13), 90), fg=(255, 255, 255),
                       accent=(56, 132, 255), tag=((255, 255, 255), (14, 14, 18)), part=(255, 255, 255), frame="laptop",
                       frame_c=(60, 63, 72), font="sans", cap=dict(style="pill", fg=(255, 255, 255), stroke=(0, 0, 0), pill_fg=(255, 255, 255))),
    "terrazzo": dict(label="Terrazzo + tablet", bg=("speckle", (222, 220, 216)), fg=(24, 22, 20), accent=(24, 22, 20),
                     tag=((24, 22, 20), (255, 255, 255)), part=(24, 22, 20), frame="tablet", frame_c=(26, 24, 26), font="display",
                     cap=dict(style="pill", fg=(24, 22, 20), stroke=None, pill_fg=(255, 255, 255))),
    "editorial": dict(label="Editorial card", bg=("solid", (243, 235, 220)), fg=(40, 32, 24), accent=(176, 112, 64),
                      tag=((40, 32, 24), (255, 255, 255)), part=(40, 32, 24), frame="card", frame_c=(255, 255, 255), header=True,
                      font="serif", cap=dict(style="underline", fg=(40, 32, 24), stroke=None, pill_fg=(40, 32, 24))),
    "neon": dict(label="Neon night (monitor)", bg=("glow", (10, 8, 24), [((255, 0, 140), 0.25, 0.18, 520), ((0, 220, 255), 0.85, 0.62, 560)]),
                 fg=(255, 255, 255), accent=(0, 224, 255), tag=((0, 224, 255), (8, 8, 20)), part=(0, 224, 255), frame="monitor",
                 frame_c=(26, 24, 44), glow=(0, 224, 255), font="display", cap=dict(style="text", fg=(255, 255, 255), stroke=(8, 8, 20), pill_fg=(0, 224, 255))),
    "sunset": dict(label="Sunset (laptop)", bg=("gradient", (255, 140, 66), (214, 51, 132), 70), fg=(255, 255, 255),
                   accent=(255, 255, 255), tag=((255, 255, 255), (150, 30, 90)), part=(255, 255, 255), frame="laptop",
                   frame_c=(40, 20, 40), font="display", cap=dict(style="pill", fg=(255, 255, 255), stroke=(90, 20, 60), pill_fg=(150, 30, 90))),
    "mint": dict(label="Mint card", bg=("gradient", (214, 247, 236), (160, 222, 205), 90), fg=(10, 52, 44), accent=(14, 140, 110),
                 tag=((10, 52, 44), (255, 255, 255)), part=(10, 52, 44), frame="card", frame_c=(255, 255, 255), font="sans",
                 cap=dict(style="pill", fg=(10, 52, 44), stroke=None, pill_fg=(255, 255, 255))),
    "bold": dict(label="Bold yellow", bg=("solid", (255, 214, 10)), fg=(10, 10, 10), accent=(10, 10, 10),
                 tag=((10, 10, 10), (255, 214, 10)), part=(10, 10, 10), frame="brutal", frame_c=(10, 10, 10), font="display",
                 cap=dict(style="pill", fg=(10, 10, 10), stroke=None, pill_fg=(255, 214, 10))),
    "slate": dict(label="Slate grid (monitor)", bg=("grid", (38, 46, 62), (30, 37, 50)), fg=(236, 241, 250), accent=(255, 176, 46),
                  tag=((255, 176, 46), (24, 28, 38)), part=(236, 241, 250), frame="monitor", frame_c=(14, 17, 24), font="sans",
                  cap=dict(style="box", fg=(255, 255, 255), stroke=None, pill_fg=(255, 176, 46))),
    "photo": dict(label="Photo wallpaper (glass)", bg=("photo",), fg=(255, 255, 255), accent=(31, 111, 209),
                  tag=((14, 14, 18), (255, 255, 255)), part=(255, 255, 255), frame="glass", frame_c=(255, 255, 255), font="sans",
                  cap=dict(style="pill", fg=(255, 255, 255), stroke=(0, 0, 0), pill_fg=(255, 255, 255))),
}
ALIASES = {"light": "clean-light", "dark": "clean-dark", "clean": "clean-light", "laptop": "clean-light", "tablet": "terrazzo",
           "paper": "editorial", "card": "mint", "yellow": "bold", "grid": "slate", "wallpaper": "photo", "default": "clean-light"}
DEFAULT_TEMPLATE = "clean-light"
FRAMES = ("laptop", "tablet", "monitor", "card", "glass", "plain", "brutal")


def template_names():
    return list(TEMPLATES)


def get_template(name):
    n = (name or "").strip().lower().replace(" ", "-").replace("_", "-")
    n = ALIASES.get(n, n)
    return n if n in TEMPLATES else DEFAULT_TEMPLATE


# ------------------------------------------------------------------------------------------------------------------
# backgrounds
# ------------------------------------------------------------------------------------------------------------------
def _bgr(c):
    return (c[2], c[1], c[0])


def make_bg(spec, W, H, photo_loader=None):
    """-> BGR uint8 canvas"""
    import cv2
    kind = spec[0]
    if kind == "solid":
        return np.full((H, W, 3), _bgr(spec[1]), np.uint8)
    if kind == "gradient":
        a, b, ang = np.array(spec[1], np.float32), np.array(spec[2], np.float32), math.radians(spec[3])
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        t = ((xx - W / 2) * math.cos(ang) + (yy - H / 2) * math.sin(ang)) / (abs(W * math.cos(ang)) + abs(H * math.sin(ang)) + 1e-6) + 0.5
        t = np.clip(t, 0, 1)[..., None]
        return (a + (b - a) * t)[..., ::-1].astype(np.uint8)
    if kind == "speckle":                       # terrazzo: grey stone with tiny coloured chips (like the tablet reference)
        img = np.full((H, W, 3), _bgr(spec[1]), np.uint8)
        rng = np.random.default_rng(7)
        chips = [(70, 130, 180), (200, 160, 60), (60, 60, 60), (150, 150, 150), (200, 70, 60), (255, 255, 255)]
        for _ in range(int(W * H / 2600)):
            x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
            r = int(rng.integers(2, 9))
            c = chips[int(rng.integers(0, len(chips)))]
            pts = np.array([[x + rng.integers(-r, r + 1), y + rng.integers(-r, r + 1)] for _ in range(5)], np.int32)
            cv2.fillConvexPoly(img, cv2.convexHull(pts), _bgr(c), cv2.LINE_AA)
        return cv2.GaussianBlur(img, (0, 0), 0.7)
    if kind == "grid":
        img = np.full((H, W, 3), _bgr(spec[1]), np.uint8)
        c = _bgr(spec[2])
        for x in range(0, W, 60):
            img[:, x:x + 2] = c
        for y in range(0, H, 60):
            img[y:y + 2, :] = c
        return img
    if kind == "glow":
        img = np.full((H, W, 3), _bgr(spec[1]), np.float32)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        for col, fx, fy, rad in spec[2]:
            d = np.hypot(xx - fx * W, yy - fy * H) / rad
            img += (np.exp(-d * d * 1.6)[..., None] * np.array(_bgr(col), np.float32) * 0.55)
        return np.clip(img, 0, 255).astype(np.uint8)
    if kind == "photo":
        if photo_loader:
            im = photo_loader(W, H)
            if im is not None:
                return im
        return make_bg(("gradient", (66, 98, 160), (22, 30, 60), 80), W, H)
    return np.zeros((H, W, 3), np.uint8)


def rounded_alpha(iw, ih, radius):
    yy, xx = np.mgrid[0:ih, 0:iw].astype(np.float32)
    qx = np.abs(xx - iw / 2) - (iw / 2 - radius)
    qy = np.abs(yy - ih / 2) - (ih / 2 - radius)
    d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - radius
    return np.clip(0.5 - d, 0, 1)[..., None].astype(np.float32)


# ------------------------------------------------------------------------------------------------------------------
# device frames (drawn around the video window at x0,y0 of size iw x ih)
# ------------------------------------------------------------------------------------------------------------------
def _shadow(img, box, radius, strength=0.45, dy=26, blur=34):
    import cv2
    H, W = img.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in box]
    m = np.zeros((H, W), np.float32)
    a = rounded_alpha(x1 - x0, y1 - y0, radius)[..., 0]
    ys, ye = max(0, y0 + dy), min(H, y1 + dy)
    if ye > ys:
        m[ys:ye, x0:x1] = a[ys - (y0 + dy):ye - (y0 + dy), :]
    m = cv2.GaussianBlur(m, (0, 0), blur)[..., None]
    return (img.astype(np.float32) * (1 - strength * m)).astype(np.uint8)


def frame_metrics(T, win):
    """Radius of the video corners, and the footprint of the frame (for tests / layout)."""
    iw, ih = win[2], win[3]
    return {"laptop": 12, "tablet": 18, "monitor": 8, "card": 24, "glass": 26, "plain": 26, "brutal": 6}.get(T["frame"], 20)


def draw_frame(img, T, win, plan):
    """Draws shadow + frame on `img` (BGR ndarray) around the window rect. Returns the video-window corner radius."""
    from PIL import Image, ImageDraw
    x0, y0, iw, ih = win
    kind, fc = T["frame"], T.get("frame_c", (20, 20, 20))
    radius = frame_metrics(T, win)
    if kind == "laptop":
        b = 16
        box = (x0 - b, y0 - b, x0 + iw + b, y0 + ih + b)
        img[:] = _shadow(img, box, 30)
        pil = Image.fromarray(img[..., ::-1])
        d = ImageDraw.Draw(pil)
        d.rounded_rectangle(box, radius=30, fill=fc)
        d.ellipse((x0 + iw / 2 - 4, y0 - b / 2 - 4, x0 + iw / 2 + 4, y0 - b / 2 + 4), fill=tuple(min(255, c + 40) for c in fc))
        by0 = y0 + ih + b
        base = (x0 - b - 26, by0 - 2, x0 + iw + b + 26, by0 + 22)
        d.rounded_rectangle(base, radius=11, fill=(228, 229, 232))
        d.rounded_rectangle((x0 + iw / 2 - 80, by0 - 2, x0 + iw / 2 + 80, by0 + 8), radius=5, fill=(196, 198, 204))
        img[:] = np.array(pil)[..., ::-1]
    elif kind == "tablet":
        b = 38
        box = (x0 - b, y0 - b, x0 + iw + b, y0 + ih + b)
        img[:] = _shadow(img, box, 54, 0.5)
        pil = Image.fromarray(img[..., ::-1])
        d = ImageDraw.Draw(pil)
        d.rounded_rectangle(box, radius=54, fill=(214, 212, 210))
        d.rounded_rectangle((box[0] + 5, box[1] + 5, box[2] - 5, box[3] - 5), radius=50, fill=fc)
        d.ellipse((box[2] - 20, y0 + ih / 2 - 4, box[2] - 12, y0 + ih / 2 + 4), fill=(60, 60, 66))
        img[:] = np.array(pil)[..., ::-1]
    elif kind == "monitor":
        b, chin = 16, 44
        box = (x0 - b, y0 - b, x0 + iw + b, y0 + ih + chin)
        img[:] = _shadow(img, box, 22, 0.5)
        pil = Image.fromarray(img[..., ::-1])
        d = ImageDraw.Draw(pil)
        glow = T.get("glow")
        if glow:
            d.rounded_rectangle((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), radius=26, outline=glow, width=4)
        d.rounded_rectangle(box, radius=22, fill=fc)
        cx, nb = x0 + iw / 2, y0 + ih + chin
        d.polygon([(cx - 36, nb - 2), (cx + 36, nb - 2), (cx + 54, nb + 104), (cx - 54, nb + 104)], fill=tuple(min(255, c + 36) for c in fc))
        d.rounded_rectangle((cx - 170, nb + 100, cx + 170, nb + 124), radius=12, fill=tuple(min(255, c + 52) for c in fc))
        img[:] = np.array(pil)[..., ::-1]
    elif kind == "card":
        pad = 22
        head = 70 if T.get("header") else 0
        box = (x0 - pad, y0 - pad - head, x0 + iw + pad, y0 + ih + pad)
        img[:] = _shadow(img, box, 34, 0.30, dy=20, blur=28)
        pil = Image.fromarray(img[..., ::-1])
        d = ImageDraw.Draw(pil)
        d.rounded_rectangle(box, radius=34, fill=fc)
        if head:
            tag = str(plan.get("tag") or "").strip() or "Quick tips"
            part = str(plan.get("part") or "").strip()
            f = font("sans", 26, tag)
            d.text((box[0] + 30, box[1] + head / 2 + 2), tag.upper(), font=f, fill=T["fg"], anchor="lm")
            if part:
                d.text((box[2] - 30, box[1] + head / 2 + 2), (f"PART {part}" if re.fullmatch(r"\d+", part) else part.upper()), font=f,
                       fill=T["fg"], anchor="rm")
            d.line((box[0] + 24, box[1] + head, box[2] - 24, box[1] + head), fill=(220, 214, 204), width=2)
        img[:] = np.array(pil)[..., ::-1]
    elif kind == "glass":
        box = (x0 - 12, y0 - 12, x0 + iw + 12, y0 + ih + 12)
        img[:] = _shadow(img, box, 36, 0.5)
        pil = Image.fromarray(img[..., ::-1]).convert("RGBA")
        ov = Image.new("RGBA", pil.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        d.rounded_rectangle(box, radius=38, fill=(255, 255, 255, 70), outline=(255, 255, 255, 190), width=3)
        img[:] = np.array(Image.alpha_composite(pil, ov).convert("RGB"))[..., ::-1]
    elif kind == "brutal":
        o = 18
        pil = Image.fromarray(img[..., ::-1])
        d = ImageDraw.Draw(pil)
        d.rounded_rectangle((x0 - 10 + o, y0 - 10 + o, x0 + iw + 10 + o, y0 + ih + 10 + o), radius=14, fill=fc)
        d.rounded_rectangle((x0 - 10, y0 - 10, x0 + iw + 10, y0 + ih + 10), radius=14, fill=(255, 255, 255), outline=fc, width=8)
        img[:] = np.array(pil)[..., ::-1]
    else:                                       # plain rounded window with a soft shadow
        img[:] = _shadow(img, (x0, y0, x0 + iw, y0 + ih), 26, 0.55, dy=22, blur=32)
    return radius


# ------------------------------------------------------------------------------------------------------------------
# badges + title + the whole base layer
# ------------------------------------------------------------------------------------------------------------------
def _fit_title(d, title, kind, W, avail, maxlines=3):
    size = int(W * 0.115)
    while size > int(W * 0.045):
        f = font(kind, size, title)
        words = title.split()
        lines, cur = [], []
        for w in words:
            t = " ".join(cur + [w])
            if cur and d.textlength(t, font=f) > W * 0.88:
                lines.append(cur)
                cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
        if len(lines) <= maxlines and len(lines) * size * 1.14 <= avail and all(d.textlength(" ".join(l), font=f) <= W * 0.9 for l in lines):
            return f, size, [" ".join(l) for l in lines]
        size -= 4
    f = font(kind, size, title)
    return f, size, [title]


def render_base(plan, template, W, H, win, photo_loader=None, frame=None):
    """-> (base BGR (H,W,3), alpha (ih,iw,1) for the video window). `frame` overrides the template's device frame."""
    from PIL import Image, ImageDraw
    T = dict(TEMPLATES[get_template(template)])
    if frame in FRAMES:
        T["frame"] = frame
        if frame == "card":
            T["frame_c"] = (255, 255, 255)
    x0, y0, iw, ih = win
    img = make_bg(T["bg"], W, H, photo_loader)
    radius = draw_frame(img, T, win, plan)
    alpha = rounded_alpha(iw, ih, radius)
    pil = Image.fromarray(img[..., ::-1])
    d = ImageDraw.Draw(pil)
    fg = T["fg"]
    title = " ".join(str(plan.get("title") or "").split())
    tag, part = str(plan.get("tag") or "").strip(), str(plan.get("part") or "").strip()
    head = T["frame"] == "card" and T.get("header")
    badges = [] if head else ([("tag", tag.upper())] if tag else []) + ([("part", f"PART {part}" if re.fullmatch(r"\d+", part) else part.upper())] if part else [])
    y = int(H * 0.075)
    bh = int(W * 0.068)
    if badges:
        bf = font("sans", int(W * 0.033), tag + part)
        pad, gap = int(W * 0.026), int(W * 0.02)
        widths = [d.textlength(t, font=bf) + 2 * pad + (int(W * 0.03) if k == "tag" else 0) for k, t in badges]
        x = (W - (sum(widths) + gap * (len(badges) - 1))) / 2
        for (k, t), w in zip(badges, widths):
            if k == "tag":
                bgc, tc = T["tag"]
                d.rounded_rectangle((x, y, x + w, y + bh), radius=bh // 2, fill=bgc)
                cy = y + bh // 2
                d.ellipse((x + pad * 0.8, cy - 8, x + pad * 0.8 + 16, cy + 8), fill=T["accent"] if T["accent"] != bgc else tc)
                d.text((x + pad + int(W * 0.03), cy), t, font=bf, fill=tc, anchor="lm")
            else:
                d.rounded_rectangle((x, y, x + w, y + bh), radius=bh // 2, outline=T["part"], width=3)
                d.text((x + w / 2, y + bh // 2), t, font=bf, fill=T["part"], anchor="mm")
            x += w + gap
    if title:
        top = y + (bh + int(H * 0.03) if badges else int(H * 0.04)) if not head else int(H * 0.09)
        frame_top = y0 - (110 if head else 40)
        avail = max(120, frame_top - int(H * 0.025) - top)
        f, size, lines = _fit_title(d, title, T["font"], W, avail)
        ty = top + max(0, (avail - len(lines) * size * 1.14) / 2)
        for ln in lines:
            d.text((W / 2, ty), ln, font=f, fill=fg, anchor="ma")
            ty += size * 1.14
    return np.array(pil)[..., ::-1].copy(), alpha


# ------------------------------------------------------------------------------------------------------------------
# ONE-LINE subtitles
# ------------------------------------------------------------------------------------------------------------------
def line_width(texts, size, style="pill"):
    """Pixel width of `texts` laid out on one line (spaces + the pill padding between words)."""
    from PIL import Image, ImageDraw
    f = font("sans", size, " ".join(texts))
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    sp = probe.textlength(" ", font=f)
    padx = int(size * 0.22)
    gap = sp + (2 * padx if style in ("pill", "box") else 0)
    return sum(probe.textlength(t, font=f) for t in texts) + gap * max(0, len(texts) - 1) + 2 * padx + 8


def split_pages(words, t0, atempo, per, fits):
    """Words of one scene -> pages that are ALWAYS one line.
    words: [(word, start, dur)] in the voice's own time;  fits(list_of_word_strings) -> bool (one line wide enough).
    A page ends at `per` words, at a sentence/phrase end, or when the next word would not fit on the line.
    Every word is kept, in order; no page is empty."""
    toks = [(w, t0 + s / atempo, t0 + (s + d) / atempo) for w, s, d in words if str(w).strip()]
    pages, cur = [], []
    for tok in toks:
        trial = cur + [tok]
        if cur and (len(trial) > per or not fits([x[0] for x in trial])):
            pages.append(cur)
            cur = [tok]
        else:
            cur = trial
        if re.search(r"[.!?,;:]$", tok[0]):
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    # a lone short last word (e.g. "it.") joins the previous page only if the line still fits
    merged = []
    for p in pages:
        if merged and len(p) == 1 and len(merged[-1]) < per and fits([x[0] for x in merged[-1] + p]) \
                and not re.search(r"[.!?]$", merged[-1][-1][0]):
            merged[-1] = merged[-1] + p
        else:
            merged.append(p)
    out = []
    for i, p in enumerate(merged):
        end = p[-1][2] + 0.18
        if i + 1 < len(merged):
            end = min(end, merged[i + 1][0][1])
        out.append({"words": p, "t0": p[0][1] - 0.04, "t1": max(end, p[-1][2])})
    return out


def render_caption(texts, active, size, max_w, style="pill", cs=None, accent=(31, 111, 209)):
    """One subtitle page, ONE line, as (bgr, alpha). Font shrinks if a single long word would still overflow."""
    from PIL import Image, ImageDraw
    cs = cs or {}
    fg, stroke, pill_fg = cs.get("fg", (255, 255, 255)), cs.get("stroke", (0, 0, 0)), cs.get("pill_fg", (255, 255, 255))
    while size > 24 and line_width(texts, size, style) > max_w:
        size = int(size * 0.92)
    f = font("sans", size, " ".join(texts))
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    sp = probe.textlength(" ", font=f)
    wid = [probe.textlength(t, font=f) for t in texts]
    padx, line_h = int(size * 0.22), int(size * 1.38)
    gap = sp + (2 * padx if style in ("pill", "box") else 0)
    total = sum(wid) + gap * (len(texts) - 1)
    Wi, Hi = int(total + 2 * padx + 8), int(line_h + 8)
    img = Image.new("RGBA", (Wi, Hi), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    yc = 4 + line_h / 2
    x = (Wi - total) / 2
    sw = max(3, size // 13) if stroke else 0
    if style == "box":
        d.rounded_rectangle((x - padx * 1.4, yc - line_h * 0.46, x + total + padx * 1.4, yc + line_h * 0.46), radius=int(line_h * 0.3), fill=(12, 14, 20, 215))
    for i, t in enumerate(texts):
        on = i == active
        if style in ("pill",) and on:
            d.rounded_rectangle((x - padx, yc - line_h * 0.44, x + wid[i] + padx, yc + line_h * 0.44), radius=int(line_h * 0.3), fill=tuple(accent) + (255,))
            d.text((x, yc), t, font=f, fill=tuple(pill_fg) + (255,), anchor="lm")
        elif style == "box":
            d.text((x, yc), t, font=f, fill=(tuple(accent) if on else tuple(fg)) + (255,), anchor="lm")
        elif style == "text":
            d.text((x, yc), t, font=f, fill=(tuple(accent) if on else tuple(fg)) + (255,), anchor="lm",
                   stroke_width=sw, stroke_fill=(tuple(stroke) + (255,)) if stroke else None)
        elif style == "underline":
            d.text((x, yc), t, font=f, fill=tuple(fg) + (255,), anchor="lm")
            if on:
                d.rounded_rectangle((x, yc + line_h * 0.30, x + wid[i], yc + line_h * 0.30 + max(6, size // 9)), radius=4, fill=tuple(accent) + (255,))
        else:
            d.text((x, yc), t, font=f, fill=tuple(fg) + (255,), anchor="lm",
                   stroke_width=sw, stroke_fill=(tuple(stroke) + (255,)) if stroke else None)
        x += wid[i] + gap
    arr = np.array(img)
    return arr[..., 2::-1].copy(), arr[..., 3:4].astype(np.float32) / 255.0


def caption_style_for(template, override=None):
    T = TEMPLATES[get_template(template)]
    cs = dict(T["cap"])
    if override in ("pill", "box", "text", "underline"):
        cs["style"] = override
    return cs["style"], cs, T["accent"]


# ------------------------------------------------------------------------------------------------------------------
# a generated "photo" for the [upload ...] action when the user did not send one
# ------------------------------------------------------------------------------------------------------------------
def sample_photo(path, w=1200, h=800):
    import cv2
    path = Path(path)
    if path.exists():
        return path
    rng = np.random.default_rng(int(hashlib.md5(path.name.encode()).hexdigest()[:6], 16))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = (yy / h)[..., None]
    sky = np.array([250, 170, 90], np.float32) * (1 - t) + np.array([60, 40, 120], np.float32) * t       # BGR dusk
    img = np.broadcast_to(sky, (h, w, 3)).copy()
    sun = np.hypot(xx - w * 0.68, yy - h * 0.42)
    img += (np.exp(-(sun / 140) ** 2)[..., None] * np.array([120, 200, 255], np.float32))
    for k, (base, col) in enumerate([(0.62, (70, 50, 90)), (0.72, (50, 36, 70)), (0.84, (30, 24, 48))]):
        ridge = base * h + 38 * np.sin(xx[0] / (110 + 40 * k) + rng.uniform(0, 6)) + 20 * np.sin(xx[0] / (37 + 9 * k) + rng.uniform(0, 6))
        mask = (yy >= ridge[None, :]).astype(np.float32)[..., None]
        img = img * (1 - mask) + np.array(col, np.float32) * mask
    img += rng.normal(0, 3, img.shape)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.clip(img, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return path


# ------------------------------------------------------------------------------------------------------------------
# preview sheet
# ------------------------------------------------------------------------------------------------------------------
def preview(out_png, W=540, H=960, names=None):
    import cv2
    sc = W / 1080.0
    names = names or template_names()
    sample_words = [("Change", 0, .3), ("these", .3, .3), ("four", .6, .3), ("settings", .9, .4)]
    tiles = []
    for n in names:
        plan = {"title": "New Windows PC?", "tag": "Windows Tips", "part": "1"}
        w_, h_ = 960, 640
        win = ((1080 - w_) // 2, int(1920 * 0.335), w_, h_)
        base, alpha = render_base(plan, n, 1080, 1920, win)
        shot = np.full((h_, w_, 3), (246, 232, 214), np.uint8)
        cv2.rectangle(shot, (0, 0), (w_, 60), (236, 224, 206), -1)
        cv2.putText(shot, "demo screen", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (90, 70, 50), 3, cv2.LINE_AA)
        roi = base[win[1]:win[1] + h_, win[0]:win[0] + w_]
        roi[:] = (shot * alpha + roi * (1 - alpha)).astype(np.uint8)
        style, cs, acc = caption_style_for(n)
        texts = [w[0] for w in sample_words]
        bgr, al = render_caption(texts, 3, int(1080 * 0.076), int(1080 * 0.9), style, cs, acc)
        h2, w2 = bgr.shape[:2]
        cx, cy = (1080 - w2) // 2, int(1920 * 0.80) - h2 // 2
        r = base[cy:cy + h2, cx:cx + w2]
        r[:] = (bgr * al + r * (1 - al)).astype(np.uint8)
        small = cv2.resize(base, (W, H), interpolation=cv2.INTER_AREA)
        cv2.putText(small, n, (14, H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(small, n, (14, H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(small)
    cols = 5
    rows = [np.hstack(tiles[i:i + cols] + [np.zeros_like(tiles[0])] * (cols - len(tiles[i:i + cols]))) for i in range(0, len(tiles), cols)]
    cv2.imwrite(str(out_png), np.vstack(rows))
    return out_png


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "preview":
        print(preview(sys.argv[2]))
    else:
        print(__doc__)
