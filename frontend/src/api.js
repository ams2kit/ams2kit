// The local JSON API: ams2kit/ui/server.py and actions.py.
export async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

// A project file (preview image, screenshot); the timestamp defeats the browser cache after a re-render.
export const fileUrl = p => "/file?path=" + encodeURIComponent(p) + "&t=" + Date.now();

export const basename = p => p.split(/[\\/]/).pop();

export function getPath(obj, path) {
  return path.split(".").reduce((o, k) => o?.[k], obj);
}

export function setPath(obj, path, val) {
  const ks = path.split(".");
  const o = ks.slice(0, -1).reduce((o, k) => o[k], obj);
  o[ks.at(-1)] = val;
}
