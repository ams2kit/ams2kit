<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { store, loadDonors, openProject } from "../store.js";
import { runJob } from "../job.js";

const pick = store.carPicker;
const form = reactive({ name: "", display: "", manufacturer: "", cls: "Street" });
const loadError = ref("");
const message = ref("");

onMounted(async () => {
  try { await loadDonors(); } catch (e) { loadError.value = e.message; }
});

const cars = computed(() => {
  if (!store.donors) return [];
  const f = pick.filter.toLowerCase();
  const list = store.donors.cars.filter(c => (!pick.cls || c.cls === pick.cls) && (c.display + c.name + c.manufacturer).toLowerCase().includes(f));
  if (pick.sort === "parts") list.sort((a, b) => (a.parts || 999) - (b.parts || 999));
  return list;
});

function create() {
  const name = form.name.trim();
  if (!/^[A-Za-z][A-Za-z0-9_]{2,40}$/.test(name)) return (message.value = "Internal name: letters, digits, _ (3-41 chars).");
  if (!pick.donor) return (message.value = "Pick a donor car.");
  message.value = "";
  runJob("new_project", {
    root: store.state.projects_root, name, donor: pick.donor, display_name: form.display || name.replace(/_/g, " "),
    manufacturer: form.manufacturer, cls: form.cls,
  }, j => { if (j.result?.path) { store.projectPath = j.result.path; store.step = "model"; } });
}
</script>

<template>
  <h1>Car &amp; donor</h1>
  <p class="lead">Every new car is a clone of an existing car, the <b>donor</b>. Your car keeps the donor's tyres, driveline layout
    (front-, rear- or all-wheel drive), interior and engine sound, so pick one close to your car: same drive layout, similar size and shape,
    ideally a plain road car without wings or add-ons.</p>
  <template v-if="store.state.projects.length">
    <h2>Open a project</h2>
    <div class="card">
      <ul class="list">
        <li v-for="p in store.state.projects" :key="p.path">
          <button class="ghost small" @click="openProject(p.path)">Open</button><b>{{ p.display || p.name }}</b><span class="status">donor {{ p.donor }}</span>
        </li>
      </ul>
    </div>
  </template>
  <h2>New car</h2>
  <div class="card">
    <div class="grid">
      <label class="f">Internal name<input v-model="form.name" placeholder="BYD_Seal"><span class="help">Letters, digits and _ only. Used in file names.</span></label>
      <label class="f">Display name<input v-model="form.display" placeholder="BYD Seal AWD"></label>
      <label class="f">Manufacturer<input v-model="form.manufacturer" placeholder="BYD"><span class="help">Also picks the logo file name.</span></label>
      <label class="f">Car class<select v-model="form.cls"><option v-for="c in store.donors?.classes" :key="c">{{ c }}</option></select><span class="help">Where the car is listed in game.</span></label>
    </div>
    <h2>Donor car</h2>
    <div class="row" style="margin-bottom:10px">
      <input v-model="pick.filter" placeholder="Search cars..." style="max-width:280px">
      <select v-model="pick.cls" style="max-width:220px"><option value="">All classes</option><option v-for="c in store.donors?.classes" :key="c">{{ c }}</option></select>
      <select v-model="pick.sort" style="max-width:200px"><option value="class">Sort by class</option><option value="parts">Fewest parts first</option></select>
      <span class="status">{{ store.donors ? `${cars.length} cars` : "" }}</span>
    </div>
    <div class="donors">
      <div v-if="loadError" style="padding:14px">{{ loadError }}</div>
      <div v-else-if="!store.donors" style="padding:14px">Loading the car list...</div>
      <div v-for="c in cars" v-else :key="c.name" class="donor" :class="{ sel: pick.donor === c.name }" @click="pick.donor = c.name">
        <span><b>{{ c.display }}</b> <small>{{ c.manufacturer }} {{ c.year }}</small></span><small>{{ c.cls }}</small>
        <small title="exterior parts to replace / all meshes">{{ c.parts ?? "?" }} parts</small>
      </div>
    </div>
    <div class="row" style="margin-top:14px"><button @click="create">Create project</button><span class="status">{{ message }}</span></div>
  </div>
</template>
