<script setup>
// The porting guide (docs/porting/*.md), bundled at build time and shown as tabs. Links between guide
// pages switch tabs; links to other docs show their path (they live in the repository's docs folder).
import { computed, ref } from "vue";
import { marked } from "marked";

const files = import.meta.glob("../../../docs/porting/*.md", { query: "?raw", import: "default", eager: true });
const pages = Object.entries(files)
  .map(([path, text]) => ({ file: path.split("/").pop(), text }))
  .sort((a, b) => (a.file === "README.md" ? -1 : b.file === "README.md" ? 1 : a.file.localeCompare(b.file)))
  .map(p => {
    const h1 = (p.text.match(/^# (.+)$/m) || [, p.file])[1];
    return { ...p, label: h1.replace(/^Porting a car:\s*/i, "").replace(/^\w/, c => c.toUpperCase()), html: marked.parse(p.text) };
  });

const tab = ref(pages[0]?.file);
const page = computed(() => pages.find(p => p.file === tab.value) || pages[0]);

function onClick(e) {
  const a = e.target.closest("a");
  if (!a) return;
  const href = a.getAttribute("href") || "";
  if (/^https?:/.test(href)) return;
  e.preventDefault();
  const name = href.split("#")[0].split("/").pop();
  if (!href.includes("..") && pages.some(p => p.file === name)) {
    tab.value = name;
    e.currentTarget.scrollIntoView({ block: "start" });
  } else {
    a.title = "docs/" + href.replace(/^\.\.\//, "") + " in the ams2kit folder";
  }
}
</script>

<template>
  <div class="guide">
    <div class="tabs guide-tabs">
      <button v-for="p in pages" :key="p.file" :class="{ active: p.file === tab }" @click="tab = p.file">{{ p.label }}</button>
    </div>
    <article class="md" @click="onClick" v-html="page?.html"></article>
    <p class="help">Source: <code>docs/porting/{{ page?.file }}</code></p>
  </div>
</template>
