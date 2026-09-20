# Knowledge graph representation options

Date: 20 September 2026

Status: Research recommendation for discussion, not an accepted design or
implementation authorization. Four primary documentation sources were checked.
No dependencies, migrations, private data, or deployment operations were used.

**Recommendation:** define an application-owned logical property graph over the
existing authoritative SQLite facts, then produce a reproducible graph snapshot.
Keep NetworkX optional until a concrete graph algorithm benefits from it. This
fits the [existing roadmap](../../../docs/MVP_PLAN.md): graph tables and Graphify
remain planned, derived projections; SQLite remains authoritative.

## Representation choices

| Choice | Representation | Fit and tradeoff |
| --- | --- | --- |
| Logical property graph | Stable node IDs, node types, directed edges with IDs and predicates, properties on both | Recommended for application-owned shopping relationships and evidence. The application must define and validate the vocabulary. |
| RDF 1.1 | A set of subject–predicate–object triples; predicates use IRIs | A standardized interchange model. It introduces identifier/vocabulary choices that this app does not yet need. |
| Existing relational facts | Entity rows plus foreign keys and association rows; graph relationships projected by queries | Recommended authoritative storage. A graph view does not require moving facts into a graph database. |

The property-graph row describes our proposed logical contract. NetworkX's
`MultiDiGraph` is one compatible representation: nodes and edges carry attribute
dictionaries, edges are directed, and multiple edges can connect the same nodes.
Edge keys distinguish those relationships. A `type` or `predicate` attribute
would be our convention, not built-in domain schema enforcement.
[NetworkX MultiDiGraph](https://networkx.org/documentation/stable/reference/classes/multidigraph.html).

RDF 1.1 defines subjects as IRIs or blank nodes, predicates as IRIs, and objects
as IRIs, blank nodes, or literals. Because a graph is a set of triples, repeating
the same triple does not identify another purchase occurrence. Purchase events
or evidence therefore need explicit modeling. This observation is an inference
from the model, not a limitation on RDF's ability to represent this domain.
RDF datasets can keep multiple graphs distinct. This comparison uses the RDF 1.1
specification as an established baseline, not a claim about the newest RDF work.
[W3C RDF 1.1 Concepts](https://www.w3.org/TR/rdf11-concepts/).

## Queries and export

SQLite documents recursive CTE traversal over graph edges stored in tables,
including both directions and indexes for endpoint lookup. Its examples also
derive parent relationships from ordinary relational columns. `UNION` can avoid
cycles when the recursive rows identify already-visited nodes; adding depth or
path fields changes row identity, so cycle handling must be designed explicitly.
A recursive `LIMIT` bounds admitted rows, and explicit ordering is needed when
traversal order matters. These facilities support bounded neighborhood queries;
they do not establish performance for this application's dataset.
[SQLite WITH and graph examples](https://www.sqlite.org/lang_with.html).

NetworkX's node-link serializer preserves graph, node, and edge attributes and
multigraph edge keys in JSON-oriented output. Attribute keys become strings;
the reader and writer must agree on structural field names. A versioned,
application-owned snapshot can use equivalent node/edge records without a
NetworkX runtime dependency. That last point is our implementation recommendation,
not a NetworkX guarantee. If NetworkX is later adopted, test a round trip and
validate reserved structural names and JSON-compatible values.
[NetworkX node_link_data](https://networkx.org/documentation/stable/reference/readwrite/generated/networkx.readwrite.json_graph.node_link_data.html).

## Proposed initial contract

The following are design recommendations, pending agreement on the actual schema
mapping and use cases:

1. Define node types, predicates, direction, cardinality, and stable identity
   rules before adding more Chat tools. Preserve purchase-line and revision
   identity rather than reducing repeated purchases to one product–order edge.
2. Distinguish recorded facts, deterministic derived relationships, and uncertain
   matches. Attach source-record/revision references and derivation versions.
   A confidence number must not imply that a receipt fact was authenticated.
3. Keep historical facts accessible and make the current-revision selection
   explicit. Repeated wrappers should add evidence, not invent purchases;
   later source events must retain their separate history.
4. Build from a consistent, bounded SQLite read. Use namespaced IDs, stable edge
   keys, sorted records, integer cents, and the existing timestamp conventions.
   Include projection version and input-selection metadata. Keep generation
   time outside the reproducibility digest so identical facts and rules yield
   identical content.
5. Start with exact relationships and a small synthetic example. Measure one
   useful neighborhood query before deciding whether to materialize the planned
   graph tables or introduce NetworkX. Keep JSON/Markdown artifacts private,
   derived, and rebuildable; never target Graphify's internal format.

The roadmap's candidate `graph_edges` uniqueness rule omits source-event identity
and its single `source_email_id` cannot itself express multiple supporting
wrappers. Review whether evidence belongs on an edge, in an association, or on
event nodes before adopting that target DDL unchanged. This is a modeling
question, not a migration proposal.

Python 3.14 compatibility, dependency installation, graph-library performance,
and Graphify behavior were not tested. No evidence here warrants adding Neo4j,
RDF tooling, embeddings, or other infrastructure.
