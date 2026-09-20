// Run: agent-browser --session purchase-focus eval --stdin < tests/browser/graph_purchase_focus.js
// Prerequisite: disposable synthetic server at 127.0.0.1:8780 started with
// `uv run python tests/browser/graph_server.py --port 8780 --purchase-focused`.
// This check never targets the operator database and intentionally describes
// the purchase-focused contract before its implementation exists.
(async () => {
  const q = s => document.querySelector(s);
  const assert = (value, message) => { if (!value) throw Error(message); };
  const root = q('#shopping-graph');
  const wait = async () => {
    const until = Date.now() + 8000;
    while (Date.now() < until) {
      if (root?.dataset.loadState === 'ready') return;
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    throw Error(`graph did not become ready: ${q('#graph-error')?.textContent || ''}`);
  };
  await wait();
  const canvas = q('#graph-canvas');
  const cy = canvas?._cyreg?.cy;
  assert(cy, 'Cytoscape instance missing');
  const frequent = [...cy.nodes()].find(node => String(node.data('label')).includes('Synthetic Frequent Product'));
  const once = [...cy.nodes()].find(node => String(node.data('label')).includes('Synthetic Once Product'));
  assert(frequent && once, 'purchase-focused products missing from overview');

  // Regression: purchase frequency must be visible in node sizing and metadata.
  const frequentSize = frequent.renderedWidth();
  const onceSize = once.renderedWidth();
  assert(frequentSize / onceSize >= 1.4, `purchase frequency size ratio too small (${frequentSize} vs ${onceSize})`);

  const productButton = [...document.querySelectorAll('#graph-relationships [data-graph-action="select"]')]
    .find(button => button.textContent.includes('Synthetic Frequent Product'));
  assert(productButton, 'frequent product is not keyboard/click accessible');
  productButton.click();
  await wait();
  const focusedCy = canvas?._cyreg?.cy;
  const focusedProduct = focusedCy.nodes('.product').filter(node => node.data('label').includes('Synthetic Frequent Product'));
  assert(focusedProduct.length === 1, 'product click did not select the frequent product');
  const focusedOrders = focusedProduct.closedNeighborhood('node').filter('.order');
  assert([6, 12].includes(focusedOrders.length), `product click should reveal six or twelve order neighbors, got ${focusedOrders.length}`);
  const focusedEdges = focusedProduct.connectedEdges().filter(edge => edge.data('canonicalPredicate') === 'PURCHASED_IN');
  const expectedOrders = focusedOrders.length;
  assert(focusedEdges.length === focusedOrders.length && focusedEdges.every(edge => edge.visible()), 'focused purchase edges are hidden');
  assert(focusedOrders.every(order => /Aug 2026/.test(String(order.data('label')))), 'order neighbors lack readable delivery dates');
  assert(focusedOrders.every(order => order.numericStyle('font-size') * focusedCy.zoom() >= 12), 'focused labels are too small');
  const boxes = [focusedProduct[0], ...focusedOrders].map(node => node.renderedBoundingBox({includeLabels:true}));
  assert(boxes.every(box => box.x1 >= -2 && box.y1 >= -2 && box.x2 <= canvas.clientWidth + 2 && box.y2 <= canvas.clientHeight + 2), 'focused labels exceed canvas bounds');
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++)
    assert(boxes[i].x2 <= boxes[j].x1 + 4 || boxes[j].x2 <= boxes[i].x1 + 4 || boxes[i].y2 <= boxes[j].y1 + 4 || boxes[j].y2 <= boxes[i].y1 + 4, 'focused node labels overlap');

  const productId = frequent.id();
  const selected = await (await fetch('/graph/view?request=' + encodeURIComponent(JSON.stringify({
    selected_id: productId,
    expanded_ids: [productId],
    purchase_scope: { analysis_date: '2026-09-20' },
  })))).json();
  const selectedNode = selected.selection?.node;
  assert(selectedNode?.type === 'product', 'selected frequent product did not load');
  assert(selectedNode.attributes?.purchase_count === expectedOrders, `frequent product should expose purchase_count ${expectedOrders}`);
  assert(Number(selected.selection?.timeline?.summary?.order_count) === expectedOrders, 'frequent product distinct order count mismatch');
  assert(selected.selection.timeline.occurrences.length === expectedOrders, 'repeated lines inflated dated order occurrences');

  // Regression: a product click should expose dated order neighbors in the
  // focused neighborhood, with meaningful direct Product -> Order relations.
  const orderNeighbors = selected.nodes.filter(node => node.type === 'order');
  assert(orderNeighbors.length === expectedOrders, `expected ${expectedOrders} order neighbors, got ${orderNeighbors.length}`);
  assert(selected.edges.some(edge => edge.type === 'PURCHASED_IN' && edge.source === productId),
    'focused product has no direct Product → Order edge');
  assert(orderNeighbors.every(node => node.attributes?.delivery_at && node.attributes?.status),
    'order neighbors lack delivery dates');
  const order = focusedOrders[0];
  const beforePositions = new Map(focusedOrders.map(node => [node.id(), {...node.position()}]));
  const productLabelBefore = focusedProduct[0].renderedBoundingBox({includeLabels:true});
  const productValignBefore = focusedProduct[0].style('text-valign');
  order.emit('tap');
  await wait();
  assert(q('#graph-inspector').textContent.includes('Scheduled delivery') || q('#graph-inspector').textContent.includes('completed'), 'order activation lost order context');
  assert(focusedCy.edges().filter(edge => edge.data('canonicalPredicate') === 'PURCHASED_IN' && edge.visible()).length === expectedOrders, 'order activation hid purchase edges');
  const liveOrders = [...beforePositions.keys()].map(id => focusedCy.$id(id)).filter(node => node.length).map(node => node[0]);
  assert(liveOrders.length === expectedOrders && liveOrders.every(node => node.visible()), 'order activation removed or hid focused orders');
  assert(liveOrders.every(node => { const before = beforePositions.get(node.id()); const now = node.position(); return Math.abs(before.x - now.x) < 1 && Math.abs(before.y - now.y) < 1; }), 'order activation moved the focused orders');
  const productLabelAfter = focusedCy.nodes('.product').filter(node => node.id() === focusedProduct[0].id())[0];
  assert(productLabelAfter.style('text-valign') === productValignBefore, 'order activation changed Product label alignment');
  const afterBox = productLabelAfter.renderedBoundingBox({includeLabels:true});
  assert(Math.abs(afterBox.x1 - productLabelBefore.x1) <= 3 && Math.abs(afterBox.y1 - productLabelBefore.y1) <= 3, 'order activation moved Product label bounds');
  assert([...q('#graph-inspector').querySelectorAll('a')].some(link => /^\/orders\/[1-9]/.test(link.getAttribute('href') || '')), 'order inspector lacks evidence link');
  q('[data-graph-action="clear-product-focus"]').click();
  await wait();
  assert(!new URL(location.href).searchParams.get('selected'), 'All products did not clear product focus');
  return { passed: true, frequentOrders: expectedOrders, onceOrders: 1, repeatedLinesCollapsed: true, datedOrderNeighbors: expectedOrders, orderContextRetained: true };
})()
