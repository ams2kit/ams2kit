<script setup>
import { computed } from "vue";
import { api } from "../api.js";
import { store } from "../store.js";
import { runJob } from "../job.js";

const p = computed(() => store.project);
const b = computed(() => store.project.build);
const DOT = { ok: "ok", warn: "warn" };

const check = () => runJob("doctor", {}, j => { store.doctor = j.result; });
const build = () => runJob("build", {}, check);
function uninstall() { if (confirm("Remove this car from the game?")) runJob("uninstall"); }
</script>

<template>
  <h1>Build &amp; install</h1>
  <p class="lead">Build writes the car's game files into the project. Check runs the tests that catch the game's silent failures.
    Install copies the car into the game (fully reversible with Uninstall).</p>
  <div class="row">
    <button @click="build">Build</button>
    <button class="ghost" @click="check">Check</button>
    <button :disabled="!b" @click="runJob('install')">Install</button>
    <button class="ghost" :disabled="!p.installed" @click="uninstall">Uninstall</button>
    <span class="status"><span class="dot" :class="{ ok: p.installed }"></span>{{ p.installed ? "installed" : "not installed" }}</span>
  </div>
  <h2>Share</h2>
  <div class="card row">
    <button :disabled="!b" @click="runJob('share')">Make share zip</button>
    <button v-if="p.share_zip" class="ghost" @click="api('/api/open', { path: p.share_zip })">Open folder</button>
    <span class="status">{{ p.share_zip ? p.share_zip : "A zip of the last build for friends: they extract it and run install.bat (no ams2kit needed)." }}</span>
  </div>
  <template v-if="store.doctor">
    <h2>Checks</h2>
    <div class="card">
      <ul class="list">
        <li v-for="(r, i) in store.doctor" :key="i"><span class="dot" :class="DOT[r.level] || 'fail'"></span>{{ r.msg }}</li>
      </ul>
    </div>
  </template>
  <template v-if="b">
    <h2>Last build</h2>
    <div class="card kv">
      <div>Engine / gearbox</div><div>{{ b.physics.engine }} / {{ b.physics.gearbox }}</div>
      <div>Physics base name</div><div>{{ b.physics.base }} (kept from the donor)</div>
      <div>Meshes replaced</div><div>{{ b.meshes }}</div>
      <div>Menu art files</div><div>{{ b.art }}</div>
      <template v-for="(x, n) in b.paks" :key="n"><div>{{ n }}</div><div>{{ x.files }} files, {{ x.added }} added, {{ x.mb }} MB</div></template>
    </div>
  </template>
</template>
