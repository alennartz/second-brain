# Graph exploration on mobile

## Research findings

Graph layout has no single winner. The useful choice depends on the task.

- **Force-directed placement** gives a strong general-purpose baseline for arbitrary graphs. Fruchterman-Reingold is simple, but its all-pairs repulsion costs `O(N²)` per iteration. Stress majorization improves distance fidelity, but costs more and needs careful incremental updates.
- **Layered drawing** from the Sugiyama family works well when edge direction and hierarchy matter. It is less useful for a cyclic knowledge graph unless the view has a clear root or direction.
- **Radial and focus+context drawing** fits local graph exploration. A parent-centered radial layout places descendants around their parent and supports smooth root changes. It can reduce crossings in the spanning tree, but it does not show every non-tree edge without crossings.
- **Multilevel layouts** coarsen a graph, lay out the coarse graph, then refine it. This improves scalability and gives a useful starting position for larger workspaces.
- **Embedding-guided layouts** combine topology with node similarity or community structure. They support discovery, but they need meaningful attributes and are too expensive for a client-only first pass.
- **Incremental layout** matters as much as static quality. New nodes must enter near their visible neighbors, while existing nodes retain their positions. This preserves the user's mental map.

The mobile interaction research points to four constraints. Snyder et al. (EuroVis 2024) recommend ubiquitous input, discoverability, rapid in-context inspection, and graceful recovery. Their formative study also reports fat-finger errors, occlusion, and frustration with complex gestures. Frisch and Dachselt's off-screen node work supports proxies that help users navigate to hidden nodes. Material Design recommends familiar touch-and-hold tooltips and standard pan and zoom behavior.

## Flutter library review

| Library | Useful primitives | Fit for this client |
| --- | --- | --- |
| [graphview](https://pub.dev/packages/graphview) | Tree, layered, radial, circular, balloon, mindmap, animation, `InteractiveViewer`, zoom-to-fit | Strong future candidate. It works best with small graphs. Dragging is an application-level `onPanUpdate` example, not a complete node interaction model. It would require adapting custom edge labels, unloaded endpoints, missing records, and parallel edge identity. MIT licensed. |
| [flutter_force_directed_graph](https://pub.dev/packages/flutter_force_directed_graph) | Force simulation controller, node and edge builders, node drag callbacks, graph pan and zoom | Good primitive package if a force simulation becomes the right strategy. It is newer and has less evidence of long-term stability. BSD-3-Clause licensed. |
| [force_directed_graphview](https://pub.dev/packages/force_directed_graphview) | Customizable Fruchterman-Reingold layout and `InteractiveViewer` navigation | Not sufficient alone because its documentation says nodes cannot be dragged by gesture. MIT licensed. |
| [graphview_plus](https://github.com/AlexHCJP/graphview_plus) | Dependency-free D3-style simulation, collision handling, drag and pinning, reveal animations, headless simulation core | Promising reference implementation. It is a GitHub project rather than the established `graphview` package, so adoption needs a separate evaluation. |

## Decision for the current client

The mobile canvas now uses a hybrid client-side layout. It starts with a focus-centered, graph-distance layout, applies bounded overlap and link relaxation, and preserves prior positions on incremental updates. A dragged node becomes pinned. This avoids a dependency while retaining the existing custom rendering for directed edges, parallel connections, unloaded endpoints, and stale records.

The canvas has a full-screen route, fit and zoom controls, an explicit **Move nodes** mode, visible drag handles, and a long-press drag fallback. The main canvas and full-screen view share positions, so changing views does not reset the user's arrangement.

### Sources

- [Interaction Techniques for Exploratory Data Visualization on Mobile Devices](https://arxiv.org/html/2404.11602)
- [Graph Exploration with Embedding-Guided Layouts](https://arxiv.org/abs/2208.13699)
- [A parent-centered radial layout algorithm for interactive graph visualization and animation](https://arxiv.org/html/cs/0606007)
- [An Incremental Layout Method for Visualizing Online Dynamic Graphs](https://vis.cs.ucdavis.edu/papers/tarik_incremental.pdf)
- [Visualizing offscreen elements of node-link diagrams](https://journals.sagepub.com/doi/10.1177/1473871612473589)
- [Graph Drawing by Stress Majorization](https://graphviz.org/documentation/GKN04.pdf)
- [Material Design data visualization](https://m2.material.io/design/communication/data-visualization.html)
