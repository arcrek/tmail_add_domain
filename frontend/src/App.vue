<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import AddressPanel from './components/AddressPanel.vue'
import { ApiError, api } from './api'
import { parseRoute } from './route'
import { loadSessions, saveSession } from './session'
import type { AddressSession } from './types'

type View = 'address' | 'inbox' | 'admin'

const initialRoute = parseRoute(window.location.pathname)
const view = ref<View>(initialRoute.name === 'admin' ? 'admin' : 'address')
const current = ref<AddressSession | null>(null)
const loading = ref(initialRoute.name === 'address')
const error = ref('')
const copied = ref(false)
let navigationVersion = 0

function openInbox(session: AddressSession, updatePath = true): void {
  current.value = session
  saveSession(session)
  view.value = 'inbox'
  const path = `/${encodeURIComponent(session.address)}`
  if (updatePath && location.pathname !== path) history.pushState({}, '', path)
}

function openCreatedInbox(session: AddressSession): void {
  navigationVersion += 1
  openInbox(session)
}

async function reconcileRoute(): Promise<void> {
  const version = ++navigationVersion
  const route = parseRoute(window.location.pathname)
  current.value = null
  error.value = ''
  copied.value = false
  loading.value = false

  if (route.name === 'admin') {
    view.value = 'admin'
    return
  }
  if (route.name !== 'address') {
    view.value = 'address'
    return
  }

  const remembered = loadSessions().find((session) => session.address === route.address)
  if (remembered) {
    openInbox(remembered, false)
    return
  }

  view.value = 'address'
  loading.value = true
  try {
    const response = await api.token(route.address)
    if (version === navigationVersion) openInbox({ address: route.address, token: response.token }, false)
  } catch (cause) {
    if (version === navigationVersion) {
      error.value = cause instanceof ApiError ? cause.message : 'The mail service is unavailable. Try again.'
      view.value = 'address'
    }
  } finally {
    if (version === navigationVersion) loading.value = false
  }
}

function newAddress(): void {
  navigationVersion += 1
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

function handlePopState(): void {
  void reconcileRoute()
}

onMounted(() => {
  window.addEventListener('popstate', handlePopState)
  void reconcileRoute()
})

onBeforeUnmount(() => {
  navigationVersion += 1
  window.removeEventListener('popstate', handlePopState)
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

      <AddressPanel v-else :initial-error="error" @open="openCreatedInbox" />
    </main>

    <footer class="site-footer">
      <span>Passwordless temporary mail</span>
      <a href="/docs">API reference</a>
    </footer>
  </div>
</template>
