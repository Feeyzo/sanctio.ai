/* Sanctio chat widget. Usage:
 *   <script src="https://YOUR-SANCTIO-HOST/widget.js"></script>
 *   <script>Sanctio.init({ sessionToken: '<token from POST /api/v1/sessions>', title: 'Support' })</script>
 * The session token is created by your backend, so no secret key is ever in the page. */
(function () {
  var script = document.currentScript
  var defaultBase = script ? new URL(script.src).origin : window.location.origin

  function el(tag, style, text) {
    var node = document.createElement(tag)
    if (style) node.style.cssText = style
    if (text) node.textContent = text
    return node
  }

  function init(options) {
    options = options || {}
    if (!options.sessionToken) throw new Error('Sanctio.init: sessionToken is required')
    var base = (options.apiBase || defaultBase).replace(/\/$/, '')
    var color = options.color || '#0a0a0a'
    var headers = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + options.sessionToken }
    var conversationId = null, shown = 0, busy = false, poll = null

    var root = el('div', 'position:fixed;right:20px;bottom:20px;z-index:2147483000;font:14px/1.45 system-ui,sans-serif')
    var panel = el('div', 'display:none;flex-direction:column;width:340px;max-width:calc(100vw - 40px);height:480px;' +
      'max-height:calc(100vh - 110px);margin-bottom:12px;background:#fff;color:#0a0a0a;border:1px solid #e6e6e6;' +
      'border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.18);overflow:hidden')
    var head = el('div', 'padding:12px 16px;font-weight:600;color:#fff;background:' + color, options.title || 'Support')
    var list = el('div', 'flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px')
    var form = el('form', 'display:flex;gap:8px;padding:10px;border-top:1px solid #e2e7ec')
    var input = el('input', 'flex:1;min-width:0;font:inherit;padding:9px 12px;border:1px solid #e2e7ec;border-radius:8px')
    input.placeholder = 'Type your message…'
    input.maxLength = 1000
    input.setAttribute('aria-label', 'Message')
    var send = el('button', 'font:inherit;font-weight:500;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;color:#fff;background:' + color, 'Send')
    var toggle = el('button', 'float:right;font:inherit;font-weight:600;border:0;border-radius:99px;padding:12px 18px;' +
      'cursor:pointer;color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.2);background:' + color, options.buttonText || 'Chat with us')
    toggle.type = 'button'
    form.append(input, send)
    panel.append(head, list, form)
    root.append(panel, toggle)
    document.body.appendChild(root)

    function add(sender, text) {
      var mine = sender === 'customer'
      var bubble = el('div', 'max-width:85%;padding:9px 12px;border-radius:12px;white-space:pre-wrap;word-break:break-word;' +
        (mine ? 'align-self:flex-end;color:#fff;background:' + color
          : 'align-self:flex-start;background:' + (sender === 'human' ? '#fff;border:1px solid #0a0a0a' : '#f3f3f3')))
      if (sender === 'human') bubble.appendChild(el('div', 'font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px', 'Support team'))
      bubble.appendChild(document.createTextNode(text))
      list.appendChild(bubble)
      list.scrollTop = list.scrollHeight
    }

    function request(path, body) {
      return fetch(base + path, { method: body ? 'POST' : 'GET', headers: headers, body: body ? JSON.stringify(body) : undefined })
        .then(function (res) {
          return res.json().catch(function () { return {} }).then(function (data) {
            if (!res.ok) throw new Error(res.status === 401 ? 'Your session has expired. Please reload the page.' : (data.detail || 'Something went wrong.'))
            return data
          })
        })
    }

    // once a human has taken over, their replies arrive by polling the conversation
    function watch() {
      if (poll) return
      poll = setInterval(function () {
        request('/api/v1/conversations/' + conversationId).then(function (c) {
          c.messages.slice(shown).forEach(function (m) { add(m.sender, m.content); shown++ })
        }).catch(function () {})
      }, 5000)
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault()
      var text = input.value.trim()
      if (!text || busy) return
      busy = true
      input.value = ''
      add('customer', text)
      request('/api/v1/chat', { message: text, conversation_id: conversationId }).then(function (d) {
        conversationId = d.conversation_id
        add('agent', d.reply)
        shown += 2 // the customer's message and this reply are now stored on the server
        if (d.status === 'handed_off') watch()
        if (options.onMessage) options.onMessage(d)
      }).catch(function (err) {
        add('agent', err.message)
      }).then(function () { busy = false })
    })

    toggle.addEventListener('click', function () {
      var open = panel.style.display === 'none'
      panel.style.display = open ? 'flex' : 'none'
      toggle.textContent = open ? 'Close' : (options.buttonText || 'Chat with us')
      if (open) input.focus()
    })

    // the greeting is local only; `shown` counts just the messages stored on the server
    add('agent', options.greeting || 'Hi! How can I help you today?')
  }

  window.Sanctio = { init: init }
})()
