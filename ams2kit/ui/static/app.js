// ams2kit UI: a step-by-step wizard over the local JSON API (see ui/server.py, actions.py).
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const fileUrl = p => "/file?path=" + encodeURIComponent(p) + "&t=" + Date.now();

const S = { step: "setup", state: null, donors: null, project: null, filter: "", cls: "", pickDonor: null };
try { const saved = JSON.parse(localStorage.getItem("ams2kit") || "{}"); S.projectPath = saved.projectPath; S.step = saved.step || "setup"; } catch (e) {}
const remember = () => { try { localStorage.setItem("ams2kit", JSON.stringify({ projectPath: S.projectPath, step: S.step })); } catch (e) {} };

// ---------------------------------------------------------------- jobs
let jobSince = 0, jobTimer = null, jobDone = null;
async function runJob(action, extra = {}, onDone) {
  try {
    await api("/api/job", { action, path: S.projectPath, ...extra });
  } catch (e) { alert(e.message); return; }
  jobSince = 0; jobDone = onDone;
  $("#job").classList.remove("hidden");
  $("#job-title").textContent = action.replace("_", " ");
  $("#job-log").textContent = "";
  pollJob();
}
async function pollJob() {
  clearTimeout(jobTimer);
  const j = await api("/api/job?since=" + jobSince);
  if (j.log.length) { $("#job-log").textContent += j.log.join("\n") + "\n"; jobSince += j.log.length; $("#job-log").scrollTop = 1e9; }
  $("#job-status").innerHTML = j.running ? '<span class="spin"></span> running' : (j.error ? "failed" : "done");
  if (j.running) { jobTimer = setTimeout(pollJob, 700); return; }
  if (j.error && j.trace) $("#job-log").textContent += "\n" + j.trace;
  const cb = jobDone; jobDone = null;
  if (cb) await cb(j);
  await refresh();
}
$("#job-close").onclick = () => $("#job").classList.add("hidden");

// ---------------------------------------------------------------- data
async function refresh() {
  S.state = await api("/api/state");
  if (S.projectPath) {
    try { S.project = await api("/api/project?path=" + encodeURIComponent(S.projectPath)); }
    catch (e) { S.project = null; S.projectPath = null; }
  }
  render();
}
async function saveCfg() {
  const r = await api("/api/project/save", { path: S.projectPath, cfg: S.project.cfg });
  S.project.errors = r.errors;
}
function setPath(obj, path, val) { const ks = path.split("."); let o = obj; ks.slice(0, -1).forEach(k => o = o[k]); o[ks.at(-1)] = val; }
function getPath(obj, path) { return path.split(".").reduce((o, k) => o?.[k], obj); }

// ---------------------------------------------------------------- views
const needsProject = ["model", "specs", "physics", "art", "build", "test"];
function render() {
  document.querySelectorAll("#steps button").forEach(b => {
    b.classList.toggle("active", b.dataset.step === S.step);
    b.disabled = needsProject.includes(b.dataset.step) && !S.project;
    b.classList.toggle("done", isDone(b.dataset.step));
    b.onclick = () => { if (!b.disabled) { S.step = b.dataset.step; remember(); render(); } };
  });
  const chip = $("#project-chip");
  chip.classList.toggle("hidden", !S.project);
  if (S.project) chip.textContent = `${S.project.cfg.car.display_name || S.project.cfg.car.name}  ·  donor ${S.project.cfg.car.donor}`;
  $("#main").innerHTML = "";
  ({ setup: viewSetup, car: viewCar, model: viewModel, specs: viewSpecs, physics: viewPhysics, art: viewArt, build: viewBuild, test: viewTest })[S.step]();
}
function isDone(step) {
  const p = S.project, s = S.state;
  if (step === "setup") return !!(s?.game && s?.blender);
  if (!p) return false;
  return { car: p.donor_unpacked, model: p.meshes_built, specs: !p.errors.length, art: p.previews.length > 0,
           build: p.installed, test: p.test_results.some(t => t.result === "ok") }[step] || false;
}
const html = (strings, ...vals) => strings.reduce((a, s, i) => a + s + (i < vals.length ? vals[i] : ""), "");
function mount(markup) { const d = document.createElement("div"); d.innerHTML = markup; $("#main").append(...d.childNodes); }

function viewSetup() {
  const s = S.state;
  const line = (ok, label, val) => `<li><span class="dot ${ok ? "ok" : "fail"}"></span><b>${label}</b><span>${esc(val || "not found")}</span></li>`;
  mount(html`
    <h1>Setup</h1>
    <p class="lead">ams2kit needs Automobilista 2 and Blender. Both are detected automatically; correct the paths here if needed.</p>
    <div class="card"><ul class="list">
      ${line(s.game, "Automobilista 2", s.game)}${line(s.blender, "Blender", s.blender)}
      <li><span class="dot ok"></span><b>Projects folder</b><span>${esc(s.projects_root)}</span></li></ul></div>
    <div class="card grid">
      <label class="f">Game folder<input id="set-game" value="${esc(s.game || "")}" placeholder="...\\steamapps\\common\\Automobilista 2"></label>
      <label class="f">Blender executable<input id="set-blender" value="${esc(s.blender || "")}" placeholder="...\\blender.exe"></label>
      <label class="f">Projects folder<input id="set-projects" value="${esc(s.projects_root)}"></label>
      <label class="f">Testing
        <span class="row"><input type="checkbox" id="set-appid" ${s.steam_appid ? "checked" : ""}> Skip Steam's "custom arguments" prompt</span>
        <span class="help">Adds steam_appid.txt next to the game exe. Untick to remove it.</span></label>
    </div>
    <button id="save-setup">Save settings</button>
    ${s.installed.length ? `<h2>Installed cars</h2><div class="card"><ul class="list">${s.installed.map(r => `<li><b>${esc(r.name)}</b><span>${r.files.length} files · ${esc(r.time)}</span></li>`).join("")}</ul></div>` : ""}`);
  $("#save-setup").onclick = async () => {
    await api("/api/settings", { game: $("#set-game").value, blender: $("#set-blender").value, projects: $("#set-projects").value, steam_appid: $("#set-appid").checked });
    await refresh();
  };
}

async function viewCar() {
  const s = S.state;
  mount(html`
    <h1>Car &amp; donor</h1>
    <p class="lead">Every new car is a clone of an existing car, the <b>donor</b>. Your car keeps the donor's tyres, driveline layout
      (front-, rear- or all-wheel drive), interior and engine sound, so pick one close to your car: same drive layout, similar size and shape,
      ideally a plain road car without wings or add-ons.</p>
    ${s.projects.length ? `<h2>Open a project</h2><div class="card"><ul class="list">${s.projects.map(p =>
      `<li><button class="ghost small" data-open="${esc(p.path)}">Open</button><b>${esc(p.display || p.name)}</b><span class="status">donor ${esc(p.donor)}</span></li>`).join("")}</ul></div>` : ""}
    <h2>New car</h2>
    <div class="card">
      <div class="grid">
        <label class="f">Internal name<input id="n-name" placeholder="BYD_Seal"><span class="help">Letters, digits and _ only. Used in file names.</span></label>
        <label class="f">Display name<input id="n-display" placeholder="BYD Seal AWD"></label>
        <label class="f">Manufacturer<input id="n-manu" placeholder="BYD"><span class="help">Also picks the logo file name.</span></label>
        <label class="f">Car class<select id="n-class"></select><span class="help">Where the car is listed in game.</span></label>
      </div>
      <h2>Donor car</h2>
      <div class="row" style="margin-bottom:10px">
        <input id="d-filter" placeholder="Search cars..." style="max-width:280px" value="${esc(S.filter)}">
        <select id="d-class" style="max-width:220px"><option value="">All classes</option></select>
        <select id="d-sort" style="max-width:200px"><option value="class">Sort by class</option><option value="parts">Fewest parts first</option></select>
        <span id="d-count" class="status"></span>
      </div>
      <div class="donors" id="donors"><div style="padding:14px">Loading the car list...</div></div>
      <div class="row" style="margin-top:14px"><button id="create">Create project</button><span id="create-msg" class="status"></span></div>
    </div>`);
  document.querySelectorAll("[data-open]").forEach(b => b.onclick = async () => { S.projectPath = b.dataset.open; S.step = "model"; remember(); await refresh(); });
  if (!S.donors) { try { S.donors = await api("/api/donors"); } catch (e) { $("#donors").innerHTML = `<div style="padding:14px">${esc(e.message)}</div>`; return; } }
  const cls = $("#d-class"), ncls = $("#n-class");
  S.donors.classes.forEach(c => { cls.add(new Option(c, c)); ncls.add(new Option(c, c)); });
  cls.value = S.cls; ncls.value = "Street";
  const draw = () => {
    const f = S.filter.toLowerCase();
    const cars = S.donors.cars.filter(c => (!S.cls || c.cls === S.cls) && (c.display + c.name + c.manufacturer).toLowerCase().includes(f));
    if (S.sort === "parts") cars.sort((a, b) => (a.parts || 999) - (b.parts || 999));
    $("#d-count").textContent = `${cars.length} cars`;
    $("#donors").innerHTML = cars.map(c => `<div class="donor ${S.pickDonor === c.name ? "sel" : ""}" data-name="${esc(c.name)}">
        <span><b>${esc(c.display)}</b> <small>${esc(c.manufacturer)} ${esc(c.year)}</small></span><small>${esc(c.cls)}</small><small title="exterior parts to replace / all meshes">${c.parts ?? "?"} parts</small></div>`).join("");
    document.querySelectorAll(".donor").forEach(d => d.onclick = () => { S.pickDonor = d.dataset.name; draw(); });
  };
  $("#d-filter").oninput = e => { S.filter = e.target.value; draw(); };
  cls.onchange = e => { S.cls = e.target.value; draw(); };
  $("#d-sort").value = S.sort || "class";
  $("#d-sort").onchange = e => { S.sort = e.target.value; draw(); };
  draw();
  $("#create").onclick = () => {
    const name = $("#n-name").value.trim();
    if (!/^[A-Za-z][A-Za-z0-9_]{2,40}$/.test(name)) return ($("#create-msg").textContent = "Internal name: letters, digits, _ (3-41 chars).");
    if (!S.pickDonor) return ($("#create-msg").textContent = "Pick a donor car.");
    runJob("new_project", { root: S.state.projects_root, name, donor: S.pickDonor, display_name: $("#n-display").value || name.replace(/_/g, " "),
      manufacturer: $("#n-manu").value, cls: $("#n-class").value }, j => { if (j.result?.path) { S.projectPath = j.result.path; S.step = "model"; remember(); } });
  };
}

function viewModel() {
  const p = S.project, donorBlend = p.donor_blend[0];
  mount(html`
    <h1>3D model</h1>
    <p class="lead">ams2kit exports the donor car to a Blender file so you can see exactly which parts to replace. Put your car into that file,
      keeping the donor's object names, then let ams2kit turn it back into game meshes.</p>
    <div class="card"><ol class="steps-howto">
      <li><b>Export the donor</b> to <code>model/donor_${esc(p.donor?.key || "")}.blend</code>.
        <div class="row" style="margin-top:8px"><button id="m-export">${donorBlend ? "Export again" : "Export donor .blend"}</button>
        ${donorBlend ? `<button class="ghost" id="m-open-donor">Open in Blender</button>` : ""}</div></li>
      <li><b>Model your car in it</b>: import your model, line its wheels up with the <code>WHEEL_*</code> markers, move your meshes into the
        <code>REPLACE_*</code> objects (or rename yours to match), assign the donor's material slots to your faces (paint, glass, lights, rims), and
        delete donor parts you don't want. The README text block inside the file explains the details.</li>
      <li><b>Save it as</b> <code>${esc(p.cfg.model.blend)}</code> in the project folder.
        <span class="status" style="margin-left:8px"><span class="dot ${p.car_blend ? "ok" : "warn"}"></span>${p.car_blend ? "found" : "not saved yet"}</span></li>
      <li><b>Build the game meshes</b> from your file.
        <div class="row" style="margin-top:8px"><button id="m-build" ${p.car_blend ? "" : "disabled"}>Build meshes</button>
        <span class="status"><span class="dot ${p.meshes_built ? "ok" : ""}"></span>${p.meshes_built ? "meshes built" : "not built"}</span></div></li>
    </ol></div>
    <div class="card row"><label class="row" style="gap:8px"><input type="checkbox" id="m-use" ${p.cfg.model.use_model ? "checked" : ""}>
      Use my model in the build</label><span class="status">Untick to build with the donor's body (useful for a first physics test).</span>
      <button class="ghost small" id="m-folder">Open project folder</button></div>`);
  $("#m-export").onclick = () => runJob("export_blend");
  if (donorBlend) $("#m-open-donor").onclick = () => api("/api/open", { path: donorBlend, with: "blender" });
  $("#m-build").onclick = () => runJob("build_meshes");
  $("#m-folder").onclick = () => api("/api/open", { path: p.path + "\\model\\" });
  $("#m-use").onchange = async e => { p.cfg.model.use_model = e.target.checked; await saveCfg(); render(); };
}

const SPEC_FIELDS = [
  ["Identity", [
    ["car.display_name", "Display name"], ["car.short_name", "Short name"], ["car.manufacturer", "Manufacturer"], ["car.model", "Model"],
    ["car.year", "Year", "number"], ["car.class", "Class", "class"], ["car.country", "Country"], ["car.region", "Region", "select", ["EU", "NA", "SA", "AS", "OC", "AF"]],
    ["car.engine_placement", "Engine placement (menu)", "select", ["", "Front", "Mid-Front", "Mid", "Mid-Rear", "Rear"], "Empty keeps the donor's."],
    ["car.description", "Description", "textarea"]]],
  ["Powertrain", [
    ["powertrain.type", "Type", "select", ["ev", "ice"], "EV: single speed with a constant-power motor curve. ICE: your torque curve and gears."],
    ["powertrain.power_kw", "Power (kW)", "number"], ["powertrain.torque_nm", "Torque (Nm)", "number", null, "Shown in the menu."],
    ["powertrain.rev_limit", "Rev limit (rpm)", "number"], ["powertrain.top_speed_kmh", "Top speed (km/h)", "number", null, "EV: the gearing is set so the rev limit gives this speed."],
    ["powertrain.base_speed_fraction", "EV base speed (share of rev limit)", "number", null, "Constant torque up to here, constant power above. 0.45 is typical."],
    ["powertrain.torque_curve", "ICE torque curve", "pairs", null, "One rpm,Nm pair per line."],
    ["powertrain.gears", "ICE gear ratios", "list", null, "Comma-separated, 1st to top gear. Must match the donor's gear count."],
    ["powertrain.final_drive", "ICE final drive", "number"],
    ["powertrain.driveline", "Driveline", "driveline", null, "Which wheels are driven and how (any layout the game has). Empty keeps the donor's."],
    ["powertrain.drivetrain", "Drivetrain (menu label)", "select", ["AWD", "RWD", "FWD"], "Follows the driveline above when one is chosen."],
    ["powertrain.engine_layout", "Engine label (menu)", "engine", null, "The game has no electric label; pick the closest."],
    ["powertrain.displacement_l", "Displacement (L)", "number"]]],
  ["Chassis", [
    ["chassis.mass_kg", "Mass (kg)", "number", null, "0 keeps the donor's."], ["chassis.cg_height_m", "CG height (m)", "number", null, "0 keeps the donor's."],
    ["chassis.wheelbase_m", "Wheelbase (m)", "number", null, "0 keeps the donor's."], ["chassis.track_front_m", "Front track (m)", "number"],
    ["chassis.track_rear_m", "Rear track (m)", "number"], ["chassis.wheel_radius_m", "Rolling radius (m)", "number", null, "Used for the EV gearing; 0 = donor's."],
    ["chassis.rear_weight", "Rear weight share (menu)", "number"], ["stats.zero_to_100_s", "0-100 km/h (menu, s)", "number"]]],
];

// Menu "Engine" labels by stats index (text\vehicledetails.tdb; mapped from base cars, docs/05).
const ENGINE_LABELS = [[1, "V6"], [2, "V8"], [3, "V10"], [4, "V12"], [18, "V4"], [5, "Straight 4"], [6, "Straight 5"], [7, "Straight 6"],
  [10, "Flat 4"], [11, "Flat 6"], [16, "Flat 8"], [17, "Flat 12"], [13, "W12"], [12, "W16"], [8, "Rotary 2"], [9, "Rotary 3"],
  [14, "Single cylinder"], [15, "Twin cylinder"]];
function field([path, label, type = "text", opts, help]) {
  const v = getPath(S.project.cfg, path);
  let input;
  if (type === "driveline") {
    const groups = S.donors?.drivelines || [];
    const byLayout = {};
    groups.forEach(g => { const k = g.split("_")[0]; (byLayout[k] = byLayout[k] || []).push(g); });
    input = `<select data-p="${path}"><option value="">Donor's driveline</option>${Object.entries(byLayout).map(([k, gs]) =>
      `<optgroup label="${esc(k)}">${gs.map(g => `<option ${g === v ? "selected" : ""}>${esc(g)}</option>`).join("")}</optgroup>`).join("")}</select>`;
  } else if (type === "engine") input = `<select data-p="${path}" data-t="number">${ENGINE_LABELS.map(([i, l]) =>
    `<option value="${i}" ${i == v ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  else if (type === "select") input = `<select data-p="${path}">${opts.map(o => `<option ${o == v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  else if (type === "class") input = `<input data-p="${path}" value="${esc(v)}" list="classes">`;
  else if (type === "textarea") input = `<textarea data-p="${path}" rows="2">${esc(v)}</textarea>`;
  else if (type === "pairs") input = `<textarea data-p="${path}" data-t="pairs" rows="4">${esc((v || []).map(x => x.join(",")).join("\n"))}</textarea>`;
  else if (type === "list") input = `<input data-p="${path}" data-t="list" value="${esc((v || []).join(", "))}">`;
  else input = `<input data-p="${path}" ${type === "number" ? 'type="number" step="any" data-t="number"' : ""} value="${esc(v)}">`;
  return `<label class="f">${label}${input}${help ? `<span class="help">${help}</span>` : ""}</label>`;
}
async function viewSpecs() {
  const p = S.project;
  if (!S.donors) { try { S.donors = await api("/api/donors"); } catch (e) {} }
  mount(html`
    <h1>Specs</h1>
    <p class="lead">What the car is and how it drives. Changes save automatically.</p>
    ${p.errors.length ? `<div class="card">${p.errors.map(e => `<div><span class="dot fail"></span> ${esc(e)}</div>`).join("")}</div>` : ""}
    ${SPEC_FIELDS.map(([title, fs]) => `<h2>${title}</h2><div class="card grid">${fs.map(field).join("")}</div>`).join("")}
    <datalist id="classes">${(S.donors?.classes || []).map(c => `<option value="${esc(c)}">`).join("")}</datalist>`);
  document.querySelectorAll("[data-p]").forEach(el => el.onchange = async () => {
    let v = el.value;
    if (el.dataset.t === "number") v = v === "" ? 0 : Number(v);
    if (el.dataset.t === "list") v = v.split(",").map(x => Number(x.trim())).filter(x => x);
    if (el.dataset.t === "pairs") v = v.split("\n").map(l => l.split(",").map(Number)).filter(x => x.length === 2 && x.every(n => !isNaN(n)));
    setPath(p.cfg, el.dataset.p, v);
    await saveCfg();
    if (el.dataset.p === "powertrain.type") render();
  });
}

// Physics: every field of the donor's engine/gearbox/chassis/suspension files; edits go to car.toml [overrides]
async function viewPhysics() {
  const p = S.project;
  mount(html`
    <h1>Physics</h1>
    <p class="lead">Every setting in the car's physics files. <b>Donor</b> is the donor car's value, <b>Built</b> what the last build wrote
      (after Specs), <b>Override</b> your value, applied last on Build. Leave an override empty to keep the built value.
      Lists keep the donor's length (e.g. <code>0.3, 0, 0</code>).</p>
    <div class="row" style="margin-bottom:10px">
      <select id="ph-kind" style="max-width:160px"><option value="">All files</option><option>engine</option><option>gearbox</option><option>chassis</option><option>suspension</option></select>
      <input id="ph-q" placeholder="Search name or key..." style="max-width:260px">
      <label class="row"><input type="checkbox" id="ph-named"> Named only</label>
      <label class="row"><input type="checkbox" id="ph-changed"> Changed only</label>
      <span id="ph-count" class="status"></span><span id="ph-msg" class="status"></span>
    </div>
    <div class="card" style="padding:0;overflow:auto;max-height:70vh"><table class="phys" id="ph-table"><tr><td style="padding:14px">Loading...</td></tr></table></div>`);
  let data;
  try { data = await api("/api/physics?path=" + encodeURIComponent(S.projectPath)); }
  catch (e) { $("#ph-table").innerHTML = `<tr><td style="padding:14px">${esc(e.message)}</td></tr>`; return; }
  if (data.error) { $("#ph-table").innerHTML = `<tr><td style="padding:14px">${esc(data.error)}</td></tr>`; return; }
  const F = S.physFilter ||= { kind: "", q: "", named: false, changed: false };
  $("#ph-kind").value = F.kind; $("#ph-q").value = F.q; $("#ph-named").checked = F.named; $("#ph-changed").checked = F.changed;
  const ov = p.cfg.overrides ||= {};
  const okey = r => `${r.kind}.${r.key}` + (r.count > 1 ? `#${r.idx}` : "");
  const fmt = v => v === null || v === undefined ? "" : Array.isArray(v) ? v.map(x => typeof x === "number" ? +x.toPrecision(6) : x).join(", ") : typeof v === "number" ? String(+v.toPrecision(7)) : String(v);
  const parse = (t, like) => {
    const parts = t.split(",").map(x => x.trim()).filter(x => x !== "").map(Number);
    if (parts.some(isNaN)) throw new Error("numbers only");
    if (Array.isArray(like)) { if (parts.length !== like.length) throw new Error(`needs ${like.length} values`); return parts; }
    if (parts.length !== 1) throw new Error("needs one value");
    return parts[0];
  };
  const draw = () => {
    const q = F.q.toLowerCase();
    const rows = data.rows.filter(r => (!F.kind || r.kind === F.kind) && (!F.named || r.name)
      && (!F.changed || ov[okey(r)] !== undefined || (r.built !== null && fmt(r.built) !== fmt(r.donor)))
      && (!q || (r.name + " " + r.key + " " + r.help).toLowerCase().includes(q)));
    $("#ph-count").textContent = `${rows.length} of ${data.rows.length} fields` + (rows.length > 600 ? " (first 600 shown)" : "");
    $("#ph-table").innerHTML = `<tr><th>File</th><th>Field</th><th>Donor</th><th>Built</th><th>Override</th></tr>` + rows.slice(0, 600).map((r, i) => {
      const o = ov[okey(r)];
      const name = r.name ? `<b>${esc(r.name)}</b>${r.unit ? ` <small>${esc(r.unit)}</small>` : ""}<br>` : "";
      return `<tr title="${esc(r.help)}"><td>${r.kind}</td>
        <td>${name}<code>${r.key}</code>${r.count > 1 ? ` <small>#${r.idx}/${r.count}</small>` : ""}${r.object ? ` <small>in ${r.object}</small>` : ""}</td>
        <td class="v">${esc(fmt(r.donor))}</td><td class="v${r.built !== null && fmt(r.built) !== fmt(r.donor) ? " chg" : ""}">${esc(fmt(r.built))}</td>
        <td><input data-i="${data.rows.indexOf(r)}" value="${esc(fmt(o))}" placeholder="${esc(fmt(r.built ?? r.donor))}" class="${o !== undefined ? "set" : ""}"></td></tr>`;
    }).join("");
    document.querySelectorAll("#ph-table input").forEach(inp => inp.onchange = async () => {
      const r = data.rows[+inp.dataset.i];
      try {
        if (inp.value.trim() === "") delete ov[okey(r)]; else ov[okey(r)] = parse(inp.value, r.donor);
        inp.classList.toggle("set", inp.value.trim() !== ""); inp.classList.remove("bad");
        await saveCfg();
        $("#ph-msg").textContent = "Saved. Build again to apply.";
      } catch (e) { inp.classList.add("bad"); $("#ph-msg").textContent = `${r.key}: ${e.message}`; }
    });
  };
  $("#ph-kind").onchange = e => { F.kind = e.target.value; draw(); };
  $("#ph-q").oninput = e => { F.q = e.target.value; draw(); };
  $("#ph-named").onchange = e => { F.named = e.target.checked; draw(); };
  $("#ph-changed").onchange = e => { F.changed = e.target.checked; draw(); };
  draw();
}

function viewArt() {
  const p = S.project;
  const liv = p.liveries || {};
  mount(html`
    <h1>Menu art</h1>
    <p class="lead">The car-select image (one per livery) and the manufacturer logo. Render the images from your Blender file in the livery
      colours below, or drop your own <code>livery_&lt;id&gt;.png</code> files into the project's <code>art</code> folder.</p>
    <h2>Livery colours</h2>
    <div class="card row">${Object.entries(liv).map(([id, c]) => `<label class="swatch"><input type="color" data-liv="${id}" value="${esc(c)}">#${id}</label>`).join("")}
      <label class="f" style="max-width:160px">Camera angle (deg)<input type="number" id="a-az" value="${p.cfg.art.render_azimuth}"></label></div>
    <h2>Logo</h2>
    <div class="card row"><input type="file" id="a-logo" accept="image/png" style="max-width:320px">
      <span class="status">${p.cfg.art.logo ? "current: " + esc(p.cfg.art.logo) : "PNG with a transparent background; it is filled white for the dark menu."}</span></div>
    <div class="row"><button id="a-render" ${p.car_blend ? "" : "disabled"}>Render from my model</button>
      <button id="a-build">Make game images</button><button class="ghost" id="a-folder">Open art folder</button></div>
    ${p.previews.length ? `<h2>Previews</h2><div class="thumbs">${p.previews.map(f => `<figure><img src="${fileUrl(f)}"><figcaption>${esc(f.split(/[\\/]/).pop())}</figcaption></figure>`).join("")}</div>` : ""}`);
  document.querySelectorAll("[data-liv]").forEach(el => el.onchange = async () => { p.cfg.art.liveries[el.dataset.liv] = el.value; await saveCfg(); });
  $("#a-az").onchange = async e => { p.cfg.art.render_azimuth = Number(e.target.value); await saveCfg(); };
  $("#a-logo").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    const r = await fetch(`/api/upload?path=${encodeURIComponent(p.path)}&name=logo.png`, { method: "POST", body: f });
    p.cfg.art.logo = (await r.json()).rel; await saveCfg(); render();
  };
  $("#a-render").onclick = () => runJob("render", {}, () => runJob("art"));
  $("#a-build").onclick = () => runJob("art");
  $("#a-folder").onclick = () => api("/api/open", { path: p.path + "\\art\\" });
}

function viewBuild() {
  const p = S.project;
  const b = p.build;
  mount(html`
    <h1>Build &amp; install</h1>
    <p class="lead">Build writes the car's game files into the project. Check runs the tests that catch the game's silent failures.
      Install copies the car into the game (fully reversible with Uninstall).</p>
    <div class="row"><button id="b-build">Build</button><button class="ghost" id="b-doctor">Check</button>
      <button id="b-install" ${b ? "" : "disabled"}>Install</button><button class="ghost" id="b-uninstall" ${p.installed ? "" : "disabled"}>Uninstall</button>
      <span class="status"><span class="dot ${p.installed ? "ok" : ""}"></span>${p.installed ? "installed" : "not installed"}</span></div>
    <div id="b-result">${doctorHtml()}</div>
    ${b ? `<h2>Last build</h2><div class="card kv">
      <div>Engine / gearbox</div><div>${esc(b.physics.engine)} / ${esc(b.physics.gearbox)}</div>
      <div>Physics base name</div><div>${esc(b.physics.base)} (kept from the donor)</div>
      <div>Meshes replaced</div><div>${b.meshes}</div><div>Menu art files</div><div>${b.art}</div>
      ${Object.entries(b.paks).map(([n, x]) => `<div>${esc(n)}</div><div>${x.files} files, ${x.added} added, ${x.mb} MB</div>`).join("")}</div>` : ""}`);
  $("#b-build").onclick = () => runJob("build", {}, () => runJob("doctor", {}, showDoctor));
  $("#b-doctor").onclick = () => runJob("doctor", {}, showDoctor);
  $("#b-install").onclick = () => runJob("install");
  $("#b-uninstall").onclick = () => { if (confirm("Remove this car from the game?")) runJob("uninstall"); };
}
let lastDoctor = null;   // drawn by viewBuild (the page re-renders after every job)
function showDoctor(j) { lastDoctor = j.result; }
function doctorHtml() {
  if (!lastDoctor) return "";
  return `<h2>Checks</h2><div class="card"><ul class="list">${lastDoctor.map(r =>
    `<li><span class="dot ${r.level === "ok" ? "ok" : r.level === "warn" ? "warn" : "fail"}"></span>${esc(r.msg)}</li>`).join("")}</ul></div>`;
}

function viewTest() {
  const p = S.project;
  const last = p.test_results.at(-1);
  mount(html`
    <h1>Test</h1>
    <p class="lead">Runs the game by itself: it starts a Custom Race straight away with the car and track you last used in Custom Race, lets the
      AI drive, records telemetry and checks for crashes. <b>Once</b>, start a Custom Race with your car by hand so the game remembers it.</p>
    <div class="row"><label class="f" style="max-width:160px">Drive for (s)<input type="number" id="t-sec" value="120"></label>
      <button id="t-run" ${p.installed ? "" : "disabled"}>Run track test</button>
      <button class="ghost" id="t-menu" ${p.installed ? "" : "disabled"}>Screenshot the menus</button>
      ${p.installed ? "" : '<span class="status">Install the car first.</span>'}</div>
    ${last ? `<h2>Last run</h2><div class="card kv">
      <div>Result</div><div><span class="dot ${last.result === "ok" ? "ok" : "fail"}"></span> ${esc(last.result)} · ${esc(last.detail)}</div>
      ${last.telemetry ? `<div>Top speed</div><div>${last.telemetry.top_speed_kmh} km/h (target ${p.cfg.powertrain.top_speed_kmh})</div>
      <div>Max rpm</div><div>${last.telemetry.max_rpm} / limit ${last.telemetry.rev_limit}</div>
      <div>Est. 0-100 km/h</div><div>${last.telemetry.est_0_100_s ?? "n/a"} s (from low-speed acceleration)</div>
      <div>Acceleration (g, p90)</div><div>${Object.entries(last.telemetry.accel_g_p90 || {}).map(([k, v]) => `${k} km/h: ${v}`).join(" · ")}</div>` : ""}
      ${last.dumps?.length ? `<div>Crash dumps</div><div>${last.dumps.map(esc).join("<br>")}</div>` : ""}</div>` : ""}
    ${p.shots.length ? `<h2>Screenshots</h2><div class="thumbs">${p.shots.map(f => `<figure><img src="${fileUrl(f)}"><figcaption>${esc(f.split(/[\\/]/).pop())}</figcaption></figure>`).join("")}</div>` : ""}`);
  $("#t-run").onclick = () => runJob("test", { seconds: Number($("#t-sec").value) });
  $("#t-menu").onclick = () => runJob("menu");
}

refresh();
