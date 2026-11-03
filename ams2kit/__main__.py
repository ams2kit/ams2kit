"""ams2kit command line. `python -m ams2kit` with no arguments opens the UI.

  ui [--port N] [--no-browser]       local web UI (default)
  donors [filter]                    list installed cars usable as donors
  new <dir> <Name> <Donor>           create a project and unpack the donor
  build|art|render|doctor|install|uninstall|test|menu|export-blend|build-meshes <project dir>
  dump <physics file>                print a ShCB physics file as text
  tyres <project dir> [size] [--race] tyre sizes (donor / Specs) and the base tyre sets closest to them
"""
import json, sys
from pathlib import Path


def main(argv):
    if not argv or argv[0] == "ui":
        from .ui import server
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else server.PORT
        server.serve(port, open_browser="--no-browser" not in argv)
        return
    cmd = argv[0]
    from . import actions, game
    if cmd == "donors":
        flt = argv[1].lower() if len(argv) > 1 else ""
        for c in actions.donors()["cars"]:
            if flt in (c["name"] + c["display"] + c["cls"]).lower():
                print(f"{c['name']:40s} {c['cls']:18s} {c['display']}")
        return
    if cmd == "new":
        root, name, donor = Path(argv[1]), argv[2], argv[3]
        fn = actions.job("new_project", {"root": str(root.parent if root.name == name else root), "name": name, "donor": donor})
        print(json.dumps(fn(print), indent=1, default=str))
        return
    if cmd == "dump":
        from . import shcb
        print(shcb.dump(Path(argv[1]).read_bytes()))
        return
    if cmd == "tyres":
        from . import project as project_mod, tyres
        pr = project_mod.Project(argv[1])
        args = [a for a in argv[2:] if not a.startswith("--")]
        if args:
            pr.cfg["chassis"]["tyre_size"], pr.cfg["chassis"]["tyre_size_rear"] = args[0], (args[1] if len(args) > 1 else "")
        print(tyres.report(pr, game.find_game(), road="--race" not in argv))
        return
    action = {"export-blend": "export_blend", "build-meshes": "build_meshes"}.get(cmd, cmd)
    res = actions.job(action, {"path": argv[1], **({"seconds": argv[2]} if len(argv) > 2 else {})})(print)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
