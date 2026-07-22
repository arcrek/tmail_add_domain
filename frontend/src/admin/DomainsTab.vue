<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../api'
import type { AdminSettings, AdminSiteSettings, SyncStatus } from '../types'

const props = defineProps<{
  site: AdminSiteSettings
  domains: string[]
  lastSync: SyncStatus
  lastSuccessfulSync: SyncStatus
  lastSyncError: SyncStatus
  csrf: string
}>()
const emit = defineEmits<{
  updated: [settings: AdminSettings]
  busy: [value: boolean]
  synced: [domains: string[], lastSync: SyncStatus]
}>()

const draft = reactive({
  autoSyncDomains: props.site.autoSyncDomains,
  fetchSeconds: props.site.fetchSeconds,
  messageLimit: props.site.messageLimit,
  localPartMin: props.site.localPartMin,
  localPartMax: props.site.localPartMax,
  forbiddenIds: props.site.forbiddenIds.join('\n'),
  blockedSenderDomains: props.site.blockedSenderDomains.join('\n'),
})
const displayedDomains = ref([...props.domains])
const displayedSync = ref({ ...props.lastSync })
const displayedSuccessfulSync = ref({ ...props.lastSuccessfulSync })
const displayedSyncError = ref({ ...props.lastSyncError })
const pending = ref(false)
const syncing = ref(false)
const status = ref('')
const error = ref('')

watch([pending, syncing], ([saving, synchronizing]) => emit('busy', saving || synchronizing))

watch(() => props.site, (value) => {
  if (!pending.value && !syncing.value) Object.assign(draft, {
    autoSyncDomains: value.autoSyncDomains,
    fetchSeconds: value.fetchSeconds,
    messageLimit: value.messageLimit,
    localPartMin: value.localPartMin,
    localPartMax: value.localPartMax,
    forbiddenIds: value.forbiddenIds.join('\n'),
    blockedSenderDomains: value.blockedSenderDomains.join('\n'),
  })
})
watch(() => props.domains, (value) => { if (!pending.value && !syncing.value) displayedDomains.value = [...value] })
watch(() => props.lastSync, (value) => { if (!pending.value && !syncing.value) displayedSync.value = { ...value } })
watch(() => props.lastSuccessfulSync, (value) => { if (!pending.value && !syncing.value) displayedSuccessfulSync.value = { ...value } })
watch(() => props.lastSyncError, (value) => { if (!pending.value && !syncing.value) displayedSyncError.value = { ...value } })

function list(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)
}

function dateTime(value?: string): string {
  return value ? new Date(value).toLocaleString() : 'Not yet'
}

function syncText(value: SyncStatus, empty: string): string {
  if (!value.created_at) return empty
  return `${value.detail || 'No detail'}, ${dateTime(value.created_at)}`
}

function applySettings(settings: AdminSettings, replaceDomains: boolean): void {
  if (replaceDomains) displayedDomains.value = [...settings.domains]
  displayedSync.value = { ...settings.lastSync }
  displayedSuccessfulSync.value = { ...settings.lastSuccessfulSync }
  displayedSyncError.value = { ...settings.lastSyncError }
}

function changeAutoSync(event: Event): void {
  const input = event.target as HTMLInputElement
  if (!input.checked && !window.confirm('Turn off auto-sync? The current whitelist will freeze until you sync manually or turn auto-sync on.')) {
    input.checked = true
    return
  }
  draft.autoSyncDomains = input.checked
}

async function save(): Promise<void> {
  error.value = ''
  status.value = ''
  if (draft.localPartMin > draft.localPartMax) {
    error.value = 'Minimum local-part length cannot exceed the maximum.'
    return
  }
  pending.value = true
  try {
    const settings = await api.admin.updateSettings({ site: {
      autoSyncDomains: draft.autoSyncDomains,
      fetchSeconds: draft.fetchSeconds,
      messageLimit: draft.messageLimit,
      localPartMin: draft.localPartMin,
      localPartMax: draft.localPartMax,
      forbiddenIds: list(draft.forbiddenIds),
      blockedSenderDomains: list(draft.blockedSenderDomains),
    } }, props.csrf)
    emit('updated', settings)
    applySettings(settings, true)
    status.value = 'Domain and inbox settings saved.'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not save domain settings.'
  } finally {
    pending.value = false
  }
}

async function syncNow(): Promise<void> {
  syncing.value = true
  error.value = ''
  status.value = ''
  try {
    try {
      const result = await api.admin.syncDomains(props.csrf)
      displayedDomains.value = [...result.domains]
      displayedSync.value = { ...result.lastSync }
      emit('synced', result.domains, result.lastSync)
      status.value = `Sync complete. ${result.domains.length} active domains.`
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : 'Domain sync failed.'
      try {
        const settings = await api.admin.settings()
        emit('updated', settings)
        applySettings(settings, false)
      } catch {
        // Keep the sync error and last known whitelist when refresh also fails.
      }
      return
    }

    try {
      const settings = await api.admin.settings()
      emit('updated', settings)
      applySettings(settings, true)
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : 'Settings refresh failed.'
      error.value = `Domains synced, but settings refresh failed. ${detail}`
    }
  } finally {
    syncing.value = false
  }
}
</script>

<template>
  <section class="admin-section" aria-labelledby="domains-title">
    <div class="admin-section-heading">
      <div><p class="eyebrow">Provisioning policy</p><h1 id="domains-title">Domains &amp; Inbox</h1></div>
      <button class="secondary-button compact-button" type="button" :disabled="syncing || pending" @click="syncNow">{{ syncing ? 'Syncing' : 'Sync now' }}</button>
    </div>

    <div class="admin-data-grid domains-overview">
      <section aria-labelledby="whitelist-title">
        <h2 id="whitelist-title">Active whitelist</h2>
        <ul class="domain-list">
          <li v-for="domain in displayedDomains" :key="domain">{{ domain }}</li>
          <li v-if="!displayedDomains.length">No active domains.</li>
        </ul>
      </section>
      <section class="sync-summary" aria-labelledby="last-sync-title">
        <h2 id="last-sync-title">Last sync</h2>
        <dl>
          <div><dt>Time</dt><dd>{{ dateTime(displayedSync.created_at) }}</dd></div>
          <div><dt>Result</dt><dd :class="{ 'status-error': displayedSync.success === false }">{{ displayedSync.success === undefined ? 'Not yet' : displayedSync.success ? 'Successful' : 'Failed' }}</dd></div>
          <div><dt>Detail</dt><dd>{{ displayedSync.detail || 'None' }}</dd></div>
          <div><dt>Last successful sync</dt><dd>{{ syncText(displayedSuccessfulSync, 'Not yet') }}</dd></div>
          <div><dt>Last error</dt><dd :class="{ 'status-error': displayedSyncError.created_at }">{{ syncText(displayedSyncError, 'None') }}</dd></div>
        </dl>
      </section>
    </div>

    <form class="settings-form" @submit.prevent="save">
      <fieldset class="settings-fields" :disabled="pending || syncing">
        <label class="check-field"><input :checked="draft.autoSyncDomains" name="autoSyncDomains" type="checkbox" @change="changeAutoSync"> Automatically sync domains from the mail server</label>
        <div class="settings-grid settings-grid-three">
          <div class="field"><label for="fetch-seconds">Polling seconds</label><input id="fetch-seconds" v-model.number="draft.fetchSeconds" name="fetchSeconds" type="number" min="10" max="300" required></div>
          <div class="field"><label for="message-limit">Message limit</label><input id="message-limit" v-model.number="draft.messageLimit" name="messageLimit" type="number" min="1" max="100" required></div>
          <div class="field"><label for="local-min">Local-part minimum</label><input id="local-min" v-model.number="draft.localPartMin" name="localPartMin" type="number" min="1" max="64" required></div>
          <div class="field"><label for="local-max">Local-part maximum</label><input id="local-max" v-model.number="draft.localPartMax" name="localPartMax" type="number" min="1" max="64" required></div>
        </div>
        <div class="settings-grid">
          <div class="field"><label for="forbidden-ids">Forbidden IDs</label><textarea id="forbidden-ids" v-model="draft.forbiddenIds" name="forbiddenIds" rows="7" /><small>One ID per line or comma-separated.</small></div>
          <div class="field"><label for="blocked-senders">Blocked sender domains</label><textarea id="blocked-senders" v-model="draft.blockedSenderDomains" name="blockedSenderDomains" rows="7" /><small>One domain per line or comma-separated.</small></div>
        </div>
        <div class="form-actions"><button class="primary-button" type="submit" :disabled="pending || syncing">{{ pending ? 'Saving' : 'Save domains and inbox' }}</button></div>
      </fieldset>
      <p class="form-status" aria-live="polite">{{ status }}</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    </form>
  </section>
</template>
