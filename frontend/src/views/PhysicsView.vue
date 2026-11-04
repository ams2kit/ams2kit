<script setup>
// Every field of the donor's engine/gearbox/chassis/suspension files; edits go to car.toml [overrides].
import { computed, reactive, ref, watch } from "vue";
import { api } from "../api.js";
import { store, saveCfg } from "../store.js";

const MAX_ROWS = 600;
const F = store.physFilter;
const data = ref(null);
const error = ref("");
const message = ref("");
const bad = reactive(new Map());   // override key -> the text that did not parse (kept in the box to fix)

// the Built column changes after every build, which replaces store.project
watch(() => store.project, async () => {
  store.project.cfg.overrides ??= {};
  try {
    const d = await api("/api/physics?path=" + encodeURIComponent(store.projectPath));
    if (d.error) error.value = d.error;
    else { d.rows.forEach((r, i) => r.i = i); data.value = d; error.value = ""; }
  } catch (e) { error.value = e.message; }
}, { immediate: true });

const overrides = () => store.project.cfg.overrides;
const okey = r => `${r.kind}.${r.key}` + (r.count > 1 ? `#${r.idx}` : "");
const fmt = v => v === null || v === undefined ? "" : Array.isArray(v) ? v.map(x => typeof x === "number" ? +x.toPrecision(6) : x).join(", ") : typeof v === "number" ? String(+v.toPrecision(7)) : String(v);
const changedByBuild = r => r.built !== null && fmt(r.built) !== fmt(r.donor);

function parse(t, like) {
  const parts = t.split(",").map(x => x.trim()).filter(x => x !== "").map(Number);
  if (parts.some(isNaN)) throw new Error("numbers only");
  if (Array.isArray(like)) { if (parts.length !== like.length) throw new Error(`needs ${like.length} values`); return parts; }
  if (parts.length !== 1) throw new Error("needs one value");
  return parts[0];
}

const rows = computed(() => {
  if (!data.value) return [];
  const q = F.q.toLowerCase(), ov = overrides();
  return data.value.rows.filter(r => (!F.kind || r.kind === F.kind) && (!F.named || r.name)
    && (!F.changed || ov[okey(r)] !== undefined || changedByBuild(r))
    && (!q || (r.name + " " + r.key + " " + r.help).toLowerCase().includes(q)));
});

async function setOverride(r, e) {
  const k = okey(r), t = e.target.value.trim();
  try {
    if (t === "") delete overrides()[k]; else overrides()[k] = parse(t, r.donor);
    bad.delete(k);
    await saveCfg();
    message.value = "Saved. Build again to apply.";
  } catch (err) { bad.set(k, e.target.value); message.value = `${r.key}: ${err.message}`; }
}
</script>

<template>
  <h1>Physics</h1>
  <p class="lead">Every setting in the car's physics files. <b>Donor</b> is the donor car's value, <b>Built</b> what the last build wrote
    (after Specs), <b>Override</b> your value, applied last on Build. Leave an override empty to keep the built value.
    Lists keep the donor's length (e.g. <code>0.3, 0, 0</code>).</p>
  <div class="row" style="margin-bottom:10px">
    <select v-model="F.kind" style="max-width:160px"><option value="">All files</option><option>engine</option><option>gearbox</option><option>chassis</option><option>suspension</option></select>
    <input v-model="F.q" placeholder="Search name or key..." style="max-width:260px">
    <label class="row"><input v-model="F.named" type="checkbox"> Named only</label>
    <label class="row"><input v-model="F.changed" type="checkbox"> Changed only</label>
    <span v-if="data" class="status">{{ rows.length }} of {{ data.rows.length }} fields{{ rows.length > MAX_ROWS ? ` (first ${MAX_ROWS} shown)` : "" }}</span>
    <span class="status">{{ message }}</span>
  </div>
  <div class="card" style="padding:0;overflow:auto;max-height:70vh">
    <table class="phys">
      <tr v-if="error || !data"><td style="padding:14px">{{ error || "Loading..." }}</td></tr>
      <template v-else>
        <tr><th>File</th><th>Field</th><th>Donor</th><th>Built</th><th>Override</th></tr>
        <tr v-for="r in rows.slice(0, MAX_ROWS)" :key="r.i" :title="r.help">
          <td>{{ r.kind }}</td>
          <td>
            <template v-if="r.name"><b>{{ r.name }}</b> <small v-if="r.unit">{{ r.unit }}</small><br></template>
            <code>{{ r.key }}</code>
            <small v-if="r.count > 1"> #{{ r.idx }}/{{ r.count }}</small>
            <small v-if="r.object"> in {{ r.object }}</small>
          </td>
          <td class="v">{{ fmt(r.donor) }}</td>
          <td class="v" :class="{ chg: changedByBuild(r) }">{{ fmt(r.built) }}</td>
          <td><input :value="bad.has(okey(r)) ? bad.get(okey(r)) : fmt(overrides()[okey(r)])" :placeholder="fmt(r.built ?? r.donor)"
                     :class="{ set: overrides()[okey(r)] !== undefined, bad: bad.has(okey(r)) }" @change="setOverride(r, $event)"></td>
        </tr>
      </template>
    </table>
  </div>
</template>
