// @vitest-environment jsdom

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminApp from '../admin/AdminApp.vue'
import ContentTab from '../admin/ContentTab.vue'
import DashboardTab from '../admin/DashboardTab.vue'
import DomainsTab from '../admin/DomainsTab.vue'
import GeneralTab from '../admin/GeneralTab.vue'
import MailServerTab from '../admin/MailServerTab.vue'

const styles = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8')

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  session: vi.fn(),
  logout: vi.fn(),
  settings: vi.fn(),
  updateSettings: vi.fn(),
  syncDomains: vi.fn(),
  testMail: vi.fn(),
  dashboard: vi.fn(),
}))

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: { ...actual.api, admin: { ...actual.api.admin, ...mocks } },
  }
})

enableAutoUnmount(afterEach)

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

const site = {
  appName: 'tmail',
  logoDataUrl: '',
  faviconDataUrl: '',
  primaryColor: '#45478f',
  accentColor: '#34366f',
  language: 'en',
  cookieEnabled: false,
  cookieText: '',
  fetchSeconds: 20,
  messageLimit: 50,
  headerHtml: '<header>Header</header>',
  footerHtml: '<footer>Footer</footer>',
  contentCss: 'body { color: navy; }',
  adSlots: { sidebar: '<script>window.ad = true</script>' },
  autoSyncDomains: true,
  localPartMin: 3,
  localPartMax: 32,
  forbiddenIds: ['admin'],
  blockedSenderDomains: ['blocked.example'],
}

const mailServer = {
  jmapUrl: 'https://mail.example/jmap',
  jmapToken: '********',
  catchallAddress: 'admin@example.com',
  mailAccountId: '',
  retentionDays: 30,
}

const settings = {
  site,
  mailServer,
  domains: ['example.com', 'mail.example'],
  lastSync: { success: true, detail: '2 domains', created_at: '2026-07-22T08:00:00Z' },
  lastSuccessfulSync: { success: true, detail: '2 domains', created_at: '2026-07-22T08:00:00Z' },
  lastSyncError: { success: false, detail: 'TimeoutError', created_at: '2026-07-21T08:00:00Z' },
}

const dashboard = {
  messages: { stored: 41, today: 6, sevenDays: 29 },
  domains: {
    active: 2,
    domainsToday: 3,
    domainsSevenDays: 9,
    recentDomains: [{ domain: 'fresh.example', created_at: '2026-07-22T07:30:00Z' }],
  },
  autoSyncDomains: true,
  lastSync: { success: false, detail: 'ValueError', created_at: '2026-07-22T09:00:00Z' },
  lastSuccessfulSync: { success: true, detail: '2 domains', created_at: '2026-07-22T08:00:00Z' },
  lastSyncError: { success: false, detail: 'ValueError', created_at: '2026-07-22T09:00:00Z' },
}

const failedSettings = {
  ...settings,
  lastSync: { success: false, detail: 'ValueError', created_at: '2026-07-22T09:00:00Z' },
  lastSyncError: { success: false, detail: 'ValueError', created_at: '2026-07-22T09:00:00Z' },
}

const syncedSettings = {
  ...settings,
  domains: ['new.example'],
  lastSync: { success: true, detail: '1 domain', created_at: '2026-07-22T10:00:00Z' },
  lastSuccessfulSync: { success: true, detail: '1 domain', created_at: '2026-07-22T10:00:00Z' },
}

describe('administration frontend', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.login.mockResolvedValue({ csrfToken: 'csrf-value' })
    mocks.session.mockRejectedValue(new Error('No active session'))
    mocks.logout.mockResolvedValue(undefined)
    mocks.settings.mockResolvedValue(settings)
    mocks.updateSettings.mockResolvedValue(settings)
    mocks.syncDomains.mockResolvedValue({
      domains: ['new.example'],
      lastSync: { success: true, detail: '1 domain', created_at: '2026-07-22T09:00:00Z' },
    })
    mocks.testMail.mockResolvedValue({ ok: true, domainCount: 2, messages: dashboard.messages })
    mocks.dashboard.mockResolvedValue(dashboard)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps the admin shell compact at the shared tablet breakpoint', () => {
    expect(styles).not.toContain('@media (max-width: 900px)')
    expect(styles).toMatch(/@media \(max-width: 952px\) \{[\s\S]*?\.admin-shell\.three-pane \{[\s\S]*?\.admin-content \{\s*grid-column: 2;/)
    expect(styles).toMatch(/\.admin-section \{[^}]*padding: 0;/)
    expect(styles).toMatch(/\.admin-section > h1,[^}]*font-size: clamp\(1\.6rem, 3vw, 2rem\);/)
    expect(styles).toMatch(/\.admin-login-panel h1 \{[^}]*font-size: clamp\(1\.6rem, 3vw, 2rem\);/)
  })

  it('logs in without persisting the password and exposes tabs in the required order', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = mount(AdminApp)

    expect(wrapper.get('input[type="password"]').exists()).toBe(true)
    expect(wrapper.get('.admin-note').text()).toContain('Your session is kept for 12 hours on this device.')
    expect(wrapper.get('.admin-note').text()).not.toContain('Sign in again after a reload.')
    expect(mocks.settings).not.toHaveBeenCalled()
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.login).toHaveBeenCalledWith('correct horse')
    expect(mocks.settings).toHaveBeenCalledTimes(1)
    expect(storage).not.toHaveBeenCalled()
    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).toEqual([
      'Dashboard',
      'General',
      'Mail Server',
      'Domains & Inbox',
      'HTML & Ads',
    ])
    expect(wrapper.get('.admin-shell').classes()).toContain('three-pane')
    expect(wrapper.get('.admin-account-rail').text()).toContain('tmail')
    expect(wrapper.get('.admin-sidebar').text()).toContain('Dashboard')
    expect(wrapper.get('.admin-content [role="tabpanel"]').exists()).toBe(true)
    expect(wrapper.text()).not.toMatch(/Sent|Contacts|Addresses/)
    expect(wrapper.find('main').exists()).toBe(false)
  })

  it('resumes an existing admin session on reload', async () => {
    mocks.session.mockResolvedValueOnce({ csrfToken: 'resumed-csrf' })
    const wrapper = mount(AdminApp)
    await flushPromises()

    expect(mocks.settings).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(5)
    await wrapper.get('.rail-signout').trigger('click')
    expect(mocks.logout).toHaveBeenCalledWith('resumed-csrf')
  })

  it('invalidates a new session when settings hydration fails', async () => {
    mocks.settings.mockRejectedValueOnce(new Error('Settings unavailable'))
    const wrapper = mount(AdminApp)
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.logout).toHaveBeenCalledWith('csrf-value')
    expect(wrapper.get('input[type="password"]').exists()).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('Settings unavailable')
  })

  it('retains failed hydration cleanup state until retry succeeds', async () => {
    mocks.settings.mockRejectedValueOnce(new Error('Settings unavailable'))
    mocks.logout.mockRejectedValueOnce(new Error('Cleanup unavailable')).mockResolvedValueOnce(undefined)
    const wrapper = mount(AdminApp)
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    const retry = () => wrapper.findAll('button').find((button) => button.text() === 'Retry session cleanup')
    expect(retry()?.exists()).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('Cleanup unavailable')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()

    await retry()!.trigger('click')
    await flushPromises()
    expect(mocks.logout).toHaveBeenCalledTimes(2)
    expect(mocks.logout).toHaveBeenLastCalledWith('csrf-value')
    expect(retry()).toBeUndefined()
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('retains the authenticated session until logout succeeds', async () => {
    const logout = deferred<void>()
    mocks.logout.mockReturnValueOnce(logout.promise)
    const wrapper = mount(AdminApp)
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    await wrapper.get('.rail-signout').trigger('click')
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(5)
    logout.reject(new Error('Logout unavailable'))
    await flushPromises()
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(5)
    expect(wrapper.get('[role="alert"]').text()).toContain('Logout unavailable')

    await wrapper.get('.rail-signout').trigger('click')
    await flushPromises()
    expect(wrapper.get('input[type="password"]').exists()).toBe(true)
  })

  it('moves between admin tabs with arrow keys', async () => {
    const wrapper = mount(AdminApp, { attachTo: document.body })
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const tabs = wrapper.findAll('[role="tab"]')

    await tabs[0]?.trigger('keydown', { key: 'ArrowRight' })

    expect(tabs[1]?.attributes('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[1]?.element)
    expect(wrapper.get('[role="tabpanel"]').attributes('aria-labelledby')).toBe(tabs[1]?.attributes('id'))
  })

  it('renders mail activity without host metrics or charts', async () => {
    const wrapper = mount(DashboardTab)
    await flushPromises()

    expect(wrapper.text()).toContain('Stored messages')
    expect(wrapper.text()).toContain('41')
    expect(wrapper.text()).toContain('Messages today')
    expect(wrapper.text()).toContain('Messages in seven days')
    expect(wrapper.find('canvas').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/CPU|memory|host uptime|active domains|provision|domain sync|auto-sync/i)
  })

  it('saves general settings with the in-memory CSRF token', async () => {
    const wrapper = mount(GeneralTab, { props: { site, csrf: 'csrf-value' } })
    await wrapper.get('input[name="appName"]').setValue('Mail Desk')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.updateSettings).toHaveBeenCalledWith({ site: {
      appName: 'Mail Desk',
      logoDataUrl: '',
      faviconDataUrl: '',
      primaryColor: '#45478f',
      accentColor: '#34366f',
      language: 'en',
      cookieEnabled: false,
      cookieText: '',
    } }, 'csrf-value')
    expect(wrapper.get('[aria-live="polite"]').text()).toContain('saved')
  })

  it('rejects non-image and oversized branding files before save', async () => {
    const wrapper = mount(GeneralTab, { props: { site, csrf: 'csrf-value' } })
    const input = wrapper.get('input[name="logo"]')
    const oversized = new File([new Uint8Array(1024 * 1024 + 1)], 'logo.png', { type: 'image/png' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [oversized] })
    await input.trigger('change')

    expect(wrapper.text()).toContain('no larger than 1 MiB')
    expect(mocks.updateSettings).not.toHaveBeenCalled()

    const text = new File(['not an image'], 'logo.txt', { type: 'text/plain' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [text] })
    await input.trigger('change')
    expect(wrapper.text()).toContain('Choose an image file')
  })

  it('keeps save disabled for overlapping file reads and uses only the latest selection', async () => {
    class DeferredReader {
      static instances: DeferredReader[] = []
      result: string | ArrayBuffer | null = null
      onload: ((event: ProgressEvent<FileReader>) => void) | null = null
      onerror: ((event: ProgressEvent<FileReader>) => void) | null = null
      onabort: ((event: ProgressEvent<FileReader>) => void) | null = null
      constructor() { DeferredReader.instances.push(this) }
      readAsDataURL() {}
    }
    vi.stubGlobal('FileReader', DeferredReader)
    const wrapper = mount(GeneralTab, { props: { site, csrf: 'csrf-value' } })
    const input = wrapper.get('input[name="logo"]')
    for (const name of ['old.png', 'new.png']) {
      Object.defineProperty(input.element, 'files', { configurable: true, value: [new File([name], name, { type: 'image/png' })] })
      await input.trigger('change')
    }

    DeferredReader.instances[1]!.result = 'data:image/png;base64,bmV3'
    DeferredReader.instances[1]!.onload?.(new ProgressEvent('load') as ProgressEvent<FileReader>)
    await flushPromises()
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    DeferredReader.instances[0]!.onabort?.(new ProgressEvent('abort') as ProgressEvent<FileReader>)
    await flushPromises()
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(mocks.updateSettings).toHaveBeenCalledWith({ site: expect.objectContaining({
      logoDataUrl: 'data:image/png;base64,bmV3',
    }) }, 'csrf-value')
    expect(wrapper.text()).not.toContain('Could not read image')
  })

  it('reports an aborted current image read and unlocks save', async () => {
    class AbortedReader {
      result = null
      onload = null
      onerror = null
      onabort: ((event: ProgressEvent<FileReader>) => void) | null = null
      readAsDataURL() { queueMicrotask(() => this.onabort?.(new ProgressEvent('abort') as ProgressEvent<FileReader>)) }
    }
    vi.stubGlobal('FileReader', AbortedReader)
    const wrapper = mount(GeneralTab, { props: { site, csrf: 'csrf-value' } })
    const input = wrapper.get('input[name="logo"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['x'], 'logo.png', { type: 'image/png' })] })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('Could not read image')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('preserves an unchanged masked token and tests mail with CSRF', async () => {
    const wrapper = mount(MailServerTab, { props: { mailServer, csrf: 'csrf-value' } })
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.updateSettings).toHaveBeenCalledWith({
      mailServer: expect.not.objectContaining({ jmapToken: expect.anything() }),
    }, 'csrf-value')

    await wrapper.get('button[type="button"]').trigger('click')
    await flushPromises()
    expect(mocks.testMail).toHaveBeenCalledWith('csrf-value')
  })

  it('locks every settings form and preserves its draft while a save is pending', async () => {
    const response = deferred<typeof settings>()
    mocks.updateSettings.mockReturnValue(response.promise)
    const general = mount(GeneralTab, { props: { site, csrf: 'csrf-value' } })
    const mail = mount(MailServerTab, { props: { mailServer, csrf: 'csrf-value' } })
    const domains = mount(DomainsTab, { props: {
      site,
      domains: settings.domains,
      lastSync: settings.lastSync,
      lastSuccessfulSync: settings.lastSuccessfulSync,
      lastSyncError: settings.lastSyncError,
      csrf: 'csrf-value',
    } })
    const content = mount(ContentTab, { props: { site, csrf: 'csrf-value' } })

    await general.get('input[name="appName"]').setValue('Draft app')
    await mail.get('input[name="jmapUrl"]').setValue('https://draft.example/jmap')
    await domains.get('input[name="fetchSeconds"]').setValue('45')
    await content.get('textarea[name="headerHtml"]').setValue('Draft header')
    for (const wrapper of [general, mail, domains, content]) await wrapper.get('form').trigger('submit')

    await general.setProps({ site: { ...site, appName: 'Remote app' } })
    await mail.setProps({ mailServer: { ...mailServer, jmapUrl: 'https://remote.example/jmap' } })
    await domains.setProps({ site: { ...site, fetchSeconds: 90 } })
    await content.setProps({ site: { ...site, headerHtml: 'Remote header' } })

    for (const wrapper of [general, mail, domains, content]) {
      expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
    }
    expect((general.get('input[name="appName"]').element as HTMLInputElement).value).toBe('Draft app')
    expect((mail.get('input[name="jmapUrl"]').element as HTMLInputElement).value).toBe('https://draft.example/jmap')
    expect((domains.get('input[name="fetchSeconds"]').element as HTMLInputElement).value).toBe('45')
    expect((content.get('textarea[name="headerHtml"]').element as HTMLTextAreaElement).value).toBe('Draft header')

    response.resolve(settings)
    await flushPromises()
    for (const wrapper of [general, mail, domains, content]) wrapper.unmount()
  })

  it('blocks tab navigation until a deferred child save updates parent settings', async () => {
    const response = deferred<typeof settings>()
    mocks.updateSettings.mockReturnValueOnce(response.promise)
    const wrapper = mount(AdminApp)
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const tab = (name: string) => wrapper.findAll('[role="tab"]').find((item) => item.text() === name)!
    await tab('General').trigger('click')
    await wrapper.get('input[name="appName"]').setValue('Saved app')
    await wrapper.get('form').trigger('submit')

    expect(tab('Mail Server').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.rail-signout').attributes('disabled')).toBeDefined()
    await tab('Mail Server').trigger('click')
    expect(wrapper.find('input[name="appName"]').exists()).toBe(true)

    response.resolve({ ...settings, site: { ...site, appName: 'Saved app' } })
    await flushPromises()
    expect(tab('Mail Server').attributes('disabled')).toBeUndefined()
    await tab('Mail Server').trigger('click')
    await tab('General').trigger('click')
    expect((wrapper.get('input[name="appName"]').element as HTMLInputElement).value).toBe('Saved app')
  })

  it('warns that disabling auto-sync freezes the current whitelist', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(DomainsTab, {
      props: {
        site,
        domains: settings.domains,
        lastSync: settings.lastSync,
        lastSuccessfulSync: settings.lastSuccessfulSync,
        lastSyncError: settings.lastSyncError,
        csrf: 'csrf-value',
      },
    })
    await wrapper.get('input[name="autoSyncDomains"]').setValue(false)

    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/current whitelist.*freeze/i))
    expect((wrapper.get('input[name="autoSyncDomains"]').element as HTMLInputElement).checked).toBe(true)
    expect(mocks.updateSettings).not.toHaveBeenCalled()
  })

  it('persists auto-sync immediately and keeps it in the later full save', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const updated = {
      ...settings,
      site: { ...site, autoSyncDomains: false },
      domains: ['updated.example'],
    }
    mocks.updateSettings.mockResolvedValueOnce(updated).mockResolvedValueOnce(updated)
    const wrapper = mount(DomainsTab, {
      props: {
        site,
        domains: settings.domains,
        lastSync: settings.lastSync,
        lastSuccessfulSync: settings.lastSuccessfulSync,
        lastSyncError: settings.lastSyncError,
        csrf: 'csrf-value',
      },
    })

    await wrapper.get('input[name="autoSyncDomains"]').setValue(false)
    await flushPromises()

    expect(mocks.updateSettings).toHaveBeenNthCalledWith(1, {
      site: { autoSyncDomains: false },
    }, 'csrf-value')
    expect(wrapper.emitted('updated')?.[0]).toEqual([updated])
    expect(wrapper.text()).toContain('updated.example')

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(mocks.updateSettings).toHaveBeenNthCalledWith(2, { site: expect.objectContaining({
      autoSyncDomains: false,
    }) }, 'csrf-value')
  })

  it('rolls back auto-sync when the immediate update fails', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mocks.updateSettings.mockRejectedValueOnce(new Error('save offline'))
    const wrapper = mount(DomainsTab, {
      props: {
        site,
        domains: settings.domains,
        lastSync: settings.lastSync,
        lastSuccessfulSync: settings.lastSuccessfulSync,
        lastSyncError: settings.lastSyncError,
        csrf: 'csrf-value',
      },
    })

    await wrapper.get('input[name="autoSyncDomains"]').setValue(false)
    await flushPromises()

    expect((wrapper.get('input[name="autoSyncDomains"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('save offline')
  })

  it('replaces the displayed whitelist only after a successful manual sync', async () => {
    mocks.syncDomains.mockRejectedValueOnce(new Error('offline'))
    mocks.settings.mockResolvedValueOnce(failedSettings).mockResolvedValueOnce(syncedSettings)
    const wrapper = mount(DomainsTab, {
      props: {
        site,
        domains: settings.domains,
        lastSync: settings.lastSync,
        lastSuccessfulSync: settings.lastSuccessfulSync,
        lastSyncError: settings.lastSyncError,
        csrf: 'csrf-value',
      },
    })

    await wrapper.get('button[type="button"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('example.com')
    expect(wrapper.text()).not.toContain('new.example')
    expect(wrapper.text()).toContain('ValueError')
    expect(wrapper.emitted('updated')?.[0]).toEqual([failedSettings])

    await wrapper.get('button[type="button"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('new.example')
    expect(wrapper.text()).not.toContain('mail.example')
    expect(wrapper.emitted('updated')?.[1]).toEqual([syncedSettings])
    expect(mocks.settings).toHaveBeenCalledTimes(2)
  })

  it('keeps the successful POST whitelist when the settings refresh fails', async () => {
    mocks.syncDomains.mockResolvedValueOnce({
      domains: ['post.example'],
      lastSync: { success: true, detail: '1 domain', created_at: '2026-07-22T11:00:00Z' },
    })
    mocks.settings.mockRejectedValue(new Error('refresh offline'))
    const wrapper = mount(DomainsTab, {
      props: {
        site,
        domains: settings.domains,
        lastSync: settings.lastSync,
        lastSuccessfulSync: settings.lastSuccessfulSync,
        lastSyncError: settings.lastSyncError,
        csrf: 'csrf-value',
      },
    })

    await wrapper.get('.admin-section-heading button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('post.example')
    expect(wrapper.text()).not.toContain('mail.example')
    const lastSuccessfulSync = wrapper.findAll('.sync-summary dl > div').find(
      (row) => row.get('dt').text() === 'Last successful sync',
    )
    expect(lastSuccessfulSync?.get('dd').text()).toContain('1 domain')
    expect(lastSuccessfulSync?.get('dd').text()).not.toContain('2 domains')
    expect(wrapper.get('[role="alert"]').text()).toContain('synced, but settings refresh failed')
    expect(mocks.settings).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('synced')?.[0]).toEqual([[
      'post.example',
    ], { success: true, detail: '1 domain', created_at: '2026-07-22T11:00:00Z' }])
  })

  it('keeps an authoritative synced whitelist after the domains tab remounts', async () => {
    mocks.settings.mockResolvedValueOnce(settings).mockResolvedValueOnce(syncedSettings)
    const wrapper = mount(AdminApp)
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const tab = (name: string) => wrapper.findAll('[role="tab"]').find((item) => item.text() === name)!

    await tab('Domains & Inbox').trigger('click')
    await wrapper.get('.admin-section-heading button').trigger('click')
    await flushPromises()
    await tab('General').trigger('click')
    await tab('Domains & Inbox').trigger('click')

    expect(wrapper.text()).toContain('new.example')
    expect(wrapper.text()).not.toContain('mail.example')
  })

  it('previews HTML and ads only in opaque content sandbox frames', () => {
    const wrapper = mount(ContentTab, { props: { site, csrf: 'csrf-value' } })
    const frames = wrapper.findAll('iframe')

    expect(frames.length).toBeGreaterThanOrEqual(3)
    for (const frame of frames) {
      expect(frame.attributes('sandbox')).toContain('allow-scripts')
      expect(frame.attributes('sandbox')).not.toContain('allow-same-origin')
    }
    expect(wrapper.text()).toContain('cannot access inbox storage')
    expect(wrapper.find('[contenteditable]').exists()).toBe(false)
  })

  it('rejects duplicate normalized ad names and oversized content before submit', async () => {
    const wrapper = mount(ContentTab, { props: { site, csrf: 'csrf-value' } })
    await wrapper.get('.subsection-heading button').trigger('click')
    const names = wrapper.findAll('.ad-editor input')
    await names[1]!.setValue(' sidebar ')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('[role="alert"]').text()).toContain('unique')
    expect(mocks.updateSettings).not.toHaveBeenCalled()

    await names[1]!.setValue('banner')
    await wrapper.get('textarea[name="headerHtml"]').setValue('x'.repeat(100_001))
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('100,000')
    expect(mocks.updateSettings).not.toHaveBeenCalled()
  })
})
