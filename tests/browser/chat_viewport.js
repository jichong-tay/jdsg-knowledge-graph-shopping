// Run on a local Chat page: agent-browser eval --stdin < tests/browser/chat_viewport.js
// Exercise the real document and styles in isolated viewports, without chat mutations.
(async () => {
  const html = new DOMParser().parseFromString(await (await fetch('/chat')).text(), 'text/html');
  html.querySelectorAll('script').forEach(script => script.remove());
  // Revalidate assets so a previous run cannot hide stylesheet edits in the HTTP cache.
  await Promise.all([...html.querySelectorAll('link[rel="stylesheet"]')].map(link =>
    fetch(link.href, {cache: 'reload'}).then(response => response.text())));
  const results = [];
  const failures = [];
  for (const [width, height] of [[1440, 900], [1024, 768], [768, 640], [760, 600], [390, 844], [390, 500], [844, 390], [320, 568]]) {
    const frame = document.createElement('iframe');
    frame.style.cssText = `position:fixed;left:0;top:0;width:${width}px;height:${height}px;border:0;z-index:1000`;
    const loaded = new Promise(resolve => frame.onload = resolve);
    frame.srcdoc = '<!doctype html>' + html.documentElement.outerHTML;
    document.body.append(frame);
    try {
      await loaded;
      const w = frame.contentWindow;
      const d = w.document;
      const messages = d.getElementById('chat-messages');
      const surface = d.getElementById('shopping-chat');
      const composer = d.getElementById('chat-composer');
      function check(condition, description) {
        if (!condition) failures.push(`${width}x${height}: ${description}`);
      }
      function checkLayout(state) {
        const root = d.scrollingElement;
        check(root.scrollHeight <= height + 1, `${state}: page overflows by ${root.scrollHeight - height}px`);
        check(root.scrollWidth <= width + 1, `${state}: page overflows horizontally`);
        check(surface.scrollHeight <= surface.clientHeight + 1, `${state}: chat contents overflow the shell`);
        check(Math.abs(surface.getBoundingClientRect().bottom - height) <= 1,
          `${state}: chat bottom is ${surface.getBoundingClientRect().bottom}px, expected ${height}px`);
        check(Math.abs(composer.getBoundingClientRect().bottom - height) <= 2,
          `${state}: composer is not at the viewport bottom`);
        check(d.getElementById('chat-send').getBoundingClientRect().bottom <= height,
          `${state}: Send button is outside the viewport`);
        w.scrollTo(0, 1000);
        check(w.scrollY === 0, `${state}: outer page can scroll`);
        results.push({width, height, state, pageHeight: root.scrollHeight, chatBottom: surface.getBoundingClientRect().bottom});
      }
      checkLayout('empty');
      // The welcome content fits in an ordinary desktop/portrait viewport.
      if (height >= 600) check(messages.scrollHeight <= messages.clientHeight + 1, 'empty: unnecessary message scrollbar');

      const transcript = d.getElementById('chat-transcript');
      transcript.replaceChildren();
      for (let i = 0; i < 40; i++) {
        const message = d.createElement('article');
        message.className = 'chat-message assistant';
        message.textContent = `Synthetic message ${i}. ` + 'Recorded purchase evidence. '.repeat(20);
        transcript.append(message);
        const conversation = d.createElement('button');
        conversation.className = 'conversation-row';
        conversation.textContent = `Synthetic conversation ${i}`;
        d.getElementById('chat-library').append(conversation);
      }
      checkLayout('long conversation');
      messages.scrollTop = messages.scrollHeight;
      check(messages.scrollTop > 0, 'long conversation: message history cannot scroll');
      check(messages.scrollHeight - messages.scrollTop - messages.clientHeight <= 1,
        'long conversation: latest message is unreachable');
      const library = d.getElementById('chat-library');
      if (width > 760) {
        library.scrollTop = library.scrollHeight;
        check(library.scrollTop > 0, 'long library: conversations cannot scroll');
      }

      d.getElementById('chat-message').style.height = '180px';
      d.getElementById('chat-connection').textContent = 'Connection lost. Choose Reconnect to recover saved state.';
      d.getElementById('chat-reconnect').hidden = false;
      checkLayout('expanded composer and reconnect');
      check(messages.clientHeight > 0, 'expanded composer: no space remains for messages');
    } finally {
      frame.remove();
    }
  }
  if (failures.length) throw new Error(failures.join('\n'));
  return {passed: results.length, viewports: results.length / 3};
})()
