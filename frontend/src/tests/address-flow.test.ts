// @vitest-environment jsdom

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import App from '../App.vue'
import AddressPanel from '../components/AddressPanel.vue'

const mocks = vi.hoisted(() => ({
  domains: vi.fn(),
  token: vi.fn(),
  site: vi.fn(),
  messages: vi.fn(),
}))

enableAutoUnmount(afterEach)

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, api: { ...actual.api, ...mocks } }
})

const domains = (values: string[]) => ({
  '@context': '/contexts/Domain',
  '@id': '/domains',
  '@type': 'hydra:Collection',
  'hydra:totalItems': values.length,
  'hydra:member': values.map((domain, index) => ({ id: String(index), domain })),
})

describe('address flow', () => {
  beforeEach(() => {
    localStorage.clear()
    history.replaceState({}, '', '/')
    mocks.domains.mockReset().mockResolvedValue(domains(['example.com']))
    mocks.token.mockReset().mockResolvedValue({ id: 'account-id', token: 'signed-token' })
    mocks.site.mockReset().mockResolvedValue({
      appName: 'tmail',
      logoDataUrl: '',
      faviconDataUrl: '',
      primaryColor: '#45478f',
      accentColor: '#34366f',
      language: 'en',
      cookieEnabled: false,
      cookieText: '',
      fetchSeconds: 20,
      messageLimit: 100,
      headerHtml: '<strong>Configured header</strong>',
      footerHtml: '<small>Configured footer</small>',
      contentCss: 'body { color: navy; }',
      adSlots: { sidebar: '<script>window.adLoaded = true</script>' },
    })
    mocks.messages.mockReset().mockResolvedValue({
      '@context': '/contexts/Message',
      '@id': '/messages?page=1',
      '@type': 'hydra:Collection',
      'hydra:totalItems': 0,
      'hydra:member': [],
      'hydra:view': {
        '@id': '/messages?page=1',
        '@type': 'hydra:PartialCollectionView',
        'hydra:first': '/messages?page=1',
        'hydra:last': '/messages?page=1',
      },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('hands a direct address link into the inbox without another action', async () => {
    history.replaceState({}, '', '/Box%40Example.com')
    const wrapper = mount(App)
    await flushPromises()

    expect(mocks.token).toHaveBeenCalledWith('box@example.com')
    expect(wrapper.text()).toContain('Inbox ready')
    expect(wrapper.text()).toContain('box@example.com')
    expect(JSON.parse(localStorage.getItem('tmail.addresses') ?? '[]')).toEqual([
      { address: 'box@example.com', token: 'signed-token' },
    ])
  })

  it('keeps configured site and ad HTML inside opaque sandbox frames', async () => {
    const wrapper = mount(App)
    await flushPromises()

    expect(mocks.site).toHaveBeenCalledTimes(1)
    const frames = wrapper.findAll('iframe.site-content-frame')
    expect(frames).toHaveLength(3)
    expect(frames[0]?.attributes('srcdoc')).toContain('<strong>Configured header</strong>')
    expect(frames[2]?.attributes('srcdoc')).toContain('<small>Configured footer</small>')
    expect(frames[1]?.attributes('sandbox')).toContain('allow-scripts')
    expect(frames[1]?.attributes('sandbox')).not.toContain('allow-same-origin')
    expect(wrapper.text()).not.toContain('Configured header')
  })

  it('applies and cleans up configured branding, language, favicon, and cookie notice', async () => {
    const root = document.documentElement
    const originalLanguage = root.lang
    root.style.setProperty('--primary', '#111111')
    root.style.setProperty('--accent', '#222222')
    const favicon = document.createElement('link')
    favicon.rel = 'icon'
    favicon.href = '/original.ico'
    document.head.append(favicon)
    mocks.site.mockResolvedValueOnce({
      appName: 'Configured Mail',
      logoDataUrl: 'data:image/png;base64,bG9nbw==',
      faviconDataUrl: 'data:image/png;base64,aWNvbg==',
      primaryColor: '#123456',
      accentColor: '#654321',
      language: 'de',
      cookieEnabled: true,
      cookieText: 'This site uses a necessary preference cookie.',
      fetchSeconds: 20,
      messageLimit: 100,
      headerHtml: '',
      footerHtml: '',
      contentCss: '',
      adSlots: {},
    })

    const wrapper = mount(App)
    await flushPromises()

    expect(wrapper.get('.brand img').attributes('src')).toBe('data:image/png;base64,bG9nbw==')
    expect(wrapper.get('.brand').attributes('aria-label')).toBe('Configured Mail home')
    expect(wrapper.get('[role="status"][aria-label="Cookie notice"]').text()).toContain('necessary preference cookie')
    expect(root.style.getPropertyValue('--primary')).toBe('#123456')
    expect(root.style.getPropertyValue('--accent')).toBe('#654321')
    expect(root.lang).toBe('de')
    expect(favicon.getAttribute('href')).toBe('data:image/png;base64,aWNvbg==')

    wrapper.unmount()
    expect(root.style.getPropertyValue('--primary')).toBe('#111111')
    expect(root.style.getPropertyValue('--accent')).toBe('#222222')
    expect(root.lang).toBe(originalLanguage)
    expect(favicon.getAttribute('href')).toBe('/original.ico')
    favicon.remove()
    root.style.removeProperty('--primary')
    root.style.removeProperty('--accent')
  })

  it('hands malformed address-shaped links to token validation for a clear error', async () => {
    history.replaceState({}, '', '/bad..local@example.com')
    mocks.token.mockRejectedValueOnce(new ApiError(422, 'Invalid address'))

    const wrapper = mount(App)
    await flushPromises()

    expect(mocks.token).toHaveBeenCalledWith('bad..local@example.com')
    expect(wrapper.text()).toContain('Invalid address')
  })

  it('opens a tokenized inbox when browser storage denies writes', async () => {
    history.replaceState({}, '', '/box@example.com')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage denied', 'SecurityError')
    })

    const wrapper = mount(App)
    await flushPromises()

    expect(mocks.token).toHaveBeenCalledWith('box@example.com')
    expect(wrapper.text()).toContain('Inbox ready')
    expect(wrapper.text()).toContain('box@example.com')
  })

  it('creates a custom address with an active domain', async () => {
    const wrapper = mount(AddressPanel)
    await flushPromises()
    await wrapper.get('#local-part').setValue('paper')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.token).toHaveBeenCalledWith('paper@example.com')
    expect(wrapper.emitted('open')?.[0]).toEqual([
      { address: 'paper@example.com', token: 'signed-token' },
    ])
  })

  it('resets copied state when the composed address changes', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const wrapper = mount(AddressPanel)
    await flushPromises()
    await wrapper.get('#local-part').setValue('paper')
    await wrapper.get('.address-preview button').trigger('click')
    await flushPromises()
    expect(wrapper.get('.address-preview button').text()).toBe('Copied')

    await wrapper.get('#local-part').setValue('changed')

    expect(wrapper.get('.address-preview button').text()).toBe('Copy')
  })

  it('shows a useful empty-domain state', async () => {
    mocks.domains.mockResolvedValue(domains([]))
    const wrapper = mount(AddressPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('No receiving domains are available')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('shows a Hydra domain-loading error separately from an empty list', async () => {
    mocks.domains.mockRejectedValue(new ApiError(502, 'Domain list unavailable'))
    const wrapper = mount(AddressPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('Domain list unavailable')
    expect(wrapper.text()).toContain('Retry')
  })

  it('keeps Back and Forward history aligned with the rendered inbox', async () => {
    const pushState = vi.spyOn(history, 'pushState')
    const travel = async (move: () => void) => {
      const moved = new Promise<void>((resolve) => {
        window.addEventListener('popstate', () => resolve(), { once: true })
      })
      move()
      await moved
      await flushPromises()
    }
    const wrapper = mount(App)
    await flushPromises()

    await wrapper.get('#local-part').setValue('alpha')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(location.pathname).toBe('/alpha%40example.com')

    await wrapper.get('.primary-button').trigger('click')
    await flushPromises()
    await wrapper.get('#local-part').setValue('beta')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(location.pathname).toBe('/beta%40example.com')

    await travel(() => history.back())
    expect(location.pathname).toBe('/')
    expect(wrapper.text()).toContain('Receive mail. Keep your address.')

    await travel(() => history.back())
    expect(location.pathname).toBe('/alpha%40example.com')
    expect(wrapper.text()).toContain('alpha@example.com')

    await travel(() => history.forward())
    expect(location.pathname).toBe('/')

    await travel(() => history.forward())
    expect(location.pathname).toBe('/beta%40example.com')
    expect(wrapper.text()).toContain('beta@example.com')
    expect(pushState).toHaveBeenCalledTimes(3)
  })

  it('removes its history listener when the app unmounts', async () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')
    const wrapper = mount(App)
    await flushPromises()
    const handler = add.mock.calls.find(([type]) => type === 'popstate')?.[1]

    expect(handler).toEqual(expect.any(Function))
    wrapper.unmount()
    expect(remove).toHaveBeenCalledWith('popstate', handler)
  })
})
