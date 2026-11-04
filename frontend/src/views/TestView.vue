<script setup>
import { computed, ref } from "vue";
import { store } from "../store.js";
import { runJob } from "../job.js";
import ImageGrid from "../components/ImageGrid.vue";

const p = computed(() => store.project);
const last = computed(() => store.project.test_results.at(-1));
const tel = computed(() => last.value?.telemetry);
const seconds = ref(120);
</script>

<template>
  <h1>Test</h1>
  <p class="lead">Runs the game by itself: it starts a Custom Race straight away with the car and track you last used in Custom Race, lets the
    AI drive, records telemetry and checks for crashes. <b>Once</b>, start a Custom Race with your car by hand so the game remembers it.</p>
  <div class="row">
    <label class="f" style="max-width:160px">Drive for (s)<input v-model.number="seconds" type="number"></label>
    <button :disabled="!p.installed" @click="runJob('test', { seconds })">Run track test</button>
    <button class="ghost" :disabled="!p.installed" @click="runJob('menu')">Screenshot the menus</button>
    <span v-if="!p.installed" class="status">Install the car first.</span>
  </div>
  <template v-if="last">
    <h2>Last run</h2>
    <div class="card kv">
      <div>Result</div><div><span class="dot" :class="last.result === 'ok' ? 'ok' : 'fail'"></span> {{ last.result }} · {{ last.detail }}</div>
      <template v-if="tel">
        <div>Top speed</div><div>{{ tel.top_speed_kmh }} km/h (target {{ p.cfg.powertrain.top_speed_kmh }})</div>
        <div>Max rpm</div><div>{{ tel.max_rpm }} / limit {{ tel.rev_limit }}</div>
        <div>Est. 0-100 km/h</div><div>{{ tel.est_0_100_s ?? "n/a" }} s (from low-speed acceleration)</div>
        <div>Acceleration (g, p90)</div><div>{{ Object.entries(tel.accel_g_p90 || {}).map(([k, v]) => `${k} km/h: ${v}`).join(" · ") }}</div>
      </template>
      <template v-if="last.dumps?.length">
        <div>Crash dumps</div><div><div v-for="d in last.dumps" :key="d">{{ d }}</div></div>
      </template>
    </div>
  </template>
  <template v-if="p.shots.length">
    <h2>Screenshots</h2>
    <ImageGrid :files="p.shots" />
  </template>
</template>
