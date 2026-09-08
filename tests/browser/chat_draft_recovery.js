// Run on a local Chat page: agent-browser eval --stdin < tests/browser/chat_draft_recovery.js
// Isolated DOM and fake transport exercise the shipped client without server mutations.
(async () => {
  const source = await (await fetch('/static/chat.js')).text();
  const html = await (await fetch('/chat')).text();
  const markup = new DOMParser().parseFromString(html, 'text/html').getElementById('shopping-chat').outerHTML;
  const results = [];
  for (const loseAck of [false, true]) {
    const storage = new Map();
    async function page() {
      const frame = document.createElement('iframe'); document.body.append(frame);
      const w = frame.contentWindow;
      w.document.body.innerHTML = markup;
      Object.defineProperty(w, 'sessionStorage', {value: {getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v)}});
      w.fetch = async () => ({ok: true, json: async () => ({token: 'synthetic'})});
      let ws;
      w.WebSocket = class {
        static OPEN = 1;
        readyState = 1;
        sent = [];
        constructor() { ws = this; setTimeout(() => this.onopen(), 0); }
        send(text) { this.sent.push(JSON.parse(text)); }
        close() {}
      };
      w.eval(source);
      await new Promise(r => setTimeout(r, 30));
      const emit = value => ws.onmessage({data: JSON.stringify({v: 1, ...value})});
      emit({type: 'ready', availability: 'available'});
      return {w, ws, emit, close() {w.dispatchEvent(new w.Event('pagehide')); frame.remove();}};
    }
    let p = await page();
    p.emit({type: 'draft', id: p.ws.sent.at(-1).id, conversation_id: 'draft-one'});
    function type(p, text) { const input = p.w.document.getElementById('chat-message'); input.value = text; input.dispatchEvent(new p.w.Event('input')); }
    type(p, 'First question');
    p.w.document.getElementById('chat-composer').dispatchEvent(new p.w.Event('submit', {cancelable: true}));
    const command = p.ws.sent.at(-1);
    const outcome = {status: 'accepted', conversation_id: 'draft-one'};
    if (!loseAck) p.emit({type: 'ack', id: command.id, outcome});
    type(p, 'Next draft before first update');
    p.close();
    p = await page();
    if (loseAck) p.emit({type: 'command_status', command_id: command.id, outcome});
    p.emit({type: 'snapshot', id: p.ws.sent.at(-1).id, conversation: {id: 'draft-one', title: 'First question', model: 'synthetic', version: 1}, items: [], next_cursor: null});
    const draft = p.w.document.getElementById('chat-message').value;
    const replayed = p.ws.sent.some(c => ['submit', 'retry'].includes(c.type));
    p.close();
    if (draft !== 'Next draft before first update' || replayed) throw new Error('Draft recovery failed: ' + loseAck);
    results.push({lostAcknowledgement: loseAck, draftPreserved: true, mutationReplayed: false});
  }
  return results;
})()
