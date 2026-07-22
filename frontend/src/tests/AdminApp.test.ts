// @vitest-environment jsdom

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminApp from '../admin/AdminApp.vue'
import ContentTab from '../admin/ContentTab.vue'
import DashboardTab from '../admin/DashboardTab.vue'
import DomainsTab from '../admin/DomainsTab.vue'
import GeneralTab from '../admin/GeneralTab.vue'
import MailServerTab from '../admin/MailServerTab.vue'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
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
  lastSync: { success: true, detail: '2 domains', created_at: '2026-07-22T08:00:00Z' },
}

describe('administration frontend', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.login.mockResolvedValue({ csrfToken: 'csrf-value' })
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

  afterEach(() => vi.restoreAllMocks())

  it('logs in without persisting the password and exposes tabs in the required order', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = mount(AdminApp)

    expect(wrapper.get('input[type="password"]').exists()).toBe(true)
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
    expect(wrapper.text()).toContain('Provisions in seven days')
    expect(wrapper.text()).toContain('9')
    expect(wrapper.text()).toContain('fresh.example')
    expect(wrapper.find('canvas').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/CPU|memory|host uptime/i)
  })

  it('saves general settings with the in-memory CSRF token', async () => {
    const wrapper = mount(GeneralTab, { props: { site, csrf: 'csrf-value' } })
    await wrapper.get('input[name="appName"]').setValue('Mail Desk')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.updateSettings).toHaveBeenCalledWith({
      site: expect.objectContaining({ appName: 'Mail Desk' }),
    }, 'csrf-value')
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

  it('warns that disabling auto-sync freezes the current whitelist', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(DomainsTab, {
      props: { site, domains: settings.domains, lastSync: settings.lastSync, csrf: 'csrf-value' },
    })
    await wrapper.get('input[name="autoSyncDomains"]').setValue(false)

    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/current whitelist.*freeze/i))
    expect((wrapper.get('input[name="autoSyncDomains"]').element as HTMLInputElement).checked).toBe(true)
    expect(mocks.updateSettings).not.toHaveBeenCalled()
  })

  it('replaces the displayed whitelist only after a successful manual sync', async () => {
    mocks.syncDomains.mockRejectedValueOnce(new Error('offline'))
    const wrapper = mount(DomainsTab, {
      props: { site, domains: settings.domains, lastSync: settings.lastSync, csrf: 'csrf-value' },
    })

    await wrapper.get('button[type="button"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('example.com')
    expect(wrapper.text()).not.toContain('new.example')

    await wrapper.get('button[type="button"]').trigger('click')
    await flushPromises()
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
})
