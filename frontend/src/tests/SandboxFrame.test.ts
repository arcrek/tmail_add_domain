// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SandboxFrame from '../components/SandboxFrame.vue'

describe('SandboxFrame', () => {
  it('posts message HTML once to the nonce-protected opaque renderer', async () => {
    const postMessage = vi.fn()
    const contentWindow = vi.spyOn(HTMLIFrameElement.prototype, 'contentWindow', 'get')
      .mockReturnValue({ postMessage } as unknown as Window)
    const wrapper = mount(SandboxFrame, {
      props: { html: '<p style="color:red">Hello</p>', mode: 'message' },
    })
    const frame = wrapper.get('iframe')
    await frame.trigger('load')

    expect(frame.attributes('sandbox')).toBe(
      'allow-scripts allow-popups allow-popups-to-escape-sandbox',
    )
    expect(frame.attributes('sandbox')).not.toContain('allow-same-origin')
    expect(frame.attributes('src')).toBe('/message-sandbox?revision=0')
    expect(frame.attributes('srcdoc')).toBeUndefined()
    expect(postMessage).toHaveBeenCalledWith({
      type: 'tmail:sandbox-content',
      html: '<p style="color:red">Hello</p>',
      css: '',
      mode: 'message',
    }, '*')
    await frame.trigger('load')
    expect(postMessage).toHaveBeenCalledTimes(1)
    contentWindow.mockRestore()
  })

  it('posts script and CSS content to the dedicated opaque sandbox document', async () => {
    const postMessage = vi.fn()
    const contentWindow = vi.spyOn(HTMLIFrameElement.prototype, 'contentWindow', 'get')
      .mockReturnValue({ postMessage } as unknown as Window)
    const wrapper = mount(SandboxFrame, {
      props: { html: '<script>void 0</script>', css: 'body { color: red }', mode: 'content' },
    })
    const frame = wrapper.get('iframe')
    await frame.trigger('load')

    expect(frame.attributes('sandbox')).toContain('allow-scripts')
    expect(frame.attributes('sandbox')).not.toContain('allow-same-origin')
    expect(frame.attributes('src')).toBe('/sandbox?revision=0')
    expect(frame.attributes('srcdoc')).toBeUndefined()
    expect(postMessage).toHaveBeenCalledWith({
      type: 'tmail:sandbox-content',
      html: '<script>void 0</script>',
      css: 'body { color: red }',
      mode: 'content',
    }, '*')
    contentWindow.mockRestore()
  })

  it('replaces the iframe document when content changes and unmounts cleanly', async () => {
    const wrapper = mount(SandboxFrame, { props: { html: '<p>First</p>', mode: 'content' } })
    const first = wrapper.get('iframe').element
    await wrapper.setProps({ html: '<p>Second</p>' })
    expect(wrapper.get('iframe').attributes('src')).toBe('/sandbox?revision=1')
    expect(wrapper.get('iframe').element).not.toBe(first)

    expect(() => wrapper.unmount()).not.toThrow()
  })
})
