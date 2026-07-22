<script setup lang="ts">
import { computed, ref, watch } from 'vue'

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

const frame = ref<HTMLIFrameElement | null>(null)
const revision = ref(0)
const sourceUrl = computed(() => `/sandbox?revision=${revision.value}`)
const messageSource = computed(() => props.mode === 'message'
  ? `<base target="_blank">${props.html}`
  : undefined)

watch(
  () => [props.html, props.css, props.mode] as const,
  () => { revision.value += 1 },
)

function sendContent(): void {
  if (props.mode !== 'content') return
  frame.value?.contentWindow?.postMessage({
    type: 'tmail:sandbox-content',
    html: props.html,
    css: props.css,
    mode: props.mode,
  }, '*')
}
</script>

<template>
  <iframe
    :key="revision"
    ref="frame"
    class="sandbox-frame"
    :sandbox="sandbox"
    :src="mode === 'content' ? sourceUrl : undefined"
    :srcdoc="messageSource"
    :title="title || (mode === 'message' ? 'Message content' : 'Site content')"
    @load="sendContent"
  />
</template>
