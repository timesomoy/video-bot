"""
xinput_linux.py - real mouse / keyboard / pointer telemetry on an X11 display, with ctypes only
(no pyautogui, no python-xlib needed on Linux).

It talks to the X server through libX11 + libXtst (the XTEST extension). To the browser these are
ordinary hardware-level input events, not browser-internal ones. Works on a real desktop and on Xvfb.
"""
import ctypes
import ctypes.util
import os
import time

_x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
_xtst = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")

_x11.XOpenDisplay.restype = ctypes.c_void_p
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XDefaultRootWindow.restype = ctypes.c_ulong
_x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
_x11.XFlush.argtypes = [ctypes.c_void_p]
_x11.XStringToKeysym.restype = ctypes.c_ulong
_x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
_x11.XKeysymToKeycode.restype = ctypes.c_ubyte
_x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_x11.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                               ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                               ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                               ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint)]
_x11.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
_x11.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
_xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
_xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
_xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]

_SPECIAL = {"\n": "Return", "\t": "Tab", " ": "space", "!": "exclam", '"': "quotedbl", "#": "numbersign",
            "$": "dollar", "%": "percent", "&": "ampersand", "'": "apostrophe", "(": "parenleft",
            ")": "parenright", "*": "asterisk", "+": "plus", ",": "comma", "-": "minus", ".": "period",
            "/": "slash", ":": "colon", ";": "semicolon", "<": "less", "=": "equal", ">": "greater",
            "?": "question", "@": "at", "[": "bracketleft", "\\": "backslash", "]": "bracketright",
            "^": "asciicircum", "_": "underscore", "`": "grave", "{": "braceleft", "|": "bar",
            "}": "braceright", "~": "asciitilde"}
_SHIFTED = set('!"#$%&()*+:<>?@^_{|}~' + "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_KEYS = {"enter": "Return", "return": "Return", "tab": "Tab", "esc": "Escape", "escape": "Escape",
         "pagedown": "Next", "pageup": "Prior", "ctrl": "Control_L", "shift": "Shift_L", "alt": "Alt_L",
         "backspace": "BackSpace", "down": "Down", "up": "Up", "left": "Left", "right": "Right",
         "end": "End", "home": "Home", "space": "space", "=": "equal", "-": "minus"}


class XDisplay:
    def __init__(self, name=None):
        name = name or os.environ.get("DISPLAY") or ":0"
        self.dpy = _x11.XOpenDisplay(name.encode())
        if not self.dpy:
            raise RuntimeError(f"Cannot open the X display {name!r}. Is Xvfb / the desktop running and DISPLAY set?")
        self.root = _x11.XDefaultRootWindow(self.dpy)
        self.width, self.height = _x11.XDisplayWidth(self.dpy, 0), _x11.XDisplayHeight(self.dpy, 0)

    # -- pointer ---------------------------------------------------------------------------------------------
    def position(self):
        """(x, y, left_button_down) of the real pointer."""
        r, c = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy, mask = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_uint()
        _x11.XQueryPointer(self.dpy, self.root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx),
                           ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask))
        return rx.value, ry.value, bool(mask.value & 0x100)

    def move_to(self, x, y):
        _xtst.XTestFakeMotionEvent(self.dpy, -1, int(round(x)), int(round(y)), 0)
        _x11.XFlush(self.dpy)

    def move_rel(self, dx, dy):
        x, y, _ = self.position()
        self.move_to(x + dx, y + dy)

    def button(self, n, down):
        _xtst.XTestFakeButtonEvent(self.dpy, n, 1 if down else 0, 0)
        _x11.XFlush(self.dpy)

    def click(self, n=1):
        self.button(n, True)
        time.sleep(0.06)
        self.button(n, False)

    def wheel(self, notches):
        """positive = scroll up (like pyautogui), negative = down. X buttons 4 (up) / 5 (down)."""
        b = 4 if notches > 0 else 5
        for _ in range(abs(int(notches))):
            self.button(b, True)
            self.button(b, False)
            time.sleep(0.012)

    # -- keyboard --------------------------------------------------------------------------------------------
    def _code(self, name):
        sym = _x11.XStringToKeysym(name.encode())
        return _x11.XKeysymToKeycode(self.dpy, sym) if sym else 0

    def key(self, name, down):
        code = self._code(_KEYS.get(name.lower(), name))
        if code:
            _xtst.XTestFakeKeyEvent(self.dpy, code, 1 if down else 0, 0)
            _x11.XFlush(self.dpy)
        return bool(code)

    def press(self, name):
        if self.key(name, True):
            time.sleep(0.03)
            self.key(name, False)

    def hotkey(self, *names):
        for n in names:
            self.key(n, True)
            time.sleep(0.03)
        for n in reversed(names):
            self.key(n, False)
            time.sleep(0.03)

    def type_char(self, ch):
        code = self._code(_SPECIAL.get(ch, ch))
        if not code:
            return False
        shifted = ch in _SHIFTED
        if shifted:
            self.key("shift", True)
        _xtst.XTestFakeKeyEvent(self.dpy, code, 1, 0)
        _xtst.XTestFakeKeyEvent(self.dpy, code, 0, 0)
        if shifted:
            self.key("shift", False)
        _x11.XFlush(self.dpy)
        return True


class PG:
    """The small slice of the pyautogui API that autovideo.py uses, backed by XDisplay (Linux)."""
    PAUSE = 0
    FAILSAFE = False

    def __init__(self):
        self.d = XDisplay()

    def moveTo(self, x, y):
        self.d.move_to(x, y)

    def moveRel(self, dx, dy):
        self.d.move_rel(dx, dy)

    def position(self):
        x, y, _ = self.d.position()
        return x, y

    def click(self):
        self.d.click()

    def mouseDown(self):
        self.d.button(1, True)

    def mouseUp(self):
        self.d.button(1, False)

    def scroll(self, notches):
        self.d.wheel(notches)

    def press(self, name):
        self.d.press(name)

    def hotkey(self, *names):
        self.d.hotkey(*names)

    def write(self, text, interval=0):
        for ch in text:
            self.d.type_char(ch)
            if interval:
                time.sleep(interval)

    def typewrite(self, text, interval=0):
        self.write(text, interval)

    def size(self):
        return self.d.width, self.d.height


if __name__ == "__main__":
    d = XDisplay()
    print("display", d.width, d.height, "pointer", d.position())
    d.move_to(100, 120)
    time.sleep(0.1)
    print("after move", d.position())
