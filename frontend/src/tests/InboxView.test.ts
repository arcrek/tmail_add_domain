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

const collection = (ids: string[], hasNext = false) => ({
  '@context': '/contexts/Message',
  '@id': '/messages?page=1',
  '@type': 'hydra:Collection',
  'hydra:totalItems': ids.length,
  'hydra:member': ids.map(summary),
  'hydra:view': {
    '@id': '/messages?page=1',
    '@type': 'hydra:PartialCollectionView',
    'hydra:first': '/messages?page=1',
    'hydra:last': '/messages?page=1',
    ...(hasNext ? { 'hydra:next': '/messages?page=2' } : {}),
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

  it('keeps a selected message selected when it survives a refresh', async () => {
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()
    await wrapper.get('.message-row').trigger('click')
    await flushPromises()
    expect(wrapper.get('.message-row').attributes('aria-current')).toBe('true')

    await wrapper.get('[data-action="refresh"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.message-row').attributes('aria-current')).toBe('true')
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
      .mockResolvedValueOnce(collection(['one'], true))
      .mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve }))
      .mockResolvedValueOnce(collection(['two']))
    const wrapper = mount(InboxView, {
      props: { session: { address: 'box@example.com', token: 'signed' }, fetchSeconds: 30 },
    })
    await flushPromises()

    await wrapper.get('[data-action="refresh"]').trigger('click')
    await wrapper.get('.pagination button:last-child').trigger('click')
    await flushPromises()

    expect(mocks.messages).toHaveBeenLastCalledWith('signed', 2)
    finishRefresh?.(collection(['one'], true))
  })
})
