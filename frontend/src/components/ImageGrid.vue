<script setup>
import { basename, fileUrl } from "../api.js";

defineProps({ files: { type: Array, required: true } });
</script>

<template>
  <div class="thumbs">
    <figure v-for="f in files" :key="f"><img :src="fileUrl(f)"><figcaption>{{ basename(f) }}</figcaption></figure>
  </div>
</template>
