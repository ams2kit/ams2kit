"""Drive a windowed AMS2: screenshots, mouse clicks and keys (scan codes, which the game reads).

  python game_harness.py shot <out.png>          client-area screenshot
  python game_harness.py click <x> <y>           left click at client coords (1920x1080 frame)
  python game_harness.py key <name> [hold_ms]    press a key: esc, enter, up, down, left, right, space, a..z, f1..f12
  python game_harness.py hold <name> <ms>        same as key with a hold time
  python game_harness.py status                  window rect and process state
"""
import ctypes, ctypes.wintypes as wt, sys, time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDPIAware()
EXE = "AMS2AVX.exe"

SCAN = {"esc": 0x01, "enter": 0x1C, "space": 0x39, "tab": 0x0F, "backspace": 0x0E,
        "up": (0x48, True), "down": (0x50, True), "left": (0x4B, True), "right": (0x4D, True),
        "pageup": (0x49, True), "pagedown": (0x51, True), "lshift": 0x2A, "lctrl": 0x1D}
SCAN.update({c: s for c, s in zip("1234567890", range(0x02, 0x0C))})
SCAN.update({c: s for c, s in zip("qwertyuiop", range(0x10, 0x1A))})
SCAN.update({c: s for c, s in zip("asdfghjkl", range(0x1E, 0x27))})
SCAN.update({c: s for c, s in zip("zxcvbnm", range(0x2C, 0x33))})
SCAN.update({f"f{i}": 0x3A + i for i in range(1, 11)})


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def game_pids():
    import subprocess
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return [int(l.split('","')[1]) for l in out.splitlines() if l.startswith(f'"{EXE}"')]


def game_window():
    pids, found = set(game_pids()), []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            r = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            if r.right > 200:
                found.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def client_origin(hwnd):
    p, r = wt.POINT(0, 0), wt.RECT()
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return p.x, p.y, r.right, r.bottom


def focus(hwnd):
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    send(INPUT(type=1, ki=KEYBDINPUT(0, 0x38, 0x8, 0, 0)), INPUT(type=1, ki=KEYBDINPUT(0, 0x38, 0xA, 0, 0)))  # alt tap unlocks SetForegroundWindow
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)


def shot(path):
    from PIL import ImageGrab
    hwnd = game_window()
    focus(hwnd)
    x, y, w, h = client_origin(hwnd)
    ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save(path)
    return w, h


def click(cx, cy):
    hwnd = game_window()
    focus(hwnd)
    x, y, w, h = client_origin(hwnd)
    sx, sy = x + int(cx * w / 1920), y + int(cy * h / 1080)
    user32.SetCursorPos(sx, sy)
    time.sleep(0.08)
    send(INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0001, 0, 0)))  # tiny move so the game sees the cursor
    time.sleep(0.05)
    send(INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0002, 0, 0)))
    time.sleep(0.06)
    send(INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0004, 0, 0)))


def key_events(name, up):
    s = SCAN[name.lower()]
    ext = isinstance(s, tuple)
    code = s[0] if ext else s
    flags = 0x8 | (0x1 if ext else 0) | (0x2 if up else 0)
    return INPUT(type=1, ki=KEYBDINPUT(0, code, flags, 0, 0))


def key(name, hold_ms=60, refocus=True):
    if refocus:
        focus(game_window())
    send(key_events(name, False))
    time.sleep(hold_ms / 1000)
    send(key_events(name, True))


def main(argv):
    cmd = argv[0]
    if cmd == "status":
        hwnd = game_window()
        print("pids", game_pids(), "hwnd", hwnd, "client", hwnd and client_origin(hwnd))
    elif cmd == "shot":
        print(shot(argv[1]))
    elif cmd == "click":
        click(float(argv[1]), float(argv[2]))
    elif cmd in ("key", "hold"):
        key(argv[1], int(argv[2]) if len(argv) > 2 else 60)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
