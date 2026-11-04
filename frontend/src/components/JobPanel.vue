<script setup>
import { nextTick, ref, watch } from "vue";
import { job } from "../job.js";

const pre = ref(null);
watch(() => job.log, () => nextTick(() => { if (pre.value) pre.value.scrollTop = pre.value.scrollHeight; }));
</script>

<template>
  <section v-if="job.visible" class="job">
    <div class="job-head">
      <span>{{ job.title }}</span>
      <span id="job-status"><template v-if="job.running"><span class="spin"></span> running</template><template v-else>{{ job.failed ? "failed" : "done" }}</template></span>
      <button class="ghost small" @click="job.visible = false">Hide</button>
    </div>
    <pre ref="pre">{{ job.log }}</pre>
  </section>
</template>
