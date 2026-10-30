import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'explore_controller.dart';
import '../persistence/models.dart';
import '../widgets/memory_labels.dart';

/// Keeps graph positions while a graph screen and its full-screen view share a
/// workspace.
///
/// Automatic layout writes positions without notifying listeners. A user move
/// pins the node and notifies every canvas that uses this controller.
final class GraphCanvasController extends ChangeNotifier {
  final Map<String, Offset> _positions = {};
  final Set<String> _pinnedNodeIds = {};

  Map<String, Offset> get positions => Map.unmodifiable(_positions);

  Set<String> get pinnedNodeIds => Set.unmodifiable(_pinnedNodeIds);

  void rememberGenerated(Map<String, Offset> positions) {
    for (final entry in positions.entries) {
      _positions.putIfAbsent(entry.key, () => entry.value);
    }
  }

  void moveNode(String id, Offset position) {
    final next = Offset(
      math.max(16.0, position.dx),
      math.max(16.0, position.dy),
    );
    if (_positions[id] == next && _pinnedNodeIds.contains(id)) return;
    _positions[id] = next;
    _pinnedNodeIds.add(id);
    notifyListeners();
  }

  void reset() {
    if (_positions.isEmpty && _pinnedNodeIds.isEmpty) return;
    _positions.clear();
    _pinnedNodeIds.clear();
    notifyListeners();
  }
}

/// A graph projection rendered with Flutter primitives.
///
/// The canvas keeps edge identity separate from node identity. Parallel and
/// unloaded edges remain individually tappable. [InteractiveViewer] owns pan
/// and zoom while this widget owns placement and node movement.
final class GraphCanvas extends StatefulWidget {
  const GraphCanvas({
    super.key,
    this.state,
    this.controller,
    this.onSelectNode,
    this.onSelectEdge,
    this.onNodeTap,
    this.onEdgeTap,
    this.onNodeSelected,
    this.onEdgeSelected,
    this.height = 360,
    this.focusRevision = 0,
    this.layoutController,
    this.allowNodeDragging = true,
  });

  /// Pass a state projection when the parent owns rebuilds.
  final ExploreWorkspaceState? state;

  /// Passing a controller is convenient for standalone use. The controller's
  /// current projection is read once per build.
  final ExploreWorkspaceController? controller;
  final ValueChanged<String>? onSelectNode;
  final ValueChanged<String>? onSelectEdge;

  /// Compatibility aliases with names commonly used by screen callers.
  final ValueChanged<String>? onNodeTap;
  final ValueChanged<String>? onEdgeTap;
  final ValueChanged<String>? onNodeSelected;
  final ValueChanged<String>? onEdgeSelected;
  final double height;
  final int focusRevision;
  final GraphCanvasController? layoutController;
  final bool allowNodeDragging;

  ExploreWorkspaceState get _state =>
      state ??
      controller?.state ??
      ExploreWorkspaceState(
          status: WorkspaceItemStatus.loaded, nodes: const [], edges: const []);

  @override
  State<GraphCanvas> createState() => _GraphCanvasState();
}

final class _GraphCanvasState extends State<GraphCanvas> {
  _GraphLayout? _layout;
  String? _layoutKey;
  String? _draggingNodeId;
  Offset? _dragStartPosition;
  Offset? _dragStartLocalPosition;
  bool _moveMode = false;

  @override
  void initState() {
    super.initState();
    widget.layoutController?.addListener(_onLayoutControllerChanged);
  }

  @override
  void didUpdateWidget(covariant GraphCanvas oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.layoutController, widget.layoutController)) {
      oldWidget.layoutController?.removeListener(_onLayoutControllerChanged);
      widget.layoutController?.addListener(_onLayoutControllerChanged);
      _layout = null;
      _layoutKey = null;
    }
  }

  @override
  void dispose() {
    widget.layoutController?.removeListener(_onLayoutControllerChanged);
    super.dispose();
  }

  void _onLayoutControllerChanged() {
    if (!mounted) return;
    final layout = _layout;
    final positions = widget.layoutController?.positions;
    if (layout == null || positions == null) {
      setState(() {
        _layout = null;
        _layoutKey = null;
      });
      return;
    }
    if (positions.isEmpty) {
      setState(() {
        _layout = null;
        _layoutKey = null;
      });
      return;
    }
    setState(() => _layout = layout.withPositions(positions));
  }

  ExploreWorkspaceState get _state => widget._state;

  _GraphLayout _ensureLayout(
      ExploreWorkspaceState state, BuildContext context) {
    final key = _layoutKeyFor(state);
    if (_layout == null || key != _layoutKey) {
      final controller = widget.layoutController;
      final seedPositions = controller?.positions ?? _layout?.positions;
      _layout = _GraphLayout.fromState(
        state,
        context,
        seedPositions: seedPositions,
        pinnedNodeIds: controller?.pinnedNodeIds,
      );
      _layoutKey = key;
      controller?.rememberGenerated(_layout!.positions);
    } else {
      _layout = _layout!.updatedFor(state, context);
    }
    return _layout!;
  }

  String _layoutKeyFor(ExploreWorkspaceState state) {
    final nodes = state.nodes.map((item) => item.node.id).toList()..sort();
    final edges = state.edges
        .map((item) => '${item.edge.id}|${item.edge.from}|${item.edge.to}')
        .toList()
      ..sort();
    return '${nodes.join('\u0000')}\u0001${edges.join('\u0000')}';
  }

  @override
  Widget build(BuildContext context) {
    final projection = _state;
    final layout = _ensureLayout(projection, context);
    final width = math.max(720.0, layout.width);
    final boardHeight = math.max(520.0, layout.height);
    final edgeHandler = widget.onSelectEdge ??
        widget.onEdgeTap ??
        widget.onEdgeSelected ??
        _controllerEdgeHandler;
    final nodeHandler = widget.onSelectNode ??
        widget.onNodeTap ??
        widget.onNodeSelected ??
        _controllerNodeHandler;

    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: Container(
        height: widget.height,
        decoration: BoxDecoration(
          border:
              Border.all(color: Theme.of(context).colorScheme.outlineVariant),
          color: Theme.of(context).colorScheme.surfaceContainerLowest,
        ),
        child: _GraphViewport(
          layout: layout,
          selectedNodeId: projection.selectedNodeId,
          focusRevision: widget.focusRevision,
          nodeMoveMode: _moveMode,
          onNodeMoveModeChanged: widget.allowNodeDragging
              ? (enabled) => setState(() => _moveMode = enabled)
              : null,
          child: SizedBox(
            width: width,
            height: boardHeight,
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Positioned.fill(
                  child: CustomPaint(
                    painter: _GraphEdgesPainter(
                      edges: projection.edges,
                      layout: layout,
                      colorScheme: Theme.of(context).colorScheme,
                    ),
                  ),
                ),
                ...projection.edges.asMap().entries.map(
                      (entry) => _edgeAction(
                        context,
                        entry.value,
                        layout,
                        edgeHandler,
                      ),
                    ),
                ..._unloadedEndpoints(context, projection, layout),
                ...projection.nodes.map(
                  (node) => _nodeAction(context, node, layout, nodeHandler),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _controllerNodeHandler(String id) {
    widget.controller?.selectNode(id);
  }

  void _controllerEdgeHandler(String id) {
    // Canvas interaction is intentionally non-blocking. Screens that want to
    // follow an edge provide [onSelectEdge] and await controller.followEdge.
    final target = widget.controller;
    if (target == null) return;
    unawaited(
      target
          .followEdge(id)
          .then<void>((_) {}, onError: (Object _, StackTrace __) {}),
    );
  }

  Iterable<Widget> _unloadedEndpoints(
    BuildContext context,
    ExploreWorkspaceState projection,
    _GraphLayout layout,
  ) {
    final loaded = projection.nodes.map((node) => node.node.id).toSet();
    final ids = <String>{};
    for (final item in projection.edges) {
      if (!loaded.contains(item.edge.from)) ids.add(item.edge.from);
      if (!loaded.contains(item.edge.to)) ids.add(item.edge.to);
    }
    return ids.map((id) {
      final offset = layout.unloadedNodePosition(id);
      return Positioned(
        left: offset.dx,
        top: offset.dy,
        width: 180,
        child: Opacity(
          opacity: .62,
          child: Card(
            margin: EdgeInsets.zero,
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
              side: BorderSide(
                color: Theme.of(context).colorScheme.outline,
                style: BorderStyle.solid,
              ),
            ),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
              child: Row(
                children: [
                  const Icon(Icons.help_outline, size: 18),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      connectedMemoryTitle(null),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    });
  }

  Widget _nodeAction(
    BuildContext context,
    WorkspaceNode item,
    _GraphLayout layout,
    ValueChanged<String>? handler,
  ) {
    final id = item.node.id;
    final offset = layout.nodePosition(id);
    final selected = id == _state.selectedNodeId;
    final missing = item.status == WorkspaceItemStatus.missing;
    final isNew = item.status == WorkspaceItemStatus.newItem;
    final title = memoryTitle(item.node);
    final status = missing
        ? 'Missing'
        : isNew
            ? 'New'
            : null;
    final scheme = Theme.of(context).colorScheme;
    final dragging = _draggingNodeId == id;
    final moveEnabled = widget.allowNodeDragging;
    final directDrag = moveEnabled && _moveMode;
    final holdDrag = moveEnabled && !_moveMode;
    final gestureHint = directDrag
        ? 'Drag to move this memory.'
        : 'Long press, then drag to move this memory.';

    return Positioned(
      left: offset.dx,
      top: offset.dy,
      width: 180,
      child: Semantics(
        label: '$title. $gestureHint',
        button: handler != null,
        child: Listener(
          behavior: HitTestBehavior.opaque,
          onPointerDown: directDrag ? (_) => _startNodeDrag(id) : null,
          onPointerMove:
              directDrag ? (event) => _moveNodeBy(id, event.delta) : null,
          onPointerUp: directDrag ? (_) => _endNodeDrag(id) : null,
          onPointerCancel: directDrag ? (_) => _endNodeDrag(id) : null,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onLongPressStart: holdDrag
                ? (details) => _startNodeDrag(id, details.localPosition)
                : null,
            onLongPressMoveUpdate: holdDrag
                ? (details) => _moveNodeFromLongPress(id, details.localPosition)
                : null,
            onLongPressEnd: holdDrag ? (_) => _endNodeDrag(id) : null,
            onLongPressCancel: holdDrag ? () => _endNodeDrag(id) : null,
            child: Opacity(
              opacity: missing ? .42 : 1,
              child: Card(
                margin: EdgeInsets.zero,
                color: dragging
                    ? scheme.secondaryContainer
                    : selected
                        ? scheme.primaryContainer
                        : scheme.surface,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                  side: BorderSide(
                    color: dragging
                        ? scheme.secondary
                        : selected
                            ? scheme.primary
                            : isNew
                                ? scheme.tertiary
                                : scheme.outlineVariant,
                    width: selected || dragging ? 2 : 1,
                  ),
                ),
                child: InkWell(
                  onTap: handler == null ? null : () => handler(id),
                  borderRadius: BorderRadius.circular(14),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: Text(
                                title,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.titleSmall,
                              ),
                            ),
                            if (moveEnabled)
                              Padding(
                                padding: const EdgeInsets.only(left: 4),
                                child: Icon(
                                  Icons.drag_indicator,
                                  size: 18,
                                  color: scheme.onSurfaceVariant,
                                ),
                              ),
                          ],
                        ),
                        const SizedBox(height: 3),
                        Text(
                          item.expanded
                              ? memoryKind(item.node)
                              : 'Tap to explore',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        if (status != null) ...[
                          const SizedBox(height: 5),
                          Align(
                            alignment: Alignment.centerLeft,
                            child: _StatusChip(label: status),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  void _startNodeDrag(String id, [Offset? localPosition]) {
    final layout = _layout;
    if (layout == null || !layout.positions.containsKey(id)) return;
    _draggingNodeId = id;
    _dragStartPosition = layout.nodePosition(id);
    _dragStartLocalPosition = localPosition ?? Offset.zero;
  }

  void _moveNodeBy(String id, Offset delta) {
    final layout = _layout;
    if (layout == null || _draggingNodeId != id) return;
    _moveNodeTo(id, layout.nodePosition(id) + delta);
  }

  void _moveNodeFromLongPress(String id, Offset localPosition) {
    final start = _dragStartPosition;
    final initial = _dragStartLocalPosition;
    if (start == null || initial == null || _draggingNodeId != id) return;
    _moveNodeTo(id, start + localPosition - initial);
  }

  void _moveNodeTo(String id, Offset position) {
    final layout = _layout;
    if (layout == null || _draggingNodeId != id) return;
    final next = layout.withNodePosition(id, position);
    setState(() => _layout = next);
    widget.layoutController?.moveNode(id, next.nodePosition(id));
  }

  void _endNodeDrag(String id) {
    if (_draggingNodeId != id) return;
    setState(() {
      _draggingNodeId = null;
      _dragStartPosition = null;
      _dragStartLocalPosition = null;
    });
  }

  Widget _edgeAction(
    BuildContext context,
    WorkspaceEdge item,
    _GraphLayout layout,
    ValueChanged<String>? handler,
  ) {
    final rawStart = layout.endpointPosition(item.edge.from);
    final rawEnd = layout.endpointPosition(item.edge.to);
    final curveOffset =
        _curveOffset(rawStart, rawEnd, layout.edgeOffset(item.edge.id));
    final start = rawStart + curveOffset;
    final end = rawEnd + curveOffset;
    final midpoint = Offset(
      (start.dx + end.dx) / 2,
      (start.dy + end.dy) / 2,
    );
    final missing = item.status == WorkspaceItemStatus.missing;
    final isNew = item.status == WorkspaceItemStatus.newItem;
    final label = item.edge.context?.trim().isNotEmpty == true
        ? item.edge.context!.trim()
        : relationshipTitle(item.edge);
    final target = layout.isLoaded(item.edge.to)
        ? memoryTitle(layout.node(item.edge.to)!.node)
        : connectedMemoryTitle(null);
    final edgeLabel =
        '$label → $target${isNew ? ' · New' : ''}${missing ? ' · Missing' : ''}';
    return Positioned(
      left: midpoint.dx - _edgeTargetWidth / 2,
      top: midpoint.dy - _edgeTargetHeight / 2,
      width: _edgeTargetWidth,
      height: _edgeTargetHeight,
      child: Opacity(
        opacity: missing ? .42 : 1,
        child: Tooltip(
          message: edgeLabel,
          excludeFromSemantics: true,
          child: Semantics(
            label: edgeLabel,
            button: true,
            enabled: handler != null && !missing,
            onTap:
                handler == null || missing ? null : () => handler(item.edge.id),
            excludeSemantics: true,
            child: TextButton(
              onPressed: handler == null || missing
                  ? null
                  : () => handler(item.edge.id),
              style: TextButton.styleFrom(
                backgroundColor: Theme.of(context).colorScheme.surface,
                foregroundColor: Theme.of(context).colorScheme.onSurfaceVariant,
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 5),
                minimumSize: const Size(20, 30),
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                shape: const StadiumBorder(),
              ),
              child: Text(
                relationshipTitle(item.edge),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

final class _GraphViewport extends StatefulWidget {
  const _GraphViewport({
    required this.layout,
    required this.selectedNodeId,
    required this.focusRevision,
    required this.nodeMoveMode,
    required this.onNodeMoveModeChanged,
    required this.child,
  });

  final _GraphLayout layout;
  final String? selectedNodeId;
  final int focusRevision;
  final bool nodeMoveMode;
  final ValueChanged<bool>? onNodeMoveModeChanged;
  final Widget child;

  @override
  State<_GraphViewport> createState() => _GraphViewportState();
}

final class _GraphViewportState extends State<_GraphViewport> {
  final _transform = TransformationController();
  Size _viewport = Size.zero;
  bool _viewInitialized = false;

  @override
  void didUpdateWidget(covariant _GraphViewport oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedNodeId != widget.selectedNodeId ||
        oldWidget.focusRevision != widget.focusRevision) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _focusSelected();
      });
    }
  }

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  void _focusSelected() {
    final nodes = widget.layout.nodes;
    if (nodes.isEmpty || _viewport.isEmpty) return;
    final selected = widget.selectedNodeId;
    final id = selected != null && widget.layout.positions.containsKey(selected)
        ? selected
        : widget.layout.positions.keys.first;
    _center(widget.layout.endpointPosition(id),
        _transform.value.getMaxScaleOnAxis().clamp(.6, 1.4).toDouble());
  }

  void _initializeView() {
    if (_viewInitialized || _viewport.isEmpty) return;
    _viewInitialized = true;
    _fit();
  }

  void _center(Offset position, double scale) {
    _transform.value = Matrix4.identity()
      ..translate(_viewport.width / 2 - position.dx * scale,
          _viewport.height / 2 - position.dy * scale)
      ..scale(scale);
  }

  void _zoom(double factor) {
    final center = _transform.toScene(_viewport.center(Offset.zero));
    final scale = (_transform.value.getMaxScaleOnAxis() * factor)
        .clamp(.2, 2.4)
        .toDouble();
    _center(center, scale);
  }

  void _fit() {
    final bounds = widget.layout.bounds;
    if (bounds.isEmpty || _viewport.isEmpty) return;
    final scale = math
        .min(_viewport.width / (bounds.width + 56),
            _viewport.height / (bounds.height + 56))
        .clamp(.2, 2.4)
        .toDouble();
    _center(bounds.center, scale);
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, constraints) {
          final size = constraints.biggest;
          if (size != _viewport) {
            _viewport = size;
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted) _initializeView();
            });
          }
          final scheme = Theme.of(context).colorScheme;
          return Stack(
            children: [
              Positioned.fill(
                child: InteractiveViewer(
                  transformationController: _transform,
                  panEnabled: !widget.nodeMoveMode,
                  scaleEnabled: !widget.nodeMoveMode,
                  minScale: .2,
                  maxScale: 2.4,
                  boundaryMargin: const EdgeInsets.all(1000),
                  constrained: false,
                  child: widget.child,
                ),
              ),
              Positioned(
                right: 12,
                bottom: 12,
                child: Material(
                  color: scheme.surface,
                  elevation: 2,
                  borderRadius: BorderRadius.circular(14),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (widget.onNodeMoveModeChanged != null)
                        IconButton(
                          tooltip: widget.nodeMoveMode
                              ? 'Stop moving nodes'
                              : 'Move nodes',
                          onPressed: () => widget.onNodeMoveModeChanged!
                              .call(!widget.nodeMoveMode),
                          color: widget.nodeMoveMode ? scheme.primary : null,
                          icon: Icon(widget.nodeMoveMode
                              ? Icons.pan_tool
                              : Icons.open_with),
                        ),
                      IconButton(
                          tooltip: 'Zoom in',
                          onPressed: () => _zoom(1.25),
                          icon: const Icon(Icons.add)),
                      IconButton(
                          tooltip: 'Zoom out',
                          onPressed: () => _zoom(.8),
                          icon: const Icon(Icons.remove)),
                      IconButton(
                          tooltip: 'Fit graph',
                          onPressed: _fit,
                          icon: const Icon(Icons.center_focus_strong)),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      );
}

final class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall),
    );
  }
}

final class _GraphLayout {
  _GraphLayout({
    required this.positions,
    required this.edges,
    required this.nodeSizes,
    required this.unloadedSize,
    required this.nodes,
    required this.unloadedPositions,
    required this.edgeOffsets,
    required this.bounds,
  });

  final Map<String, Offset> positions;
  final List<WorkspaceEdge> edges;
  final Map<String, Size> nodeSizes;
  final Size unloadedSize;
  final Map<String, WorkspaceNode> nodes;
  final Map<String, Offset> unloadedPositions;
  final Map<String, double> edgeOffsets;
  final Rect bounds;

  double get width => math.max(720.0, bounds.right + 56);
  double get height => math.max(520.0, bounds.bottom + 56);

  factory _GraphLayout.fromState(
    ExploreWorkspaceState state,
    BuildContext context, {
    Map<String, Offset>? seedPositions,
    Set<String>? pinnedNodeIds,
  }) {
    final measurements = _measureGraph(state, context);
    final ids = measurements.ids;
    final adjacency = _adjacency(state, ids);
    final initial = _initialPositions(
      state,
      ids,
      measurements.sizes,
      measurements.unloadedSize,
      adjacency,
      seedPositions ?? const {},
    );
    final optimized = _optimizePositions(
      ids,
      measurements.sizes,
      measurements.unloadedSize,
      state.edges,
      initial,
      seedPositions ?? const {},
      pinnedNodeIds ?? const {},
    );
    final normalized = _normalizePositions(optimized, ids);
    return _GraphLayout._fromPositions(state, context, normalized);
  }

  factory _GraphLayout._fromPositions(ExploreWorkspaceState state,
      BuildContext context, Map<String, Offset> positions) {
    final measurements = _measureGraph(state, context);
    final current = <String, Offset>{};
    for (final id in measurements.ids) {
      current[id] = positions[id] ?? const Offset(56, 56);
    }
    final unloadedPositions = <String, Offset>{};
    for (final id in measurements.unloadedIds) {
      unloadedPositions[id] = current[id]!;
    }
    final edgeOffsets = _calculateEdgeOffsets(
      state.edges,
      current,
      measurements.sizes,
      measurements.unloadedSize,
    );
    return _GraphLayout(
      positions: Map.unmodifiable(current),
      edges: List.unmodifiable(state.edges),
      nodeSizes: Map.unmodifiable(measurements.sizes),
      unloadedSize: measurements.unloadedSize,
      nodes: Map.unmodifiable({
        for (final item in state.nodes) item.node.id: item,
      }),
      unloadedPositions: Map.unmodifiable(unloadedPositions),
      edgeOffsets: Map.unmodifiable(edgeOffsets),
      bounds:
          _graphBounds(current, measurements.sizes, measurements.unloadedSize),
    );
  }

  _GraphLayout updatedFor(ExploreWorkspaceState state, BuildContext context) =>
      _GraphLayout._fromPositions(state, context, positions);

  _GraphLayout withPositions(Map<String, Offset> updates) {
    final next = <String, Offset>{...positions};
    for (final entry in updates.entries) {
      if (next.containsKey(entry.key)) next[entry.key] = entry.value;
    }
    return _copyWithPositions(next);
  }

  _GraphLayout withNodePosition(String id, Offset position) {
    if (!positions.containsKey(id)) return this;
    final next = <String, Offset>{...positions};
    next[id] = Offset(math.max(16.0, position.dx), math.max(16.0, position.dy));
    return _copyWithPositions(next);
  }

  _GraphLayout _copyWithPositions(Map<String, Offset> next) {
    return _GraphLayout(
      positions: Map.unmodifiable(next),
      edges: edges,
      nodeSizes: nodeSizes,
      unloadedSize: unloadedSize,
      nodes: nodes,
      unloadedPositions: Map.unmodifiable({
        for (final id in unloadedPositions.keys) id: next[id]!,
      }),
      edgeOffsets: Map.unmodifiable(_calculateEdgeOffsets(
        edges,
        next,
        nodeSizes,
        unloadedSize,
      )),
      bounds: _graphBounds(next, nodeSizes, unloadedSize),
    );
  }

  bool isLoaded(String id) => nodes.containsKey(id);

  WorkspaceNode? node(String id) => nodes[id];

  Offset nodePosition(String id) => positions[id] ?? unloadedNodePosition(id);

  Offset unloadedNodePosition(String id) =>
      unloadedPositions[id] ?? const Offset(56, 56);

  Size endpointSize(String id) => nodeSizes[id] ?? unloadedSize;

  double edgeOffset(String id) => edgeOffsets[id] ?? 0;

  Offset endpointPosition(String id) =>
      nodePosition(id) + endpointSize(id).center(Offset.zero);
}

final class _GraphMeasurements {
  _GraphMeasurements({
    required this.ids,
    required this.unloadedIds,
    required this.sizes,
    required this.unloadedSize,
  });

  final List<String> ids;
  final List<String> unloadedIds;
  final Map<String, Size> sizes;
  final Size unloadedSize;
}

_GraphMeasurements _measureGraph(
    ExploreWorkspaceState state, BuildContext context) {
  final textTheme = Theme.of(context).textTheme;
  double textHeight(String text, TextStyle? style, int maxLines, double width) {
    final painter = TextPainter(
      text: TextSpan(text: text, style: style),
      textDirection: Directionality.of(context),
      textScaler: MediaQuery.textScalerOf(context),
      maxLines: maxLines,
      ellipsis: '…',
    )..layout(maxWidth: width);
    final height = painter.height;
    painter.dispose();
    return height;
  }

  final sizes = <String, Size>{};
  final loadedIds = <String>[];
  for (final item in state.nodes) {
    final status = item.status == WorkspaceItemStatus.missing
        ? 'Missing'
        : item.status == WorkspaceItemStatus.newItem
            ? 'New'
            : null;
    final title =
        textHeight(memoryTitle(item.node), textTheme.titleSmall, 2, 142);
    final kind = textHeight(
        item.expanded ? memoryKind(item.node) : 'Tap to explore',
        textTheme.bodySmall,
        1,
        142);
    final statusHeight = status == null
        ? 0.0
        : 11 + textHeight(status, textTheme.labelSmall, 1, 144);
    sizes[item.node.id] = Size(180, 20 + title + 3 + kind + statusHeight);
    loadedIds.add(item.node.id);
  }
  final unloadedSize = Size(
    180,
    20 +
        math.max(
          18.0,
          textHeight(connectedMemoryTitle(null), textTheme.bodySmall, 2, 133),
        ),
  );
  final unloadedSet = <String>{};
  for (final item in state.edges) {
    if (!sizes.containsKey(item.edge.from)) unloadedSet.add(item.edge.from);
    if (!sizes.containsKey(item.edge.to)) unloadedSet.add(item.edge.to);
  }
  final unloadedIds = unloadedSet.toList()..sort();
  final ids = <String>[...loadedIds];
  ids.addAll(unloadedIds);
  return _GraphMeasurements(
    ids: ids,
    unloadedIds: unloadedIds,
    sizes: sizes,
    unloadedSize: unloadedSize,
  );
}

Map<String, Set<String>> _adjacency(
    ExploreWorkspaceState state, List<String> ids) {
  final adjacency = <String, Set<String>>{
    for (final id in ids) id: <String>{},
  };
  for (final item in state.edges) {
    adjacency[item.edge.from]?.add(item.edge.to);
    adjacency[item.edge.to]?.add(item.edge.from);
  }
  return adjacency;
}

Map<String, Offset> _initialPositions(
  ExploreWorkspaceState state,
  List<String> ids,
  Map<String, Size> sizes,
  Size unloadedSize,
  Map<String, Set<String>> adjacency,
  Map<String, Offset> seeds,
) {
  if (ids.isEmpty) return {};
  final positions = <String, Offset>{};
  final seededIds = ids.where(seeds.containsKey).toSet();
  for (final id in seededIds) {
    positions[id] = seeds[id]!;
  }

  final selected = state.selectedNodeId;
  final focusId =
      selected != null && ids.contains(selected) ? selected : ids.first;
  final seededCenters = seededIds
      .map((id) => seeds[id]! + (sizes[id] ?? unloadedSize).center(Offset.zero))
      .toList();
  final anchor = seededCenters.isEmpty
      ? const Offset(360, 260)
      : seededCenters.reduce((a, b) => a + b) / seededCenters.length.toDouble();

  final distances = <String, int>{focusId: 0};
  final queue = <String>[focusId];
  for (var index = 0; index < queue.length; index++) {
    final current = queue[index];
    for (final next in adjacency[current] ?? const <String>{}) {
      if (distances.containsKey(next)) continue;
      distances[next] = distances[current]! + 1;
      queue.add(next);
    }
  }
  final unseeded = ids.where((id) => !seededIds.contains(id)).toList();
  if (unseeded.contains(focusId)) {
    positions[focusId] =
        anchor - (sizes[focusId] ?? unloadedSize).center(Offset.zero);
  }
  final groups = <int, List<String>>{};
  for (final id in unseeded) {
    if (id == focusId) continue;
    final distance = math.max(1, distances[id] ?? 2);
    groups.putIfAbsent(distance, () => []).add(id);
  }
  for (final group in groups.entries) {
    group.value.sort();
    final count = group.value.length;
    for (var index = 0; index < count; index++) {
      final id = group.value[index];
      final phase = (_stableHash(id) % 360) * math.pi / 180;
      final angle =
          phase + (index / math.max(1, count).toDouble()) * math.pi * 2;
      final radius = 120.0 * group.key;
      final center =
          anchor + Offset(math.cos(angle) * radius, math.sin(angle) * radius);
      positions[id] = center - (sizes[id] ?? unloadedSize).center(Offset.zero);
    }
  }
  return positions;
}

Map<String, Offset> _optimizePositions(
  List<String> ids,
  Map<String, Size> sizes,
  Size unloadedSize,
  List<WorkspaceEdge> edges,
  Map<String, Offset> initial,
  Map<String, Offset> seeds,
  Set<String> pinned,
) {
  if (ids.length < 2) return {...initial};
  final positions = <String, Offset>{...initial};
  final endpointSizes = <String, Size>{
    for (final id in ids) id: sizes[id] ?? unloadedSize,
  };
  final edgesByPair = <String, List<String>>{};
  for (final item in edges) {
    final endpoints = [item.edge.from, item.edge.to]..sort();
    edgesByPair.putIfAbsent(
        '${endpoints[0]}\u0000${endpoints[1]}',
        () => [
              item.edge.from,
              item.edge.to,
            ]);
  }
  final initialCenters = <String, Offset>{
    for (final entry in initial.entries)
      entry.key: entry.value + endpointSizes[entry.key]!.center(Offset.zero),
  };
  final seedCenters = <String, Offset>{
    for (final entry in seeds.entries)
      if (positions.containsKey(entry.key))
        entry.key: entry.value + endpointSizes[entry.key]!.center(Offset.zero),
  };
  for (var iteration = 0; iteration < 90; iteration++) {
    final forces = <String, Offset>{for (final id in ids) id: Offset.zero};
    for (var left = 0; left < ids.length; left++) {
      final first = ids[left];
      final firstCenter =
          positions[first]! + endpointSizes[first]!.center(Offset.zero);
      for (var right = left + 1; right < ids.length; right++) {
        final second = ids[right];
        final secondCenter =
            positions[second]! + endpointSizes[second]!.center(Offset.zero);
        var delta = firstCenter - secondCenter;
        var distance = delta.distance;
        if (distance < .1) {
          delta = Offset(
              (_stableHash(first) % 17) - 8, (_stableHash(second) % 17) - 8);
          distance = math.max(.1, delta.distance);
        }
        final unit = delta / distance;
        final firstSize = endpointSizes[first]!;
        final secondSize = endpointSizes[second]!;
        final required = math.max(
          (firstSize.width + secondSize.width) / 2 + 42,
          (firstSize.height + secondSize.height) / 2 + 42,
        );
        final overlap = math.max(0.0, required - distance);
        final magnitude = 5200 / math.max(distance, 40.0) + overlap * .25;
        final push = unit * magnitude;
        forces[first] = forces[first]! + push;
        forces[second] = forces[second]! - push;
      }
    }
    for (final pair in edgesByPair.values) {
      final from = pair[0];
      final to = pair[1];
      if (!positions.containsKey(from) || !positions.containsKey(to)) continue;
      final fromCenter =
          positions[from]! + endpointSizes[from]!.center(Offset.zero);
      final toCenter = positions[to]! + endpointSizes[to]!.center(Offset.zero);
      var delta = toCenter - fromCenter;
      var distance = delta.distance;
      if (distance < .1) {
        delta = const Offset(1, 0);
        distance = 1;
      }
      final spring = delta / distance * ((distance - 270) * .016);
      forces[from] = forces[from]! + spring;
      forces[to] = forces[to]! - spring;
    }
    final cooling = 1 - iteration / 110;
    for (final id in ids) {
      if (pinned.contains(id) && seedCenters.containsKey(id)) {
        positions[id] =
            seedCenters[id]! - endpointSizes[id]!.center(Offset.zero);
        continue;
      }
      var force = forces[id]!;
      final center = positions[id]! + endpointSizes[id]!.center(Offset.zero);
      final initialCenter = initialCenters[id];
      if (initialCenter != null) force += (initialCenter - center) * .5;
      final seed = seedCenters[id];
      if (seed != null) force += (seed - center) * .055;
      final distance = force.distance;
      if (distance > 22) force = force / distance * 22;
      positions[id] = positions[id]! + force * cooling;
    }
    _separateOverlaps(ids, positions, endpointSizes, pinned);
  }
  return positions;
}

void _separateOverlaps(
  List<String> ids,
  Map<String, Offset> positions,
  Map<String, Size> sizes,
  Set<String> pinned,
) {
  for (var left = 0; left < ids.length; left++) {
    final first = ids[left];
    for (var right = left + 1; right < ids.length; right++) {
      final second = ids[right];
      final a = positions[first]!;
      final b = positions[second]!;
      final firstSize = sizes[first]!;
      final secondSize = sizes[second]!;
      final overlapX =
          math.min(a.dx + firstSize.width, b.dx + secondSize.width) -
              math.max(a.dx, b.dx);
      final overlapY =
          math.min(a.dy + firstSize.height, b.dy + secondSize.height) -
              math.max(a.dy, b.dy);
      if (overlapX <= 0 || overlapY <= 0) continue;
      final firstPinned = pinned.contains(first);
      final secondPinned = pinned.contains(second);
      if (overlapX < overlapY) {
        final direction =
            (a.dx + firstSize.width / 2) <= (b.dx + secondSize.width / 2)
                ? -1.0
                : 1.0;
        final amount = overlapX + 12;
        if (firstPinned && !secondPinned) {
          positions[second] = b + Offset(-direction * amount, 0);
        } else if (secondPinned && !firstPinned) {
          positions[first] = a + Offset(direction * amount, 0);
        } else {
          positions[first] = a + Offset(direction * amount / 2, 0);
          positions[second] = b + Offset(-direction * amount / 2, 0);
        }
      } else {
        final direction =
            (a.dy + firstSize.height / 2) <= (b.dy + secondSize.height / 2)
                ? -1.0
                : 1.0;
        final amount = overlapY + 12;
        if (firstPinned && !secondPinned) {
          positions[second] = b + Offset(0, -direction * amount);
        } else if (secondPinned && !firstPinned) {
          positions[first] = a + Offset(0, direction * amount);
        } else {
          positions[first] = a + Offset(0, direction * amount / 2);
          positions[second] = b + Offset(0, -direction * amount / 2);
        }
      }
    }
  }
}

Map<String, Offset> _normalizePositions(
    Map<String, Offset> positions, List<String> ids) {
  if (ids.isEmpty) return {};
  var left = double.infinity;
  var top = double.infinity;
  for (final id in ids) {
    left = math.min(left, positions[id]!.dx);
    top = math.min(top, positions[id]!.dy);
  }
  final shift = Offset(56 - left, 56 - top);
  return {
    for (final id in ids) id: positions[id]! + shift,
  };
}

Rect _graphBounds(
    Map<String, Offset> positions, Map<String, Size> sizes, Size unloadedSize) {
  if (positions.isEmpty) return Rect.zero;
  var left = double.infinity;
  var top = double.infinity;
  var right = -double.infinity;
  var bottom = -double.infinity;
  for (final entry in positions.entries) {
    final size = sizes[entry.key] ?? unloadedSize;
    left = math.min(left, entry.value.dx);
    top = math.min(top, entry.value.dy);
    right = math.max(right, entry.value.dx + size.width);
    bottom = math.max(bottom, entry.value.dy + size.height);
  }
  return Rect.fromLTRB(left, top, right, bottom);
}

Map<String, double> _calculateEdgeOffsets(
  List<WorkspaceEdge> edges,
  Map<String, Offset> positions,
  Map<String, Size> sizes,
  Size unloadedSize,
) {
  final pairs = <String, List<WorkspaceEdge>>{};
  for (final item in edges) {
    final endpoints = [item.edge.from, item.edge.to]..sort();
    pairs
        .putIfAbsent('${endpoints[0]}\u0000${endpoints[1]}', () => [])
        .add(item);
  }
  final offsets = <String, double>{};
  for (final pair in pairs.values) {
    final first = pair.first.edge;
    final start = positions[first.from] ?? const Offset(56, 56);
    final end = positions[first.to] ?? const Offset(56, 56);
    final startSize = sizes[first.from] ?? unloadedSize;
    final endSize = sizes[first.to] ?? unloadedSize;
    final normal = _curveOffset(
      start + startSize.center(Offset.zero),
      end + endSize.center(Offset.zero),
      1,
    );
    final spacing = normal == Offset.zero
        ? _edgeTargetHeight + 8
        : math.min(
            normal.dx == 0
                ? double.infinity
                : (_edgeTargetWidth + 8) / normal.dx.abs(),
            normal.dy == 0
                ? double.infinity
                : (_edgeTargetHeight + 8) / normal.dy.abs(),
          );
    for (var index = 0; index < pair.length; index++) {
      final edge = pair[index].edge;
      final direction = edge.from.compareTo(edge.to) <= 0 ? 1 : -1;
      offsets[edge.id] = (index - (pair.length - 1) / 2) * spacing * direction;
    }
  }
  return offsets;
}

int _stableHash(String value) {
  var hash = 0x811c9dc5;
  for (final codeUnit in value.codeUnits) {
    hash ^= codeUnit;
    hash = (hash * 0x01000193) & 0x7fffffff;
  }
  return hash;
}

final class _GraphEdgesPainter extends CustomPainter {
  _GraphEdgesPainter({
    required this.edges,
    required this.layout,
    required this.colorScheme,
  });

  final List<WorkspaceEdge> edges;
  final _GraphLayout layout;
  final ColorScheme colorScheme;

  @override
  void paint(Canvas canvas, Size size) {
    for (final item in edges) {
      final rawStart = layout.endpointPosition(item.edge.from);
      final rawEnd = layout.endpointPosition(item.edge.to);
      final curveOffset =
          _curveOffset(rawStart, rawEnd, layout.edgeOffset(item.edge.id));
      final start =
          _nodeBorder(rawStart, rawEnd, layout.endpointSize(item.edge.from));
      final end =
          _nodeBorder(rawEnd, rawStart, layout.endpointSize(item.edge.to));
      final control = (start + end) / 2 + curveOffset * 2;
      final path = Path()
        ..moveTo(start.dx, start.dy)
        ..quadraticBezierTo(control.dx, control.dy, end.dx, end.dy);
      final missing = item.status == WorkspaceItemStatus.missing;
      final isNew = item.status == WorkspaceItemStatus.newItem;
      final paint = Paint()
        ..color = missing
            ? colorScheme.outline.withAlpha(100)
            : isNew
                ? colorScheme.tertiary
                : colorScheme.primary
        ..strokeWidth = isNew ? 2.6 : 2
        ..style = PaintingStyle.stroke;
      if (missing) paint.strokeWidth = 1.8;
      if (missing) {
        _drawDashedPath(canvas, path, paint);
      } else {
        canvas.drawPath(path, paint);
      }
      _drawArrow(canvas, control, end, paint);
    }
  }

  void _drawArrow(Canvas canvas, Offset start, Offset end, Paint paint) {
    final direction = end - start;
    if (direction.distance < 1) return;
    final unit = direction / direction.distance;
    final tip = end - unit * 10;
    final perpendicular = Offset(-unit.dy, unit.dx);
    final path = Path()
      ..moveTo(tip.dx, tip.dy)
      ..lineTo(
        tip.dx - unit.dx * 10 + perpendicular.dx * 5,
        tip.dy - unit.dy * 10 + perpendicular.dy * 5,
      )
      ..lineTo(
        tip.dx - unit.dx * 10 - perpendicular.dx * 5,
        tip.dy - unit.dy * 10 - perpendicular.dy * 5,
      )
      ..close();
    final arrowPaint = Paint()..color = paint.color;
    canvas.drawPath(path, arrowPaint);
  }

  void _drawDashedPath(Canvas canvas, Path path, Paint paint) {
    for (final metric in path.computeMetrics()) {
      for (var offset = 0.0; offset < metric.length; offset += 12) {
        canvas.drawPath(
            metric.extractPath(offset, math.min(offset + 7, metric.length)),
            paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _GraphEdgesPainter oldDelegate) {
    return oldDelegate.edges != edges ||
        oldDelegate.layout != layout ||
        oldDelegate.colorScheme != colorScheme;
  }
}

const _edgeTargetWidth = 100.0;
const _edgeTargetHeight = 40.0;

Offset _nodeBorder(Offset center, Offset towards, Size size) {
  final delta = towards - center;
  if (delta.distance < 1) return center;
  final fraction = math.min(
    delta.dx == 0 ? double.infinity : size.width / 2 / delta.dx.abs(),
    delta.dy == 0 ? double.infinity : size.height / 2 / delta.dy.abs(),
  );
  return center + delta * fraction;
}

Offset _curveOffset(Offset start, Offset end, double amount) {
  final direction = end - start;
  if (direction.distance < 1) return Offset.zero;
  final unit = direction / direction.distance;
  final perpendicular = Offset(-unit.dy, unit.dx);
  return perpendicular * amount;
}
