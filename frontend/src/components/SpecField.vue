<script setup>
// One Specs field, saved on change. Numbers stay numbers ("" = 0, which keeps the donor's value), gear
// lists are comma-separated, torque curves are one "rpm,Nm" pair per line.
import { computed } from "vue";
import { getPath, setPath } from "../api.js";
import { store, saveCfg } from "../store.js";
import { ENGINE_LABELS } from "../specFields.js";

const props = defineProps({ field: { type: Array, required: true } });
const [path, label, type = "text", options, help] = props.field;

const value = computed(() => getPath(store.project.cfg, path));

const text = computed(() => {
  const v = value.value;
  if (type === "pairs") return (v || []).map(x => x.join(",")).join("\n");
  if (type === "list") return (v || []).join(", ");
  return v ?? "";
});

// drivelines grouped by layout prefix (FWD_..., RWD_..., AWD_...)
const drivelines = computed(() => {
  const by = {};
  (store.donors?.drivelines || []).forEach(g => (by[g.split("_")[0]] ||= []).push(g));
  return by;
});

function parse(raw) {
  if (type === "number" || type === "engine") return raw === "" ? 0 : Number(raw);
  if (type === "list") return raw.split(",").map(x => Number(x.trim())).filter(x => x);
  if (type === "pairs") return raw.split("\n").map(l => l.split(",").map(Number)).filter(x => x.length === 2 && x.every(n => !isNaN(n)));
  return raw;
}

async function save(e) {
  setPath(store.project.cfg, path, parse(e.target.value));
  await saveCfg();
}
</script>

<template>
  <label class="f">{{ label }}
    <select v-if="type === 'driveline'" :value="value || ''" @change="save">
      <option value="">Donor's driveline</option>
      <optgroup v-for="(group, layout) in drivelines" :key="layout" :label="layout">
        <option v-for="g in group" :key="g">{{ g }}</option>
      </optgroup>
    </select>
    <select v-else-if="type === 'engine'" :value="value" @change="save">
      <option v-for="[i, l] in ENGINE_LABELS" :key="i" :value="i">{{ l }}</option>
    </select>
    <select v-else-if="type === 'select'" :value="value ?? ''" @change="save">
      <option v-for="o in options" :key="o">{{ o }}</option>
    </select>
    <input v-else-if="type === 'class'" :value="text" list="classes" @change="save">
    <textarea v-else-if="type === 'textarea' || type === 'pairs'" :value="text" :rows="type === 'pairs' ? 4 : 2" @change="save"></textarea>
    <input v-else-if="type === 'number'" type="number" step="any" :value="text" @change="save">
    <input v-else :value="text" @change="save">
    <span v-if="help" class="help">{{ help }}</span>
  </label>
</template>
