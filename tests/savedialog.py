"""Helper di test: compila e conferma il dialogo "Salva con nome" aperto dall'app.
Uso: python tests/savedialog.py <percorso file di destinazione>"""

import ctypes
import sys
import time
from ctypes import wintypes

u32 = ctypes.WinDLL("user32")
u32.FindWindowExW.restype = wintypes.HWND
u32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPVOID]
u32.GetDlgItem.restype = wintypes.HWND


def find_dialog():
    found = []
    Enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        c = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, c, 64)
        if c.value == "#32770" and u32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, t, 256)
            found.append((h, t.value))
        return True

    u32.EnumWindows(Enum(cb), 0)
    return found


target = sys.argv[1]
for _ in range(40):
    dlgs = find_dialog()
    if dlgs:
        break
    time.sleep(0.5)
print("dialoghi:", [t for _, t in dlgs])
dlg = dlgs[0][0]
cbex = u32.FindWindowExW(dlg, None, "DUIViewWndClassName", None)
# il campo nome file è un Edit dentro ComboBoxEx32 (id 1148/1001): cerchiamolo ricorsivamente
edits = []
Enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def cb(h, _):
    c = ctypes.create_unicode_buffer(64)
    u32.GetClassNameW(h, c, 64)
    if c.value == "Edit":
        p = u32.GetParent(h)
        pc = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(p, pc, 64)
        edits.append((h, pc.value))
    return True


u32.EnumChildWindows(dlg, Enum(cb), 0)
edit = next(h for h, pc in edits if pc == "ComboBox")
u32.SendMessageW(edit, 0x000C, 0, ctypes.c_wchar_p(target))  # WM_SETTEXT
time.sleep(0.3)
u32.SendMessageW(dlg, 0x0111, 1, None)  # WM_COMMAND IDOK = Salva
print("confermato:", target)
