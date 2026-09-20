// Run: agent-browser --session ticket21 eval --stdin < tests/browser/graph_explorer.js
// Prerequisite: synthetic server at 127.0.0.1:8766 with 2 Products, Family 1
// accepting Product 1, and Revision 3 containing 60 items. Start from a fresh
// /graph page with no expanded nodes or search query.
(async () => {
  const q = s => document.querySelector(s);
  const root = q('#shopping-graph');
  if (!root) throw Error('Open the synthetic Graph page first.');
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async (test, label) => {
    const end = Date.now() + 8000;
    while (Date.now() < end) { if (test()) return; await new Promise(r => setTimeout(r, 20)); }
    throw Error(`Timed out: ${label}; ${q('#graph-error')?.textContent}`);
  };
  const ready = () => wait(() => root.dataset.loadState === 'ready', 'ready');
  const click = selector => { assert(q(selector), `Missing ${selector}`); q(selector).click(); };
  const select = async (type, id) => {
    click(`[data-graph-action="select"][data-node-id$=":${type}:${id}"]`);
    await ready();
  };
  const summary = () => {
    const n = q('[data-graph-order-count]');
    return [n?.dataset.graphOrderCount, n?.dataset.graphDayCount];
  };
  await ready();
  await select('family', 1);
  const familyName = q('#graph-inspector h2').textContent;
  assert(summary().join() === '3,2', 'Fixture family summary differs from 3 orders/2 days');
  const form = q('#graph-filters');
  form.elements.query.value = familyName;
  form.requestSubmit(); await ready();
  assert(!q('#graph-relationships [data-node-id$=":product:2"]'), 'Search failed to narrow overview');
  form.elements.query.value = ''; form.requestSubmit(); await ready();
  assert(q('#graph-relationships [data-node-id$=":product:2"]'), 'Clear search did not restore product');
  const boxes = [...form.querySelectorAll('[name=node_types]')];
  boxes.filter(n => ['order','product'].includes(n.value)).forEach(n => n.checked = false);
  form.requestSubmit(); await ready();
  assert(summary().join() === '3,2', 'Visibility changed analytics');
  boxes.forEach(n => n.checked = true); form.requestSubmit(); await ready();
  const canvas = q('#graph-canvas');
  const cy = canvas?._cyreg?.cy;
  assert(cy, 'Cytoscape renderer missing');
  const beforeZoom = cy.zoom(); click('[data-graph-action="zoom-in"]');
  assert(cy.zoom() > beforeZoom, 'Zoom in did not increase zoom');
  click('[data-graph-action="fit"]'); const fitted = cy.zoom();
  click('[data-graph-action="reset"]');
  assert(cy.zoom() === 1 && fitted !== 1, 'Fit/reset failed');
  click('#graph-inspector [data-graph-action="expand"]'); await ready();
  assert(cy.edges().length, 'Family expansion omitted membership edge');
  const keyboardNode = q('#graph-relationships [data-graph-action="select"][data-node-id$=":product:2"]');
  assert(keyboardNode, 'Product missing from accessible list');
  keyboardNode.focus(); keyboardNode.click();
  await ready(); assert(q('#graph-inspector h2').textContent.includes('Paper Towels'), 'Keyboard selection failed');
  await select('family', 1);
  await select('revision', 3);
  click('#graph-inspector [data-graph-action="expand"]'); await ready();
  const continuation = q('[data-graph-action="relationship-next"][data-root-id$=":revision:3"]');
  assert(continuation, '60-item revision needs bounded relationship continuation');
  const firstItems = cy.nodes().filter(n => n.id().includes(':item:')).map(n => n.id());
  continuation.click(); await ready();
  const nextItems = cy.nodes().filter(n => n.id().includes(':item:')).map(n => n.id());
  assert(nextItems.length && nextItems.some(id => !firstItems.includes(id)), 'Continuation did not advance');
  assert(cy.nodes().length <= 200 && cy.edges().length <= 400, 'Graph caps exceeded');
  await select('family', 1);
  const originalFetch = window.fetch;
  let mode = '', releaseA;
  window.fetch = async (url, options) => {
    if (!String(url).startsWith('/graph/view')) return originalFetch(url, options);
    if (mode === 'A') {
      const response = await originalFetch(url, {...options, signal:undefined});
      return new Promise(resolve => { releaseA = () => resolve(response); });
    }
    if (mode === '409' || mode === '500') return new Response(JSON.stringify({code:'synthetic_failure'}), {status:Number(mode),headers:{'Content-Type':'application/json'}});
    return originalFetch(url, options);
  };
  try {
    mode = 'A'; click('[data-graph-action="select"][data-node-id$=":product:1"]');
    await wait(() => releaseA, 'delayed successful A');
    mode = 'B'; await select('family', 1);
    const stableInspector = q('#graph-inspector').textContent;
    const stableTimeline = q('#graph-timeline').textContent;
    releaseA(); await new Promise(r => setTimeout(r, 100));
    assert(q('#graph-inspector').textContent === stableInspector, 'Late Product A overwrote Family B');
    for (const code of ['409','500']) {
      mode = code; click('[data-graph-action="refresh"]');
      await wait(() => root.dataset.loadState === 'error', `${code} surfaced`);
      assert(q('#graph-error').textContent, 'Missing error message');
      assert(q('#graph-inspector').textContent === stableInspector && q('#graph-timeline').textContent === stableTimeline, `${code} replaced prior view`);
    }
  } finally { window.fetch = originalFetch; }
  click('[data-graph-action="refresh"]'); await ready();
  assert(!q('#graph-error').textContent, 'Refresh did not recover');
  return {passed:true,summary:summary(),search:true,filterIndependent:true,keyboard:true,zoomFitReset:true,relationshipContinuation:true,delayedSuccessIgnored:true,errorRecovery:true};
})()
