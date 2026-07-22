import { describe, expect, it } from 'vitest'
import { parseRoute } from '../route'

describe('parseRoute', () => {
  it('reserves admin and API documentation paths', () => {
    expect(parseRoute('/admin')).toEqual({ name: 'admin' })
    expect(parseRoute('/docs')).toEqual({ name: 'reserved' })
    expect(parseRoute('/openapi.json')).toEqual({ name: 'reserved' })
  })

  it('decodes a one-segment address once', () => {
    expect(parseRoute('/box%40example.com')).toEqual({ name: 'address', address: 'box@example.com' })
    expect(parseRoute('/box@example.com')).toEqual({ name: 'address', address: 'box@example.com' })
  })

  it('rejects malformed and nested paths', () => {
    expect(parseRoute('/not-an-address')).toEqual({ name: 'home' })
    expect(parseRoute('/a/b@example.com')).toEqual({ name: 'home' })
    expect(parseRoute('/a%2Fb@example.com')).toEqual({ name: 'home' })
    expect(parseRoute('/a%5Cb@example.com')).toEqual({ name: 'home' })
    expect(parseRoute('//box@example.com')).toEqual({ name: 'home' })
    expect(parseRoute('/box@example.com/')).toEqual({ name: 'home' })
    expect(parseRoute('/box%ZZ@example.com')).toEqual({ name: 'home' })
  })
})
