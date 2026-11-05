<script setup>
// ams2kit UI: a step-by-step wizard over the local JSON API (see ui/server.py, actions.py).
import { computed, onMounted } from "vue";
import { STEPS, store, refresh, isDone } from "./store.js";
import JobPanel from "./components/JobPanel.vue";
import SetupView from "./views/SetupView.vue";
import CarView from "./views/CarView.vue";
import ModelView from "./views/ModelView.vue";
import SpecsView from "./views/SpecsView.vue";
import PhysicsView from "./views/PhysicsView.vue";
import ArtView from "./views/ArtView.vue";
import SoundView from "./views/SoundView.vue";
import BuildView from "./views/BuildView.vue";
import TestView from "./views/TestView.vue";

const VIEWS = { setup: SetupView, car: CarView, model: ModelView, specs: SpecsView, physics: PhysicsView, art: ArtView, sound: SoundView, build: BuildView, test: TestView };

const locked = step => step.needsProject && !store.project;
// a remembered step whose project is gone falls back to Setup
const current = computed(() => {
  const step = STEPS.find(s => s.id === store.step);
  return !step || locked(step) ? "setup" : step.id;
});

onMounted(refresh);
</script>

<template>
  <header class="top">
    <div class="brand"><span class="mark"></span>ams2kit <small>car builder for Automobilista 2</small></div>
    <div v-if="store.project" class="chip">
      {{ store.project.cfg.car.display_name || store.project.cfg.car.name }} · donor {{ store.project.cfg.car.donor }}
    </div>
  </header>
  <div class="layout">
    <nav class="steps">
      <button v-for="(s, i) in STEPS" :key="s.id" :class="{ active: current === s.id, done: isDone(s.id) }"
              :disabled="locked(s)" @click="store.step = s.id">{{ i + 1 }}<span>{{ s.label }}</span></button>
    </nav>
    <main>
      <component :is="VIEWS[current]" v-if="store.state" :key="current" />
    </main>
  </div>
  <JobPanel />
</template>
