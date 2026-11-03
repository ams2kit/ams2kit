"""Automated in-game checks (docs/06): a track run with telemetry, and menu screenshots.

Track run: `-runTest 0` starts a Custom Race with the profile's last car and track and lets the AI
drive. Pick the new car once in Custom Race by hand; after that every run uses it.
"""
import csv, glob, os, subprocess, time
from pathlib import Path

from . import game_harness as gh, telemetry as tm

RUN_ARGS = "-novr -windowed -doNotPauseOnFocusLoss -enableSharedMem -runTest 0"
MENU_ARGS = "-novr -windowed -doNotPauseOnFocusLoss"
DUMPS = os.path.expandvars(r"%LOCALAPPDATA%\Temp\AMS2AVX*.dmp")
MENU_SINGLE_RACE = (500, 360)       # main menu tile (1920x1080 frame)
MENU_VEHICLE_PANEL = (640, 380)     # Custom Event -> Select Vehicle
MENU_SHOWROOM = (1344, 954)         # Select Vehicle -> Showroom (3D view of the car)


def steam_appid(gamedir, enable=None):
    """steam_appid.txt next to the exe stops Steam's custom-arguments prompt. Query or set."""
    f = Path(gamedir) / "steam_appid.txt"
    if enable is True:
        f.write_text("1066890")
    elif enable is False and f.exists():
        f.unlink()
    return f.exists()


def kill():
    subprocess.run(["taskkill", "/IM", "AMS2AVX.exe", "/F"], capture_output=True)
    for _ in range(30):
        if not gh.game_pids():
            return
        time.sleep(1)


def launch(gamedir, args):
    exe = Path(gamedir) / "AMS2AVX.exe"
    # detached, so the game outlives the calling process
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-Process -FilePath '{exe}' -WorkingDirectory '{gamedir}' -ArgumentList '{args}'"], check=True)


def wait_on_track(timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not gh.game_pids() and time.time() - t0 > 20:
            return False, "game exited", None
        try:
            s, _ = tm.sample(tm.open_view())
            # in session with our car loaded (standing still is fine: a race start is the cleanest
            # 0-100 measurement, so logging starts before the car moves)
            if s["game_state"] == 2 and s["car"] and s["track"]:
                return True, f"{s['car']} at {s['track']} after {time.time() - t0:.0f}s", s
        except SystemExit:
            pass
        time.sleep(0.5)
    return False, "timeout", None


def summarise(csv_path):
    rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(open(csv_path))]
    moving = [r for r in rows if r["speed"] > 0.5]
    out = {"samples": len(rows)}
    if not moving:
        return out
    out["top_speed_kmh"] = round(max(r["speed"] for r in rows) * 3.6, 1)
    out["max_rpm"] = round(max(r["rpm"] for r in rows))
    out["rev_limit"] = round(rows[-1]["max_rpm"])
    bands = {}
    for lo, hi in ((0, 50), (50, 100), (100, 150), (150, 200), (200, 300)):
        band = sorted(abs(r["local_accel_z"]) for r in moving if r["throttle"] > 0.95 and lo <= r["speed"] * 3.6 < hi)
        if band:
            bands[f"{lo}-{hi}"] = round(band[int(len(band) * 0.9)] / 9.81, 2)
    out["accel_g_p90"] = bands
    low = [g for k, g in bands.items() if k in ("0-50", "50-100")]
    if low:
        out["est_0_100_s"] = round(100 / 3.6 / (sum(low) / len(low) * 9.81), 1)
    # measured standing start (race start from the grid): last sample under 2 km/h before a run to
    # 100 km/h with the throttle mostly held
    for i, r in enumerate(rows):
        if r["speed"] * 3.6 >= 2 or i + 1 >= len(rows) or rows[i + 1]["speed"] * 3.6 < 2:
            continue
        for s in rows[i + 1:]:
            if s["speed"] * 3.6 >= 100:
                run = [x for x in rows if r["t"] <= x["t"] <= s["t"]]
                if sum(x["throttle"] > 0.8 for x in run) >= 0.8 * len(run):
                    out["measured_0_100_s"] = round(s["t"] - r["t"], 2)
                break
            if s["speed"] * 3.6 < 2:
                break
        if "measured_0_100_s" in out:
            break
    return out


def performance(csv_path, bin_kmh=5):
    """Standing-start and braking figures estimated from AI-driven telemetry.

    Full-throttle samples give acceleration per speed bin a(v) (median; longitudinal local accel).
    Bins without data below the first measured one take that bin's value (launch is grip-limited);
    gaps are interpolated. t = sum dv/a, s = sum v dv/a give 0-60 mph, 0-100 km/h, quarter mile and
    1000 m. Braking: median deceleration with the brake above 90% between 40 and 120 km/h, turned into
    a 100-0 km/h distance. Estimates, not stopwatch figures: the AI's throttle and line vary."""
    import statistics as st
    rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(open(csv_path))]
    # acceleration from the speed trace (central difference over +-2 samples): the game's local
    # acceleration channel reads well below dv/dt (0.37 vs 0.59 g at 60-100 km/h), so it is not used
    for i, r in enumerate(rows):
        j0, j1 = max(0, i - 2), min(len(rows) - 1, i + 2)
        dt = rows[j1]["t"] - rows[j0]["t"]
        r["dvdt"] = (rows[j1]["speed"] - rows[j0]["speed"]) / dt if dt > 0 else 0.0
    acc = {}
    for r in rows:
        v = r["speed"] * 3.6
        # straight-line samples only: corner exits mix lateral grip into the numbers
        if r["throttle"] > 0.95 and r["brake"] < 0.05 and v > 3 and abs(r.get("local_accel_x", 0.0)) < 0.2 * 9.81:
            acc.setdefault(int(v // bin_kmh), []).append(r["dvdt"])
    bins = {b: st.median(a) for b, a in acc.items() if len(a) >= 3}
    out = {}
    if not bins:
        return out
    top = max(r["speed"] for r in rows) * 3.6
    hi = max(bins)
    lo = min(bins)
    a_of = {}
    for b in range(0, hi + 1):
        if b in bins:
            a_of[b] = bins[b]
        elif b < lo:
            a_of[b] = bins[lo]
        else:
            prev = max(k for k in bins if k < b)
            nxt = min(k for k in bins if k > b)
            a_of[b] = bins[prev] + (bins[nxt] - bins[prev]) * (b - prev) / (nxt - prev)
    t = s = 0.0
    marks = {"0_60mph_s": 96.56, "0_100_s": 100.0, "0_150_s": 150.0}
    dist_marks = {"quarter_mile_s": 402.34, "1000m_s": 1000.0}
    for b in range(0, hi + 1):
        v0, v1 = b * bin_kmh / 3.6, (b + 1) * bin_kmh / 3.6
        a = max(a_of[b], 0.05)
        dt = (v1 - v0) / a
        ds = (v0 + v1) / 2 * dt
        for k, m in list(marks.items()):
            if v1 * 3.6 >= m and k not in out:
                out[k] = round(t + (m / 3.6 - v0) / a, 2)
        for k, m in list(dist_marks.items()):
            if s + ds >= m and k not in out:
                # solve within the bin: s + v0*x + a*x^2/2 = m
                x = (-v0 + (v0 * v0 + 2 * a * (m - s)) ** 0.5) / a
                out[k] = round(t + x, 2)
                out[k.replace("_s", "_trap_kmh")] = round((v0 + a * x) * 3.6, 1)
        t += dt
        s += ds
    out["top_speed_kmh"] = round(top, 1)
    out["accel_g_by_speed"] = {f"{b * bin_kmh}": round(a / 9.81, 2) for b, a in sorted(bins.items())}
    brk = [-r["dvdt"] for r in rows if r["brake"] > 0.9 and 40 < r["speed"] * 3.6 < 120]
    if len(brk) >= 5:
        d = st.median(brk)
        out["brake_decel_g"] = round(d / 9.81, 2)
        out["brake_100_0_m"] = round((100 / 3.6) ** 2 / (2 * d), 1)
    return out


def track_run(gamedir, out_dir, name, seconds=120, shots=True, log=print, expect_car=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kill()
    before = set(glob.glob(DUMPS))
    launch(gamedir, RUN_ARGS)
    ok, why, first = wait_on_track()
    log(f"on track: {ok} ({why})")
    res = {"name": name, "reached_track": ok, "detail": why, "car": first and first["car"], "track": first and first["track"]}
    if ok and expect_car and first["car"].strip().lower() != expect_car.strip().lower():
        kill()
        res["result"] = "wrong car"
        res["detail"] = (f"the game loaded '{first['car']}', not '{expect_car}'. Start one Custom Race with your car by hand "
                         "so the game remembers it, then run the test again.")
        log(res["detail"])
        return res
    csv_path = out_dir / f"{name}.csv"
    if ok:
        if shots:
            gh.shot(str(out_dir / f"{name}_start.png"))
        try:
            tm.log(str(csv_path), seconds)
        except Exception as e:  # the mapping vanishes if the game dies mid-log
            log(f"telemetry stopped: {e}")
        if shots and gh.game_pids():
            gh.shot(str(out_dir / f"{name}_end.png"))
    alive = bool(gh.game_pids())
    kill()
    dumps = sorted(set(glob.glob(DUMPS)) - before)
    res["result"] = "crash" if dumps or (ok and not alive) else ("ok" if ok else "did not reach track")
    res["dumps"] = dumps
    if ok and csv_path.exists():
        res["telemetry"] = summarise(csv_path)
    log(f"result: {res['result']}")
    return res


def menu_check(gamedir, out_dir, name, log=print):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kill()
    launch(gamedir, MENU_ARGS)
    time.sleep(75)
    if not gh.game_pids():
        return {"result": "game exited"}
    gh.click(*MENU_SINGLE_RACE)
    time.sleep(7)
    gh.shot(str(out_dir / f"{name}_event.png"))
    gh.click(*MENU_VEHICLE_PANEL)
    time.sleep(7)
    gh.shot(str(out_dir / f"{name}_select.png"))
    gh.click(*MENU_SHOWROOM)
    time.sleep(10)
    gh.shot(str(out_dir / f"{name}_showroom.png"))
    kill()
    log("menu screenshots saved")
    return {"result": "ok", **{k: str(out_dir / f"{name}_{k}.png") for k in ("event", "select", "showroom")}}
