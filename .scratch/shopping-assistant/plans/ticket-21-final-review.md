# Ticket 21 final review

Historical scope note — 21 September 2026: renderer and line references in this
review describe the earlier native-SVG phase. The current acceptance is the
Cytoscape redesign and resolved tickets 21–23; use the latest execution ledgers
and ticket completion answers for current status.

Baseline: `b5e601863167824941f1f405ec57804cb2e32f15`.
Reviewed the assembled final diff and current implementation, accepted model,
ticket, implementation plan, and correction ledger. Read-only source review;
no private data reads, application writes, or repeated full-suite execution.

## Final status

No outstanding confirmed Critical/Important findings. The sole finding below
was addressed and its correction received a scoped source re-review.

## Resolved Important finding

1. **Make the analytic coverage limitation visible in the Graph UI — resolved.**
   `src/shopping/web/static/graph.js:898-918` presents the scope and complete
   eligible/excluded/missing/upcoming counts, but neither this timeline nor
   `graph_views.py` says these counts cover only successfully parsed purchase
   records. Unparsed archived orders and shopping outside the archive are absent
   from all those counts. The implementation plan explicitly requires
   “parsed-records-only coverage. No invented fulfillment or archive completeness”
   (line 628); the ticket also requires known coverage gaps to remain visible.
   Reproduce by selecting any Product or Family: the rendered scope and coverage
   text contains no warning that absent/unparsed purchases are outside the
   population. Add a visible scope notice explaining those limitations and that
   scheduled delivery does not certify fulfillment. Household-specific failed
   import counts do not need to be disclosed or hardcoded.

   Correction verified: `src/shopping/web/graph_views.py:75-82` renders a
   persistent `graph-coverage-note` immediately after the graph counts. It states
   that counts cover successfully parsed records, unparsed/outside-archive
   purchases are absent, scheduled Singapore delivery is not confirmed
   fulfillment, and quantities retain exact Product/recorded-unit scope without
   package conversion. `tests/web/test_graph_web.py:37` asserts that the notice
   is present in the rendered shell. The changed hunks introduce no confirmed
   Important breakage. This scoped re-review inspected those hunks only; the
   controller reports passing focused web tests and installed-wheel/browser
   verification, which were not repeated here.

## Other review results

No other confirmed Critical/Important finding in the reviewed membership
commands and migration, current-membership timeline calculations, bounded graph
snapshot/projection/continuation reads, protected HTTP routes, or browser
selection/write lifecycle. The deliberate 501-member budget behavior was not
reopened. Prior passing tests and browser checks are controller-reported evidence;
this review does not claim to have rerun them or verified homelab deployment.
