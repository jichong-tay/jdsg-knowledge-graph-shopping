/* Saved snapshots are authoritative. Reconnect never replays a mutation. */
(function () {
  "use strict";
  const root = document.getElementById("shopping-chat");
  if (!root) return;
  const byId = id => document.getElementById(id);
  const input = byId("chat-message"), transcript = byId("chat-transcript");
  const dialog = byId("chat-dialog"), rail = byId("chat-rail");
  const encoder = new TextEncoder(), decoder = new TextDecoder();
  let epoch = 0;
  let socket, ready = false, selected = null, conversation = null, draftLoaded = false;
  let availability = "available", attempts = new Map(), older = null, libraryCursor = null;
  let reconnectTimer, heartbeat, lastSeen = 0, started = 0, retryNumber = 0, disposed = false;
  let partial = null, refreshPending = false, selecting = null, library = new Map();
  let pending = read("chat-pending", null), restored = read("chat-selected", null);
  const toolNames = {get_order: "Read order", search_products: "Find products",
    get_product_history: "Read product history", list_recent_orders: "Read recent orders"};

  function read(key, fallback) {
    try { return JSON.parse(sessionStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; }
  }
  function store(key, value) {
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
  }
  function draftKey() { return "chat-draft:" + (selected || "new"); }
  function saveDraft() {
    if (!draftLoaded) return;
    store(draftKey(), input.value);
    if (!conversation) store("chat-draft:new", input.value);
  }
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(text, action, className = "chat-btn") {
    const node = element("button", text, className);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }
  function latest() {
    return Array.from(attempts.values()).sort((a, b) => b.id - a.id)[0];
  }
  function controls() {
    const current = latest(), active = current && ["running", "stopping"].includes(current.status);
    byId("chat-send").disabled = !ready || !selected || Boolean(pending) || availability !== "available" || active;
    byId("chat-stop").hidden = !active;
    byId("chat-stop").disabled = !ready || Boolean(pending) || current?.status === "stopping";
    byId("chat-stop").textContent = current?.status === "stopping" ? "Stopping…" : "Stop";
    byId("chat-retry").hidden = !current || !["failed", "stopped", "interrupted"].includes(current.status);
    byId("chat-retry").disabled = !ready || Boolean(pending) || availability !== "available";
    for (const id of ["chat-rename", "chat-delete"]) byId(id).disabled = !ready || !conversation || Boolean(pending);
    if (conversation?.deleting) {
      byId("chat-send").disabled = true;
      byId("chat-retry").disabled = true;
      byId("chat-rename").disabled = true;
    }
  }
  function notice(text) { byId("chat-connection").textContent = text; controls(); }
  function connectedNotice() {
    if (conversation?.deleting) notice("Deleting… Messages remain saved until cleanup succeeds.");
    else if (availability === "faulted") notice("Responses are unavailable until the service restarts. Saved history is still readable.");
    else if (availability === "busy") notice("A response is running. You can keep writing a draft.");
    else notice("Connected · saved on this machine");
  }
  function send(type, fields = {}, id = crypto.randomUUID()) {
    if (!ready || socket?.readyState !== WebSocket.OPEN) return null;
    const command = {v: 1, type, id, ...fields};
    if (encoder.encode(JSON.stringify(command)).length > 65536) return null;
    socket.send(JSON.stringify(command));
    return id;
  }
  function mutate(type, fields) {
    if (!ready || pending) return;
    const id = crypto.randomUUID();
    pending = {id, type, ...fields};
    store("chat-pending", pending);
    if (!send(type, fields, id)) {
      pending = null; store("chat-pending", null);
      notice("Not sent. Your draft is preserved.");
    } else { notice("Saving…"); controls(); }
  }
  function select(cid) {
    saveDraft();
    selecting = send("subscribe", {conversation_id: cid});
    if (!selecting) notice("Reconnect to open another conversation. Your draft is preserved.");
  }
  function snapshot() {
    if (refreshPending || !conversation) return;
    refreshPending = Boolean(send("snapshot", {conversation_id: selected, before: null}));
  }
  function rememberAttempt(attempt) {
    if (!attempt) return;
    const existing = attempts.get(attempt.id);
    if (!existing || attempt.version > existing.version) attempts.set(attempt.id, attempt);
  }
  function render() {
    byId("chat-title").textContent = conversation?.title || "New conversation";
    if (conversation) byId("chat-model").textContent = "Ollama · " + conversation.model;
    const scroll = byId("chat-messages"), atBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;
    const nodes = [], messages = new Set();
    for (const attempt of Array.from(attempts.values()).sort((a, b) => a.id - b.id)) {
      if (!messages.has(attempt.message_id)) {
        const user = element("article", undefined, "chat-message user");
        user.append(element("small", "You", "message-author"), element("p", attempt.question));
        nodes.push(user); messages.add(attempt.message_id);
      }
      const assistant = element("article", undefined, "chat-message assistant");
      assistant.append(element("small", "Shopping Assistant", "message-author"));
      if (attempt.tools.length) {
        const tools = element("details", undefined, "tool-activity");
        tools.append(element("summary", `${attempt.tools.length} purchase-history read${attempt.tools.length === 1 ? "" : "s"}`));
        for (const tool of attempt.tools) {
          tools.append(element("p", (toolNames[tool.name] || "Read tool") + " · " +
            (tool.result ? tool.result.status.replaceAll("_", " ") : (attempt.status === "running" ? "reading…" : "incomplete"))));
        }
        assistant.append(tools);
      }
      assistant.append(element("p", attempt.text.replace(/\[\[(order|product):[1-9][0-9]*\]\]/g, ""), "response-text"));
      for (const evidence of attempt.evidence) {
        const match = /^(order|product):([1-9][0-9]*)$/.exec(evidence.id);
        if (!match) continue;
        const url = "/" + match[1] + "s/" + match[2];
        const link = element("a", match[1] === "order" ? "Order " + match[2] : "Product " + match[2], "evidence-link");
        link.href = url;
        if (match[1] === "order") {
          link.setAttribute("hx-get", url + "?view=drawer");
          link.setAttribute("hx-target", "#drawer-root");
          link.setAttribute("hx-swap", "innerHTML");

        }
        assistant.append(link);
      }
      if (attempt.status !== "complete") {
        const labels = {running: "Responding…", stopping: "Stopping… Waiting for cleanup.",
          failed: "Response failed · incomplete", stopped: "Stopped · incomplete", interrupted: "Interrupted by service restart · incomplete"};
        const reason = {provider_unavailable: "Ollama is unavailable. Try again when it is running.",
          accounting_unsupported: "The model configuration needs verification.",
          deadline: "The response reached its time limit.",
          cleanup_fault: "Cleanup could not be confirmed. The service needs to restart."}[attempt.code];
        assistant.append(element("p", (labels[attempt.status] || "Incomplete") + (reason ? ". " + reason : ""), "response-notice"));
      }
      nodes.push(assistant);
    }
    if (!nodes.length) {
      const empty = element("div", undefined, "chat-empty");
      empty.append(element("h2", "Ask about your purchases"),
        element("p", "Find recorded orders, items, dates and prices. Answers link back to your evidence."));
      nodes.push(empty);
    }
    transcript.replaceChildren(...nodes);
    if (window.htmx) window.htmx.process(transcript);
    byId("chat-older").hidden = !older;
    if (atBottom) scroll.scrollTop = scroll.scrollHeight;
    controls();
  }
  function renderLibrary() {
    const nodes = [];
    for (const item of library.values()) {
      const row = button(item.title, () => { select(item.id); dialog.close(); }, "conversation-row");
      row.classList.toggle("selected", item.id === selected);
      if (item.id === selected) row.setAttribute("aria-current", "true");
      nodes.push(row);
    }
    if (!nodes.length) nodes.push(element("p", "No saved conversations yet.", "rail-foot"));
    byId("chat-library").replaceChildren(...nodes);
    byId("chat-library-more").hidden = !libraryCursor;
  }
  function gone(cid) {
    library.delete(cid); renderLibrary();
    if (selected === cid || restored === cid) {
      conversation = null; attempts.clear(); restored = null; store("chat-selected", null);
      selected = null; older = null; render();
      notice("Conversation deleted. Choose New conversation to continue.");
    }
  }
  function acknowledge(id, outcome) {
    if (!pending || pending.id !== id) return;
    const previous = pending;
    pending = null; store("chat-pending", null);
    if (outcome?.status === "accepted" && previous.type === "submit") {
      const key = "chat-draft:" + previous.conversation_id;
      if (read(key, "") === previous.text) store(key, "");
      if (read("chat-draft:new", "") === previous.text) store("chat-draft:new", "");
      if (selected === previous.conversation_id && input.value === previous.text) { input.value = ""; saveDraft(); }
      restored = outcome.conversation_id; store("chat-selected", restored);
    }
    if (!outcome) notice("This command was not accepted. Review the saved state and send again if needed.");
    controls();
  }
  function event(value) {
    if (!value || value.v !== 1) throw new Error("protocol");
    if (value.type === "part") {
      if (!Number.isInteger(value.total) || value.total < 1 || value.total > 6 || typeof value.data !== "string") throw new Error("protocol");
      if (value.index === 0) partial = {id: value.transfer, chunks: [], total: value.total, size: 0};
      if (!partial || partial.id !== value.transfer || value.index !== partial.chunks.length || partial.total !== value.total) throw new Error("protocol");
      const bytes = Uint8Array.from(atob(value.data), c => c.charCodeAt(0));
      partial.size += bytes.length;
      if (partial.size > 192 * 1024) throw new Error("protocol");
      partial.chunks.push(bytes);
      if (partial.chunks.length === partial.total) {
        const all = new Uint8Array(partial.size); let offset = 0;
        for (const chunk of partial.chunks) { all.set(chunk, offset); offset += chunk.length; }
        partial = null; event(JSON.parse(decoder.decode(all)));
      }
      return;
    }
    if (value.availability) availability = value.availability;
    if (value.type === "ready") {
      clearTimeout(reconnectTimer);
      ready = true; started = 0; retryNumber = 0; byId("chat-reconnect").hidden = true;
      if (pending) send("status", {command_id: pending.id});
      select(restored);
      connectedNotice();
    } else if (value.type === "draft") {
      if (value.id !== selecting) return;
      selected = value.conversation_id; draftLoaded = true; conversation = null; attempts.clear(); older = null;
      restored = null; store("chat-selected", null);
      input.value = read("chat-draft:new", ""); render(); renderLibrary(); input.focus();
    } else if (value.type === "snapshot") {
      if (value.id === selecting) {
        selected = value.conversation.id; attempts.clear(); conversation = null;
        input.value = read("chat-draft:" + selected, ""); draftLoaded = true;
        restored = selected; store("chat-selected", selected);
      }
      if (value.conversation.id !== selected) return;
      if (!conversation || value.conversation.version >= conversation.version) conversation = value.conversation;
      value.items.forEach(rememberAttempt);
      older = value.next_cursor; refreshPending = false;
      render(); renderLibrary(); connectedNotice();
    } else if (value.type === "update") {
      if (value.conversation.id !== selected) return;
      if (conversation && value.conversation.version <= conversation.version) return;
      if (conversation && value.conversation.version > conversation.version + 1) snapshot();
      const wasDraft = !conversation;
      conversation = value.conversation; rememberAttempt(value.attempt);
      if (wasDraft) { saveDraft(); store("chat-draft:new", ""); }
      restored = selected; store("chat-selected", selected); render(); connectedNotice();
    } else if (value.type === "library") {
      if (!value.older) library = new Map();
      value.items.forEach(item => library.set(item.id, item));
      libraryCursor = value.next_cursor; renderLibrary();
    } else if (value.type === "ack") {
      acknowledge(value.id, value.outcome);
    } else if (value.type === "command_status") {
      const needsSelection = pending?.type === "submit" && value.outcome?.status === "accepted";
      acknowledge(value.command_id, value.outcome);
      if (value.outcome?.status === "gone") gone(value.outcome.conversation_id);
      if (needsSelection) select(value.outcome.conversation_id);
      else if (conversation) snapshot();
    } else if (value.type === "gone") {
      gone(value.conversation_id);
    } else if (value.type === "error") {
      if (pending?.id === value.id) { pending = null; store("chat-pending", null); }
      refreshPending = false;
      const messages = {busy: "Another response is running. Your draft is preserved.",
        faulted: "Responses are unavailable until the service restarts. Saved history is still readable.",
        configuration_changed: "This conversation uses a different model configuration. Start a new conversation.",
        cleanup_fault: "Cleanup could not be confirmed. The conversation is still saved. Restart the service before deleting again.",
        gone: "This conversation is gone. Choose New conversation to continue.",
        storage_failure: "Saving failed. Reconnect to check the last saved state.",
        persistence_or_runtime_failure: "The response could not be saved or finished. Reconnect to check the last saved state."};
      notice(messages[value.code] || "The command was rejected. Your draft is preserved.");
      if (value.code === "gone") gone(selected || restored);
    } else if (["availability", "pong"].includes(value.type)) connectedNotice();
    else throw new Error("protocol");
  }
  async function connect() {
    if (disposed || !navigator.onLine) { notice("Offline · saved state may be stale. Your draft is preserved."); return; }
    clearTimeout(reconnectTimer); clearInterval(heartbeat);
    const attempt = ++epoch, previous = socket; socket = null; previous?.close();
    ready = false; partial = null; refreshPending = false;
    notice("Connecting… Saved state may be stale.");
    try {
      const response = await fetch("/chat/token", {headers: {"X-Chat-Page": "1"}, cache: "no-store", credentials: "same-origin"});
      if (!response.ok) { notice("Refresh the page or check the configured application origin."); byId("chat-reconnect").hidden = false; return; }
      const context = await response.json();
      if (attempt !== epoch || disposed || !navigator.onLine) return;
      socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/chat/ws");
      const current = socket; let protocolFault = false;
      socket.onopen = () => {
        lastSeen = Date.now();
        current.send(JSON.stringify({v: 1, type: "initialize", id: crypto.randomUUID(), token: context.token}));
        heartbeat = setInterval(() => {
          if (Date.now() - lastSeen >= 40000) { current.close(); return; }
          if (ready && current.readyState === WebSocket.OPEN) current.send(JSON.stringify({v: 1, type: "ping"}));
        }, 20000);
      };
      socket.onmessage = message => {
        if (socket !== current) return;
        lastSeen = Date.now();
        try {
          if (typeof message.data !== "string" || encoder.encode(message.data).length > 65536) throw new Error("protocol");
          event(JSON.parse(message.data));
        } catch (_) { protocolFault = true; current.close(4400); }
      };
      socket.onclose = close => {
        if (socket !== current || disposed) return;
        ready = false; clearInterval(heartbeat); controls();
        if (protocolFault || close.code >= 4400) {
          notice("Connection rejected or expired. Refresh the page to renew access.");
          byId("chat-reconnect").hidden = false;
        } else retryConnect();
      };
    } catch (_) { retryConnect(); }
  }
  function retryConnect() {
    if (disposed || !navigator.onLine) { notice("Offline · saved state may be stale."); return; }
    if (!started) started = Date.now();
    if (Date.now() - started > 120000) {
      notice("Connection lost. Choose Reconnect to recover saved state."); byId("chat-reconnect").hidden = false; return;
    }
    const delay = Math.min(30000, 1000 * 2 ** retryNumber++) * (.85 + Math.random() * .3);
    notice("Reconnecting… Saved state may be stale; a response may still be running.");
    reconnectTimer = setTimeout(connect, delay);
  }
  function openDialog(...nodes) {
    dialog.replaceChildren(...nodes); dialog.showModal();
  }
  dialog.addEventListener("close", () => {
    if (dialog.contains(rail)) root.prepend(rail);
  });
  byId("chat-history-toggle").onclick = () => openDialog(rail, button("Close", () => dialog.close()));
  byId("chat-new").onclick = () => { select(null); dialog.close(); };
  byId("chat-library-more").onclick = () => send("snapshot", {conversation_id: null, before: libraryCursor});
  byId("chat-older").onclick = () => send("snapshot", {conversation_id: selected, before: older});
  byId("chat-reconnect").onclick = () => { started = 0; retryNumber = 0; connect(); };
  byId("chat-stop").onclick = () => mutate("stop", {conversation_id: selected, attempt_id: latest().id});
  byId("chat-retry").onclick = () => mutate("retry", {conversation_id: selected, attempt_id: latest().id});
  byId("chat-rename").onclick = () => {
    const label = element("label", "Conversation name"), name = element("input");
    name.id = "chat-name"; label.htmlFor = name.id; name.value = conversation.title; name.maxLength = 80;
    openDialog(element("h2", "Rename conversation"), label, name,
      button("Save name", () => { if (name.value.trim()) { mutate("rename", {conversation_id: selected, text: name.value}); dialog.close(); } }),
      button("Cancel", () => dialog.close())); name.focus();
  };
  byId("chat-delete").onclick = () => openDialog(element("h2", "Delete this conversation?"),
    element("p", "This also stops any active response. Messages and tool activity are removed after cleanup. Purchase records and existing backups are unaffected. This cannot be undone."),
    button("Delete conversation", () => { mutate("delete", {conversation_id: selected, confirmed: true}); dialog.close(); }, "chat-btn danger"),
    button("Keep conversation", () => dialog.close()));
  byId("chat-composer").onsubmit = e => {
    e.preventDefault();
    if (!input.value.trim() || byId("chat-send").disabled) return;
    saveDraft(); mutate("submit", {conversation_id: selected, text: input.value});
  };
  input.addEventListener("input", saveDraft);
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); byId("chat-composer").requestSubmit(); }
  });
  window.addEventListener("offline", () => { clearTimeout(reconnectTimer); started = 0; ready = false; socket?.close(); notice("Offline · saved state may be stale. Your draft is preserved."); });
  window.addEventListener("online", () => { started = 0; retryNumber = 0; connect(); });
  window.addEventListener("pagehide", () => { saveDraft(); disposed = true; clearInterval(heartbeat); clearTimeout(reconnectTimer); socket?.close(); });
  window.addEventListener("pageshow", e => {
    if (e.persisted) { disposed = false; started = 0; retryNumber = 0; connect(); }
  });
  connect();
})();
