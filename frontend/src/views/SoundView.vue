<script setup>
import { computed, onMounted, ref } from "vue";
import { api, fileUrl } from "../api.js";
import { store, saveCfg } from "../store.js";
import { runJob } from "../job.js";

const p = computed(() => store.project);
const kits = ref(null), info = ref(null), filter = ref(""), error = ref("");

async function load() {
  info.value = await api("/api/sound?path=" + encodeURIComponent(store.projectPath));
}
onMounted(async () => {
  await load();
  try { kits.value = (await api("/api/sound/kits")).kits; } catch (e) { error.value = e.message; }
});

const donor = computed(() => p.value.cfg.car.donor);
const current = computed(() => p.value.cfg.sound.kit || donor.value);
const engineBank = k => k.banks.find(b => b.includes("/Sort/") || b.includes("/Engine/")) || "";
const shown = computed(() => {
  const f = filter.value.toLowerCase();
  return (kits.value || []).filter(k => (k.display + k.name + k.cls + k.engine).toLowerCase().includes(f));
});
// cars that share the engine banks sound the same
const sharing = computed(() => {
  const n = {};
  for (const k of kits.value || []) n[engineBank(k)] = (n[engineBank(k)] || 0) + 1;
  return n;
});

async function pick(name) {
  p.value.cfg.sound.kit = name.toLowerCase() === donor.value.toLowerCase() ? "" : name;
  await saveCfg();
  await load();
}
async function setReplace(e) { p.value.cfg.sound.replace_samples = e.target.checked; await saveCfg(); }

async function upload(bank, row, e) {
  const f = e.target.files[0];
  if (!f) return;
  const r = await fetch(`/api/upload?path=${encodeURIComponent(p.value.path)}&bank=${encodeURIComponent(bank)}&name=${encodeURIComponent(row.file)}`,
                        { method: "POST", body: f });
  if (!r.ok) alert((await r.json()).error);
  e.target.value = "";
  await load();
}
async function remove(bank, row) {
  await api("/api/sound/remove", { path: p.value.path, bank, file: row.file });
  await load();
}
const fmtLoop = r => r.loop ? `${(r.loop[0] / r.rate).toFixed(2)}–${(r.loop[1] / r.rate).toFixed(2)} s` : "";
</script>

<template>
  <h1>Sound</h1>
  <p class="lead">The engine, starter and gear-shift sounds come from a <b>sound kit</b>: by default the donor's, but any car in the game
    can lend its sound. You can also replace single samples of the kit with your own recordings; ams2kit packs them into a copy of the
    kit's FMOD bank, so the game's engine logic (RPM crossfades, load, effects) plays your audio.</p>

  <h2>Sound kit</h2>
  <div class="card">
    <div class="row" style="margin-bottom:10px">
      <input v-model="filter" placeholder="Search cars or engines..." style="max-width:280px">
      <span class="status">Using <b>{{ current }}</b>{{ p.cfg.sound.kit ? "" : " (the donor)" }}</span>
      <button v-if="p.cfg.sound.kit" class="ghost small" @click="pick(donor)">Back to the donor's sound</button>
    </div>
    <div class="donors">
      <div v-if="error" style="padding:14px">{{ error }}</div>
      <div v-else-if="!kits" style="padding:14px">Reading every car's sound setup (first time only, about 15 s)...</div>
      <div v-for="k in shown" v-else :key="k.name" class="donor" :class="{ sel: current.toLowerCase() === k.name.toLowerCase() }" @click="pick(k.name)">
        <span><b>{{ k.display }}</b> <small>{{ k.engine }}</small></span><small>{{ k.cls }}</small>
        <small :title="engineBank(k)">{{ sharing[engineBank(k)] > 1 ? `shared by ${sharing[engineBank(k)]} cars` : "" }}</small>
      </div>
    </div>
    <p class="status" style="margin-top:10px">A new kit applies on the next Build. To hear one, drive that car in the game.</p>
  </div>

  <h2>Replace samples <small class="status">experimental</small></h2>
  <div class="card">
    <ol class="steps-howto">
      <li><b>Extract the kit's samples</b> to <code>sound/original/</code> as WAV files (with their loop points).
        <div class="row" style="margin-top:8px">
          <button @click="runJob('sound_extract', {}, load)">{{ info?.extracted ? "Extract again" : "Extract samples" }}</button>
          <button v-if="info?.extracted" class="ghost" @click="api('/api/open', { path: info.dir + '/original' })">Open folder</button>
          <span v-if="info && !info.vgmstream" class="status"><span class="dot warn"></span>Most engine samples are Vorbis: set vgmstream-cli in Setup to decode them.</span>
        </div></li>
      <li><b>Edit or record</b> new versions in any audio editor (or render them from FMOD Studio). Keep loops seamless; a loop in the WAV's
        sampler (<code>smpl</code>) chunk is used, otherwise the original loop is kept (scaled if the length changed).</li>
      <li><b>Add them</b> below (or save them as <code>sound/replace/&lt;bank&gt;/&lt;sample name&gt;.wav</code>), then Build.</li>
    </ol>
    <label class="row" style="gap:8px;margin-top:12px"><input type="checkbox" :checked="p.cfg.sound.replace_samples" @change="setReplace">
      Use my replaced samples in the build</label>
    <p v-if="info?.stale" class="status" style="margin-top:8px"><span class="dot warn"></span>The extracted samples are from
      {{ info.extracted.kit }}, not {{ current }}: extract again (replacements are only used for the kit they were made for).</p>
  </div>

  <template v-if="info?.extracted && !info.stale">
    <template v-for="(b, short) in info.extracted.banks" :key="short">
      <h2>{{ short }} <small class="status">{{ b.samples.filter(r => r.replacement).length }} of {{ b.samples.length }} replaced</small></h2>
      <div class="card" style="padding:0;overflow:auto">
        <table class="phys">
          <thead><tr><th>Sample</th><th>Length</th><th>Loop</th><th>Original</th><th>Replacement</th></tr></thead>
          <tbody>
            <tr v-for="r in b.samples" :key="r.file">
              <td>{{ r.name }}<br><small>{{ r.codec }} · {{ r.channels }} ch · {{ r.rate }} Hz</small></td>
              <td>{{ r.seconds }} s</td>
              <td><small>{{ fmtLoop(r) }}</small></td>
              <td><audio v-if="r.original" controls preload="none" :src="fileUrl(r.original)"></audio><small v-else>not decoded</small></td>
              <td>
                <div v-if="r.replacement" class="row"><audio controls preload="none" :src="fileUrl(r.replacement)"></audio>
                  <button class="ghost small" @click="remove(short, r)">Remove</button></div>
                <input v-else type="file" accept=".wav,audio/wav" @change="upload(short, r, $event)">
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <p class="status">Replaced banks keep the original's FMOD ids: don't race the car in the same session as the car(s) that use that
      bank (Check lists them).</p>
  </template>
</template>
