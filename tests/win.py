"""Helper di test per le finestre: python tests/win.py close|info|foreground [titolo]"""

import ctypes
import sys
from ctypes import wintypes

u32 = ctypes.WinDLL("user32")


def windows(title="Music Studio for ACE-Step"):
    found = []
    Enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        b = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(h, b, 256)
        c = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(h, c, 256)
        if b.value == title and c.value.startswith("WindowsForms"):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            r = wintypes.RECT()
            u32.GetWindowRect(h, ctypes.byref(r))
            found.append({"hwnd": h, "pid": pid.value, "visible": bool(u32.IsWindowVisible(h)),
                          "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top)})
        return True

    u32.EnumWindows(Enum(cb), 0)
    return found


if __name__ == "__main__":
    cmd = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "Music Studio for ACE-Step"
    ws = windows(title)
    if cmd == "info":
        fg = u32.GetForegroundWindow()
        print({"windows": ws, "foreground": fg, "foreground_is_app": any(w["hwnd"] == fg for w in ws)})
    elif cmd == "close":
        for w in ws:
            u32.PostMessageW(w["hwnd"], 0x0010, 0, 0)  # WM_CLOSE, come la X della finestra
        print("chiuse", len(ws))
    elif cmd == "click":  # python tests/win.py click <title> x y  (pixel fisici relativi alla finestra)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        w = windows(title)[0]
        r = wintypes.RECT()
        u32.GetWindowRect(w["hwnd"], ctypes.byref(r))
        if "nofg" not in sys.argv:  # nofg: keep an open dropdown menu open
            u32.SetForegroundWindow(w["hwnd"])
        u32.SetCursorPos(r.left + int(sys.argv[3]), r.top + int(sys.argv[4]))
        u32.mouse_event(2, 0, 0, 0, 0)
        u32.mouse_event(4, 0, 0, 0, 0)
        print("clic", sys.argv[3], sys.argv[4])
    elif cmd == "minimize":
        for w in ws:
            u32.ShowWindow(w["hwnd"], 6)
        print("minimizzate", len(ws))
