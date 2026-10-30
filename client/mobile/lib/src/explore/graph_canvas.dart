import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'explore_controller.dart';
import '../persistence/models.dart';
import '../widgets/memory_labels.dart';

/// A graph projection rendered with Flutter primitives.
///
/// The canvas deliberately keeps edge identity separate from node identity.
/// Parallel and unloaded edges remain individually tappable. [InteractiveViewer]
/// owns pan and zoom while this widget owns deterministic item placement.
final class GraphCanvas extends StatelessWidget {
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

  ExploreWorkspaceState get _state =>
      state ??
      controller?.state ??
      ExploreWorkspaceState(
          status: WorkspaceItemStatus.loaded, nodes: const [], edges: const []);

  @override
  Widget build(BuildContext context) {
    final projection = _state;
    final layout = _GraphLayout.fromState(projection, context);
    final width = math.max(900.0, layout.width);
    final boardHeight = math.max(560.0, layout.height);
    final edgeHandler =
        onSelectEdge ?? onEdgeTap ?? onEdgeSelected ?? _controllerEdgeHandler;
    final nodeHandler =
        onSelectNode ?? onNodeTap ?? onNodeSelected ?? _controllerNodeHandler;

    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: Container(
        height: height,
        decoration: BoxDecoration(
          border:
              Border.all(color: Theme.of(context).colorScheme.outlineVariant),
          color: Theme.of(context).colorScheme.surfaceContainerLowest,
        ),
        child: _GraphViewport(
          layout: layout,
          selectedNodeId: projection.selectedNodeId,
          focusRevision: focusRevision,
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
                        entry.key,
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
    controller?.selectNode(id);
  }

  void _controllerEdgeHandler(String id) {
    // Canvas interaction is intentionally non-blocking. Screens that want to
    // follow an edge provide [onSelectEdge] and await controller.followEdge.
    final target = controller;
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
    final offset = layout.nodePosition(item.node.id);
    final selected = item.node.id == _state.selectedNodeId;
    final missing = item.status == WorkspaceItemStatus.missing;
    final isNew = item.status == WorkspaceItemStatus.newItem;
    final title = memoryTitle(item.node);
    final status = missing
        ? 'Missing'
        : isNew
            ? 'New'
            : null;
    final scheme = Theme.of(context).colorScheme;
    return Positioned(
      left: offset.dx,
      top: offset.dy,
      width: 180,
      child: Opacity(
        opacity: missing ? .42 : 1,
        child: Card(
          margin: EdgeInsets.zero,
          color: selected ? scheme.primaryContainer : scheme.surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
            side: BorderSide(
              color: selected
                  ? scheme.primary
                  : isNew
                      ? scheme.tertiary
                      : scheme.outlineVariant,
              width: selected ? 2 : 1,
            ),
          ),
          child: InkWell(
            onTap: handler == null ? null : () => handler(item.node.id),
            borderRadius: BorderRadius.circular(14),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 3),
                  Text(
                    item.expanded ? memoryKind(item.node) : 'Tap to explore',
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
    );
  }

  Widget _edgeAction(
    BuildContext context,
    WorkspaceEdge item,
    int index,
    _GraphLayout layout,
    ValueChanged<String>? handler,
  ) {
    final rawStart = layout.endpointPosition(item.edge.from, index);
    final rawEnd = layout.endpointPosition(item.edge.to, index);
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
    required this.child,
  });

  final _GraphLayout layout;
  final String? selectedNodeId;
  final int focusRevision;
  final Widget child;

  @override
  State<_GraphViewport> createState() => _GraphViewportState();
}

final class _GraphViewportState extends State<_GraphViewport> {
  final _transform = TransformationController();
  Size _viewport = Size.zero;

  @override
  void didUpdateWidget(covariant _GraphViewport oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedNodeId != widget.selectedNodeId ||
        oldWidget.focusRevision != widget.focusRevision) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _focus();
      });
    }
  }

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  void _focus() {
    final nodes = widget.layout.nodes;
    if (nodes.isEmpty || _viewport.isEmpty) return;
    final selected = widget.selectedNodeId;
    final id = selected != null && nodes.containsKey(selected)
        ? selected
        : nodes.keys.first;
    _center(widget.layout.endpointPosition(id, 0), 1);
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
    final positions = [
      ...widget.layout.positions.values,
      ...widget.layout.unloadedPositions.values,
    ];
    if (positions.isEmpty) return;
    final left = positions.map((point) => point.dx).reduce(math.min);
    final top = positions.map((point) => point.dy).reduce(math.min);
    final right = positions.map((point) => point.dx + 180).reduce(math.max);
    final bottom = positions.map((point) => point.dy + 95).reduce(math.max);
    final scale = math
        .min(_viewport.width / (right - left + 60),
            _viewport.height / (bottom - top + 60))
        .clamp(.2, 2.4)
        .toDouble();
    _center(Offset((left + right) / 2, (top + bottom) / 2), scale);
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, constraints) {
          final size = constraints.biggest;
          if (size != _viewport) {
            _viewport = size;
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted) _focus();
            });
          }
          return Stack(
            children: [
              Positioned.fill(
                child: InteractiveViewer(
                  transformationController: _transform,
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
                  color: Theme.of(context).colorScheme.surface,
                  elevation: 2,
                  borderRadius: BorderRadius.circular(14),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
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
  _GraphLayout(
      {required this.positions,
      required this.nodeSizes,
      required this.unloadedSize,
      required this.nodes,
      required this.unloadedPositions,
      required this.edgeOffsets,
      this.width = 900,
      this.height = 560});

  final Map<String, Offset> positions;
  final Map<String, Size> nodeSizes;
  final Size unloadedSize;
  final Map<String, WorkspaceNode> nodes;
  final Map<String, Offset> unloadedPositions;
  final Map<String, double> edgeOffsets;
  final double width;
  final double height;

  factory _GraphLayout.fromState(
      ExploreWorkspaceState state, BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    double textHeight(
        String text, TextStyle? style, int maxLines, double width) {
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

    final nodeSizes = <String, Size>{};
    for (final item in state.nodes) {
      final status = item.status == WorkspaceItemStatus.missing
          ? 'Missing'
          : item.status == WorkspaceItemStatus.newItem
              ? 'New'
              : null;
      final title =
          textHeight(memoryTitle(item.node), textTheme.titleSmall, 2, 158);
      final kind = textHeight(
          item.expanded ? memoryKind(item.node) : 'Tap to explore',
          textTheme.bodySmall,
          1,
          158);
      final statusHeight = status == null
          ? 0.0
          : 11 + textHeight(status, textTheme.labelSmall, 1, 144);
      nodeSizes[item.node.id] = Size(180, 20 + title + 3 + kind + statusHeight);
    }
    final unloadedSize = Size(
        180,
        20 +
            math.max(
                18,
                textHeight(
                    connectedMemoryTitle(null), textTheme.bodySmall, 2, 133)));
    final rowSpacing = math.max(
        185.0,
        nodeSizes.values.fold<double>(unloadedSize.height,
                (height, size) => math.max(height, size.height)) +
            60);
    final positions = <String, Offset>{};
    final nodes = <String, WorkspaceNode>{};
    for (var index = 0; index < state.nodes.length; index++) {
      final column = index % 3;
      final row = index ~/ 3;
      final node = state.nodes[index];
      nodes[node.node.id] = node;
      positions[node.node.id] =
          Offset(56 + column * 285, 56 + row * rowSpacing);
    }
    final unloadedPositions = <String, Offset>{};
    final pairs = <String, List<WorkspaceEdge>>{};
    for (final item in state.edges) {
      for (final id in [item.edge.from, item.edge.to]) {
        if (!positions.containsKey(id)) {
          unloadedPositions.putIfAbsent(
            id,
            () => Offset(940, 56 + unloadedPositions.length * 185),
          );
        }
      }
      final endpoints = [item.edge.from, item.edge.to]..sort();
      final key = '${endpoints[0]}\u0000${endpoints[1]}';
      pairs.putIfAbsent(key, () => []).add(item);
    }
    final edgeOffsets = <String, double>{};
    for (final pair in pairs.values) {
      final first = pair.first.edge;
      final start = positions[first.from] ?? unloadedPositions[first.from]!;
      final end = positions[first.to] ?? unloadedPositions[first.to]!;
      final normal = _curveOffset(start, end, 1);
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
      for (var rank = 0; rank < pair.length; rank++) {
        final edge = pair[rank].edge;
        final direction = edge.from.compareTo(edge.to) <= 0 ? 1 : -1;
        edgeOffsets[edge.id] =
            (rank - (pair.length - 1) / 2) * spacing * direction;
      }
    }
    final rows = (state.nodes.length + 2) ~/ 3;
    return _GraphLayout(
      positions: positions,
      nodeSizes: nodeSizes,
      unloadedSize: unloadedSize,
      nodes: nodes,
      unloadedPositions: unloadedPositions,
      edgeOffsets: edgeOffsets,
      width: unloadedPositions.isEmpty ? 56 + 3 * 285 : 1176,
      height: math.max(
          560,
          56 +
              math.max(math.max(1, rows), unloadedPositions.length) *
                  rowSpacing),
    );
  }

  bool isLoaded(String id) => positions.containsKey(id);

  WorkspaceNode? node(String id) => nodes[id];

  Offset nodePosition(String id) => positions[id] ?? unloadedNodePosition(id);

  Offset unloadedNodePosition(String id) =>
      unloadedPositions[id] ?? Offset.zero;

  Size endpointSize(String id) => nodeSizes[id] ?? unloadedSize;

  Offset endpointPosition(String id, int edgeIndex) =>
      nodePosition(id) + endpointSize(id).center(Offset.zero);

  double edgeOffset(String id) => edgeOffsets[id] ?? 0;
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
    for (var index = 0; index < edges.length; index++) {
      final item = edges[index];
      final rawStart = layout.endpointPosition(item.edge.from, index);
      final rawEnd = layout.endpointPosition(item.edge.to, index);
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
