// @vitest-environment jsdom

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InboxView from '../components/InboxView.vue'

const mocks = vi.hoisted(() => ({
  messages: vi.fn(),
  message: vi.fn(),
  setSeen: vi.fn(),
}))

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, api: { ...actual.api, ...mocks } }
})

enableAutoUnmount(afterEach)

const summary = (id: string) => ({
  '@context': '/contexts/Message',
  '@id': `/messages/${id}`,
  '@type': 'Message',
  id,
  accountId: 'account',
  msgid: id,
  from: { name: 'Sender', address: 'sender@example.com' },
  to: [{ name: '', address: 'box@example.com' }],
  subject: `Message ${id}`,
  intro: 'Preview',
  seen: false,
  isDeleted: false,
  hasAttachments: false,
  size: 12,
  downloadUrl: `/sources/${id}`,
  createdAt: '2026-07-22T00:00:00Z',
  updatedAt: '2026-07-22T00:00:00Z',
})

const collection = (
  ids: string[],
  { page = 1, next = false, previous = false }: { page?: number; next?: boolean; previous?: boolean } = {},
) => ({
  '@context': '/contexts/Message',
  '@id': `/messages?page=${page}`,
  '@type': 'hydra:Collection',
  'hydra:totalItems': ids.length,
  'hydra:member': ids.map(summary),
  'hydra:view': {
    '@id': `/messages?page=${page}`,
    '@type': 'hydra:PartialCollectionView',
    'hydra:first': '/messages?page=1',
    'hydra:last': '/messages?page=1',
    ...(next ? { 'hydra:next': `/messages?page=${page + 1}` } : {}),
    ...(previous ? { 'hydra:previous': `/messages?page=${page - 1}` } : {}),
  },
})

describe('InboxView polling', () => {
  let hidden = false

  beforeEach(() => {
    vi.useFakeTimers()
    hidden = false
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
    mocks.messages.mockReset().mockResolvedValue(collection(['one']))
    mocks.message.mockReset().mockResolvedValue({ ...summary('one'), cc: [], bcc: [], flagged: false, verifications: [], retention: false, retentionDate: null, text: 'Body', html: [], attachments: [] })
    mocks.setSeen.mockReset().mockResolvedValue({ seen: true })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('pauses while hidden, refreshes on return, and cleans up', async () => {
    const remove = vi.spyOn(document, 'removeEventListener')
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 1 },
    })
    await flushPromises()
    expect(mocks.messages).toHaveBeenCalledTimes(1)

    hidden = true
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(1000)
    expect(mocks.messages).toHaveBeenCalledTimes(1)

    hidden = false
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(mocks.messages).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
    await vi.advanceTimersByTimeAsync(1000)
    expect(mocks.messages).toHaveBeenCalledTimes(2)
  })

  it('starts a fresh visibility refresh when an older request is pending', async () => {
    let finishPending: ((value: ReturnType<typeof collection>) => void) | undefined
    mocks.messages
      .mockResolvedValueOnce(collection(['one']))
      .mockImplementationOnce(() => new Promise((resolve) => { finishPending = resolve }))
      .mockResolvedValueOnce(collection(['fresh']))
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()

    await wrapper.get('[data-action="refresh"]').trigger('click')
    hidden = true
    document.dispatchEvent(new Event('visibilitychange'))
    hidden = false
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()

    expect(mocks.messages).toHaveBeenCalledTimes(3)
    finishPending?.(collection(['stale']))
    await flushPromises()
    expect(wrapper.text()).toContain('Message fresh')
    expect(wrapper.text()).not.toContain('Message stale')
  })

  it('keeps a selected message when an ordinary refresh moves it off the current page', async () => {
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()
    await wrapper.get('.message-row').trigger('click')
    await flushPromises()
    expect(wrapper.get('.message-row').attributes('aria-current')).toBe('true')

    mocks.messages.mockResolvedValueOnce(collection([]))
    await wrapper.get('[data-action="refresh"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.message-row').exists()).toBe(false)
    expect(wrapper.find('.message-reader').exists()).toBe(true)
  })

  it('returns from the reader to the selected inbox message list', async () => {
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()

    await wrapper.get('.message-row').trigger('click')
    await flushPromises()
    expect(wrapper.find('.message-reader').exists()).toBe(true)
    expect(wrapper.find('.reader-placeholder').exists()).toBe(false)

    await wrapper.get('[data-action="close"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.message-reader').exists()).toBe(false)
    expect(wrapper.find('.message-list').exists()).toBe(true)
    expect(wrapper.find('.reader-placeholder').exists()).toBe(true)
  })

  it('requests notification permission only from its explicit action', async () => {
    const requestPermission = vi.fn().mockResolvedValue('granted')
    vi.stubGlobal('Notification', class {
      static permission = 'default'
      static requestPermission = requestPermission
    })
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()
    expect(requestPermission).not.toHaveBeenCalled()

    await wrapper.get('[data-action="notifications"]').trigger('click')
    await flushPromises()
    expect(requestPermission).toHaveBeenCalledTimes(1)
  })

  it('loads a requested page even when the current refresh is still pending', async () => {
    let finishRefresh: ((value: ReturnType<typeof collection>) => void) | undefined
    mocks.messages
      .mockResolvedValueOnce(collection(['one'], { next: true }))
      .mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve }))
      .mockResolvedValueOnce(collection(['two'], { page: 2, previous: true }))
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()

    await wrapper.get('.message-row').trigger('click')
    await flushPromises()
    await wrapper.get('[data-action="refresh"]').trigger('click')
    await wrapper.get('.pagination button:last-child').trigger('click')
    await flushPromises()

    expect(mocks.messages).toHaveBeenLastCalledWith('signed', 2)
    expect(wrapper.find('.message-reader').exists()).toBe(false)
    expect(wrapper.find('.reader-placeholder').exists()).toBe(true)
    finishRefresh?.(collection(['one'], { next: true }))
  })

  it('resets state and ignores stale results when the address session changes', async () => {
    let finishOldRefresh: ((value: ReturnType<typeof collection>) => void) | undefined
    mocks.messages
      .mockResolvedValueOnce(collection(['old-one'], { next: true }))
      .mockResolvedValueOnce(collection(['old-two'], { page: 2, previous: true }))
      .mockImplementationOnce(() => new Promise((resolve) => { finishOldRefresh = resolve }))
      .mockResolvedValueOnce(collection(['new-one']))
    const wrapper = mount(InboxView, {
      props: { session: { address: 'old@example.com', token: 'old-token' }, fetchSeconds: 30 },
    })
    await flushPromises()
    await wrapper.get('.pagination button:last-child').trigger('click')
    await flushPromises()
    await wrapper.get('.message-row').trigger('click')
    await flushPromises()
    expect(wrapper.find('.message-reader').exists()).toBe(true)

    await wrapper.get('[data-action="refresh"]').trigger('click')
    await wrapper.setProps({ session: { address: 'new@example.com', token: 'new-token' } })
    await flushPromises()

    expect(mocks.messages).toHaveBeenLastCalledWith('new-token', 1)
    expect(wrapper.text()).toContain('new@example.com')
    expect(wrapper.text()).toContain('Message new-one')
    expect(wrapper.text()).not.toContain('Message old-two')
    expect(wrapper.find('.message-reader').exists()).toBe(false)

    finishOldRefresh?.(collection(['stale-old'], { page: 2, previous: true }))
    await flushPromises()
    expect(wrapper.text()).toContain('Message new-one')
    expect(wrapper.text()).not.toContain('Message stale-old')
  })

  it('notifies only for new page-one IDs without exposing message metadata', async () => {
    const notifications: Array<[string, NotificationOptions | undefined]> = []
    const requestPermission = vi.fn().mockResolvedValue('granted')
    vi.stubGlobal('Notification', class {
      static permission = 'default'
      static requestPermission = requestPermission
      constructor(title: string, options?: NotificationOptions) {
        notifications.push([title, options])
      }
    })
    mocks.messages
      .mockResolvedValueOnce(collection(['one'], { next: true }))
      .mockResolvedValueOnce(collection(['page-two'], { page: 2, previous: true }))
      .mockResolvedValueOnce(collection(['two', 'one'], { next: true }))
      .mockResolvedValueOnce(collection(['two'], { next: true }))
      .mockResolvedValueOnce(collection(['one'], { next: true }))
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()
    await wrapper.get('[data-action="notifications"]').trigger('click')
    await wrapper.get('.pagination button:last-child').trigger('click')
    await flushPromises()
    expect(notifications).toEqual([])

    await wrapper.get('.pagination button:first-child').trigger('click')
    await flushPromises()
    expect(notifications).toEqual([[
      'New message',
      { body: 'A new message arrived in your temporary inbox.' },
    ]])

    await wrapper.get('[data-action="refresh"]').trigger('click')
    await flushPromises()
    expect(notifications).toHaveLength(1)

    await wrapper.get('[data-action="refresh"]').trigger('click')
    await flushPromises()
    expect(notifications).toHaveLength(1)
    expect(JSON.stringify(notifications)).not.toContain('Message two')
    expect(JSON.stringify(notifications)).not.toContain('sender@example.com')
  })

  it('uses the approved account, message-list, and reader columns without fake navigation', async () => {
    const session = { address: 'box@example.com', token: 'signed' }
    const wrapper = mount(InboxView, {
      props: { session, fetchSeconds: 20, appName: 'Temporary Inbox', logoDataUrl: '' },
    })
    await flushPromises()

    expect(wrapper.classes()).toContain('three-pane')
    expect(wrapper.get('.account-rail').text()).toContain(session.address)
    expect(wrapper.get('.message-list').exists()).toBe(true)
    expect(wrapper.get('.mail-detail').exists()).toBe(true)
    expect(wrapper.text()).not.toMatch(/Sent|Contacts|Addresses/)
  })
})
