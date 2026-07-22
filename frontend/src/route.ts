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
  const nextSlash = pathname.indexOf('/', 1)
  const firstSegment = pathname.slice(1, nextSlash === -1 ? undefined : nextSlash)
  if (firstSegment === 'admin') return { name: 'admin' }
  if (RESERVED.has(firstSegment)) return { name: 'reserved' }
  if (!pathname.startsWith('/') || pathname.length === 1 || nextSlash !== -1) return { name: 'home' }

  try {
    const address = decodeURIComponent(firstSegment).toLowerCase()
    if (/[\\/]/.test(address)) return { name: 'home' }
    const [local, domain, extra] = address.split('@')
    return local && domain && extra === undefined ? { name: 'address', address } : { name: 'home' }
  } catch {
    return { name: 'home' }
  }
}
