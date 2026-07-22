<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, api } from '../api'
import type { AttachmentResource, MessageResource } from '../types'
import SandboxFrame from './SandboxFrame.vue'

const props = defineProps<{ token: string; id: string }>()
const emit = defineEmits<{
  deleted: [id: string]
  seen: [id: string]
  stale: [id: string]
}>()

const message = ref<MessageResource | null>(null)
const loading = ref(true)
const error = ref('')
const actionError = ref('')
const bodyMode = ref<'html' | 'text'>('html')
const busy = ref('')
let requestVersion = 0

function formatAddress(value: { name: string; address: string }): string {
  return value.name ? `${value.name} <${value.address}>` : value.address
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

async function loadMessage(): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  actionError.value = ''
  message.value = null
  bodyMode.value = 'html'
  try {
    const value = await api.message(props.token, props.id)
    if (version !== requestVersion) return
    message.value = value
    if (!value.seen) {
      try {
        await api.setSeen(props.token, props.id, true)
        if (version === requestVersion) emit('seen', props.id)
      } catch (cause) {
        if (version === requestVersion) {
          actionError.value = cause instanceof ApiError ? cause.message : 'The read status could not be saved.'
        }
      }
    }
  } catch (cause) {
    if (version !== requestVersion) return
    if (cause instanceof ApiError && cause.status === 404) {
      error.value = 'This message is no longer available.'
      emit('stale', props.id)
    } else {
      error.value = cause instanceof ApiError ? cause.message : 'The message could not be loaded.'
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function safeFilename(value: string): string {
  return value.split(/[\\/]/).pop() || 'attachment'
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function downloadAttachment(attachment: AttachmentResource): Promise<void> {
  if (!message.value) return
  busy.value = attachment.id
  actionError.value = ''
  try {
    saveBlob(
      await api.attachment(props.token, message.value.id, attachment.id),
      safeFilename(attachment.filename),
    )
  } catch (cause) {
    actionError.value = cause instanceof ApiError ? cause.message : 'The attachment could not be downloaded.'
  } finally {
    busy.value = ''
  }
}

async function downloadSource(): Promise<void> {
  if (!message.value) return
  busy.value = 'source'
  actionError.value = ''
  try {
    saveBlob(await api.source(props.token, message.value.id), `${message.value.id}.eml`)
  } catch (cause) {
    actionError.value = cause instanceof ApiError ? cause.message : 'The message source could not be downloaded.'
  } finally {
    busy.value = ''
  }
}

async function deleteCurrent(): Promise<void> {
  if (!message.value || !window.confirm('Delete this message permanently?')) return
  busy.value = 'delete'
  actionError.value = ''
  try {
    await api.deleteMessage(props.token, message.value.id)
    emit('deleted', message.value.id)
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) emit('deleted', props.id)
    else actionError.value = cause instanceof ApiError ? cause.message : 'The message could not be deleted.'
  } finally {
    busy.value = ''
  }
}

watch(() => [props.token, props.id], () => void loadMessage(), { immediate: true })
onBeforeUnmount(() => { requestVersion += 1 })
</script>

<template>
  <article class="message-reader" aria-live="polite">
    <div v-if="loading" class="reader-loading">
      <span class="skeleton skeleton-label" />
      <span class="skeleton skeleton-title" />
      <span class="skeleton skeleton-field" />
      <span class="sr-only">Loading message</span>
    </div>

    <div v-else-if="error" class="reader-state">
      <h2>Message unavailable</h2>
      <p>{{ error }}</p>
      <button class="secondary-button" type="button" @click="loadMessage">Retry</button>
    </div>

    <template v-else-if="message">
      <header class="reader-header">
        <div>
          <p class="reader-sender">{{ formatAddress(message.from) }}</p>
          <h2>{{ message.subject || '(No subject)' }}</h2>
          <time :datetime="message.createdAt">{{ formatDate(message.createdAt) }}</time>
        </div>
        <div class="reader-actions">
          <button
            class="secondary-button compact-button"
            type="button"
            data-download-source
            :disabled="Boolean(busy)"
            @click="downloadSource"
          >
            {{ busy === 'source' ? 'Saving' : 'Download .eml' }}
          </button>
          <button
            class="danger-button compact-button"
            type="button"
            data-action="delete"
            :disabled="Boolean(busy)"
            @click="deleteCurrent"
          >
            {{ busy === 'delete' ? 'Deleting' : 'Delete' }}
          </button>
        </div>
      </header>

      <dl class="message-meta">
        <div><dt>To</dt><dd>{{ message.to.map(formatAddress).join(', ') || 'Undisclosed' }}</dd></div>
        <div v-if="message.cc.length"><dt>Cc</dt><dd>{{ message.cc.map(formatAddress).join(', ') }}</dd></div>
        <div v-if="message.bcc.length"><dt>Bcc</dt><dd>{{ message.bcc.map(formatAddress).join(', ') }}</dd></div>
      </dl>

      <p v-if="actionError" class="form-error reader-error" role="alert">{{ actionError }}</p>

      <section v-if="message.attachments.length" class="attachments" aria-labelledby="attachments-title">
        <h3 id="attachments-title">Attachments</h3>
        <ul>
          <li v-for="attachment in message.attachments" :key="attachment.id">
            <span>
              <strong>{{ attachment.filename }}</strong>
              <small>{{ formatBytes(attachment.size) }} · {{ attachment.contentType }}</small>
            </span>
            <button
              class="text-button"
              type="button"
              data-download-attachment
              :disabled="Boolean(busy)"
              @click="downloadAttachment(attachment)"
            >
              {{ busy === attachment.id ? 'Saving' : 'Download' }}
            </button>
          </li>
        </ul>
      </section>

      <div v-if="message.html.length && message.text" class="body-switcher" aria-label="Message format">
        <button type="button" :aria-pressed="bodyMode === 'html'" @click="bodyMode = 'html'">HTML</button>
        <button type="button" :aria-pressed="bodyMode === 'text'" @click="bodyMode = 'text'">Plain text</button>
      </div>

      <SandboxFrame
        v-if="message.html.length && bodyMode === 'html'"
        :html="message.html.join('\n')"
        mode="message"
        :title="`Message: ${message.subject || 'No subject'}`"
      />
      <pre v-else class="plain-message">{{ message.text || 'This message has no readable body.' }}</pre>
    </template>
  </article>
</template>
