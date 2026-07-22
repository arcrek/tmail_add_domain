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
  const token = props.token
  const id = props.id
  loading.value = true
  error.value = ''
  actionError.value = ''
  busy.value = ''
  message.value = null
  bodyMode.value = 'html'
  try {
    const value = await api.message(token, id)
    if (version !== requestVersion) return
    message.value = value
    if (!value.seen) {
      try {
        await api.setSeen(token, id, true)
        if (version === requestVersion) emit('seen', id)
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
      emit('stale', id)
    } else {
      error.value = cause instanceof ApiError ? cause.message : 'The message could not be loaded.'
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function safeFilename(value: string, fallback = 'attachment', maxLength = 120): string {
  const basename = value
    .normalize('NFKC')
    .split(/[\\/]/)
    .pop()
    ?.replace(/[\u0000-\u001f\u007f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g, '')
    .replace(/[<>:"|?*]/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/^[ .]+|[ .]+$/g, '') || ''
  if (!basename) return fallback
  if (basename.length <= maxLength) return basename

  const dot = basename.lastIndexOf('.')
  const extension = dot > 0 && /^\.[a-z0-9]{1,15}$/i.test(basename.slice(dot))
    ? basename.slice(dot)
    : ''
  const stem = basename.slice(0, maxLength - extension.length).replace(/[ .]+$/g, '') || fallback
  return `${stem}${extension}`
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
  const current = message.value
  if (!current) return
  const version = requestVersion
  const token = props.token
  const messageId = current.id
  const attachmentId = attachment.id
  const filename = safeFilename(attachment.filename)
  const action = `attachment:${attachmentId}`
  busy.value = action
  actionError.value = ''
  try {
    const blob = await api.attachment(token, messageId, attachmentId)
    if (version === requestVersion) saveBlob(blob, filename)
  } catch (cause) {
    if (version === requestVersion) {
      actionError.value = cause instanceof ApiError ? cause.message : 'The attachment could not be downloaded.'
    }
  } finally {
    if (version === requestVersion && busy.value === action) busy.value = ''
  }
}

async function downloadSource(): Promise<void> {
  const current = message.value
  if (!current) return
  const version = requestVersion
  const token = props.token
  const messageId = current.id
  const filename = `${safeFilename(messageId, 'message', 116)}.eml`
  const action = 'source'
  busy.value = action
  actionError.value = ''
  try {
    const blob = await api.source(token, messageId)
    if (version === requestVersion) saveBlob(blob, filename)
  } catch (cause) {
    if (version === requestVersion) {
      actionError.value = cause instanceof ApiError ? cause.message : 'The message source could not be downloaded.'
    }
  } finally {
    if (version === requestVersion && busy.value === action) busy.value = ''
  }
}

async function deleteCurrent(): Promise<void> {
  const current = message.value
  if (!current || !window.confirm('Delete this message permanently?')) return
  const version = requestVersion
  const token = props.token
  const messageId = current.id
  const action = 'delete'
  busy.value = action
  actionError.value = ''
  try {
    await api.deleteMessage(token, messageId)
    if (version === requestVersion) emit('deleted', messageId)
  } catch (cause) {
    if (version === requestVersion) {
      if (cause instanceof ApiError && cause.status === 404) emit('deleted', messageId)
      else actionError.value = cause instanceof ApiError ? cause.message : 'The message could not be deleted.'
    }
  } finally {
    if (version === requestVersion && busy.value === action) busy.value = ''
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
              <strong>{{ safeFilename(attachment.filename) }}</strong>
              <small>{{ formatBytes(attachment.size) }} · {{ attachment.contentType }}</small>
            </span>
            <button
              class="text-button"
              type="button"
              data-download-attachment
              :disabled="Boolean(busy)"
              :aria-label="`Download ${safeFilename(attachment.filename)}`"
              @click="downloadAttachment(attachment)"
            >
              {{ busy === `attachment:${attachment.id}` ? 'Saving' : 'Download' }}
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
