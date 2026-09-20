(function() {
  "use strict";
  class GraphCanvas {
    displayLabel(value) {
      const label = String(value);
      return label.length > 54 ? `${label.slice(0, 53)}…` : label;
    }
    predicateLabel(value) {
      if (value === "PURCHASED_IN") return "";
      return { MAPS_TO_PRODUCT: "Maps to product", MEMBER_OF: "Member of", HAS_ITEM: "Has item", HAS_REVISION: "Has revision", CURRENT_REVISION: "Current revision" }[value] || String(value).replaceAll("_", " ").toLowerCase();
    }
    constructor(container, onSelect) {
      this.container = container;
      this.onSelect = onSelect;
      this.lastView = null;
      this.topology = "";
      this.lastWidth = container.clientWidth;
      this.resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(() => { this.cy?.resize(); if (this.lastView?.selection && container.clientWidth !== this.lastWidth) { this.lastWidth = container.clientWidth; this.topology = ""; this.render(this.lastView); } }) : null;
      this.themeObserver = typeof MutationObserver === "function" ? new MutationObserver(() => this.updateTheme()) : null;
      this.cy = null;
      this.camera = null;
      this.ready = typeof window.cytoscape === "function";
      if (this.ready) this.cy = window.cytoscape({ container, minZoom: .02, maxZoom: 4, elements: [], style: [
        { selector: "node", style: { "background-color": "#4f46e5", "label": "data(label)", color: "#111827", "font-size": 14, "text-wrap": "wrap", "text-max-width": 150, width: 52, height: 52, "border-width": 2, "border-color": "#ffffff", "text-valign": "bottom", "text-margin-y": 8, "text-outline-width": 2, "text-outline-color": "#ffffff" } },
        { selector: ".product", style: { width: "mapData(purchaseCount, 0, 10, 38, 100)", height: "mapData(purchaseCount, 0, 10, 38, 100)" } },
        { selector: "edge", style: { width: 1.5, "line-color": "#64748b", "target-arrow-color": "#64748b", "target-arrow-shape": "triangle", opacity: .8, "curve-style": "bezier", label: "data(predicate)", "font-size": 12, color: "#334155", "text-background-color": "#ffffff", "text-background-opacity": .9, "text-background-padding": 3 } },
        ...[["family", "#f59e0b"], ["product", "#10b981"], ["listing", "#06b6d4"], ["item", "#8b5cf6"], ["revision", "#ec4899"], ["order", "#6366f1"], ["retailer", "#f97316"], ["source", "#64748b"]].map(([type, color]) => ({ selector: `.${type}`, style: { "background-color": color } })),
        { selector: ".selected", style: { "border-width": 5, "border-color": "#111827" } },
        { selector: ".neighbor", style: { "border-width": 3, "border-color": "#facc15" } },
        { selector: ".inactive", style: { opacity: .35, "line-style": "dashed" } }
        ,{ selector: ".focus-dimmed", style: { opacity: .08, "text-opacity": .08 } },
        { selector: ".focus-hidden", style: { opacity: 0, "text-opacity": 0, events: "no" } }
      ], layout: { name: "grid", animate: false } });
      this.cy?.on("tap", "node", event => this.onSelect(event.target.id()));
      this.cy?.on("mouseover", "node", event => { this.cy.elements().removeClass("neighbor"); event.target.neighborhood().addClass("neighbor"); });
      this.cy?.on("mouseout", "node", () => this.cy.elements().removeClass("neighbor"));
      this.resizeObserver?.observe(container);
      this.themeObserver?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      this.updateTheme();
    }
    render(view) {
      this.lastView = view;
      if (!this.cy) return;
      const selectedNode = view.selection?.node;
      const focusProductId = selectedNode?.type === "product" && view.nodes.some(node => node.id === selectedNode.id && node.type === "product")
        ? selectedNode.id
        : selectedNode?.type === "order"
          ? view.edges.find(edge => edge.type === "PURCHASED_IN" && edge.target === selectedNode.id && view.nodes.some(node => node.id === edge.source && node.type === "product"))?.source || null
          : null;
      const topology = JSON.stringify([focusProductId, view.nodes.map(n => n.id).sort(), view.edges.map(e => `${e.id}:${e.source}:${e.target}:${e.type}`).sort()]);
      const changed = topology !== this.topology;
      this.topology = topology;
      const elements = [
        ...view.nodes.map(node => ({ data: { id: node.id, label: this.nodeLabel(node), purchaseCount: node.attributes?.purchase_count || 0, deliveryAt: node.attributes?.delivery_at || "" }, classes: node.type })),
        ...view.edges.map(edge => ({ data: { id: String(edge.id || `${edge.source}-${edge.target}-${edge.type}`), source: edge.source, target: edge.target, predicate: this.predicateLabel(edge.type), canonicalPredicate: edge.type }, classes: edge.state === "inactive" ? "inactive" : "" }))
      ];
      const positions = new Map(this.cy.nodes().map(node => [node.id(), node.position()]));
      this.cy.elements().remove();
      this.cy.add(elements);
      let focus = null;
      if (view.selection?.node) {
        const selected = this.cy.$id(view.selection.node.id);
        selected.addClass("selected");
        if (view.selection.node.type === "product" || view.selection.node.type === "order") {
          const productId = focusProductId;
          if (!productId) { this.topology = topology; }
          else {
          const product = this.cy.$id(productId);
          const orders = this.cy.nodes(".order").filter(order => view.edges.some(edge => edge.type === "PURCHASED_IN" && edge.source === productId && edge.target === order.id()));
          focus = product.union(orders);
          const focusEdges = this.cy.edges().filter(edge => edge.data("canonicalPredicate") === "PURCHASED_IN" && focus.contains(edge.source()) && focus.contains(edge.target()));
          const focusElements = focus.union(focusEdges);
          this.cy.elements().difference(focusElements).addClass("focus-dimmed");
          this.cy.elements().difference(focusElements).addClass("focus-hidden");
          }
        }
      }
      if (changed && !view.edges.length && !focus?.length) {
        this.container.style.height = "";
        this.cy.resize();
        const columns = Math.max(1, Math.floor((this.container.clientWidth - 40) / 210));
        const nodes = this.cy.nodes().toArray();
        const rows = Math.ceil(nodes.length / columns);
        const rowHeights = Array.from({ length: rows }, () => 150);
        nodes.forEach((node, index) => {
          const row = Math.floor(index / columns), col = index % columns;
          node.position({ x: 105 + col * 210, y: 75 + row * 150 });
          rowHeights[row] = Math.max(rowHeights[row], node.renderedBoundingBox({ includeLabels: true }).h + 24);
        });
        let y = 75;
        nodes.forEach((node, index) => {
          const row = Math.floor(index / columns), col = index % columns;
          node.position({ x: 105 + col * 210, y });
          if (col === columns - 1 || index === nodes.length - 1) y += rowHeights[row];
        });
        this.cy.zoom(1);
        this.cy.pan({ x: 0, y: 0 });
      } else if (changed) {
        const selectedNode = view.selection?.node;
        if (focus?.length) {
          const selected = focus.filter(".product").first();
          if (!selected.length) { this.cy.layout({ name: "cose", fit: false, animate: false, randomize: true, numIter: 300, idealEdgeLength: 100, nodeDimensionsIncludeLabels: true }).run(); return; }
          const orders = focus.filter(".order").sort((a, b) => String(a.data("deliveryAt")).localeCompare(String(b.data("deliveryAt"))) || a.id().localeCompare(b.id()));
          const mobile = this.container.clientWidth < 560;
          const rowHeight = 110;
          const height = mobile ? 320 + orders.length * rowHeight : Math.max(560, 180 + Math.ceil(orders.length / 2) * rowHeight);
          this.container.style.height = `${height}px`;
          this.cy.resize();
          selected.position({ x: mobile ? 90 : this.container.clientWidth / 2, y: mobile ? 125 : height / 2 });
          orders.forEach((order, index) => {
            if (mobile) order.position({ x: Math.max(150, this.container.clientWidth - 90), y: 230 + index * rowHeight });
            else {
              const column = index % 2, row = Math.floor(index / 2);
              order.position({ x: this.container.clientWidth / 2 + (column ? 190 : -190), y: 120 + row * rowHeight });
            }
          });
          this.cy.zoom(1); this.cy.pan({ x: 0, y: 0 });
        } else { this.container.style.height = ""; this.cy.resize(); this.cy.layout({ name: "cose", fit: false, animate: false, randomize: true, numIter: 400, idealEdgeLength: 100, componentSpacing: 120, nodeDimensionsIncludeLabels: true }).run(); }
        if (!focus?.length) this.cy.zoom(1);
      }
      else this.cy.nodes().forEach(node => { const position = positions.get(node.id()); if (position) node.position(position); });
      if (focusProductId) {
        const product = this.cy.$id(focusProductId);
        const mobile = this.container.clientWidth < 560;
        product.style(mobile ? { "text-valign": "top", "text-margin-y": -14 } : { "text-valign": "bottom", "text-margin-y": 8 });
      }
    }
    nodeLabel(node) {
      const attrs = node.attributes || {};
      if (node.type === "product") return `${this.displayLabel(node.label)}\n${Number(attrs.purchase_count || 0)} orders`;
      if (node.type === "order" && attrs.delivery_at) {
        const date = new Intl.DateTimeFormat("en-SG", { timeZone: "Asia/Singapore", day: "numeric", month: "short", year: "numeric" }).format(new Date(attrs.delivery_at));
        return `${date}${attrs.status ? `\n${attrs.status}` : ""}`;
      }
      return `${node.type}\n${this.displayLabel(node.label)}`;
    }
    updateTheme() {
      if (!this.cy) return;
      const dark = document.documentElement.dataset.theme === "dark";
      this.cy.style().selector("node").style({ color: dark ? "#f8fafc" : "#111827", "text-outline-color": dark ? "#0f172a" : "#ffffff", "border-color": dark ? "#0f172a" : "#ffffff" }).update();
      this.cy.style().selector("node.selected").style({ "border-color": dark ? "#a5b4fc" : "#4338ca", "border-width": 4 }).update();
      this.cy.style().selector("edge").style({ "line-color": dark ? "#cbd5e1" : "#64748b", "target-arrow-color": dark ? "#cbd5e1" : "#64748b", color: dark ? "#f8fafc" : "#334155", "text-background-color": dark ? "#0f172a" : "#ffffff" }).update();
    }
    zoom(factor) { if (this.cy) this.cy.zoom({ level: Math.max(.02, Math.min(4, this.cy.zoom() * factor)), renderedPosition: { x: this.container.clientWidth / 2, y: this.container.clientHeight / 2 } }); }
    fit() { this.cy?.fit(undefined, 48); }
    focusSelected() { const n = this.cy?.elements(".selected"); if (n?.length) this.cy.animate({ center: { eles: n }, zoom: Math.min(1.2, Math.max(0.8, this.cy.zoom())), duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 200 }); }
    reset() { this.cy?.reset(); }
    dispose() { this.resizeObserver?.disconnect(); this.themeObserver?.disconnect(); this.cy?.destroy(); this.cy = null; }
  }
  const G = "__shoppingGraphInstalled";
  if (window[G]) return;
  window[G] = true;
  const roots = new WeakMap(),
    active = new Set(),
    types = new Set(["order", "revision", "item", "listing", "product", "family", "retailer", "source"]);
  const idRx = /^[0-9a-f]{32}:(?:order|revision|item|listing|product|family|retailer|source):[1-9]\d*$/,
    dateRx = /^\d{4}-\d{2}-\d{2}$/;

  function sgToday() {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Singapore",
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    }).formatToParts(new Date()).filter(x => x.type !== "literal").map(x => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day}`;
  }
  const validId = x => typeof x === "string" && idRx.test(x),
    validDate = x => x == null || (typeof x === "string" && dateRx.test(x));

  function parseURL(root) {
    const p = new URLSearchParams(location.search),
      a = p.get("analysis") || root.dataset.analysisDate || sgToday(),
      selected = p.get("selected"),
      expanded = p.getAll("expanded"),
      nt = (p.get("types") || [...types].join(",")).split(",");
    if (!validDate(a) || selected && !validId(selected) || expanded.length > 12 || expanded.some(x => !validId(x)) || !nt.length || nt.some(x => !types.has(x))) throw Error("Invalid Graph URL state");
    return {
      query: p.get("q") || "",
      selected_id: selected || null,
      expanded_ids: expanded,
      mode: p.get("mode") === "history" ? "history" : "current",
      node_types: nt,
      purchase_scope: {
        analysis_date: a,
        start_date: p.get("start") || null,
        end_date: p.get("end") || null
      }
    };
  }

  function writeURL(s) {
    const p = new URLSearchParams();
    if (s.query) p.set("q", s.query);
    if (s.selected_id) p.set("selected", s.selected_id);
    s.expanded_ids.forEach(x => p.append("expanded", x));
    if (s.mode === "history") p.set("mode", "history");
    p.set("types", s.node_types.join(","));
    p.set("analysis", s.purchase_scope.analysis_date);
    if (s.purchase_scope.start_date) p.set("start", s.purchase_scope.start_date);
    if (s.purchase_scope.end_date) p.set("end", s.purchase_scope.end_date);
    history.replaceState({
      htmx: true
    }, "", `${location.pathname}?${p}`);
  }
  class GraphController {
    constructor(root) {
      this.root = root;
      this.view = null;
      this.snapshot = null;
      this.cursors = {
        overview_cursor: null,
        relationship_cursors: {},
        timeline_cursor: null
      };
      this.pending = null;
      this.requestId = 0;
      this.disposed = false;
      this.events = new AbortController();
      let initialError = false;
      try {
        this.state = parseURL(root);
      } catch (e) {
        initialError = true;
        this.state = {
          query: "",
          selected_id: null,
          expanded_ids: [],
          mode: "current",
          node_types: [...types],
          purchase_scope: {
            analysis_date: root.dataset.analysisDate || sgToday(),
            start_date: null,
            end_date: null
          }
        };
        this.error(e.message);
      }
      this.canvas = new GraphCanvas(this.q("#graph-canvas"), (id) => this.select(id));
      if (!this.canvas.ready) this.q("#graph-status").textContent = "Graph renderer unavailable. Reload the page to try again.";
      this.review = {
        mode: "pending",
        cursor: null,
        view: null,
        pending: null,
        requestId: 0
      };
      this.choices = new Map();
      this.proposalBase = null;
      this.command = null;
      this.writeBusy = false;
      this.writePending = null;
      root.addEventListener("click", e => this.click(e), {
        signal: this.events.signal
      });
      root.querySelector("#graph-filters")?.addEventListener("submit", e => this.submit(e), {
        signal: this.events.signal
      });
      root.querySelector("#graph-family-form")?.addEventListener("submit", e => this.submitFamily(e), {
        signal: this.events.signal
      });
      root.querySelector("#graph-proposal-form")?.addEventListener("submit", e => this.submitProposal(e), {
        signal: this.events.signal
      });
      root.querySelector("#graph-review-mode")?.addEventListener("change", e => this.loadReviews(e.target.value), {
        signal: this.events.signal
      });
      window.addEventListener("popstate", () => this.reloadFromURL(), {
        signal: this.events.signal
      });
      this.syncForms();
      this.initialError = initialError;
    }
    q(s) {
      return this.root.querySelector(s);
    }
    status(x) {
      const n = this.q("#graph-status");
      if (n) n.textContent = x;
    }
    error(x) {
      const n = this.q("#graph-error");
      if (n) n.textContent = x;
      this.status("Previous view retained. Choose Refresh.");
      this.root.dataset.loadState = "error";
    }
    clearError() {
      const n = this.q("#graph-error");
      if (n) n.textContent = "";
    }
    syncForms() {
      const f = this.q("#graph-filters");
      if (!f) return;
      const set = (n, v) => {
        if (f.elements[n]) f.elements[n].value = v || ""
      };
      set("query", this.state.query);
      set("mode", this.state.mode);
      set("analysis_date", this.state.purchase_scope.analysis_date);
      set("start_date", this.state.purchase_scope.start_date);
      set("end_date", this.state.purchase_scope.end_date);
      f.querySelectorAll("[name=node_types]").forEach(x => x.checked = this.state.node_types.includes(x.value));
    }
    reset() {
      this.cursors = {
        overview_cursor: null,
        relationship_cursors: {},
        timeline_cursor: null
      };
    }
    reloadFromURL() {
      if (location.pathname !== "/graph") return this.dispose();
      try {
        this.state = parseURL(this.root);
        this.snapshot = null;
        this.reset();
        this.syncForms();
        this.loadView();
      } catch (e) {
        this.error(e.message);
      }
    }
    submit(e) {
      e.preventDefault();
      const f = e.currentTarget,
        nt = [...f.querySelectorAll("[name=node_types]:checked")].map(x => x.value);
      if (!nt.length) return this.error("Choose at least one node type.");
      const s = {
        query: f.elements.query?.value || "",
        selected_id: this.state.selected_id,
        expanded_ids: this.state.expanded_ids,
        mode: f.elements.mode?.value === "history" ? "history" : "current",
        node_types: nt,
        purchase_scope: {
          analysis_date: f.elements.analysis_date?.value || this.state.purchase_scope.analysis_date,
          start_date: f.elements.start_date?.value || null,
          end_date: f.elements.end_date?.value || null
        }
      };
      if (!validDate(s.purchase_scope.analysis_date) || !validDate(s.purchase_scope.start_date) || !validDate(s.purchase_scope.end_date)) return this.error("Use YYYY-MM-DD dates.");
      this.state = s;
      this.reset();
      writeURL(s);
      this.loadView();
    }
    click(e) {
      const b = e.target.closest?.("[data-graph-action]");
      if (!b || !this.root.contains(b)) return;
      const a = b.dataset.graphAction,
        id = b.dataset.nodeId;
      if (a === "select" && id) return this.select(id);
      if (a === "clear-product-focus") return this.clearProductFocus();
      if (a === "expand" && id) return this.expand(id);
      if (a === "collapse" && id) return this.collapse(id);
      if (a === "refresh") return this.refresh();
      if (a === "zoom-in") return this.canvas.zoom(1.1);
      if (a === "zoom-out") return this.canvas.zoom(.9);
      if (a === "fit") return this.canvas.fit();
      if (a === "focus") return this.canvas.focusSelected();
      if (a === "reset") return this.canvas.reset();
      if (a === "reviews") return this.loadReviews(this.q("#graph-review-mode")?.value || "pending");
      if (a === "reviews-next") {
        if (!this.review.cursor) return;
        return this.loadReviews(this.review.mode, this.review.cursor);
      }
      if (a === "overview-next") {
        const cursor = this.view?.page?.overview?.cursor;
        if (!cursor) return;
        this.cursors.overview_cursor = cursor;
      }
      if (a === "timeline-next") {
        const cursor = this.view?.page?.timeline?.cursor;
        if (!cursor) return;
        this.cursors.timeline_cursor = cursor;
      }
      if (a === "relationship-next" && b.dataset.rootId) {
        const cursor = this.view?.page?.relationships?.[b.dataset.rootId]?.cursor;
        if (!cursor) return;
        this.cursors.relationship_cursors[b.dataset.rootId] = cursor;
      }
      if (["overview-next", "timeline-next", "relationship-next"].includes(a)) this.loadView();
    }
    mutationStatus(message) {
      this.q('#graph-mutation-status').textContent = message;
    }
    rememberChoice(type, id, label) {
      const key = `${type}:${id}`;
      this.choices.delete(key);
      this.choices.set(key, {
        type,
        id,
        label
      });
      while (this.choices.size > 200) this.choices.delete(this.choices.keys().next().value);
    }
    updateChoices(view = this.view) {
      const form = this.q('#graph-proposal-form');
      for (const node of [...(view?.nodes || []), view?.selection?.node].filter(Boolean)) {
        if (['product', 'family'].includes(node.type)) this.rememberChoice(node.type, node.record.row_id, node.label);
      }
      for (const type of ['product', 'family']) {
        const select = form.elements[`${type}_id`];
        const previous = select.value;
        const old = select.selectedOptions[0];
        if (previous && old) this.rememberChoice(type, Number(previous), old.textContent);
        select.replaceChildren(new Option(`Choose a ${type}`, ''));
        for (const entry of this.choices.values()) {
          if (entry.type === type) select.add(new Option(entry.label, String(entry.id)));
        }
        select.value = previous;
      }
    }
    async loadReviews(mode, cursor = null) {
      const rid = ++this.review.requestId;
      this.review.pending?.abort();
      this.review.pending = new AbortController();
      this.review.mode = mode;
      const params = new URLSearchParams({
        mode,
        limit: '25'
      });
      if (cursor) params.set('cursor', cursor);
      const status = this.q('#graph-review-status');
      status.textContent = 'Loading reviews…';
      try {
        const response = await fetch(`/graph/reviews?${params}`, {
          credentials: 'same-origin',
          cache: 'no-store',
          signal: this.review.pending.signal
        });
        const body = await response.json();
        if (this.disposed || !this.root.isConnected || rid !== this.review.requestId) return false;
        if (!response.ok) throw Error(response.status === 409 ? 'Reviews changed. Load reviews again.' : 'Reviews could not be loaded. Try Load reviews.');
        this.review.view = body;
        this.review.cursor = body.page.cursor;
        this.renderReviews(body);
        status.textContent = `${body.entries.length} ${mode} review records shown${body.page.has_more ? '; more available' : ''}.`;
        return true;
      } catch (error) {
        if (error.name !== 'AbortError' && !this.disposed && this.root.isConnected && rid === this.review.requestId) status.textContent = error.message;
        return false;
      }
    }
    renderReviews(view) {
      const target = this.q('#graph-review-list');
      target.replaceChildren();
      if (!view.entries.length) {
        const empty = document.createElement('p');
        empty.textContent = 'No review records in this view. Propose a membership below to begin.';
        target.append(empty);
      }
      const dataset = view.snapshot.dataset_id;
      const selectButton = (type, id, label) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.graphAction = 'select';
        button.dataset.nodeId = `${dataset}:${type}:${id}`;
        button.textContent = label;
        return button;
      };
      for (const entry of view.entries) {
        this.rememberChoice('product', entry.product_id, entry.product_name);
        this.rememberChoice('family', entry.family_id, entry.family_name);
        const row = document.createElement('article');
        row.className = 'graph-review-entry';
        row.dataset.membershipId = String(entry.id);
        row.dataset.reviewState = entry.state;
        const heading = document.createElement('h3');
        heading.textContent = `${entry.state} · ${entry.is_current ? 'current' : 'historical'} · version ${entry.version}`;
        const details = document.createElement('p');
        details.textContent = `Origin: ${entry.origin}. Method: ${entry.method}. Rationale: ${entry.rationale}. Proposal ${entry.proposal_event_id}; event ${entry.event_id}. ${entry.review_reason ? `Review: ${entry.review_reason}` : ''}`;
        row.append(heading, selectButton('product', entry.product_id, entry.product_name), document.createTextNode(' → '), selectButton('family', entry.family_id, entry.family_name), details);
        for (const ref of entry.support_refs) {
          row.append(types.has(ref.entity_type) ? selectButton(ref.entity_type, ref.row_id, `${ref.entity_type} ${ref.row_id}`) : document.createTextNode(`Membership evidence ${ref.row_id}`));
        }
        if (entry.actions.length) {
          const label = document.createElement('label');
          label.textContent = 'Review reason';
          const reason = document.createElement('textarea');
          reason.maxLength = 2000;
          reason.required = true;
          label.append(reason);
          row.append(label);
          for (const decision of entry.actions) {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.graphWrite = 'review';
            button.dataset.reviewAction = decision;
            button.textContent = {
              accepted: 'Accept',
              rejected: 'Reject',
              withdrawn: 'Withdraw'
            } [decision];
            button.disabled = this.writeBusy;
            button.addEventListener('click', () => {
              if (!reason.reportValidity() || !reason.value.trim()) return;
              this.mutate(`/graph/memberships/${entry.id}/review`, {
                proposal_event_id: entry.proposal_event_id,
                expected_version: entry.version,
                decision,
                reason: reason.value
              }, () => {});
            });
            row.append(button);
          }
        }
        if (entry.is_current && ['rejected', 'withdrawn'].includes(entry.state)) {
          const propose = document.createElement('button');
          propose.type = 'button';
          propose.textContent = 'Prepare new proposal';
          propose.addEventListener('click', () => {
            const form = this.q('#graph-proposal-form');
            this.rememberChoice('product', entry.product_id, entry.product_name);
            this.rememberChoice('family', entry.family_id, entry.family_name);
            this.updateChoices();
            form.elements.product_id.value = String(entry.product_id);
            form.elements.family_id.value = String(entry.family_id);
            this.proposalBase = {
              product: String(entry.product_id),
              family: String(entry.family_id),
              version: entry.version
            };
            form.elements.rationale.focus();
            this.mutationStatus('Write a new rationale, then propose. This does not accept membership.');
          });
          row.append(propose);
        }
        target.append(row);
      }
      this.updateChoices();
      this.q('[data-graph-action="reviews-next"]').disabled = !view.page.cursor;
    }
    submitFamily(event) {
      event.preventDefault();
      const form = event.currentTarget;
      if (!form.reportValidity()) return;
      this.mutate('/graph/families', {
        name: form.elements.name.value,
        definition: form.elements.definition.value
      }, result => {
        form.reset();
        this.rememberChoice('family', result.id, result.name);
        this.updateChoices();
        this.q('#graph-proposal-form').elements.family_id.value = String(result.id);
        if (this.snapshot) this.state.selected_id = `${this.snapshot.dataset_id}:family:${result.id}`;
        writeURL(this.state);
      });
    }
    submitProposal(event) {
      event.preventDefault();
      const form = event.currentTarget;
      if (!form.reportValidity()) return;
      const product = form.elements.product_id.value,
        family = form.elements.family_id.value;
      const version = this.proposalBase?.product === product && this.proposalBase?.family === family ? this.proposalBase.version : 0;
      this.mutate('/graph/memberships', {
        product_id: Number(product),
        family_id: Number(family),
        expected_version: version,
        origin: form.elements.origin.value,
        method: form.elements.method.value,
        rationale: form.elements.rationale.value,
        support_refs: [{
          entity_type: 'product',
          row_id: Number(product)
        }, {
          entity_type: 'family',
          row_id: Number(family)
        }]
      }, () => {
        form.elements.rationale.value = '';
        this.proposalBase = null;
        this.review.mode = 'pending';
        this.q('#graph-review-mode').value = 'pending';
      });
    }
    async mutate(url, values, onSaved) {
      if (this.writeBusy || this.disposed) return;
      const key = JSON.stringify([url, values]);
      if (this.command?.key !== key) this.command = {
        key,
        id: crypto.randomUUID().replaceAll('-', '')
      };
      const body = JSON.stringify({
        ...values,
        command_id: this.command.id
      });
      this.writeBusy = true;
      this.writePending = new AbortController();
      const controls = [...this.root.querySelectorAll('#graph-family-form button, #graph-proposal-form button, [data-graph-write]')];
      controls.forEach(control => control.disabled = true);
      this.mutationStatus('Saving…');
      try {
        const tokenResponse = await fetch('/graph/token', {
          credentials: 'same-origin',
          cache: 'no-store',
          signal: this.writePending.signal,
          headers: {
            'X-Graph-Page': '1'
          }
        });
        if (!tokenResponse.ok) throw Error('Write authorization could not be refreshed. Try again.');
        const {
          token
        } = await tokenResponse.json();
        const response = await fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
          signal: this.writePending.signal,
          headers: {
            'Content-Type': 'application/json',
            'X-Graph-Token': token
          },
          body
        });
        const result = await response.json();
        if (this.disposed || !this.root.isConnected) return;
        if (!response.ok) {
          if (response.status === 409) {
            this.mutationStatus('This membership or command changed. Load Current reviews and inspect the latest decision before retrying; use Prepare new proposal for a rejected or withdrawn membership.');
            return;
          }
          throw Error(response.status === 400 ? 'Check the form values and try again.' : 'Save could not be confirmed. Retry unchanged values to safely reuse this request.');
        }
        this.command = null;
        onSaved(result);
        this.snapshot = null;
        this.reset();
        ++this.review.requestId;
        this.review.pending?.abort();
        const updated = await this.loadView();
        await this.loadReviews(this.review.mode);
        if (!this.disposed && this.root.isConnected) this.mutationStatus(updated ? 'Saved. The graph and timeline show the latest state.' : 'Saved. The displayed graph is stale; choose Refresh to see the latest state.');
      } catch (error) {
        if (error.name !== 'AbortError' && !this.disposed && this.root.isConnected) this.mutationStatus(error.message || 'Save could not be confirmed. Retry unchanged values safely.');
      } finally {
        this.writeBusy = false;
        if (!this.disposed) this.root.querySelectorAll('#graph-family-form button, #graph-proposal-form button, [data-graph-write]').forEach(control => control.disabled = false);
      }
    }
    select(id) {
      if (!validId(id)) return this.error("Invalid node selection.");
      this.state.selected_id = id;
      const type = id.split(":")[1];
      if (type === "product") {
        this.state.expanded_ids = [id];
        this.cursors.relationship_cursors = {};
        this.reset();
      } else {
        this.cursors.timeline_cursor = null;
      }
      writeURL(this.state);
      this.loadView();
    }
    clearProductFocus() {
      this.state.selected_id = null;
      this.state.expanded_ids = [];
      this.reset();
      writeURL(this.state);
      this.loadView();
    }
    expand(id) {
      if (!validId(id)) return this.error("Invalid node expansion.");
      if (!this.state.expanded_ids.includes(id)) {
        if (this.state.expanded_ids.length >= 12) return this.error("Too many expanded nodes.");
        this.state.expanded_ids = [...this.state.expanded_ids, id];
      }
      this.reset();
      writeURL(this.state);
      this.loadView();
    }
    collapse(id) {
      this.state.expanded_ids = this.state.expanded_ids.filter(x => x !== id);
      delete this.cursors.relationship_cursors[id];
      writeURL(this.state);
      this.loadView();
    }
    refresh() {
      this.snapshot = null;
      this.reset();
      this.review.cursor = null;
      this.loadReviews(this.review.mode);
      this.state.purchase_scope.analysis_date = sgToday();
      this.syncForms();
      writeURL(this.state);
      this.loadView();
    }
    async loadView() {
      const rid = ++this.requestId;
      this.pending?.abort();
      this.pending = new AbortController();
      this.status("Loading…");
      this.root.dataset.loadState = "loading";
      const p = new URLSearchParams({
        request: JSON.stringify({
          ...this.state,
          ...this.cursors
        })
      });
      if (this.snapshot) p.set("snapshot", JSON.stringify(this.snapshot));
      try {
        const r = await fetch(`/graph/view?${p}`, {
          credentials: "same-origin",
          cache: "no-store",
          signal: this.pending.signal
        });
        let body;
        try {
          body = await r.json();
        } catch (_) {
          throw Error("Graph returned invalid JSON.");
        }
        if (!this.root.isConnected || this.disposed || rid !== this.requestId) return false;
        if (!r.ok) {
          this.error(r.status === 409 ? "This view is stale. Choose Refresh." : (body.message || "Graph could not be loaded."));
          return false;
        }
        this.view = body;
        this.snapshot = body.snapshot || null;
        this.clearError();
        this.renderView(body);
        this.root.dataset.loadState = "ready";
        this.status(this.canvas.ready ? "Ready" : "Graph renderer unavailable; use the accessible node list below.");
        return true;
      } catch (e) {
        if (e.name !== "AbortError" && this.root.isConnected && !this.disposed && rid === this.requestId) this.error(e.message || "Graph could not be loaded. Choose Refresh.");
        return false;
      }
    }
    renderView(v) {
      this.renderCanvas(v);
      const counts = this.q("#graph-counts");
      if (counts) {
        const reasons = v.coverage?.reasons || [];
        const scope = v.scope || this.state.purchase_scope;
        const labels = { overview_limit: "More records available", relationship_limit: "More relationships available", timeline_limit: "More timeline records available" };
        const readableReasons = reasons.map(reason => labels[reason] || "Additional records available");
        counts.textContent = `${v.nodes.length} nodes · ${v.edges.length} edges · ${v.build_metadata?.mode || this.state.mode} · Singapore ${scope.analysis_date} · ${scope.start_date||"all"} to ${scope.end_date||"all"}${v.coverage?.partial?" · partial":""}${readableReasons.length?` · ${readableReasons.join(", ")}`:""}`;
      }
      const next = this.q('[data-graph-action="overview-next"]');
      if (next) next.disabled = !v.page?.overview?.cursor;
      this.renderDetails(v);
      this.renderTimeline(v);
      this.renderList(v);
      this.updateChoices(v);
    }
    renderCanvas(v) {
      this.canvas.render(v);
    }
    renderDetails(v) {
      const n = this.q("#graph-inspector");
      const timeline = this.q("#graph-timeline");
      if (!n) return;
      n.textContent = "";
      if (timeline) timeline.textContent = "";
      const selection = v.selection;
      if (!selection) {
        const heading = document.createElement("h2");
        heading.textContent = "Explore the graph";
        n.append(heading);
        const guidance = document.createElement("p");
        guidance.textContent = "Select a product to see its purchase frequency and dated orders. Use Explore connections for deeper evidence.";
        n.append(guidance);
        return;
      }
      const node = selection.node || {};
      const details = selection.details || {};
      const heading = document.createElement("h2");
      heading.textContent = String(node.label || details.canonical_name || "Selected node");
      n.append(heading);
      const kind = document.createElement("p");
      kind.textContent = String(node.type || selection.record?.entity_type || "Record");
      n.append(kind);
      if (node.type === "product" && Number.isFinite(Number(node.attributes?.purchase_count))) {
        const frequency = document.createElement("p");
        frequency.className = "graph-purchase-count";
        frequency.textContent = `${node.attributes.purchase_count} qualifying orders`;
        n.append(frequency);
        const back = document.createElement("button");
        back.type = "button";
        back.dataset.graphAction = "clear-product-focus";
        back.textContent = "All products";
        n.append(back);
      }
      const expand = document.createElement("button");
      expand.type = "button";
      expand.dataset.graphAction = this.state.expanded_ids.includes(node.id) ? "collapse" : "expand";
      expand.dataset.nodeId = node.id || "";
      expand.textContent = this.state.expanded_ids.includes(node.id) ? "Collapse connections" : "Explore connections";
      n.append(expand);
      const humanize = (key) => key.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
      const summary = document.createElement("p");
      summary.className = "graph-summary";
      if (node.type === "product") summary.textContent = `${details.variant || "Variant not recorded"}${details.package_quantity ? ` · ${details.package_quantity} ${details.package_unit || ""}` : ""} · ${details.unassigned ? "No family assigned" : "Family assigned"}${details.identity_status ? ` · Identity ${details.identity_status}` : ""}`;
      else if (node.type === "family") summary.textContent = String(details.definition || "Product family");
      else if (node.type === "order") summary.textContent = `${details.status || "Order"}${details.total_cents != null ? ` · ${details.total_cents} cents` : ""}`;
      else summary.textContent = String(details.name || details.canonical_name || node.type);
      n.append(summary);
      const dl = document.createElement("dl");
      for (const [key, value] of Object.entries(details)) {
        const row = document.createElement("div");
        row.className = "graph-metadata";
        const term = document.createElement("dt");
        term.textContent = humanize(key);
        const description = document.createElement("dd");
        let shown = value == null ? "Unknown" : Array.isArray(value) || typeof value === "object" ? JSON.stringify(value) : String(value);
        if (key.endsWith("_cents") && typeof value === "number") shown = `${value} cents`;
        description.textContent = shown;
        if ((key === "identity_status" && value === "provisional") || (key === "unassigned" && value === true)) row.dataset.highlight = "true";
        row.append(term, description);
        dl.append(row);
      }
      const raw = document.createElement("details");
      raw.className = "graph-metadata";
      const rawSummary = document.createElement("summary");
      rawSummary.textContent = "Record details";
      raw.append(rawSummary, dl);
      n.append(raw);
      if (node.local_url && /^\/(products|orders)\/[1-9][0-9]*$/.test(node.local_url)) {
        const link = document.createElement("a");
        link.href = node.local_url;
        link.textContent = node.type === "product" ? "View product history" : "View order";
        n.append(link);
      }
      for (const membership of selection.memberships || []) {
        const row = document.createElement("div");
        const product = document.createElement("button");
        product.type = "button";
        product.dataset.graphAction = "select";
        product.dataset.nodeId = `${node.id?.split(":")[0]||""}:product:${membership.product_id}`;
        product.textContent = `Product ${membership.product_id}`;
        row.append(product, document.createTextNode(` ${membership.origin||""} ${membership.method||""} ${membership.rationale||""} event ${membership.event_id} proposal ${membership.proposal_event_id}`));
        for (const ref of membership.support_refs || []) {
          if (!["order", "revision", "item", "listing", "product", "family", "retailer", "source"].includes(ref.entity_type)) continue;
          const support = document.createElement("button");
          support.type = "button";
          support.dataset.graphAction = "select";
          support.dataset.nodeId = `${node.id?.split(":")[0]||""}:${ref.entity_type}:${ref.row_id}`;
          support.textContent = `${ref.entity_type} ${ref.row_id}`;
          row.append(document.createTextNode(" "), support);
        }
        n.append(row);
      }
      if (details.has_more_memberships) {
        const more = document.createElement("p");
        more.textContent = "Showing the first 500 family memberships; analytical timeline completeness is separate.";
        n.append(more);
      }
      if (timeline && node.type !== "product" && node.type !== "family") timeline.textContent = "";
    }
    renderTimeline(v) {
      const n = this.q("#graph-timeline");
      if (!n) return;
      n.textContent = "";
      const node = v.selection?.node;
      const timeline = v.selection?.timeline;
      const heading = document.createElement("h2");
      heading.textContent = "Scheduled delivery · Singapore";
      n.append(heading);
      if (!node || !["product", "family"].includes(node.type)) {
        const message = document.createElement("p");
        message.textContent = "Timeline is available for products and families.";
        n.append(message);
        return;
      }
      const scope = document.createElement("p");
      scope.textContent = `Analysis date ${this.state.purchase_scope.analysis_date}; period ${this.state.purchase_scope.start_date||"all"} to ${this.state.purchase_scope.end_date||"all"}. Current placed/completed records with known dates are shown.`;
      n.append(scope);
      if (!timeline || !timeline.summary) {
        const unavailable = document.createElement("p");
        unavailable.textContent = "Timeline unavailable for this scope; narrow the dates or reduce the selected family.";
        n.append(unavailable);
        return;
      }
      const summary = timeline.summary;
      const summaryText = document.createElement("p");
      summaryText.textContent = `${summary.order_count} orders across ${summary.purchase_day_count} purchase days`;
      summaryText.dataset.graphOrderCount = String(summary.order_count);
      summaryText.dataset.graphDayCount = String(summary.purchase_day_count);
      n.append(summaryText);
      const dates = document.createElement("p");
      dates.textContent = `Purchase dates: ${summary.purchase_dates.map(String).join(", ")||"None"}; gaps: ${summary.gaps_days.join(", ")||"None"} days`;
      n.append(dates);
      const coverage = timeline.coverage;
      const coverageText = document.createElement("p");
      coverageText.textContent = coverage.counts_complete ? `Eligible ${coverage.eligible_order_count}; excluded ${coverage.excluded_order_count}; missing date ${coverage.missing_date_count}; upcoming ${coverage.upcoming_order_count}; outside range ${coverage.outside_range_count}.` : `Coverage counts unavailable${coverage.reason?`: ${coverage.reason}`:"."}`;
      n.append(coverageText);
      const list = document.createElement("div");
      const label = document.createElement("p");
      label.textContent = `Quantities in these displayed occurrences (${timeline.occurrences.length})`;
      list.append(label);
      const buttonFor = (type, id) => {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.graphAction = "select";
        button.dataset.nodeId = `${node.id.split(":")[0]}:${type}:${id}`;
        button.textContent = `${type} ${id}`;
        return button;
      };
      for (const occurrence of timeline.occurrences) {
        const row = document.createElement("div");
        row.className = "graph-occurrence";
        const date = document.createElement("p");
        date.textContent = String(occurrence.purchase_date);
        row.append(date);
        const order = document.createElement("a");
        order.href = `/orders/${occurrence.order_id}`;
        order.textContent = `Open order ${occurrence.order_id}`;
        row.append(order, document.createTextNode(" "));
        for (const [product, unit, quantity] of occurrence.quantities) row.append(document.createTextNode(`${quantity} ${unit} · Product #${product} `));
        const evidence = document.createElement("details");
        const evidenceSummary = document.createElement("summary");
        evidenceSummary.textContent = "Purchase evidence";
        evidence.append(evidenceSummary);
        for (const [type, ids] of [
            ["order", [occurrence.order_id]],
            ["revision", [occurrence.revision_id]],
            ["item", occurrence.item_ids],
            ["listing", occurrence.listing_ids],
            ["product", occurrence.product_ids],
            ["source", occurrence.source_ids]
          ])
          for (const id of ids) evidence.append(buttonFor(type, id), document.createTextNode(" "));
        evidence.append(document.createTextNode(`Membership events: ${occurrence.membership_event_ids.join(", ")||"none"}`));
        row.append(evidence);
        list.append(row);
      }
      n.append(list);
      if (timeline.page?.has_more) {
        const next = document.createElement("button");
        next.type = "button";
        next.dataset.graphAction = "timeline-next";
        next.textContent = `Next occurrences (${timeline.occurrences.length} shown)`;
        n.append(next);
      }
    }
    renderList(v) {
      const n = this.q("#graph-relationships");
      if (!n) return;
      n.textContent = "";
      const nodes = new Map(v.nodes.map((node) => [node.id, node]));
      const phrases = {
        HAS_REVISION: "Has revision",
        CURRENT_REVISION: "Current revision",
        ORDERED_FROM: "Ordered from",
        HAS_ITEM: "Has item",
        REFERS_TO_LISTING: "Refers to listing",
        LISTED_BY: "Listed by",
        MAPS_TO_PRODUCT: "Maps to product",
        MEMBER_OF: "Member of",
        SUPPORTED_BY: "Supported by",
      };
      const selected = v.selection?.node?.id;
      const visible = v.nodes;
      if (!visible.length) {
        const empty = document.createElement("p");
        empty.textContent = "No matching nodes. Clear filters or create a family to begin.";
        n.append(empty);
      } else
        for (const node of visible) {
          const item = document.createElement("div");
          item.setAttribute("role", "listitem");
          const select = document.createElement("button");
          select.type = "button";
          select.dataset.graphAction = "select";
          select.dataset.nodeId = node.id;
          select.setAttribute("aria-pressed", String(node.id === selected));
          select.textContent = `${node.type}: ${String(node.label??"")}`;
          item.append(select);
          const expand = document.createElement("button");
          expand.type = "button";
          expand.dataset.graphAction = this.state.expanded_ids.includes(node.id) ? "collapse" : "expand";
          expand.dataset.nodeId = node.id;
          expand.textContent = this.state.expanded_ids.includes(node.id) ? "Collapse connections" : "Explore connections";
          item.append(expand);
          n.append(item);
        }
      if (selected) {
        const incident = v.edges.filter((edge) => edge.source === selected || edge.target === selected);
        const heading = document.createElement("p");
        heading.textContent = "Selected node relationships";
        n.append(heading);
        for (const edge of incident) {
          const row = document.createElement("div");
          const source = nodes.get(edge.source);
          const target = nodes.get(edge.target);
          const phrase = phrases[edge.type] || edge.type;
          const state = edge.state === "inactive" ? " (Historical inactive)" : "";
          const button = (node) => {
            if (!node) return document.createTextNode("Unavailable endpoint");
            const result = document.createElement("button");
            result.type = "button";
            result.dataset.graphAction = "select";
            result.dataset.nodeId = node.id;
            result.textContent = `${node.type}: ${String(node.label??"")}`;
            return result;
          };
          row.append(button(source), document.createTextNode(` → ${phrase}${state} → `), button(target));
          n.append(row);
        }
      }
      const roots = v.page?.relationships || {};
      for (const [rootId, page] of Object.entries(roots)) {
        const heading = document.createElement("p");
        heading.textContent = `Relationships for ${nodes.get(rootId)?.label||rootId}`;
        n.append(heading);
        if (page.has_more) {
          const reason = document.createElement("p");
          reason.textContent = page.reason || "More relationships are available.";
          n.append(reason);
          if (page.cursor) {
            const next = document.createElement("button");
            next.type = "button";
            next.dataset.graphAction = "relationship-next";
            next.dataset.rootId = rootId;
            next.textContent = "Next relationships";
            n.append(next);
          } else {
            const capped = document.createElement("p");
            capped.textContent = "Relationship display is capped; collapse or narrow the view to continue.";
            n.append(capped);
          }
        }
      }
    }
    dispose() {
      if (this.disposed) return;
      this.disposed = true;
      ++this.requestId;
      ++this.review.requestId;
      this.pending?.abort();
      this.review.pending?.abort();
      this.writePending?.abort();
      this.canvas.dispose();
      this.events.abort();
      active.delete(this);
      roots.delete(this.root);
    }
  }

  function mount(root) {
    if (!roots.has(root)) {
      const c = new GraphController(root);
      roots.set(root, c);
      active.add(c);
      if (!c.initialError) {
        c.loadView();
        c.loadReviews("pending");
      }
    }
  }

  function scan() {
    document.querySelectorAll("#shopping-graph").forEach(mount);
    active.forEach(c => {
      if (!c.root.isConnected) c.dispose();
    });
  }
  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true
  });
  document.addEventListener("DOMContentLoaded", scan, {
    once: true
  });
  document.addEventListener("htmx:afterSwap", scan);
  document.addEventListener("htmx:historyRestore", scan);
  document.addEventListener("htmx:beforeCleanupElement", e => {
    const elt = e.detail?.elt || e.target;
    active.forEach(c => {
      if (elt === c.root || elt.contains?.(c.root)) c.dispose();
    });
  });
  scan();
})();
