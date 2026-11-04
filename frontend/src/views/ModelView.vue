<script setup>
import { computed } from "vue";
import { api } from "../api.js";
import { store, saveCfg } from "../store.js";
import { runJob } from "../job.js";

const p = computed(() => store.project);
const donorBlend = computed(() => p.value.donor_blend[0]);

async function setUseModel(e) {
  p.value.cfg.model.use_model = e.target.checked;
  await saveCfg();
}
</script>

<template>
  <h1>3D model</h1>
  <p class="lead">ams2kit exports the donor car to a Blender file so you can see exactly which parts to replace. Put your car into that file,
    keeping the donor's object names, then let ams2kit turn it back into game meshes.</p>
  <div class="card">
    <ol class="steps-howto">
      <li><b>Export the donor</b> to <code>model/donor_{{ p.donor?.key || "" }}.blend</code>.
        <div class="row" style="margin-top:8px">
          <button @click="runJob('export_blend')">{{ donorBlend ? "Export again" : "Export donor .blend" }}</button>
          <button v-if="donorBlend" class="ghost" @click="api('/api/open', { path: donorBlend, with: 'blender' })">Open in Blender</button>
        </div></li>
      <li><b>Model your car in it</b>: import your model, line its wheels up with the <code>WHEEL_*</code> markers, move your meshes into the
        <code>REPLACE_*</code> objects (or rename yours to match), assign the donor's material slots to your faces (paint, glass, lights, rims), and
        delete donor parts you don't want. The README text block inside the file explains the details.</li>
      <li><b>Save it as</b> <code>{{ p.cfg.model.blend }}</code> in the project folder.
        <span class="status" style="margin-left:8px"><span class="dot" :class="p.car_blend ? 'ok' : 'warn'"></span>{{ p.car_blend ? "found" : "not saved yet" }}</span></li>
      <li><b>Build the game meshes</b> from your file.
        <div class="row" style="margin-top:8px">
          <button :disabled="!p.car_blend" @click="runJob('build_meshes')">Build meshes</button>
          <span class="status"><span class="dot" :class="{ ok: p.meshes_built }"></span>{{ p.meshes_built ? "meshes built" : "not built" }}</span>
        </div></li>
    </ol>
  </div>
  <div class="card row">
    <label class="row" style="gap:8px"><input type="checkbox" :checked="p.cfg.model.use_model" @change="setUseModel"> Use my model in the build</label>
    <span class="status">Untick to build with the donor's body (useful for a first physics test).</span>
    <button class="ghost small" @click="api('/api/open', { path: p.path + '/model' })">Open project folder</button>
  </div>
</template>
