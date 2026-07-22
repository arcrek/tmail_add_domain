<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../api'
import type { AdminSettings, MailServerSettings } from '../types'

const props = defineProps<{ mailServer: MailServerSettings; csrf: string }>()
const emit = defineEmits<{ updated: [settings: AdminSettings] }>()
const draft = reactive({ ...props.mailServer })
const pending = ref(false)
const testing = ref(false)
const status = ref('')
const error = ref('')

watch(() => props.mailServer, (value) => Object.assign(draft, value))

function valid(): boolean {
  try {
    const url = new URL(draft.jmapUrl)
    return ['http:', 'https:'].includes(url.protocol) && draft.catchallAddress.includes('@') && draft.retentionDays >= 1 && draft.retentionDays <= 3650
  } catch {
    return false
  }
}

async function save(): Promise<void> {
  error.value = ''
  status.value = ''
  if (!valid()) {
    error.value = 'Enter a valid JMAP URL, catch-all address, and retention period.'
    return
  }
  pending.value = true
  const values: Partial<MailServerSettings> = { ...draft }
  if (values.jmapToken === '********') delete values.jmapToken
  try {
    const settings = await api.admin.updateSettings({ mailServer: values }, props.csrf)
    emit('updated', settings)
    status.value = 'Mail server settings saved.'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not save mail server settings.'
  } finally {
    pending.value = false
  }
}

async function testConnection(): Promise<void> {
  testing.value = true
  error.value = ''
  status.value = ''
  try {
    const result = await api.admin.testMail(props.csrf)
    status.value = `Connection passed. ${result.domainCount} domains and ${result.messages.stored} stored messages.`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Mail connection failed.'
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <section class="admin-section" aria-labelledby="mail-server-title">
    <p class="eyebrow">JMAP connection</p>
    <h1 id="mail-server-title">Mail Server</h1>
    <form class="settings-form" @submit.prevent="save">
      <div class="field"><label for="jmap-url">JMAP URL</label><input id="jmap-url" v-model.trim="draft.jmapUrl" name="jmapUrl" type="url" required></div>
      <div class="field"><label for="jmap-token">JMAP token</label><input id="jmap-token" v-model="draft.jmapToken" name="jmapToken" type="password" autocomplete="new-password" required><small>The masked value keeps the saved token unchanged.</small></div>
      <div class="settings-grid">
        <div class="field"><label for="catchall-address">Catch-all address</label><input id="catchall-address" v-model.trim="draft.catchallAddress" name="catchallAddress" type="email" required></div>
        <div class="field"><label for="mail-account-id">Account ID</label><input id="mail-account-id" v-model.trim="draft.mailAccountId" name="mailAccountId"><small>Optional. Leave empty for discovery.</small></div>
        <div class="field"><label for="retention-days">Retention days</label><input id="retention-days" v-model.number="draft.retentionDays" name="retentionDays" type="number" min="1" max="3650" required></div>
      </div>
      <div class="form-actions">
        <button class="secondary-button" type="button" :disabled="testing || pending" @click="testConnection">{{ testing ? 'Testing' : 'Test connection' }}</button>
        <button class="primary-button" type="submit" :disabled="pending || testing">{{ pending ? 'Saving' : 'Save mail server' }}</button>
      </div>
      <p class="form-status" aria-live="polite">{{ status }}</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    </form>
  </section>
</template>
