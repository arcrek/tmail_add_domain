// @vitest-environment jsdom

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MessageReader from '../components/MessageReader.vue'

const mocks = vi.hoisted(() => ({
  message: vi.fn(),
  setSeen: vi.fn(),
  attachment: vi.fn(),
  source: vi.fn(),
  deleteMessage: vi.fn(),
}))

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return { ...actual, api: { ...actual.api, ...mocks } }
})

enableAutoUnmount(afterEach)

const detail = {
  '@context': '/contexts/Message',
  '@id': '/messages/one',
  '@type': 'Message',
  id: 'one',
  accountId: 'account',
  msgid: 'one',
  from: { name: 'Sender', address: 'sender@example.com' },
  to: [{ name: '', address: 'box@example.com' }],
  cc: [],
  bcc: [],
  subject: 'A useful subject',
  intro: 'Preview',
  seen: false,
  isDeleted: false,
  hasAttachments: true,
  flagged: false,
  verifications: [],
  retention: false,
  retentionDate: null,
  size: 12,
  downloadUrl: '/sources/one',
  createdAt: '2026-07-22T00:00:00Z',
  updatedAt: '2026-07-22T00:00:00Z',
  text: 'Plain body',
  html: ['<p>HTML body</p>'],
  attachments: [{
    '@context': '/contexts/Attachment',
    '@id': '/messages/one/attachments/blob-one',
    '@type': 'Attachment',
    id: 'blob-one',
    filename: 'notes.txt',
    contentType: 'text/plain',
    disposition: 'attachment',
    transferEncoding: 'base64',
    related: false,
    size: 4,
    downloadUrl: '/messages/one/attachments/blob-one',
    createdAt: '2026-07-22T00:00:00Z',
    updatedAt: '2026-07-22T00:00:00Z',
  }],
}

const message = (id: string, filename = 'notes.txt') => ({
  ...detail,
  '@id': `/messages/${id}`,
  id,
  msgid: id,
  subject: `Message ${id}`,
  attachments: detail.attachments.map((attachment) => ({ ...attachment, filename })),
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => {
    resolve = yes
  })
  return { promise, resolve }
}

describe('MessageReader', () => {
  let downloadNames: string[]

  beforeEach(() => {
    downloadNames = []
    mocks.message.mockReset().mockResolvedValue(message('one'))
    mocks.setSeen.mockReset().mockResolvedValue({ seen: true })
    mocks.attachment.mockReset().mockResolvedValue(new Blob(['note']))
    mocks.source.mockReset().mockResolvedValue(new Blob(['source']))
    mocks.deleteMessage.mockReset().mockResolvedValue(undefined)
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:test'), revokeObjectURL: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      downloadNames.push(this.download)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('loads on selection, marks unread mail seen, and isolates HTML', async () => {
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: 'one' } })
    await flushPromises()

    expect(mocks.message).toHaveBeenCalledWith('signed', 'one')
    expect(mocks.setSeen).toHaveBeenCalledWith('signed', 'one', true)
    expect(wrapper.get('iframe').attributes('sandbox')).not.toContain('allow-scripts')
    expect(wrapper.get('iframe').attributes('src')).toBeUndefined()
    expect(wrapper.get('iframe').attributes('srcdoc')).toContain('<p>HTML body</p>')
  })

  it('downloads attachments and source through the authenticated API', async () => {
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: 'one' } })
    await flushPromises()

    await wrapper.get('[data-download-attachment]').trigger('click')
    await wrapper.get('[data-download-source]').trigger('click')
    await flushPromises()

    expect(mocks.attachment).toHaveBeenCalledWith('signed', 'one', 'blob-one')
    expect(mocks.source).toHaveBeenCalledWith('signed', 'one')
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(2)
    expect(downloadNames).toEqual(['notes.txt', 'one.eml'])
  })

  it('deletes only after confirmation and clears the parent selection', async () => {
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: 'one' } })
    await flushPromises()
    await wrapper.get('[data-action="delete"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith('Delete this message permanently?')
    expect(mocks.deleteMessage).toHaveBeenCalledWith('signed', 'one')
    expect(wrapper.emitted('deleted')?.[0]).toEqual(['one'])
  })

  it('does not let a completed delete for A clear selected message B', async () => {
    const pending = deferred<void>()
    mocks.deleteMessage.mockReturnValueOnce(pending.promise)
    const wrapper = mount(MessageReader, { props: { token: 'signed-a', id: 'one' } })
    await flushPromises()
    await wrapper.get('[data-action="delete"]').trigger('click')

    mocks.message.mockResolvedValueOnce(message('two'))
    await wrapper.setProps({ token: 'signed-b', id: 'two' })
    await flushPromises()
    pending.resolve()
    await flushPromises()

    expect(mocks.deleteMessage).toHaveBeenCalledWith('signed-a', 'one')
    expect(wrapper.emitted('deleted')).toBeUndefined()
    expect(wrapper.text()).toContain('Message two')
  })

  it('does not save source A with message B state after selection changes', async () => {
    const pending = deferred<Blob>()
    mocks.source.mockReturnValueOnce(pending.promise)
    const wrapper = mount(MessageReader, { props: { token: 'signed-a', id: 'one' } })
    await flushPromises()
    await wrapper.get('[data-download-source]').trigger('click')

    mocks.message.mockResolvedValueOnce(message('two'))
    await wrapper.setProps({ token: 'signed-b', id: 'two' })
    await flushPromises()
    pending.resolve(new Blob(['source-a']))
    await flushPromises()

    expect(mocks.source).toHaveBeenCalledWith('signed-a', 'one')
    expect(downloadNames).toEqual([])
  })

  it('ignores an action completion after unmount', async () => {
    const pending = deferred<Blob>()
    mocks.source.mockReturnValueOnce(pending.promise)
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: 'one' } })
    await flushPromises()
    await wrapper.get('[data-download-source]').trigger('click')
    wrapper.unmount()

    pending.resolve(new Blob(['source']))
    await flushPromises()
    expect(downloadNames).toEqual([])
  })

  it('normalizes a bounded safe attachment basename and preserves its extension', async () => {
    const unsafe = `../folder\\\u202ereport\u0000${'a'.repeat(140)}.txt`
    mocks.message.mockResolvedValueOnce(message('one', unsafe))
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: 'one' } })
    await flushPromises()
    await wrapper.get('[data-download-attachment]').trigger('click')
    await flushPromises()

    expect(downloadNames[0]).toHaveLength(120)
    expect(downloadNames[0]).toMatch(/\.txt$/)
    expect(downloadNames[0]).not.toMatch(/[\\/\u0000-\u001f\u007f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/)
    expect(wrapper.get('.attachments strong').text()).toBe(downloadNames[0])
    expect(wrapper.get('[data-download-attachment]').attributes('aria-label')).toBe(`Download ${downloadNames[0]}`)
    expect(wrapper.get('.attachments').text()).not.toMatch(/[\u0000-\u001f\u007f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/)
  })

  it('uses a safe fallback for an empty attachment basename', async () => {
    mocks.message.mockResolvedValueOnce(message('one', '../\u202e\u0000'))
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: 'one' } })
    await flushPromises()
    await wrapper.get('[data-download-attachment]').trigger('click')
    await flushPromises()

    expect(downloadNames).toEqual(['attachment'])
  })

  it('normalizes the source download basename from an untrusted message ID', async () => {
    mocks.message.mockResolvedValueOnce(message('../\u202ereport'))
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: '../\u202ereport' } })
    await flushPromises()
    await wrapper.get('[data-download-source]').trigger('click')
    await flushPromises()

    expect(downloadNames).toEqual(['report.eml'])
  })

  it('uses a message fallback before appending the source extension', async () => {
    mocks.message.mockResolvedValueOnce(message('../\\\u202e\u0000'))
    const wrapper = mount(MessageReader, { props: { token: 'signed', id: '../\\\u202e\u0000' } })
    await flushPromises()
    await wrapper.get('[data-download-source]').trigger('click')
    await flushPromises()

    expect(downloadNames).toEqual(['message.eml'])
  })
})
