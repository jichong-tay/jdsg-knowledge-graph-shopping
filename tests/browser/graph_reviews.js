// Run: agent-browser --session ticket21 eval --stdin < tests/browser/graph_reviews.js
// Prerequisite: disposable synthetic server at 127.0.0.1:8766. This script
// creates and reviews synthetic Family data; never run it against real data.
(async () => {
  const q = s => document.querySelector(s);
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async (test, label) => {
    const until = Date.now() + 8000;
    while (Date.now() < until) { if (test()) return; await new Promise(r => setTimeout(r, 30)); }
    throw Error(`Timed out: ${label}. ${q('#graph-mutation-status')?.textContent}`);
  };
  const saved = () => q('#graph-mutation-status').textContent.startsWith('Saved.');
  const count = () => q('[data-graph-order-count]')?.dataset.graphOrderCount;
  const form = q('#graph-family-form');
  const name = `Synthetic <b>Family</b> ${Date.now()}`;
  form.elements.name.value = name;
  form.elements.definition.value = 'Include synthetic oat drinks; exclude other types.';
  const originalFetch = window.fetch;
  const sent = [];
  let lose = true;
  window.fetch = async (url, options) => {
    const response = await originalFetch(url, options);
    if (String(url) === '/graph/families' && options?.method === 'POST') {
      sent.push(JSON.parse(options.body));
      if (lose) { lose = false; throw Error('Synthetic connection lost after commit'); }
    }
    return response;
  };
  try {
    form.requestSubmit();
    await wait(() => q('#graph-mutation-status').textContent.includes('Synthetic connection'), 'uncertain save');
    form.requestSubmit();
    form.requestSubmit();
    await wait(saved, 'safe retry');
  } finally { window.fetch = originalFetch; }
  assert(sent.length === 2 && sent[0].command_id === sent[1].command_id, 'retry did not reuse command');
  assert(q('#graph-inspector h2').textContent === name, 'created family not selected');
  assert(!q('#graph-inspector b'), 'stored name rendered as HTML');
  assert(count() === '0', 'empty family nonzero');
  const proposal = q('#graph-proposal-form');
  const family = proposal.elements.family_id.value;
  assert(family, 'new family not chosen');
  proposal.elements.product_id.value = '1';
  proposal.elements.rationale.value = 'Synthetic evidence matches the family definition.';
  proposal.requestSubmit();
  await wait(() => saved() && q('[data-review-state="pending"]'), 'pending proposal');
  assert(count() === '0', 'pending changed timeline');
  const pending = q('[data-review-state="pending"]');
  pending.querySelector('textarea').value = 'Verified synthetic product type.';
  pending.querySelector('[data-review-action="accepted"]').click();
  await wait(() => saved() && count() === '3', 'accept updates timeline');
  q('#graph-review-mode').value = 'current';
  q('#graph-review-mode').dispatchEvent(new Event('change', {bubbles:true}));
  await wait(() => [...document.querySelectorAll('[data-review-state="accepted"]')].some(n => n.textContent.includes(name)), 'current accepted review');
  let row = [...document.querySelectorAll('[data-review-state="accepted"]')].find(n => n.textContent.includes(name));
  row.querySelector('textarea').value = 'Synthetic correction for withdrawal check.';
  row.querySelector('[data-review-action="withdrawn"]').click();
  await wait(() => saved() && count() === '0', 'withdraw updates timeline');
  row = [...document.querySelectorAll('[data-review-state="withdrawn"]')].find(n => n.textContent.includes(name));
  assert(row, 'withdrawn review missing');
  [...row.querySelectorAll('button')].find(n => n.textContent === 'Prepare new proposal').click();
  assert(proposal.elements.family_id.value === family && proposal.elements.product_id.value === '1', 'reproposal targets incorrect pair');
  proposal.elements.rationale.value = 'Synthetic second proposal for reject check.';
  proposal.requestSubmit();
  await wait(() => saved() && q('[data-review-state="pending"]'), 'reproposal');
  row = q('[data-review-state="pending"]');
  row.querySelector('textarea').value = 'Rejected after synthetic review.';
  row.querySelector('[data-review-action="rejected"]').click();
  await wait(() => saved() && !q('[data-review-state="pending"]'), 'reject');
  assert(count() === '0', 'rejected affected timeline');
  q('#graph-review-mode').value = 'history';
  q('#graph-review-mode').dispatchEvent(new Event('change', {bubbles:true}));
  await wait(() => q('#graph-review-status').textContent.includes('history'), 'history');
  const rows = [...document.querySelectorAll('.graph-review-entry')].filter(n => n.textContent.includes(name));
  assert(rows.length === 5, `expected five events, got ${rows.length}`);
  assert(rows.filter(n => n.querySelector('[data-graph-write]')).length === 0, 'historical events have actions');
  const view = await (await fetch('/graph/view?request=' + encodeURIComponent(JSON.stringify({query:name,purchase_scope:{analysis_date:'2026-09-20'}})))).json();
  assert(view.nodes.filter(n => n.type === 'family' && n.label === name).length === 1, 'uncertain retry duplicated family');
  return {passed:true, safeRetry:true, escapedName:true, states:['pending','accepted','withdrawn','pending','rejected'], timelineCounts:[0,3,0], events:rows.length};
})()
