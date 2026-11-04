"""Fake backend for trying the UI without Automobilista 2, Blender or a real donor.

    python3 tools/mock_ui.py            # then open http://127.0.0.1:8765/
    python3 tools/mock_ui.py --reset    # start again from the two sample cars

It serves the built page (ams2kit/ui/static) and the same JSON API as ams2kit/ui/server.py, backed by two
sample projects in mock_projects/ (git-ignored): "Mock GT" (ICE) and "Mock EV". car.toml is real: it is
loaded, validated and saved by ams2kit.project, so Specs/Physics edits persist across restarts. The donor
data (torque table, gearbox, physics fields) is invented. Jobs (Build, Doctor, ...) only log a few lines;
Build also records the "built" torque table so the EV curve and the Built column show something.

For frontend work, run this and `npm run dev` in frontend/ (Vite proxies /api to port 8765).
"""
import json, math, shutil, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ams2kit import project as project_mod  # noqa: E402

STATIC = ROOT / "ams2kit" / "ui" / "static"
PROJECTS = ROOT / "mock_projects"
PORT = 8765

# ----------------------------------------------------------------------------- sample data

DONOR = {  # an invented turbo-less V8 donor
    "torque": [[0, -20, 150], [1000, -25, 260], [2000, -30, 330], [3000, -35, 360], [4000, -40, 380],
               [5000, -45, 370], [6000, -50, 340], [6800, -55, 300], [7050, -60, -100]],
    "rev_limit": 6800, "gears": [3.36, 2.07, 1.43, 1.0, 0.84, 0.56], "final_drive": 3.42, "radius": 0.334,
}

CARS = {
    "mock_gt": {
        "car": {"name": "mock_gt", "display_name": "Mock GT", "short_name": "Mock GT", "manufacturer": "Mockworks",
                "model": "GT", "class": "GT3", "donor": "mock_donor_v8"},
        "powertrain": {"type": "ice", "power_kw": 300.0, "torque_nm": 480.0, "rev_limit": 7500,
                       "torque_curve": [[1000, 300], [2500, 420], [4000, 470], [5500, 450], [7000, 380]],
                       "gears": [3.2, 2.1, 1.55, 1.22, 1.0, 0.84], "final_drive": 3.7, "drivetrain": "RWD",
                       "engine_layout": 2, "displacement_l": 4.0},
    },
    "mock_ev": {
        "car": {"name": "mock_ev", "display_name": "Mock EV", "short_name": "Mock EV", "manufacturer": "Mockworks",
                "model": "EV", "class": "Street", "donor": "mock_donor_v8"},
        "powertrain": {"type": "ev", "power_kw": 350.0, "torque_nm": 650.0, "rev_limit": 12000, "top_speed_kmh": 250.0},
    },
}

DONORS = {
    "cars": [{"name": "mock_donor_v8", "display": "Mock Donor V8", "manufacturer": "Mockworks", "cls": "GT3"},
             {"name": "mock_donor_i4", "display": "Mock Donor I4", "manufacturer": "Mockworks", "cls": "Street"}],
    "classes": ["GT3", "Street"],
    "drivelines": ["RWD_Mock_Open", "RWD_Mock_LSD", "AWD_Mock"],
}

# a few rows for the "All fields" tab: (kind, key, name, unit, help, donor value)
FIELDS = [
    ("engine", "8b0ab771", "RPMTorque", "rpm, Nm, Nm", "Torque table row (rpm, engine braking, torque).", None),
    ("engine", "4665ae87", "EngineInertia", "kg m^2", "Rotating inertia of the engine.", 0.2),
    ("engine", "dea72eb7", "RevLimitRange", "rpm, rpm step, count", "Rev limit setup range.", [6800, 0, 0]),
    ("engine", "40f1d2b9", "IdleThrottle", "fraction", "Idle throttle opening.", 0.02),
    ("gearbox", "9d58f964", "Ratio", "cogs (driver, driven)", "Gear ratio as cog counts.", None),
    ("chassis", "670b57ab", "Mass", "kg", "Car mass.", 1450.0),
    ("chassis", "1824eaa8", "CGHeight", "m", "Centre of gravity height.", 0.45),
    ("chassis", "beba677b", "CGRearRange", "fraction", "Rear weight share setup range.", [0.52, 0, 0]),
    ("chassis", "3363edfd", "BodyDragBase", "1/2 rho Cd A", "Body drag.", 0.41),
    ("chassis", "4ba4817a", "BrakeTorque", "Nm", "Brake torque at full pedal.", 3800.0),
    ("suspension", "a5123d0d", "SpringRange", "N/m", "Spring setup range.", [90000, 5000, 20]),
    ("suspension", "51374153", "DamperMult", "factor", "Damper motion-ratio multiplier.", 1.0),
]


def _cogs(r):
    return [20, round(r * 20)]


def physics(pr):
    built = _read_built(pr)
    rows = []
    for kind, key, name, unit, help_, value in FIELDS:
        vals = (DONOR["torque"] if key == "8b0ab771" else [_cogs(g) for g in DONOR["gears"]] if key == "9d58f964" else [value])
        bvals = (built["torque"] if built and key == "8b0ab771" else None)
        for i, v in enumerate(vals):
            b = bvals[i] if bvals and i < len(bvals) else (v if built else None)
            ov = pr.cfg["overrides"].get(f"{kind}.{key}#{i}", pr.cfg["overrides"].get(f"{kind}.{key}"))
            rows.append({"kind": kind, "key": key, "idx": i, "count": len(vals), "object": None, "type": "tuple" if isinstance(v, list) else "f32",
                         "donor": v, "built": b, "override": ov, "name": name, "unit": unit, "help": help_, "confidence": "proven"})
    curves = {"donor_torque": DONOR["torque"], "donor_rev_limit": DONOR["rev_limit"], "donor_gears": DONOR["gears"],
              "donor_final_drive": DONOR["final_drive"], "boost": False, "radius": pr.cfg["chassis"]["wheel_radius_m"] or DONOR["radius"],
              "radius_source": "Specs rolling radius" if pr.cfg["chassis"]["wheel_radius_m"] else "donor tyre (mock)",
              "built_torque": built["torque"] if built else None}
    return {"rows": rows, "built": bool(built), "curves": curves}


def _read_built(pr):
    f = pr.build_dir / "mock_build.json"
    return json.loads(f.read_text()) if f.exists() else None


def fake_build(pr, log):
    pt = pr.cfg["powertrain"]
    if pt["type"] == "ev":
        try:
            from ams2kit import ev
            kw = pt.get("sim_power_kw") or pt["power_kw"]
            peak = pt.get("sim_torque_nm") or kw * 1000 / (pt["rev_limit"] * pt["base_speed_fraction"] * 2 * math.pi / 60)
            rows = [list(r) for r in ev.motor_rows(kw, peak, pt["rev_limit"], regen_kw=pt["regen_kw"], regen_nm=pt["regen_nm"])]
        except Exception as e:   # keep the mock usable if ev.py changes
            log(f"ev.motor_rows failed ({e}); flat curve instead")
            rows = [[0, -15, pt["torque_nm"]], [pt["rev_limit"], -15, pt["torque_nm"]]]
        log(f"EV: motor curve, {len(rows)} rows")
    else:
        rows = [[r, -30.0, t] for r, t in sorted(pt["torque_curve"])] + [[pt["rev_limit"] + 250, -60.0, -100.0]]
        log(f"ICE: torque table {len(rows)} rows, {len(pt['gears'])} gears, final drive {pt['final_drive']}")
    pr.build_dir.mkdir(parents=True, exist_ok=True)
    (pr.build_dir / "mock_build.json").write_text(json.dumps({"torque": rows}))
    (pr.build_dir / "build.json").write_text(json.dumps({"mock": True}))


# ----------------------------------------------------------------------------- server

def seed(reset=False):
    if reset and PROJECTS.exists():
        shutil.rmtree(PROJECTS)
    for name, cfg in CARS.items():
        pr = project_mod.Project(PROJECTS / name)
        if not pr.toml.exists():
            pr.update(cfg)
            pr.save()


def projects():
    return [{"path": str(t.parent), "name": p.name, "display": p.cfg["car"]["display_name"], "donor": p.cfg["car"]["donor"]}
            for t in sorted(PROJECTS.glob("*/car.toml")) for p in [project_mod.Project(t.parent)]]


def project_info(path):
    pr = project_mod.Project(path)
    return {"path": str(pr.root), "cfg": pr.cfg, "errors": pr.validate(), "donor_unpacked": True,
            "donor": {"name": pr.cfg["car"]["donor"], "physics_key": "mock"}, "donor_blend": [], "car_blend": None,
            "meshes_built": True, "built": (pr.build_dir / "build.json").exists(), "build": None, "previews": [],
            "art_sources": [], "liveries": {}, "test_results": [], "shots": [], "installed": False}


JOB = {"running": False, "log": [], "error": None, "result": None}


def start_job(action, body):
    JOB.update(running=True, log=[], error=None, result=None)

    def run():
        log = JOB["log"].append
        log(f"[mock] {action}")
        time.sleep(0.5)
        if action == "build":
            fake_build(project_mod.Project(body["path"]), log)
        elif action == "new_project":
            name = body.get("name") or "mock_new"
            pr = project_mod.new_project(PROJECTS / name, name, body.get("donor") or "mock_donor_v8",
                                         display_name=body.get("display_name") or name,
                                         manufacturer=body.get("manufacturer", ""), **{"class": body.get("cls") or "Street"})
            JOB["result"] = {"path": str(pr.root)}
            log(f"created mock_projects/{name}")
        else:
            log("(nothing happens in the mock)")
        log("done")
        JOB["running"] = False

    threading.Thread(target=run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj, ctype="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/" or u.path.startswith("/static/"):
            f = STATIC / ("index.html" if u.path == "/" else u.path[len("/static/"):])
            if not f.resolve().is_relative_to(STATIC.resolve()) or not f.exists():
                return self._send(404, {"error": "not found"})
            ctype = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(f.suffix, "application/octet-stream")
            return self._send(200, f.read_bytes(), ctype)
        if u.path == "/api/state":
            return self._send(200, {"game": "(mock)", "blender": "(mock)", "steam_appid": False, "projects_root": str(PROJECTS),
                                    "projects": projects(), "installed": [], "data_dir": str(PROJECTS)})
        if u.path == "/api/donors":
            return self._send(200, DONORS)
        if u.path == "/api/project":
            return self._send(200, project_info(q["path"]))
        if u.path == "/api/physics":
            return self._send(200, physics(project_mod.Project(q["path"])))
        if u.path == "/api/job":
            since = int(q.get("since", 0))
            return self._send(200, {"running": JOB["running"], "log": JOB["log"][since:], "error": JOB["error"], "result": JOB["result"]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/project/save":
            pr = project_mod.Project(body["path"])
            pr.cfg = project_mod._merge(project_mod.DEFAULTS, body["cfg"])
            pr.save()
            return self._send(200, {"ok": True, "errors": pr.validate()})
        if u.path == "/api/job":
            start_job(body["action"], body)
            return self._send(200, {"started": body["action"]})
        if u.path in ("/api/settings", "/api/open"):
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"ams2kit mock UI on http://127.0.0.1:{PORT}/  (projects in {PROJECTS}; Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
