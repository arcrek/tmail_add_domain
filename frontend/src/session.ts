import type { AddressSession } from './types'

const ADDRESSES_KEY = 'tmail.addresses'
const ACTIVE_KEY = 'tmail.activeAddress'

const normalize = (address: string) => address.trim().toLowerCase()

export function loadSessions(): AddressSession[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(ADDRESSES_KEY) ?? '[]')
    if (!Array.isArray(value)) return []
    return value.filter(
      (item): item is AddressSession =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as AddressSession).address === 'string' &&
        typeof (item as AddressSession).token === 'string',
    )
  } catch {
    return []
  }
}

export function saveSession(session: AddressSession): AddressSession[] {
  const normalized = { ...session, address: normalize(session.address) }
  const sessions = [
    normalized,
    ...loadSessions().filter((item) => normalize(item.address) !== normalized.address),
  ]
  localStorage.setItem(ADDRESSES_KEY, JSON.stringify(sessions))
  setActiveAddress(normalized.address)
  return sessions
}

export function removeSession(address: string): AddressSession[] {
  const normalized = normalize(address)
  const sessions = loadSessions().filter((item) => normalize(item.address) !== normalized)
  localStorage.setItem(ADDRESSES_KEY, JSON.stringify(sessions))
  if (activeAddress() === normalized) setActiveAddress(sessions[0]?.address ?? '')
  return sessions
}

export function activeAddress(): string {
  return localStorage.getItem(ACTIVE_KEY) ?? ''
}

export function setActiveAddress(address: string): void {
  const normalized = normalize(address)
  if (normalized) localStorage.setItem(ACTIVE_KEY, normalized)
  else localStorage.removeItem(ACTIVE_KEY)
}
