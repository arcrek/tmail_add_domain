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

describe('MessageReader', () => {
  beforeEach(() => {
    mocks.message.mockReset().mockResolvedValue(detail)
    mocks.setSeen.mockReset().mockResolvedValue({ seen: true })
    mocks.attachment.mockReset().mockResolvedValue(new Blob(['note']))
    mocks.source.mockReset().mockResolvedValue(new Blob(['source']))
    mocks.deleteMessage.mockReset().mockResolvedValue(undefined)
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:test'), revokeObjectURL: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
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
})
