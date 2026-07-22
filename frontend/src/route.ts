export type AppRoute =
  | { name: 'home' }
  | { name: 'address'; address: string }
  | { name: 'admin' }
  | { name: 'reserved' }

const RESERVED = new Set([
  'api',
  'docs',
  'redoc',
  'openapi.json',
  'settings',
  'assets',
  'favicon.ico',
])

export function parseRoute(pathname: string): AppRoute {
  const segments = pathname.split('/').filter(Boolean)
  if (segments[0] === 'admin') return { name: 'admin' }
  if (segments[0] && RESERVED.has(segments[0])) return { name: 'reserved' }
  if (segments.length !== 1) return { name: 'home' }

  try {
    const address = decodeURIComponent(segments[0]!).toLowerCase()
    const [local, domain, extra] = address.split('@')
    return local && domain && extra === undefined ? { name: 'address', address } : { name: 'home' }
  } catch {
    return { name: 'home' }
  }
}
