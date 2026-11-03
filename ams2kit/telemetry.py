"""Log AMS2 shared-memory telemetry ($pcars2$, needs -enableSharedMem) and summarise a run.

  python telemetry.py log <out.csv> <seconds>     sample at 20 Hz while the game runs
  python telemetry.py summary <in.csv>            top speed, 0-100 km/h, accelerations
  python telemetry.py probe                       one sample with field offsets checked
Offsets follow the Project CARS 2 SharedMemory.h layout (ParticipantInfo = 100 bytes).
"""
import csv, ctypes, ctypes.wintypes as wt, struct, sys, time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenFileMappingW.restype = wt.HANDLE
k32.MapViewOfFile.restype = ctypes.c_void_p
SIZE = 0x4000

FIELDS = {  # name: (offset, format)
    "version": (0, "<I"), "game_state": (8, "<I"), "session_state": (12, "<I"), "race_state": (16, "<I"),
    "viewed": (20, "<i"), "participants": (24, "<i"),
    "car": (6444, "64s"), "car_class": (6508, "64s"), "track": (6576, "64s"), "variation": (6640, "64s"),
    "current_time": (6724, "<f"), "speed": (6848, "<f"), "rpm": (6852, "<f"), "max_rpm": (6856, "<f"),
    "brake": (6860, "<f"), "throttle": (6864, "<f"), "steering": (6872, "<f"),
    "gear": (6876, "<i"), "num_gears": (6880, "<i"), "odometer": (6884, "<f"),
    "local_accel_x": (6956, "<f"), "local_accel_y": (6960, "<f"), "local_accel_z": (6964, "<f"),
}
COLUMNS = ["t", "game_state", "session_state", "race_state", "speed", "rpm", "max_rpm", "throttle",
           "brake", "gear", "num_gears", "odometer", "local_accel_x", "local_accel_y", "local_accel_z"]


def open_view():
    h = k32.OpenFileMappingW(0x4, False, "$pcars2$")
    if not h:
        raise SystemExit("shared memory $pcars2$ not found (game not running or no -enableSharedMem)")
    return k32.MapViewOfFile(h, 0x4, 0, 0, SIZE)


def sample(view):
    raw = ctypes.string_at(view, SIZE)
    out = {}
    for name, (off, fmt) in FIELDS.items():
        v = struct.unpack_from(fmt, raw, off)[0]
        out[name] = v.split(b"\0")[0].decode("latin-1") if isinstance(v, bytes) else v
    return out, raw


def log(path, seconds):
    view = open_view()
    t0 = time.time()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        s, _ = sample(view)
        print("car:", s["car"], "| class:", s["car_class"], "| track:", s["track"], s["variation"], flush=True)
        w.writerow(COLUMNS)
        while time.time() - t0 < seconds:
            s, _ = sample(view)
            w.writerow([round(time.time() - t0, 3)] + [s[c] for c in COLUMNS[1:]])
            time.sleep(0.05)


def summary(path):
    rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(open(path))]
    moving = [r for r in rows if r["speed"] > 0.5]
    if not moving:
        print("car never moved"); return
    top = max(r["speed"] for r in rows) * 3.6
    print(f"samples {len(rows)}, moving {len(moving)}; top speed {top:.1f} km/h; "
          f"max rpm {max(r['rpm'] for r in rows):.0f} (limit {rows[-1]['max_rpm']:.0f}); "
          f"gears seen {sorted({int(r['gear']) for r in moving})}")
    # best acceleration windows: time from <=5 km/h to >=100 km/h with throttle held
    best = None
    for i, r in enumerate(rows):
        if r["speed"] * 3.6 > 5:
            continue
        for s in rows[i + 1:]:
            if s["throttle"] < 0.9 and s["speed"] * 3.6 < 100 and s["t"] - r["t"] > 0.5 and s["speed"] * 3.6 > 10:
                break
            if s["speed"] * 3.6 >= 100:
                d = s["t"] - r["t"]
                best = d if best is None else min(best, d)
                break
    print("0-100 km/h:", f"{best:.2f} s" if best else "no full-throttle standing start in the log")
    # peak longitudinal acceleration at full throttle per speed band (accel z is negative forwards)
    for lo, hi in ((0, 50), (50, 100), (100, 150), (150, 200)):
        band = [abs(r["local_accel_z"]) for r in moving if r["throttle"] > 0.95 and lo <= r["speed"] * 3.6 < hi]
        if band:
            band.sort()
            print(f"  {lo:3d}-{hi:3d} km/h full throttle: accel p90 {band[int(len(band) * .9)] / 9.81:.2f} g ({len(band)} samples)")


def probe():
    s, raw = sample(open_view())
    for k, v in s.items():
        print(f"{k:15s} {v}")
    for needle in (s["car"].encode() if s["car"] else b"",):
        print("car name found at", [hex(i) for i in range(len(raw)) if raw.startswith(needle, i)][:5] if needle else None)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "log":
        log(sys.argv[2], float(sys.argv[3]))
    elif cmd == "summary":
        summary(sys.argv[2])
    elif cmd == "probe":
        probe()
    else:
        raise SystemExit(__doc__)
