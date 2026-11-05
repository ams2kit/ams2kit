<script setup>
import { reactive } from "vue";
import { api } from "../api.js";
import { store, refresh } from "../store.js";

const s = store.state;
const form = reactive({ game: s.game || "", blender: s.blender || "", vgmstream: s.vgmstream || "", projects: s.projects_root, steam_appid: !!s.steam_appid });

async function save() {
  await api("/api/settings", { ...form });
  await refresh();
}
</script>

<template>
  <h1>Setup</h1>
  <p class="lead">ams2kit needs Automobilista 2 and Blender. Both are detected automatically; correct the paths here if needed.</p>
  <div class="card">
    <ul class="list">
      <li><span class="dot" :class="store.state.game ? 'ok' : 'fail'"></span><b>Automobilista 2</b><span>{{ store.state.game || "not found" }}</span></li>
      <li><span class="dot" :class="store.state.blender ? 'ok' : 'fail'"></span><b>Blender</b><span>{{ store.state.blender || "not found" }}</span></li>
      <li><span class="dot" :class="store.state.vgmstream ? 'ok' : ''"></span><b>vgmstream-cli</b><span>{{ store.state.vgmstream || "not set (optional, for the Sound page)" }}</span></li>
      <li><span class="dot ok"></span><b>Projects folder</b><span>{{ store.state.projects_root }}</span></li>
    </ul>
  </div>
  <div class="card grid">
    <label class="f">Game folder<input v-model="form.game" placeholder="...\steamapps\common\Automobilista 2"></label>
    <label class="f">Blender executable<input v-model="form.blender" placeholder="...\blender.exe"></label>
    <label class="f">vgmstream-cli (optional)<input v-model="form.vgmstream" placeholder="...gmstream-cli.exe">
      <span class="help">Decodes the game's Vorbis sound samples on the Sound page.</span></label>
    <label class="f">Projects folder<input v-model="form.projects"></label>
    <label class="f">Testing
      <span class="row"><input v-model="form.steam_appid" type="checkbox"> Skip Steam's "custom arguments" prompt</span>
      <span class="help">Adds steam_appid.txt next to the game exe. Untick to remove it.</span></label>
  </div>
  <button @click="save">Save settings</button>
  <template v-if="store.state.installed.length">
    <h2>Installed cars</h2>
    <div class="card">
      <ul class="list">
        <li v-for="r in store.state.installed" :key="r.name"><b>{{ r.name }}</b><span>{{ r.files.length }} files · {{ r.time }}</span></li>
      </ul>
    </div>
  </template>
</template>
