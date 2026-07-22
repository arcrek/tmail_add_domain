export interface AddressSession {
  address: string
  token: string
}

export interface Resource {
  '@id': string
  '@type': string
  id: string
  createdAt: string
  updatedAt: string
}

export interface AccountResource extends Resource {
  '@context': string
  address: string
  quota: number
  used: number
  isDisabled: boolean
  isDeleted: boolean
}

export interface DomainResource extends Resource {
  '@context': string
  domain: string
  isActive: boolean
  isPrivate: boolean
}

export interface EmailAddress {
  name: string
  address: string
}

export interface AttachmentResource extends Resource {
  '@context': string
  filename: string
  contentType: string
  disposition: string
  transferEncoding: string
  related: boolean
  size: number
  downloadUrl: string
}

export interface MessageSummary extends Resource {
  '@context': string
  accountId: string
  msgid: string
  from: EmailAddress
  to: EmailAddress[]
  subject: string
  intro: string
  seen: boolean
  isDeleted: boolean
  hasAttachments: boolean
  size: number
  downloadUrl: string
}

export interface MessageResource extends MessageSummary {
  cc: EmailAddress[]
  bcc: EmailAddress[]
  flagged: boolean
  verifications: string[]
  retention: boolean
  retentionDate: string | null
  text: string
  html: string[]
  attachments: AttachmentResource[]
}

export interface HydraView {
  '@id': string
  '@type': string
  'hydra:first': string
  'hydra:last': string
  'hydra:previous'?: string
  'hydra:next'?: string
}

export interface HydraSearchMapping {
  '@type': string
  variable: string
  property: string
  required: boolean
}

export interface HydraSearch {
  '@type': string
  'hydra:template': string
  'hydra:variableRepresentation': string
  'hydra:mapping': HydraSearchMapping[]
}

export interface HydraCollection<T> {
  '@context': string
  '@id': string
  '@type': string
  'hydra:totalItems': number
  'hydra:member': T[]
  'hydra:view': HydraView
  'hydra:search': HydraSearch
}

export interface HydraError {
  '@context': string
  '@type': 'hydra:Error'
  'hydra:title': string
  'hydra:description': string
}

export interface TokenResponse {
  id: string
  token: string
}

export interface SiteResource {
  appName: string
  logoDataUrl: string
  faviconDataUrl: string
  primaryColor: string
  accentColor: string
  language: string
  cookieEnabled: boolean
  cookieText: string
  fetchSeconds: number
  messageLimit: number
  headerHtml: string
  footerHtml: string
  contentCss: string
  adSlots: Record<string, unknown>
}

export interface AdminSiteSettings extends SiteResource {
  autoSyncDomains: boolean
  localPartMin: number
  localPartMax: number
  forbiddenIds: string[]
  blockedSenderDomains: string[]
}

export interface MailServerSettings {
  jmapUrl: string
  jmapToken: string
  catchallAddress: string
  mailAccountId: string
  retentionDays: number
}

export interface SyncStatus {
  success?: boolean
  detail?: string
  created_at?: string
}

export interface SyncHistory {
  lastSync: SyncStatus
  lastSuccessfulSync: SyncStatus
  lastSyncError: SyncStatus
}

export interface AdminSettings extends SyncHistory {
  site: AdminSiteSettings
  mailServer: MailServerSettings
  domains: string[]
}

export interface AdminSettingsUpdate {
  site?: Partial<AdminSiteSettings>
  mailServer?: Partial<MailServerSettings>
}

export interface DashboardResource extends SyncHistory {
  messages: { stored: number; today: number; sevenDays: number }
  domains: {
    active: number
    domainsToday: number
    domainsSevenDays: number
    recentDomains: Array<{ domain: string; created_at: string }>
  }
  autoSyncDomains: boolean
}
