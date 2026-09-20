// Synthetic Graph page; exercises real HTMX swaps and browser history.
(async () => {
  const q = s => document.querySelector(s);
  const assert = (ok, text) => { if (!ok) throw Error(text); };
  const wait = async (fn, label) => {
    const end = Date.now() + 8000;
    while (Date.now() < end) { if (fn()) return; await new Promise(r => setTimeout(r, 20)); }
    throw Error(`Timeout ${label}`);
  };
  const ready = () => q('#shopping-graph')?.dataset.loadState === 'ready';
  const originalFetch = window.fetch;
  let viewRequests = 0, delayed = false, release;
  window.fetch = async (url, options) => {
    if (!String(url).startsWith('/graph/view')) return originalFetch(url, options);
    viewRequests++;
    if (delayed) {
      const response = await originalFetch(url, {...options, signal:undefined});
      return new Promise(resolve => { release = () => resolve(response); });
    }
    return originalFetch(url, options);
  };
  try {
    await wait(ready, 'initial graph');
    for (let round = 0; round < 3; round++) {
      q('[data-nav-path="/orders"]').click();
      await wait(() => !q('#shopping-graph') && location.pathname === '/orders', 'orders navigation');
      const before = viewRequests;
      q('[data-nav-path="/graph"]').click();
      await wait(ready, 'graph navigation');
      assert(viewRequests === before + 1, 'duplicate Graph controllers during navigation');
    }
    const first = q('#graph-relationships [data-graph-action="select"]');
    first.click(); await wait(ready, 'selected graph');
    const selectedURL = location.href;
    const selectedHeading = q('#graph-inspector h2').textContent;
    q('[data-nav-path="/orders"]').click();
    await wait(() => !q('#shopping-graph'), 'orders before Back');
    history.back();
    await wait(() => ready() && location.href === selectedURL, 'Back restored URL and fresh graph');
    assert(q('#graph-inspector h2').textContent === selectedHeading, 'Back lost selected node');
    history.forward(); await wait(() => !q('#shopping-graph'), 'Forward to orders');
    history.back(); await wait(ready, 'second Back');
    const oldRoot = q('#shopping-graph');
    delayed = true;
    q('[data-graph-action="refresh"]').click();
    await wait(() => release, 'pending graph response');
    q('[data-nav-path="/orders"]').click();
    await wait(() => !oldRoot.isConnected, 'detached old Graph');
    release(); await new Promise(r => setTimeout(r, 100));
    assert(!q('#shopping-graph'), 'late response remounted Graph');
    assert(oldRoot.dataset.loadState === 'loading', 'detached controller rendered late response');
    delayed = false;
    q('[data-nav-path="/graph"]').click(); await wait(ready, 'return after late response');
    const before = viewRequests;
    q('[data-graph-action="refresh"]').click(); await wait(ready, 'one refresh');
    assert(viewRequests === before + 1, 'Refresh dispatched multiple graph reads');
    const persisted = JSON.stringify(localStorage);
    assert(!persisted.includes('Breakfast staples') && !persisted.includes('graph-review-entry'), 'private Graph DOM persisted');
    assert(!JSON.stringify(history.state).includes('nodes'), 'Graph result persisted in history');
    return {passed:true,repeatedNavigation:3,backForward:true,detachedLateResponseIgnored:true,oneRequestPerAction:true,noGraphHistoryPayload:true};
  } finally { window.fetch = originalFetch; }
})()
