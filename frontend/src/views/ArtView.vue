<script setup>
import { computed } from "vue";
import { api } from "../api.js";
import { store, saveCfg } from "../store.js";
import { runJob } from "../job.js";
import ImageGrid from "../components/ImageGrid.vue";

const p = computed(() => store.project);

async function setLivery(id, e) { p.value.cfg.art.liveries[id] = e.target.value; await saveCfg(); }
async function setAzimuth(e) { p.value.cfg.art.render_azimuth = Number(e.target.value); await saveCfg(); }

async function uploadLogo(e) {
  const f = e.target.files[0];
  if (!f) return;
  const r = await fetch(`/api/upload?path=${encodeURIComponent(p.value.path)}&name=logo.png`, { method: "POST", body: f });
  p.value.cfg.art.logo = (await r.json()).rel;
  await saveCfg();
}

// render the previews from the .blend, then turn them into the game's images
const renderThenBuild = () => runJob("render", {}, () => runJob("art"));
</script>

<template>
  <h1>Menu art</h1>
  <p class="lead">The car-select image (one per livery) and the manufacturer logo. Render the images from your Blender file in the livery
    colours below, or drop your own <code>livery_&lt;id&gt;.png</code> files into the project's <code>art</code> folder.</p>
  <h2>Livery colours</h2>
  <div class="card row">
    <label v-for="(c, id) in p.liveries" :key="id" class="swatch"><input type="color" :value="c" @change="setLivery(id, $event)">#{{ id }}</label>
    <label class="f" style="max-width:160px">Camera angle (deg)<input type="number" :value="p.cfg.art.render_azimuth" @change="setAzimuth"></label>
  </div>
  <h2>Logo</h2>
  <div class="card row">
    <input type="file" accept="image/png" style="max-width:320px" @change="uploadLogo">
    <span class="status">{{ p.cfg.art.logo ? "current: " + p.cfg.art.logo : "PNG with a transparent background; it is filled white for the dark menu." }}</span>
  </div>
  <div class="row">
    <button :disabled="!p.car_blend" @click="renderThenBuild">Render from my model</button>
    <button @click="runJob('art')">Make game images</button>
    <button class="ghost" @click="api('/api/open', { path: p.path + '/art' })">Open art folder</button>
  </div>
  <template v-if="p.previews.length">
    <h2>Previews</h2>
    <ImageGrid :files="p.previews" />
  </template>
</template>
