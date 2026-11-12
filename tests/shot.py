"""Helper di test: salva uno screenshot della finestra "Music Studio for ACE-Step" (PrintWindow). Uso: python tests/shot.py out.png"""

import ctypes
import sys
from ctypes import wintypes

from PIL import Image

ctypes.windll.shcore.SetProcessDpiAwareness(2)  # coordinate fisiche, niente ritaglio

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from win import windows  # noqa: E402

u32, g32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
w = windows()[0]
x, y, cw, ch = w["rect"]
hdc = u32.GetWindowDC(w["hwnd"])
mdc = g32.CreateCompatibleDC(hdc)
bmp = g32.CreateCompatibleBitmap(hdc, cw, ch)
g32.SelectObject(mdc, bmp)
u32.PrintWindow(w["hwnd"], mdc, 2)  # PW_RENDERFULLCONTENT


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("a", ctypes.c_long), ("b", ctypes.c_long),
                ("c", wintypes.DWORD), ("d", wintypes.DWORD)]


bih = BIH(ctypes.sizeof(BIH), cw, -ch, 1, 32, 0, 0, 0, 0, 0, 0)
buf = ctypes.create_string_buffer(cw * ch * 4)
g32.GetDIBits(mdc, bmp, 0, ch, buf, ctypes.byref(bih), 0)
Image.frombuffer("RGBA", (cw, ch), buf, "raw", "BGRA", 0, 1).convert("RGB").save(sys.argv[1])
print("salvato", sys.argv[1], (cw, ch))
