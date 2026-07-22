<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AddressPanel from './components/AddressPanel.vue'
import { ApiError, api } from './api'
import { parseRoute } from './route'
import { saveSession } from './session'
import type { AddressSession } from './types'

type View = 'address' | 'inbox' | 'admin'

const route = parseRoute(window.location.pathname)
const view = ref<View>(route.name === 'admin' ? 'admin' : 'address')
const current = ref<AddressSession | null>(null)
const loading = ref(route.name === 'address')
const error = ref('')
const copied = ref(false)

function openInbox(session: AddressSession, updatePath = true): void {
  current.value = session
  saveSession(session)
  view.value = 'inbox'
  if (updatePath) history.pushState({}, '', `/${encodeURIComponent(session.address)}`)
}

async function handoff(address: string): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const response = await api.token(address)
    openInbox({ address, token: response.token }, false)
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause.message : 'The mail service is unavailable. Try again.'
    view.value = 'address'
  } finally {
    loading.value = false
  }
}

function newAddress(): void {
  current.value = null
  error.value = ''
  view.value = 'address'
  history.pushState({}, '', '/')
}

async function copyCurrent(): Promise<void> {
  if (!current.value) return
  try {
    await navigator.clipboard.writeText(current.value.address)
    copied.value = true
  } catch {
    error.value = 'Copy failed. Select the address and copy it manually.'
  }
}

onMounted(() => {
  if (route.name === 'address') void handoff(route.address)
})
</script>

<template>
  <div class="app-frame">
    <header class="site-header">
      <a class="brand" href="/" aria-label="Temporary Mail home">tmail</a>
      <nav aria-label="Site navigation">
        <a href="/docs">API docs</a>
        <a href="/admin">Admin</a>
      </nav>
    </header>

    <main>
      <section v-if="view === 'admin'" class="admin-placeholder" aria-labelledby="admin-title">
        <p class="eyebrow">Administration</p>
        <h1 id="admin-title">Admin access</h1>
        <p>The settings interface is being prepared.</p>
      </section>

      <section v-else-if="view === 'inbox' && current" class="inbox-handoff" aria-labelledby="inbox-title">
        <div>
          <p class="eyebrow">Inbox ready</p>
          <h1 id="inbox-title">{{ current.address }}</h1>
          <p class="lede">Messages sent to this address will appear here.</p>
        </div>
        <div class="inbox-actions">
          <button class="secondary-button" type="button" @click="copyCurrent">
            {{ copied ? 'Copied' : 'Copy address' }}
          </button>
          <button class="primary-button" type="button" @click="newAddress">New address</button>
        </div>
        <p v-if="error" class="form-error inbox-error" aria-live="polite">{{ error }}</p>
        <div class="inbox-empty">
          <h2>Waiting for mail</h2>
          <p>Keep this page open. The inbox view will refresh when messages arrive.</p>
        </div>
      </section>

      <section v-else-if="loading" class="handoff-loading" aria-live="polite">
        <span class="skeleton skeleton-label" />
        <span class="skeleton skeleton-title" />
        <span class="skeleton skeleton-field" />
        <span class="sr-only">Opening address</span>
      </section>

      <AddressPanel v-else :initial-error="error" @open="openInbox" />
    </main>

    <footer class="site-footer">
      <span>Passwordless temporary mail</span>
      <a href="/docs">API reference</a>
    </footer>
  </div>
</template>
