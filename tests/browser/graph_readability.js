(async () => {
  const root = document.querySelector('#shopping-graph');
  const canvas = document.querySelector('#graph-canvas');
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async () => { const end = Date.now() + 8000; while (Date.now() < end) { if (root.dataset.loadState === 'ready') return; await new Promise(r => setTimeout(r, 25)); } throw Error('graph did not become ready'); };
  await wait();
  const cy = canvas?._cyreg?.cy;
  assert(cy, 'Cytoscape instance missing');
  assert(cy.nodes().length >= 40, 'many-product fixture did not load');
  assert(cy.nodes().every(node => String(node.data('label')).length <= 65), 'display labels were not bounded');
  const boxes = cy.nodes().map(node => node.renderedBoundingBox({ includeLabels: true }));
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    assert(a.x2 <= b.x1 + 6 || b.x2 <= a.x1 + 6 || a.y2 <= b.y1 + 6 || b.y2 <= a.y1 + 6, 'overview labels overlap');
  }
  const font = cy.nodes()[0].numericStyle('font-size') * cy.zoom();
  assert(font >= 12, 'initial labels are too small');
  const initialZoom = cy.zoom();
  document.querySelector('[data-graph-action="fit"]')?.click();
  const fitZoom = cy.zoom();
  document.querySelector('[data-graph-action="zoom-out"]')?.click();
  assert(cy.zoom() < fitZoom, 'zoom out increased zoom after fit');
  document.querySelector('[data-graph-action="reset"]')?.click();
  assert(cy.zoom() >= initialZoom && Number.parseFloat(getComputedStyle(canvas).fontSize || '14') * cy.zoom() >= 12, 'reset did not restore readable scale');
  const rect = canvas.getBoundingClientRect();
  assert(canvas.scrollWidth <= rect.width + 2, 'graph has horizontal overflow');
  return { passed: true, initialFontPx: font, nodeCount: cy.nodes().length, fitZoom, resetZoom: cy.zoom(), noHorizontalOverflow: true };
})();
