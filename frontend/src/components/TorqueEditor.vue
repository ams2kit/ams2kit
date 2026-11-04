<script setup>
// Torque curve editor (vue-chartjs + chartjs-plugin-dragdata): drag the points of Specs
// powertrain.torque_curve (ICE) and the rev-limit handle. Power is derived and drawn in its own chart
// under the torque chart (same rpm axis, no second y-axis). EVs: the motor curve is computed on Build
// from power / rev limit / base speed, shown read-only.
import { computed, ref as vref } from "vue";
import { Scatter } from "vue-chartjs";
import { store, saveCfg } from "../store.js";
import { C, HP, baseOptions, kw, niceMax, powerPts, ref } from "../chart.js";

const props = defineProps({ curves: { type: Object, required: true } });

const pt = computed(() => store.project.cfg.powertrain);
const ev = computed(() => pt.value.type === "ev");
const curve = computed(() => pt.value.torque_curve || []);

const mine = computed(() => {
  if (!ev.value) return [...curve.value].sort((a, b) => a[0] - b[0]);
  const b = props.curves.built_torque;
  return b ? b.filter(r => r[2] >= 0 && r[0] <= pt.value.rev_limit).map(r => [r[0], r[2]]) : [];
});
const donor = computed(() => (props.curves.donor_torque || [])
  .filter(r => r[2] > 0 && r[0] <= props.curves.donor_rev_limit + 300).map(r => [r[0], r[2]]));
const minePow = computed(() => powerPts(mine.value));
const donorPow = computed(() => powerPts(donor.value));

// axes: hold still while dragging, otherwise fit the data
const frozen = vref(null);
const axes = computed(() => frozen.value || {
  x: niceMax(Math.max(pt.value.rev_limit, ...mine.value.map(p => p[0]), ...donor.value.map(p => p[0])) * 1.04),
  t: niceMax(Math.max(100, ...mine.value.map(p => p[1]), ...donor.value.map(p => p[1])) * 1.1),
  p: niceMax(Math.max(50, ...minePow.value.map(p => p[1]), ...donorPow.value.map(p => p[1])) * 1.1),
});

const peak = pts => pts.reduce((m, p) => p[1] > m[1] ? p : m, [0, 0]);
const peakT = computed(() => peak(mine.value));
const peakP = computed(() => peak(minePow.value));
const menuOff = computed(() => !ev.value && mine.value.length >= 3 &&
  (Math.abs(pt.value.power_kw - peakP.value[1]) > 0.02 * peakP.value[1] || Math.abs(pt.value.torque_nm - peakT.value[1]) > 0.02 * peakT.value[1]));

// dataset order matters: the drag callbacks key on it
const D_MINE = 0, D_KNOB = 3;
const mineLabel = computed(() => ev.value ? "Computed (last build)" : "Yours (Specs)");
const revLine = (top) => ref("_limit", [[pt.value.rev_limit, 0], [pt.value.rev_limit, top]], C.limit, { borderDash: [4, 3], borderWidth: 1.5 });

const torqueData = computed(() => ({ datasets: [
  ref(mineLabel.value, mine.value, C.mine, ev.value ? {} : { pointRadius: 5, pointHoverRadius: 7, pointHitRadius: 14, dragData: true }),
  ref("Donor", donor.value, C.donor, { borderDash: [5, 4] }),
  revLine(axes.value.t),
  { label: `_Rev limit`, data: [{ x: pt.value.rev_limit, y: axes.value.t }], pointStyle: "rectRounded", pointRadius: 7, pointHoverRadius: 9,
    pointHitRadius: 14, backgroundColor: C.limit, borderColor: C.limit, dragData: true, clip: false },
] }));
const powerData = computed(() => ({ datasets: [
  ref(mineLabel.value, minePow.value, C.mine),
  ref("Donor", donorPow.value, C.donor, { borderDash: [5, 4] }),
  revLine(axes.value.p),
] }));

const status = vref("");
const sel = vref(null);
const snap = (v, s) => Math.round(v / s) * s;

async function save() {
  if (!ev.value) pt.value.torque_curve = [...curve.value].sort((a, b) => a[0] - b[0]);
  await saveCfg();
  status.value = "Saved. Build again to apply.";
}

function setPoint(i, rpm, nm) {
  const c = curve.value;
  const lo = i > 0 ? c[i - 1][0] + 50 : 0, hi = i < c.length - 1 ? c[i + 1][0] - 50 : 30000;
  c[i] = [Math.min(hi, Math.max(lo, snap(rpm, 50))), Math.max(0, Math.round(nm))];
  return c[i];
}

// the plugin hands over the new value before writing it back: snap / clamp it in place
function onDrag(e, d, i, v) {
  frozen.value ??= { ...axes.value };
  if (d === D_KNOB) { pt.value.rev_limit = Math.max(1000, snap(v.x, 50)); v.x = pt.value.rev_limit; v.y = axes.value.t; return true; }
  if (d !== D_MINE || ev.value) return false;
  sel.value = i;
  [v.x, v.y] = setPoint(i, v.x, v.y);
  return true;
}
async function onDragEnd() { frozen.value = null; await save(); }

const torqueOpts = computed(() => baseOptions({
  x: { max: axes.value.x, ticks: { color: "transparent" } }   /* same tick space as the power chart, so the x pixels line up */, y: { max: axes.value.t, title: "Torque (Nm)" }, onDrag, onDragEnd,
  tooltip: { callbacks: { label: c => c.datasetIndex === D_KNOB ? `Rev limit ${c.parsed.x} rpm` : `${c.dataset.label}: ${Math.round(c.parsed.y)} Nm @ ${Math.round(c.parsed.x)} rpm` } },
}));
const powerOpts = computed(() => {
  const o = baseOptions({ x: { max: axes.value.x, title: "rpm" }, y: { max: axes.value.p, title: "Power (kW)" },
    tooltip: { mode: "nearest", intersect: false, callbacks: { label: c => `${c.dataset.label}: ${Math.round(c.parsed.y)} kW (${Math.round(c.parsed.y * HP)} hp) @ ${Math.round(c.parsed.x)} rpm` } } });
  o.plugins.dragData = false;
  o.plugins.legend.display = false;
  return o;
});

// double-click: on a point removes it, on empty space adds one
const tchart = vref(null);
async function dblclick(e) {
  if (ev.value) return;
  const chart = tchart.value?.chart;
  if (!chart) return;
  const hit = chart.getElementsAtEventForMode(e, "nearest", { intersect: true }, false).find(h => h.datasetIndex === D_MINE);
  if (hit) return remove(hit.index);
  const { x, y } = chart.scales, rect = chart.canvas.getBoundingClientRect();
  const px = e.clientX - rect.left, py = e.clientY - rect.top;
  if (px < x.left || px > x.right || py < y.top || py > y.bottom) return;
  const rpm = Math.max(0, snap(x.getValueForPixel(px), 50)), nm = Math.max(0, Math.round(y.getValueForPixel(py)));
  if (curve.value.some(q => Math.abs(q[0] - rpm) < 50)) return;
  curve.value.push([rpm, nm]);
  curve.value.sort((a, b) => a[0] - b[0]);
  sel.value = curve.value.findIndex(q => q[0] === rpm);
  await save();
}

async function remove(i) {
  if (curve.value.length <= 3) { status.value = "A torque curve needs at least 3 points."; return; }
  curve.value.splice(i, 1);
  sel.value = null;
  await save();
}

async function edit(i, col, e) {
  const v = Number(e.target.value);
  if (isNaN(v)) return;
  const [r, t] = curve.value[i];
  col === 0 ? setPoint(i, v, t) : setPoint(i, r, v);
  await save();
}

async function fromDonor() {
  pt.value.torque_curve = donor.value.filter(p => p[0] <= props.curves.donor_rev_limit).map(p => [p[0], Math.round(p[1])]);
  await save();
}

async function usePeaks() {
  pt.value.power_kw = Math.round(peakP.value[1]);
  pt.value.torque_nm = Math.round(peakT.value[1]);
  await save();
}
const fmt = (v, d = 0) => v.toLocaleString(undefined, { maximumFractionDigits: d });
</script>

<template>
  <h2 style="margin-top:0">Torque curve</h2>
  <p v-if="ev" class="help">Electric: the motor curve is computed on Build from power, rev limit and base speed (Specs).
    {{ curves.built_torque ? "Shown from the last build." : "Build once to see it." }} You can still drag the rev-limit handle.</p>
  <p v-else class="help">Drag a point to move it, double-click empty space to add one, double-click a point to remove it.
    Drag the yellow handle to move the rev limit.</p>
  <p v-if="curves.boost && !ev" class="help warn">The donor is turbocharged: its table is before boost, so it reads low. Your curve is the real (boosted) torque.</p>

  <div class="ce-wrap">
    <div style="height:290px" @dblclick="dblclick"><Scatter ref="tchart" :data="torqueData" :options="torqueOpts" /></div>
    <div style="height:170px"><Scatter :data="powerData" :options="powerOpts" /></div>
    <div v-if="!ev && curve.length < 3" class="ce-empty">
      <p>No torque curve yet.</p>
      <button @click="fromDonor" :disabled="!donor.length">Start from the donor's curve</button>
    </div>
  </div>

  <div class="row ce-foot">
    <template v-if="!ev && sel !== null && curve[sel]">
      <span class="muted">Point {{ sel + 1 }}</span>
      <input type="number" step="50" :value="curve[sel][0]" @change="edit(sel, 0, $event)" style="width:100px"> rpm
      <input type="number" step="1" :value="curve[sel][1]" @change="edit(sel, 1, $event)" style="width:90px"> Nm
      <button class="ghost small" @click="remove(sel)">Remove</button>
    </template>
    <span v-if="mine.length >= 2" class="muted">Peak {{ fmt(peakP[1]) }} kW ({{ fmt(peakP[1] * HP) }} hp) @ {{ fmt(peakP[0]) }},
      {{ fmt(peakT[1]) }} Nm @ {{ fmt(peakT[0]) }} rpm</span>
    <template v-if="menuOff">
      <span class="muted">· menu says {{ fmt(pt.power_kw) }} kW / {{ fmt(pt.torque_nm) }} Nm</span>
      <button class="ghost small" @click="usePeaks">Use curve peaks</button>
    </template>
    <span class="status">{{ status }}</span>
  </div>

  <details v-if="mine.length" class="ce-table">
    <summary>Show as table</summary>
    <table class="phys">
      <tr><th>rpm</th><th>Torque (Nm)</th><th>Power (kW)</th><th>Power (hp)</th></tr>
      <tr v-for="p in mine" :key="p[0]"><td class="v">{{ fmt(p[0]) }}</td><td class="v">{{ fmt(p[1]) }}</td>
        <td class="v">{{ fmt(kw(p[1], p[0]), 1) }}</td><td class="v">{{ fmt(kw(p[1], p[0]) * HP) }}</td></tr>
    </table>
  </details>
</template>
