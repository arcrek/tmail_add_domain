import type {
  AccountResource,
  AdminSettings,
  AdminSettingsUpdate,
  DashboardResource,
  DomainResource,
  HydraCollection,
  HydraError,
  MessageResource,
  MessageSummary,
  SiteResource,
  SyncStatus,
  TokenResponse,
} from './types'

interface RequestOptions extends RequestInit {
  token?: string
  csrf?: string
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: HydraError,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { token, csrf, ...init } = options
  const headers: Record<string, string> = Object.fromEntries(new Headers(init.headers).entries())
  if (token) headers.Authorization = `Bearer ${token}`
  if (csrf) headers['X-CSRF-Token'] = csrf
  if (init.body && !(init.body instanceof FormData)) headers['Content-Type'] = 'application/json'

  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  if (response.status === 204) return undefined as T

  const isJson = response.headers.get('content-type')?.includes('json')
  const body: unknown = isJson ? await response.json() : await response.blob()
  if (!response.ok) {
    const error = body as Partial<HydraError> & { detail?: string }
    throw new ApiError(
      response.status,
      error['hydra:description'] ?? error.detail ?? response.statusText ?? 'Request failed',
      error['@type'] === 'hydra:Error' ? error as HydraError : undefined,
    )
  }
  return body as T
}

const json = (body: unknown): Pick<RequestInit, 'body'> => ({ body: JSON.stringify(body) })

export const api = {
  site: () => request<SiteResource>('/site'),
  domains: (page = 1) => request<HydraCollection<DomainResource>>(`/domains?page=${page}`),
  domain: (id: string) => request<DomainResource>(`/domains/${encodeURIComponent(id)}`),
  account: (address: string) =>
    request<AccountResource>('/accounts', { method: 'POST', ...json({ address }) }),
  token: (address: string) =>
    request<TokenResponse>('/token', { method: 'POST', ...json({ address }) }),
  me: (token: string) => request<AccountResource>('/me', { token }),
  messages: (token: string, page = 1) =>
    request<HydraCollection<MessageSummary>>(`/messages?page=${page}`, { token }),
  message: (token: string, id: string) =>
    request<MessageResource>(`/messages/${encodeURIComponent(id)}`, { token }),
  setSeen: (token: string, id: string, seen: boolean) =>
    request<{ seen: boolean }>(`/messages/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      token,
      ...json({ seen }),
    }),
  deleteMessage: (token: string, id: string) =>
    request<void>(`/messages/${encodeURIComponent(id)}`, { method: 'DELETE', token }),
  attachment: (token: string, messageId: string, blobId: string) =>
    request<Blob>(
      `/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(blobId)}`,
      { token },
    ),
  source: (token: string, messageId: string) =>
    request<Blob>(`/sources/${encodeURIComponent(messageId)}`, { token }),
  admin: {
    login: (password: string) =>
      request<{ csrfToken: string }>('/admin/api/login', { method: 'POST', ...json({ password }) }),
    session: () => request<{ csrfToken: string }>('/admin/api/session'),
    logout: (csrf: string) =>
      request<void>('/admin/api/logout', { method: 'POST', csrf }),
    settings: () => request<AdminSettings>('/admin/api/settings'),
    updateSettings: (values: AdminSettingsUpdate, csrf: string) =>
      request<AdminSettings>('/admin/api/settings', { method: 'PUT', csrf, ...json(values) }),
    syncDomains: (csrf: string) =>
      request<{ domains: string[]; lastSync: SyncStatus }>('/admin/api/sync-domains', {
        method: 'POST',
        csrf,
      }),
    testMail: (csrf: string) =>
      request<{ ok: boolean; domainCount: number; messages: DashboardResource['messages'] }>(
        '/admin/api/test-mail',
        { method: 'POST', csrf },
      ),
    dashboard: () => request<DashboardResource>('/admin/api/dashboard'),
  },
}
