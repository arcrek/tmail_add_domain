import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../api'

describe('api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts an address for a passwordless token', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'account-id', token: 'signed' }), {
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetch)

    await expect(api.token('box@example.com')).resolves.toEqual({ id: 'account-id', token: 'signed' })
    expect(fetch).toHaveBeenCalledWith('/token', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ address: 'box@example.com' }),
    }))
  })

  it('sends mailbox and admin security headers', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({}), { headers: { 'Content-Type': 'application/json' } }),
    ))
    vi.stubGlobal('fetch', fetch)

    await api.messages('mail-token')
    await api.admin.syncDomains('csrf-token')
    expect(fetch.mock.calls[0]?.[1]?.headers).toMatchObject({ Authorization: 'Bearer mail-token' })
    expect(fetch.mock.calls[1]?.[1]?.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-token' })
  })

  it('turns Hydra responses into useful errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        '@context': '/contexts/Error',
        '@type': 'hydra:Error',
        'hydra:title': 'Validation error',
        'hydra:description': 'Domain is not active',
      }), { status: 422, headers: { 'Content-Type': 'application/json' } }),
    ))

    await expect(api.token('box@example.com')).rejects.toEqual(
      expect.objectContaining<ApiError>({ status: 422, message: 'Domain is not active' }),
    )
  })
})
