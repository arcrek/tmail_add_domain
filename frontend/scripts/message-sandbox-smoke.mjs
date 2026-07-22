const cdpEndpoint = process.env.CDP_ENDPOINT || process.argv[2]
const baseUrl = new URL(process.env.BASE_URL || process.argv[3] || 'http://127.0.0.1:5173')

if (!cdpEndpoint) {
  console.error('Usage: npm run test:sandbox-browser -- <CDP endpoint> [base URL]')
  process.exit(2)
}
if (!globalThis.WebSocket) {
  console.error('This smoke check requires a Node version with the built-in WebSocket API.')
  process.exit(2)
}

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))
const endpoint = cdpEndpoint.replace(/\/$/, '')
let target

if (/^wss?:/.test(endpoint)) {
  target = { webSocketDebuggerUrl: endpoint }
} else {
  const created = await fetch(`${endpoint}/json/new?about%3Ablank`, { method: 'PUT' })
  if (!created.ok) throw new Error(`Could not create a CDP target (${created.status})`)
  target = await created.json()
}

const socket = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true })
  socket.addEventListener('error', reject, { once: true })
})

let sequence = 0
const pending = new Map()
socket.addEventListener('message', ({ data }) => {
  const message = JSON.parse(data)
  const request = pending.get(message.id)
  if (!request) return
  pending.delete(message.id)
  if (message.error) request.reject(new Error(message.error.message))
  else request.resolve(message.result)
})

function call(method, params = {}) {
  const id = ++sequence
  socket.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}

async function evaluate(expression, contextId) {
  const response = await call('Runtime.evaluate', {
    expression,
    contextId,
    awaitPromise: true,
    returnByValue: true,
  })
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text)
  return response.result.value
}

async function waitFor(check, message) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (await check()) return
    await delay(100)
  }
  throw new Error(typeof message === 'function' ? message() : message)
}

try {
  await call('Page.enable')
  await call('Runtime.enable')
  const sandboxUrl = new URL('/message-sandbox', baseUrl).href
  await call('Page.navigate', { url: sandboxUrl })
  await waitFor(() => evaluate("document.readyState === 'complete'"), 'Message sandbox did not load')

  const escapeUrl = new URL('/__message_sandbox_escape__', baseUrl).href
  const hostileHtml = `
    <meta http-equiv="refresh" content="0;url=${escapeUrl}">
    <div id="probe" style="background-color: rgb(219, 234, 254)">Styled content</div>
    <script>globalThis.__tmailScriptRan = true<\/script>
    <img id="attack-image" src="data:image/png;base64,broken" onerror="globalThis.__tmailEventRan = true">
    <form id="attack-form" action="${escapeUrl}" target="_top"><button>Submit</button></form>
  `
  await evaluate(`window.postMessage({
    type: 'tmail:sandbox-content', mode: 'message', html: ${JSON.stringify(hostileHtml)}, css: ''
  }, '*')`)

  await waitFor(() => evaluate("Boolean(document.getElementById('probe'))"), 'Hostile HTML was not rendered')
  await delay(250)

  const checks = {
    inlineStyle: await evaluate("getComputedStyle(document.getElementById('probe')).backgroundColor === 'rgb(219, 234, 254)'"),
    scriptBlocked: await evaluate("typeof globalThis.__tmailScriptRan === 'undefined'"),
    eventHandlerBlocked: await evaluate("document.getElementById('attack-image').complete && typeof globalThis.__tmailEventRan === 'undefined'"),
    refreshNavigationBlocked: (await evaluate('location.href')).startsWith(sandboxUrl),
  }

  await evaluate("document.getElementById('attack-form').requestSubmit()")
  await delay(250)
  checks.formNavigationBlocked = (await evaluate('location.href')).startsWith(sandboxUrl)

  const failed = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name)
  if (failed.length) throw new Error(`Failed checks: ${failed.join(', ')}`)
  console.log('PASS message-sandbox browser smoke')
} catch (cause) {
  console.error(`FAIL message-sandbox browser smoke: ${cause instanceof Error ? cause.message : cause}`)
  process.exitCode = 1
} finally {
  socket.close()
  if (target.id && !/^wss?:/.test(endpoint)) await fetch(`${endpoint}/json/close/${target.id}`).catch(() => {})
}
