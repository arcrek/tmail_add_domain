// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SandboxFrame from '../components/SandboxFrame.vue'

describe('SandboxFrame', () => {
  it('isolates message HTML without scripts or same-origin access', () => {
    const wrapper = mount(SandboxFrame, { props: { html: '<p>Hello</p>', mode: 'message' } })
    const frame = wrapper.get('iframe')
    expect(frame.attributes('sandbox')).toBe('allow-popups allow-popups-to-escape-sandbox')
    expect(frame.attributes('srcdoc')).toContain('<p>Hello</p>')
  })

  it('allows scripts for ad content without same-origin access', () => {
    const wrapper = mount(SandboxFrame, { props: { html: '<script>void 0</script>', mode: 'content' } })
    expect(wrapper.get('iframe').attributes('sandbox')).toContain('allow-scripts')
    expect(wrapper.get('iframe').attributes('sandbox')).not.toContain('allow-same-origin')
  })
})
