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

const sandbox = computed(() => 'allow-scripts allow-popups allow-popups-to-escape-sandbox')

const frame = ref<HTMLIFrameElement | null>(null)
const revision = ref(0)
let sentMessageRevision = -1
const sourceUrl = computed(() => `${props.mode === 'message' ? '/message-sandbox' : '/sandbox'}?revision=${revision.value}`)

watch(
  () => [props.html, props.css, props.mode] as const,
  () => { revision.value += 1 },
)

function sendContent(): void {
  const target = frame.value?.contentWindow
  if (!target || (props.mode === 'message' && sentMessageRevision === revision.value)) return
  if (props.mode === 'message') sentMessageRevision = revision.value
  target.postMessage({
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
    :src="sourceUrl"
    :title="title || (mode === 'message' ? 'Message content' : 'Site content')"
    @load="sendContent"
  />
</template>
