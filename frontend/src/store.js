// App state shared by the views. The open project and step survive a reload (localStorage).
import { reactive, watch } from "vue";
import { api } from "./api.js";

export const STEPS = [
  { id: "setup", label: "Setup" },
  { id: "car", label: "Car & donor" },
  { id: "model", label: "3D model", needsProject: true },
  { id: "specs", label: "Specs", needsProject: true },
  { id: "physics", label: "Physics", needsProject: true },
  { id: "art", label: "Menu art", needsProject: true },
  { id: "sound", label: "Sound", needsProject: true },
  { id: "build", label: "Build & install", needsProject: true },
  { id: "test", label: "Test", needsProject: true },
];

const saved = (() => { try { return JSON.parse(localStorage.getItem("ams2kit") || "{}"); } catch { return {}; } })();

export const store = reactive({
  step: saved.step || "setup",
  projectPath: saved.projectPath || null,
  state: null,      // /api/state: game, Blender, projects, installed cars
  project: null,    // /api/project for projectPath
  donors: null,     // /api/donors, loaded once
  // view state kept while switching steps
  carPicker: { filter: "", cls: "", sort: "class", donor: null },
  physFilter: { tab: "curves", kind: "", q: "", named: false, changed: false },
  doctor: null,     // last Check result, shown on Build
});

watch(() => [store.projectPath, store.step], ([projectPath, step]) => {
  try { localStorage.setItem("ams2kit", JSON.stringify({ projectPath, step })); } catch {}
});

export async function refresh() {
  store.state = await api("/api/state");
  if (store.projectPath) {
    try { store.project = await api("/api/project?path=" + encodeURIComponent(store.projectPath)); }
    catch { store.project = null; store.projectPath = null; }
  }
}

export async function openProject(path) {
  store.projectPath = path;
  store.step = "model";
  await refresh();
}

export async function saveCfg() {
  const r = await api("/api/project/save", { path: store.projectPath, cfg: store.project.cfg });
  store.project.errors = r.errors;
}

export async function loadDonors() {
  store.donors ??= await api("/api/donors");
  return store.donors;
}

export function isDone(step) {
  const p = store.project, s = store.state;
  if (step === "setup") return !!(s?.game && s?.blender);
  if (!p) return false;
  return { car: p.donor_unpacked, model: p.meshes_built, specs: !p.errors.length, art: p.previews.length > 0,
           build: p.installed, test: p.test_results.some(t => t.result === "ok") }[step] || false;
}
