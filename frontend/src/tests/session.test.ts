// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest'
import {
  activeAddress,
  loadSessions,
  removeSession,
  saveSession,
  setActiveAddress,
} from '../session'

describe('address sessions', () => {
  beforeEach(() => localStorage.clear())

  it('returns no sessions for invalid stored JSON', () => {
    localStorage.setItem('tmail.addresses', '{invalid')
    expect(loadSessions()).toEqual([])
  })

  it('normalizes and deduplicates addresses while updating the token', () => {
    saveSession({ address: ' Box@Example.COM ', token: 'old' })
    expect(saveSession({ address: 'box@example.com', token: 'new' })).toEqual([
      { address: 'box@example.com', token: 'new' },
    ])
    expect(activeAddress()).toBe('box@example.com')
  })

  it('remembers and clears the active address with a removed session', () => {
    saveSession({ address: 'one@example.com', token: 'one' })
    saveSession({ address: 'two@example.com', token: 'two' })
    setActiveAddress('one@example.com')
    expect(removeSession('one@example.com')).toEqual([
      { address: 'two@example.com', token: 'two' },
    ])
    expect(activeAddress()).toBe('two@example.com')
  })
})
