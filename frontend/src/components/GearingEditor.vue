<script setup>
// Gearing editor (ICE, vue-chartjs + chartjs-plugin-dragdata): engine rpm against road speed for each
// gear, from Specs powertrain.gears, final_drive and rev_limit, with the rolling radius the build uses.
// Drag a gear's handle (where it meets the rev limit) left or right to change its ratio.
import { computed, ref as vref } from "vue";
import { Scatter } from "vue-chartjs";
import { store, saveCfg } from "../store.js";
import { C, baseOptions, niceMax, ref } from "../chart.js";

const props = defineProps({ curves: { type: Object, required: true } });

const pt = computed(() => store.project.cfg.powertrain);
const gears = computed(() => pt.value.gears || []);
const rl = computed(() => pt.value.rev_limit);
const r = computed(() => props.curves.radius);
const ready = computed(() => gears.value.length > 0 && pt.value.final_drive > 0);
const donorOk = computed(() => props.curves.donor_gears.length > 0 && props.curves.donor_gears.length <= 10);

const K = computed(() => 2 * Math.PI / 60 * r.value * 3.6);          // km/h per (rpm / overall ratio)
const kmh = (rpm, g, fd) => rpm * K.value / (g * fd);
const ratioAt = v => rl.value * K.value / (v * pt.value.final_drive);

const tops = computed(() => gears.value.map(g => kmh(rl.value, g, pt.value.final_drive)));
const donorTops = computed(() => donorOk.value
  ? props.curves.donor_gears.map(g => kmh(rl.value, g, props.curves.donor_final_drive)) : []);

const frozen = vref(null);
const axes = computed(() => frozen.value || { x: niceMax(Math.max(100, ...tops.value, ...donorTops.value) * 1.06), y: niceMax(rl.value * 1.06) });

// the rpm trace of a full-throttle run shifting at the rev limit
function saw(gs, vs) {
  const pts = [[0, 0]];
  vs.forEach((v, i) => {
    pts.push([v, rl.value]);
    if (i < gs.length - 1) pts.push([v, rl.value * gs[i + 1] / gs[i]]);
  });
  return pts;
}

const D_HANDLES = 0;
const data = computed(() => ({ datasets: [
  { label: "_gears", data: ready.value ? tops.value.map(v => ({ x: v, y: rl.value })) : [], backgroundColor: C.mine, borderColor: "#1d1d21",
    borderWidth: 2, pointRadius: 6, pointHoverRadius: 8, pointHitRadius: 14, dragData: true },
  ...(ready.value ? [ref("Yours (Specs)", saw(gears.value, tops.value), C.mine)] : []),
  ...(donorTops.value.length ? [ref("Donor", saw(props.curves.donor_gears, donorTops.value), C.donor, { borderDash: [5, 4] })] : []),
  ...(ready.value ? tops.value.map((v, i) => ref("_g" + i, [[0, 0], [v, rl.value]], C.faint, { borderWidth: 1 })) : []),
  ref("_limit", [[0, rl.value], [axes.value.x, rl.value]], C.limit, { borderDash: [4, 3], borderWidth: 1.5 }),
] }));

const status = vref("");
async function save() {
  await saveCfg();
  status.value = "Saved. Build again to apply.";
}

function setRatio(i, g) {
  const gs = gears.value;
  const hi = i > 0 ? gs[i - 1] - 0.01 : 20, lo = i < gs.length - 1 ? gs[i + 1] + 0.01 : 0.2;
  gs[i] = +Math.min(hi, Math.max(lo, g)).toFixed(3);
}

function onDrag(e, d, i, v) {
  if (d !== D_HANDLES) return false;
  frozen.value ??= { ...axes.value };
  setRatio(i, ratioAt(Math.max(5, v.x)));
  v.x = tops.value[i];
  v.y = rl.value;
  return true;
}
async function onDragEnd() { frozen.value = null; await save(); }

const options = computed(() => baseOptions({
  x: { max: axes.value.x, title: "km/h" }, y: { max: axes.value.y, title: "rpm" }, onDrag, onDragEnd,
  tooltip: { callbacks: { label: c => c.datasetIndex === D_HANDLES
    ? `Gear ${c.dataIndex + 1}: ratio ${gears.value[c.dataIndex]}, ${Math.round(c.parsed.x)} km/h at the limit`
    : `${c.dataset.label}: ${Math.round(c.parsed.y)} rpm @ ${Math.round(c.parsed.x)} km/h` } },
}));

async function edit(i, e) {
  const v = Number(e.target.value);
  if (!(v > 0)) return;
  setRatio(i, v);
  await save();
}

async function editFinal(e) {
  const v = Number(e.target.value);
  if (!(v > 0)) return;
  pt.value.final_drive = v;
  await save();
}

async function fromDonor() {
  pt.value.gears = [...props.curves.donor_gears];
  pt.value.final_drive = props.curves.donor_final_drive;
  await save();
}
const fmt = (v, d = 0) => v.toLocaleString(undefined, { maximumFractionDigits: d });
</script>

<template>
  <h2 style="margin-top:0">Gearing</h2>
  <p class="help">Engine speed against road speed, shifting at the rev limit. Drag a gear's handle left or right to change its ratio.
    Speeds use a rolling radius of {{ fmt(r, 3) }} m ({{ curves.radius_source }}).</p>
  <p v-if="ready && gears.length !== curves.donor_gears.length" class="help warn">
    The donor gearbox lists {{ curves.donor_gears.length }} gear options; you have {{ gears.length }}. The game may expect the donor's count.</p>

  <div class="ce-wrap">
    <div style="height:320px"><Scatter :data="data" :options="options" /></div>
    <div v-if="!ready" class="ce-empty">
      <p>Enter gear ratios and a final drive, or start from the donor's.</p>
      <button v-if="donorOk" @click="fromDonor">Start from the donor's gearing</button>
      <p v-else-if="curves.donor_gears.length" class="muted">The donor gearbox lists {{ curves.donor_gears.length }} ratio options (a setup choice), so there is no single set to copy.</p>
    </div>
  </div>

  <div class="row ce-foot">
    <label class="row">Final drive <input type="number" step="0.01" min="0" :value="pt.final_drive || ''" @change="editFinal" style="width:90px"></label>
    <span v-if="ready" class="muted">Top gear at the limit: {{ fmt(tops.at(-1)) }} km/h</span>
    <span class="status">{{ status }}</span>
  </div>
  <table v-if="ready" class="phys gears">
    <tr><th>Gear</th><th>Ratio</th><th>km/h at limit</th><th>rpm after upshift</th></tr>
    <tr v-for="(g, i) in gears" :key="i">
      <td>{{ i + 1 }}</td>
      <td><input type="number" step="0.01" :value="g" @change="edit(i, $event)" style="width:90px"></td>
      <td class="v">{{ fmt(tops[i]) }}</td>
      <td class="v">{{ i < gears.length - 1 ? fmt(rl * gears[i + 1] / g) : "" }}</td>
    </tr>
  </table>
</template>
