<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AddressPanel from './components/AddressPanel.vue'
import InboxView from './components/InboxView.vue'
import SandboxFrame from './components/SandboxFrame.vue'
import AdminApp from './admin/AdminApp.vue'
import { ApiError, api } from './api'
import { parseRoute } from './route'
import { loadSessions, saveSession } from './session'
import type { AddressSession, SiteResource } from './types'

type View = 'address' | 'inbox' | 'admin'

const initialRoute = parseRoute(window.location.pathname)
const view = ref<View>(initialRoute.name === 'admin' ? 'admin' : 'address')
const current = ref<AddressSession | null>(null)
const site = ref<SiteResource | null>(null)
const loading = ref(initialRoute.name === 'address')
const error = ref('')
let navigationVersion = 0
let siteVersion = 0
const root = document.documentElement
const originalLanguage = root.getAttribute('lang')
const originalPrimary = root.style.getPropertyValue('--primary')
const originalAccent = root.style.getPropertyValue('--accent')
const originalFavicon = document.head.querySelector<HTMLLinkElement>('link[rel~="icon"]')
const originalFaviconHref = originalFavicon?.getAttribute('href') ?? null
let favicon = originalFavicon
let createdFavicon = false

const adSlots = computed(() => Object.entries(site.value?.adSlots ?? {})
  .filter((entry): entry is [string, string] => typeof entry[1] === 'string' && Boolean(entry[1])))

function applySite(value: SiteResource | null): void {
  if (!value) return
  root.style.setProperty('--primary', value.primaryColor)
  root.style.setProperty('--accent', value.accentColor)
  root.lang = value.language
  if (value.faviconDataUrl) {
    if (!favicon) {
      favicon = document.createElement('link')
      favicon.rel = 'icon'
      favicon.dataset.tmailFavicon = ''
      document.head.append(favicon)
      createdFavicon = true
    }
    favicon.setAttribute('href', value.faviconDataUrl)
  } else if (createdFavicon) {
    favicon?.remove()
    favicon = null
    createdFavicon = false
  } else if (favicon) {
    if (originalFaviconHref === null) favicon.removeAttribute('href')
    else favicon.setAttribute('href', originalFaviconHref)
  }
}

function cleanupSite(): void {
  if (originalPrimary) root.style.setProperty('--primary', originalPrimary)
  else root.style.removeProperty('--primary')
  if (originalAccent) root.style.setProperty('--accent', originalAccent)
  else root.style.removeProperty('--accent')
  if (originalLanguage === null) root.removeAttribute('lang')
  else root.setAttribute('lang', originalLanguage)
  if (createdFavicon) favicon?.remove()
  else if (originalFavicon) {
    if (originalFaviconHref === null) originalFavicon.removeAttribute('href')
    else originalFavicon.setAttribute('href', originalFaviconHref)
  }
}

watch(site, applySite)

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

async function loadSite(): Promise<void> {
  const version = ++siteVersion
  try {
    const value = await api.site()
    if (version === siteVersion) site.value = value
  } catch {
    // Site customization is optional; core mail remains available.
  }
}

function handlePopState(): void {
  void reconcileRoute()
}

onMounted(() => {
  window.addEventListener('popstate', handlePopState)
  void loadSite()
  void reconcileRoute()
})

onBeforeUnmount(() => {
  navigationVersion += 1
  siteVersion += 1
  window.removeEventListener('popstate', handlePopState)
  cleanupSite()
})
</script>

<template>
  <div class="app-frame">
    <SandboxFrame
      v-if="site?.headerHtml"
      class="site-content-frame site-header-frame"
      :html="site.headerHtml"
      :css="site.contentCss"
      mode="content"
      title="Configured site header"
    />
    <header class="site-header">
      <a class="brand" href="/" :aria-label="`${site?.appName || 'tmail'} home`">
        <img v-if="site?.logoDataUrl" :src="site.logoDataUrl" alt="">
        <span>{{ site?.appName || 'tmail' }}</span>
      </a>
      <nav aria-label="Site navigation">
        <a href="/docs">API docs</a>
        <a href="/admin">Admin</a>
      </nav>
    </header>

    <main>
      <SandboxFrame
        v-for="([name, html]) in adSlots"
        :key="name"
        class="site-content-frame ad-frame"
        :html="html"
        :css="site?.contentCss"
        mode="content"
        :title="`Configured ${name} content`"
      />
      <AdminApp v-if="view === 'admin'" />

      <InboxView
        v-else-if="view === 'inbox' && current"
        :session="current"
        :fetch-seconds="site?.fetchSeconds ?? 20"
        @new-address="newAddress"
      />

      <section v-else-if="loading" class="handoff-loading" aria-live="polite">
        <span class="skeleton skeleton-label" />
        <span class="skeleton skeleton-title" />
        <span class="skeleton skeleton-field" />
        <span class="sr-only">Opening address</span>
      </section>

      <AddressPanel v-else :initial-error="error" @open="openCreatedInbox" />
    </main>

    <section
      v-if="site?.cookieEnabled && site.cookieText"
      class="cookie-notice"
      role="status"
      aria-label="Cookie notice"
    >
      {{ site.cookieText }}
    </section>

    <SandboxFrame
      v-if="site?.footerHtml"
      class="site-content-frame site-footer-frame"
      :html="site.footerHtml"
      :css="site.contentCss"
      mode="content"
      title="Configured site footer"
    />
    <footer class="site-footer">
      <span>Passwordless temporary mail</span>
      <a href="/docs">API reference</a>
    </footer>
  </div>
</template>
