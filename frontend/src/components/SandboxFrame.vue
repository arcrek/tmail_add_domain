<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  html: string
  mode: 'message' | 'content'
  css?: string
  title?: string
}>(), {
  css: '',
  title: '',
})

const sandbox = computed(() => props.mode === 'message'
  ? 'allow-popups allow-popups-to-escape-sandbox'
  : 'allow-scripts allow-popups allow-popups-to-escape-sandbox')

const srcdoc = computed(() => props.mode === 'message'
  ? `<base target="_blank">${props.html}`
  : `<!doctype html><html><head><base target="_blank"><style>${props.css}</style></head><body>${props.html}</body></html>`)
</script>

<template>
  <iframe
    class="sandbox-frame"
    :sandbox="sandbox"
    :srcdoc="srcdoc"
    :title="title || (mode === 'message' ? 'Message content' : 'Site content')"
  />
</template>
