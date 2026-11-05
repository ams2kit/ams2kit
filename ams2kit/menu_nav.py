"""Drive the game's menus by reading them: capture the game window, OCR it (Windows' built-in engine,
ocr.ps1), wait until the wanted label is on screen, click it. No fixed coordinates, no blind waits.

The game draws its menus itself (its window has no UI Automation tree), and Windows OCR misses text on
the colourful menu backgrounds unless the capture is converted to grayscale first.

    from ams2kit import menu_nav
    menu_nav.showroom(out_dir, "jetta")      # main menu -> Single Race -> vehicle -> Showroom, screenshots
"""
import json, os, subprocess, tempfile, time
from pathlib import Path

from . import game, game_harness as gh

OCR_SCRIPT = Path(__file__).with_name("ocr.ps1")
FRAME = (1920, 1080)          # game_harness.click() takes coordinates in this frame


class MenuError(RuntimeError):
    pass


class CarMismatch(MenuError):
    """The menus show another car than the one asked for (the profile's current car)."""


def capture():
    """(PIL image, client width, client height) of the game window, or None when it isn't in front."""
    from PIL import ImageGrab
    hwnd = gh.game_window()
    if not hwnd:
        return None
    gh.focus(hwnd)
    if gh.user32.GetForegroundWindow() != hwnd:
        return None
    x, y, w, h = gh.client_origin(hwnd)
    return ImageGrab.grab((x, y, x + w, y + h), all_screens=True), w, h


def ocr(img):
    """[{text, x, y, w, h}] text lines in a PIL image (grayscale first: colour menus defeat the engine)."""
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        img.convert("L").save(tmp)
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(OCR_SCRIPT), tmp],
                             capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    finally:
        os.unlink(tmp)
    return [json.loads(l, strict=False) for l in out.splitlines() if l.startswith("{")]


def _norm(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


def find(lines, label, where=None):
    """Lines whose text contains `label` (case/space/punctuation-insensitive); `where(line)` filters by position."""
    want = _norm(label)
    return [l for l in lines if want in _norm(l["text"]) and (where is None or where(l))]


def wait_for(labels, timeout=60, where=None, poll=1.0, log=None):
    """Wait until any of `labels` is on screen. Returns (label, line, lines, size)."""
    labels = [labels] if isinstance(labels, str) else list(labels)
    t0, last = time.time(), []
    while time.time() - t0 < timeout:
        if not gh.game_pids():
            raise MenuError("the game exited")
        cap = capture()
        if cap:
            img, w, h = cap
            last = ocr(img)
            for lab in labels:
                hits = find(last, lab, where)
                if hits:
                    return lab, hits[0], last, (w, h)
        time.sleep(poll)
    raise MenuError(f"none of {labels} appeared within {timeout:.0f} s; last screen read: {[l['text'] for l in last][:20]}")


def click_line(line, size):
    w, h = size
    cx, cy = line["x"] + line["w"] / 2, line["y"] + line["h"] / 2
    gh.click(cx * FRAME[0] / w, cy * FRAME[1] / h)


def click_label(label, timeout=30, where=None, log=print):
    lab, line, _, size = wait_for(label, timeout, where)
    if log:
        log(f"menu: click {line['text']!r}")
    click_line(line, size)
    return line


def settle(path, timeout=20, threshold=1.5):
    """Wait until two captures a second apart differ by less than `threshold` (mean abs, 0-255), then save."""
    import numpy as np
    prev, t0 = None, time.time()
    while time.time() - t0 < timeout:
        cap = capture()
        if cap:
            a = np.asarray(cap[0].convert("L"), dtype=np.float32)
            if prev is not None and float(np.abs(a - prev).mean()) < threshold:
                cap[0].save(path)
                return True
            prev = a
        time.sleep(1.0)
    if cap:
        cap[0].save(path)
    return False


def orbit_frames(out_dir, name, frames=8, interval=3.0):
    """The showroom camera orbits the car: save `frames` captures `interval` s apart (<name>_orbit_NN.png)."""
    paths = []
    for i in range(frames):
        t0 = time.time()
        cap = capture()
        if cap:
            p = Path(out_dir) / f"{name}_orbit_{i:02d}.png"
            cap[0].save(p)
            paths.append(str(p))
        time.sleep(max(0.0, interval - (time.time() - t0)))
    return paths


def showroom(out_dir, name, car=None, gamedir=None, log=print, boot_timeout=240, frames=8, interval=3.0):
    """Main menu -> Single Race -> vehicle panel -> Select Vehicle -> Showroom. Saves <name>_{event,select,
    showroom}.png and `frames` orbit captures in out_dir. Shows the profile's current car (`car` only checks it).
    Starts and closes its own game instance; refuses if the game is already running."""
    from . import testing
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if gh.game_pids():
        raise MenuError("AMS2 is already running: close it first (the menu test never touches a running game)")
    testing.launch(Path(gamedir or game.find_game()), testing.MENU_ARGS)
    res = {}
    try:
        click_label("SINGLE RACE", timeout=boot_timeout, log=log)
        # Custom Event: the vehicle panel shows the car's name under the "Custom Event" title
        _, title, lines, size = wait_for("Custom Event", timeout=60)
        settle(out_dir / f"{name}_event.png", timeout=5)
        below = [l for l in lines if l["y"] > title["y"] + title["h"] and l["y"] < title["y"] + 160 and l["x"] < size[0] * 0.4]
        panel = find(below, car) if car else sorted(below, key=lambda l: -l["h"])[:1]
        if not panel:
            if car and below:
                raise CarMismatch(f"the current car is {below[0]['text']!r}, not {car!r}")
            raise MenuError(f"vehicle panel not found under 'Custom Event' (read: {[l['text'] for l in below]})")
        log(f"menu: open vehicle panel {panel[0]['text']!r}")
        click_line(panel[0], size)
        _, _, lines, size = wait_for("Showroom", timeout=60)
        if car and not find(lines, car):
            raise CarMismatch(f"Select Vehicle shows {[l['text'] for l in lines if l['h'] > 30]}, not {car!r}")
        settle(out_dir / f"{name}_select.png", timeout=5)
        click_label("Showroom", timeout=10, log=log)
        wait_for("Take Photo", timeout=60)
        res["settled"] = settle(out_dir / f"{name}_showroom.png", timeout=8)
        res["orbit"] = orbit_frames(out_dir, name, frames, interval) if frames else []
        res.update({k: str(out_dir / f"{name}_{k}.png") for k in ("event", "select", "showroom")}, result="ok")
    except MenuError as e:
        res.update(result="car_mismatch" if isinstance(e, CarMismatch) else "error", error=str(e))
        log(f"menu: {e}")
    finally:
        testing.kill()
    return res
