// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import App from '../App.vue'
import AddressPanel from '../components/AddressPanel.vue'

const mocks = vi.hoisted(() => ({
  domains: vi.fn(),
  token: vi.fn(),
}))

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, api: { ...actual.api, domains: mocks.domains, token: mocks.token } }
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
})
