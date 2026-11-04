<script setup>
import { onMounted } from "vue";
import { store, loadDonors } from "../store.js";
import { SPEC_FIELDS } from "../specFields.js";
import SpecField from "../components/SpecField.vue";

// classes and drivelines come from the donor list; the page works without them
onMounted(() => loadDonors().catch(() => {}));
</script>

<template>
  <h1>Specs</h1>
  <p class="lead">What the car is and how it drives. Changes save automatically.</p>
  <div v-if="store.project.errors.length" class="card">
    <div v-for="e in store.project.errors" :key="e"><span class="dot fail"></span> {{ e }}</div>
  </div>
  <template v-for="[title, fields] in SPEC_FIELDS" :key="title">
    <h2>{{ title }}</h2>
    <div class="card grid">
      <SpecField v-for="f in fields" :key="f[0]" :field="f" />
    </div>
  </template>
  <datalist id="classes"><option v-for="c in store.donors?.classes" :key="c" :value="c"></option></datalist>
</template>
