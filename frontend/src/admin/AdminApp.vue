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
const error = ref('')

function moveTab(event: KeyboardEvent, index: number): void {
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

async function login(): Promise<void> {
  pending.value = true
  error.value = ''
  try {
    const session = await api.admin.login(password.value)
    const loaded = await api.admin.settings()
    csrf.value = session.csrfToken
    settings.value = loaded
    password.value = ''
  } catch (cause) {
    csrf.value = ''
    settings.value = null
    error.value = cause instanceof Error ? cause.message : 'Could not sign in.'
  } finally {
    password.value = ''
    pending.value = false
  }
}

async function logout(): Promise<void> {
  const token = csrf.value
  csrf.value = ''
  settings.value = null
  activeTab.value = 'Dashboard'
  error.value = ''
  if (!token) return
  try {
    await api.admin.logout(token)
  } catch {
    // In-memory credentials are already cleared.
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
        <div class="field"><label for="admin-password">Administrator password</label><input id="admin-password" v-model="password" type="password" autocomplete="current-password" required autofocus></div>
        <button class="primary-button" type="submit" :disabled="pending">{{ pending ? 'Signing in' : 'Log in' }}</button>
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
          :aria-selected="activeTab === tab"
          :tabindex="activeTab === tab ? 0 : -1"
          @click="activeTab = tab"
          @keydown="moveTab($event, index)"
        >{{ tab }}</button>
      </nav>
      <button class="text-button" type="button" @click="logout">Log out</button>
    </aside>

    <main class="admin-content">
      <div role="tabpanel" tabindex="0" :aria-labelledby="`admin-tab-${tabs.indexOf(activeTab)}`">
        <DashboardTab v-if="activeTab === 'Dashboard'" />
        <GeneralTab v-else-if="activeTab === 'General'" :site="settings.site" :csrf="csrf" @updated="settings = $event" />
        <MailServerTab v-else-if="activeTab === 'Mail Server'" :mail-server="settings.mailServer" :csrf="csrf" @updated="settings = $event" />
        <DomainsTab v-else-if="activeTab === 'Domains & Inbox'" :site="settings.site" :domains="settings.domains" :last-sync="settings.lastSync" :csrf="csrf" @updated="settings = $event" />
        <ContentTab v-else :site="settings.site" :csrf="csrf" @updated="settings = $event" />
      </div>
    </main>
  </div>
</template>
