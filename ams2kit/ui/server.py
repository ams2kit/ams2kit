"""Local web UI: `python -m ams2kit ui` serves http://127.0.0.1:8765 and opens the browser.

JSON API under /api/*; long actions run one at a time as a background job whose log the page polls.
Only listens on localhost.
"""
import json, mimetypes, os, threading, time, traceback, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import actions, game, project as project_mod

STATIC = Path(__file__).parent / "static"
PORT = 8765


class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False, "action": None, "log": [], "result": None, "error": None, "started": 0}

    def log(self, *parts):
        with self.lock:
            self.state["log"].append(" ".join(str(p) for p in parts))

    def start(self, action, fn):
        with self.lock:
            if self.state["running"]:
                raise RuntimeError(f"busy with {self.state['action']}")
            self.state = {"running": True, "action": action, "log": [], "result": None, "error": None, "started": time.time()}

        def run():
            try:
                res = fn(self.log)
                with self.lock:
                    self.state["result"] = res
            except Exception as e:  # shown in the UI
                self.log("ERROR:", e)
                with self.lock:
                    self.state["error"] = str(e)
                    self.state["trace"] = traceback.format_exc()
            finally:
                with self.lock:
                    self.state["running"] = False
        threading.Thread(target=run, daemon=True).start()

    def snapshot(self, since=0):
        with self.lock:
            s = dict(self.state)
            s["log"] = s["log"][since:]
            s["log_from"] = since
            return s


JOB = Job()


def projects_root():
    cfg = game.load_config()
    return Path(cfg.get("projects") or Path.home() / "Documents" / "ams2kit projects")


def list_projects():
    root = projects_root()
    out = []
    if root.exists():
        for t in sorted(root.glob("*/car.toml")):
            p = project_mod.Project(t.parent)
            out.append({"path": str(t.parent), "name": p.name, "display": p.cfg["car"]["display_name"],
                        "donor": p.cfg["car"]["donor"]})
    return out


def _allowed_file(path):
    """Files the page may fetch: inside the projects root or the ams2kit data dir."""
    p = Path(path).resolve()
    roots = [projects_root().resolve(), game.DATA_DIR.resolve()] + [Path(x["path"]).resolve() for x in list_projects()]
    return any(r == p or r in p.parents for r in roots)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _local(self):
        """Only our own page: other web pages (Origin) and DNS-rebinding hosts are refused, since the API
        writes files and starts programs."""
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host", "") in hosts and (origin is None or origin in {"http://" + h for h in hosts})

    def do_GET(self):
        if not self._local():
            return self._send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/" or u.path.startswith("/static/"):
                f = STATIC / ("index.html" if u.path == "/" else u.path[len("/static/"):])
                if not f.resolve().is_relative_to(STATIC.resolve()) or not f.exists():
                    return self._send(404, {"error": "not found"})
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            if u.path == "/api/state":
                return self._send(200, actions.state(projects_root(), list_projects()))
            if u.path == "/api/donors":
                return self._send(200, actions.donors(refresh=q.get("refresh") == "1"))
            if u.path == "/api/project":
                return self._send(200, actions.project_info(q["path"]))
            if u.path == "/api/physics":
                return self._send(200, actions.physics_fields(q["path"]))
            if u.path == "/api/job":
                return self._send(200, JOB.snapshot(int(q.get("since", 0))))
            if u.path == "/file":
                p = Path(q["path"])
                if not (_allowed_file(p) and p.is_file()):
                    return self._send(403, {"error": "forbidden"})
                return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e), "trace": traceback.format_exc()})

    def do_POST(self):
        if not self._local():
            return self._send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/upload":   # raw body -> <project>/art/<name>
                pr = project_mod.Project(q["path"])
                name = Path(q["name"]).name
                dst = pr.art_dir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(self._body())
                return self._send(200, {"saved": str(dst), "rel": f"art/{name}"})
            body = json.loads(self._body() or b"{}")
            if u.path == "/api/settings":
                return self._send(200, actions.save_settings(body))
            if u.path == "/api/project/save":
                return self._send(200, actions.save_project(body["path"], body["cfg"]))
            if u.path == "/api/open":
                return self._send(200, actions.open_path(body["path"], body.get("with")))
            if u.path == "/api/job":
                action = body["action"]
                fn = actions.job(action, body)
                JOB.start(action, fn)
                return self._send(200, {"started": action})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e), "trace": traceback.format_exc()})


class Server(ThreadingHTTPServer):
    allow_reuse_address = False   # on Windows reuse would let two servers share the port silently
    daemon_threads = True


def _already_running(port):
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return "projects_root" in json.loads(r.read())
    except Exception:
        return False


def serve(port=PORT, open_browser=True):
    if _already_running(port):
        url = f"http://127.0.0.1:{port}/"
        print("ams2kit is already running at", url, "- opening it.")
        if open_browser:
            webbrowser.open(url)
        return
    for p in range(port, port + 20):
        try:
            srv = Server(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    else:
        raise OSError(f"no free port between {port} and {port + 19}")
    url = f"http://127.0.0.1:{srv.server_port}/"
    print("ams2kit UI on", url, "(Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
