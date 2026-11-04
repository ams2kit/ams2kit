// Long actions run one at a time on the server as a background job; the page polls its log.
import { reactive } from "vue";
import { api } from "./api.js";
import { store, refresh } from "./store.js";

export const job = reactive({ visible: false, title: "", running: false, failed: false, log: "" });

let since = 0, timer = null, onDone = null;

export async function runJob(action, extra = {}, done) {
  try {
    await api("/api/job", { action, path: store.projectPath, ...extra });
  } catch (e) { alert(e.message); return; }
  since = 0; onDone = done;
  Object.assign(job, { visible: true, title: action.replace("_", " "), running: true, failed: false, log: "" });
  poll();
}

async function poll() {
  clearTimeout(timer);
  const j = await api("/api/job?since=" + since);
  if (j.log.length) { job.log += j.log.join("\n") + "\n"; since += j.log.length; }
  job.running = j.running;
  job.failed = !!j.error;
  if (j.running) { timer = setTimeout(poll, 700); return; }
  if (j.error && j.trace) job.log += "\n" + j.trace;
  const cb = onDone; onDone = null;
  if (cb) await cb(j);   // may start the next job
  await refresh();
}
