<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import type { AdminSettings } from '../types'
import ContentTab from './ContentTab.vue'
import DashboardTab from './DashboardTab.vue'
import DomainsTab from './DomainsTab.vue'
import GeneralTab from './GeneralTab.vue'
import MailServerTab from './MailServerTab.vue'

const tabs = ['Dashboard', 'General', 'Mail Server', 'Domains & Inbox', 'HTML & Ads'] as const
type Tab = typeof tabs[number]

const password = ref('')
const csrf = ref('')
const settings = ref<AdminSettings | null>(null)
const activeTab = ref<Tab>('Dashboard')
const pending = ref(false)
const childBusy = ref(false)
const cleanupCsrf = ref('')
const error = ref('')

function moveTab(event: KeyboardEvent, index: number): void {
  if (childBusy.value) return
  let next = index
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tabs.length
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + tabs.length) % tabs.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = tabs.length - 1
  else return
  event.preventDefault()
  const tab = tabs[next]
  if (!tab) return
  activeTab.value = tab
  const buttons = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role="tab"]')
  buttons?.[next]?.focus()
}

function selectTab(tab: Tab): void {
  if (!childBusy.value) activeTab.value = tab
}

function applyDomainSync(domains: string[], lastSync: AdminSettings['lastSync']): void {
  if (!settings.value) return
  settings.value = {
    ...settings.value,
    domains: [...domains],
    lastSync: { ...lastSync },
    lastSuccessfulSync: { ...lastSync },
  }
}

async function login(): Promise<void> {
  if (cleanupCsrf.value) return
  pending.value = true
  error.value = ''
  let newCsrf = ''
  try {
    const session = await api.admin.login(password.value)
    newCsrf = session.csrfToken
    const loaded = await api.admin.settings()
    csrf.value = newCsrf
    settings.value = loaded
    password.value = ''
  } catch (cause) {
    const loginError = cause instanceof Error ? cause.message : 'Could not sign in.'
    if (newCsrf) {
      try {
        await api.admin.logout(newCsrf)
      } catch (cleanupCause) {
        cleanupCsrf.value = newCsrf
        const detail = cleanupCause instanceof Error ? cleanupCause.message : 'Cleanup unavailable.'
        error.value = `${loginError} Session cleanup failed. ${detail}`
      }
    }
    csrf.value = ''
    settings.value = null
    if (!cleanupCsrf.value) error.value = loginError
  } finally {
    password.value = ''
    pending.value = false
  }
}

async function retryCleanup(): Promise<void> {
  const token = cleanupCsrf.value
  if (!token) return
  pending.value = true
  error.value = ''
  try {
    await api.admin.logout(token)
    cleanupCsrf.value = ''
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : 'Cleanup unavailable.'
    error.value = `Session cleanup failed. ${detail}`
  } finally {
    pending.value = false
  }
}

async function logout(): Promise<void> {
  if (childBusy.value) return
  const token = csrf.value
  error.value = ''
  if (!token) return
  pending.value = true
  try {
    await api.admin.logout(token)
    csrf.value = ''
    settings.value = null
    activeTab.value = 'Dashboard'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not log out.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section v-if="!settings" class="admin-login" aria-labelledby="admin-login-title">
    <div class="admin-login-panel panel">
      <p class="eyebrow">Administration</p>
      <h1 id="admin-login-title">Admin access</h1>
      <p class="admin-note">Sign in again after a reload. Credentials are never stored in this browser.</p>
      <form class="settings-form" @submit.prevent="login">
        <div class="field"><label for="admin-password">Administrator password</label><input id="admin-password" v-model="password" type="password" autocomplete="current-password" required autofocus :disabled="pending || Boolean(cleanupCsrf)"></div>
        <button class="primary-button" type="submit" :disabled="pending || Boolean(cleanupCsrf)">{{ pending ? 'Signing in' : 'Log in' }}</button>
        <button v-if="cleanupCsrf" class="secondary-button" type="button" :disabled="pending" @click="retryCleanup">{{ pending ? 'Retrying cleanup' : 'Retry session cleanup' }}</button>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      </form>
    </div>
  </section>

  <div v-else class="admin-shell">
    <aside class="admin-sidebar">
      <div><p class="eyebrow">Administration</p><strong>{{ settings.site.appName }}</strong></div>
      <nav role="tablist" aria-label="Administration sections">
        <button
          v-for="(tab, index) in tabs"
          :id="`admin-tab-${index}`"
          :key="tab"
          role="tab"
          type="button"
          :disabled="childBusy"
          :aria-selected="activeTab === tab"
          :tabindex="activeTab === tab ? 0 : -1"
          @click="selectTab(tab)"
          @keydown="moveTab($event, index)"
        >{{ tab }}</button>
      </nav>
      <button class="text-button" type="button" :disabled="pending || childBusy" @click="logout">{{ pending ? 'Logging out' : 'Log out' }}</button>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    </aside>

    <div class="admin-content">
      <div role="tabpanel" tabindex="0" :aria-labelledby="`admin-tab-${tabs.indexOf(activeTab)}`">
        <DashboardTab v-if="activeTab === 'Dashboard'" />
        <GeneralTab v-else-if="activeTab === 'General'" :site="settings.site" :csrf="csrf" @busy="childBusy = $event" @updated="settings = $event" />
        <MailServerTab v-else-if="activeTab === 'Mail Server'" :mail-server="settings.mailServer" :csrf="csrf" @busy="childBusy = $event" @updated="settings = $event" />
        <DomainsTab v-else-if="activeTab === 'Domains & Inbox'" :site="settings.site" :domains="settings.domains" :last-sync="settings.lastSync" :last-successful-sync="settings.lastSuccessfulSync" :last-sync-error="settings.lastSyncError" :csrf="csrf" @busy="childBusy = $event" @synced="applyDomainSync" @updated="settings = $event" />
        <ContentTab v-else :site="settings.site" :csrf="csrf" @busy="childBusy = $event" @updated="settings = $event" />
      </div>
    </div>
  </div>
</template>
