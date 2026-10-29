import 'dart:async';

import '../gateway/brain_gateway.dart';
import '../gateway/models.dart';
import '../persistence/models.dart';
import '../persistence/repositories.dart';

/// The current in-memory workspace projection.
///
/// The controller returns a fresh projection for every state transition. The
/// node and edge lists cannot be changed by a caller.
final class ExploreWorkspaceState {
  ExploreWorkspaceState({
    required this.status,
    required Iterable<WorkspaceNode> nodes,
    required Iterable<WorkspaceEdge> edges,
    this.selectedNodeId,
  })  : nodes = List<WorkspaceNode>.unmodifiable(nodes),
        edges = List<WorkspaceEdge>.unmodifiable(edges);

  final String? selectedNodeId;
  final WorkspaceItemStatus status;
  final List<WorkspaceNode> nodes;
  final List<WorkspaceEdge> edges;
}

/// Owns Explore workspace refresh, deletion, and clear behavior.
abstract interface class ExploreWorkspaceController {
  ExploreWorkspaceState get state;

  /// Completes when the currently scheduled refresh finishes.
  Future<void> get refreshCompleted;

  void selectNode(String recordId);

  Future<void> openNode(String recordId);

  Future<void> followEdge(String edgeId);

  Future<void> refresh();

  void clearDeleted();

  Future<void> clearWorkspace();
}

/// A persistence-backed Explore workspace controller.
///
/// [initialWorkspace] is a snapshot loaded by the caller. Use
/// [ExploreWorkspaceControllerImpl.load] when construction must read the
/// repository first.
final class ExploreWorkspaceControllerImpl
    implements ExploreWorkspaceController {
  ExploreWorkspaceControllerImpl({
    required String brainId,
    required GraphWorkspaceRepository workspaces,
    required BrainGateway gateway,
    Future<BrainGateway> Function()? resolveGateway,
    Workspace? initialWorkspace,
  })  : _brainId = brainId,
        _workspaces = workspaces,
        _gateway = gateway,
        _resolveGateway = resolveGateway,
        _fetchedAt = initialWorkspace?.fetchedAt,
        _state = _stateFromWorkspace(initialWorkspace ?? _emptyWorkspace());

  /// Loads one profile's workspace without contacting the server.
  static Future<ExploreWorkspaceControllerImpl> load({
    required String brainId,
    required GraphWorkspaceRepository workspaces,
    required BrainGateway gateway,
    Future<BrainGateway> Function()? resolveGateway,
  }) async {
    final workspace = await workspaces.load(brainId);
    return ExploreWorkspaceControllerImpl(
      brainId: brainId,
      workspaces: workspaces,
      gateway: gateway,
      resolveGateway: resolveGateway,
      initialWorkspace: workspace,
    );
  }

  final String _brainId;
  final GraphWorkspaceRepository _workspaces;
  final BrainGateway _gateway;
  final Future<BrainGateway> Function()? _resolveGateway;

  Future<BrainGateway> _currentGateway() async =>
      _resolveGateway == null ? _gateway : await _resolveGateway();
  DateTime? _fetchedAt;
  ExploreWorkspaceState _state;

  // Writes from void clearDeleted calls must retain their order. Later
  // awaited operations drain this chain before writing their own snapshot.
  Future<void> _pendingPersistence = Future<void>.value();
  Future<void>? _refreshInFlight;
  int _workspaceGeneration = 0;

  @override
  ExploreWorkspaceState get state => _state;

  @override
  Future<void> get refreshCompleted => _refreshInFlight ?? Future<void>.value();

  @override
  void selectNode(String recordId) {
    _state = _stateFor(
      _state,
      selectedNodeId: recordId,
    );
  }

  @override
  Future<void> openNode(String recordId) async {
    final generation = _workspaceGeneration;
    final gateway = await _currentGateway();
    final detail = await gateway.getGraph(recordId);
    if (generation != _workspaceGeneration) return;
    final next = mergeOpenedNode(_state, recordId, detail);
    await _persistAndSet(next);
  }

  @override
  Future<void> followEdge(String edgeId) async {
    final selected = _state.selectedNodeId;
    final workspaceEdge = _findEdge(_state.edges, edgeId);
    if (workspaceEdge == null ||
        workspaceEdge.status == WorkspaceItemStatus.missing) {
      return;
    }

    final edge = workspaceEdge.edge;
    final target = selected == edge.to ? edge.from : edge.to;
    await openNode(target);
  }

  @override
  Future<void> refresh() {
    final inFlight = _refreshInFlight;
    if (inFlight != null) {
      return inFlight;
    }

    final completion = Completer<void>();
    _refreshInFlight = completion.future;
    _performRefresh().then<void>(
      (_) {
        if (identical(_refreshInFlight, completion.future)) {
          _refreshInFlight = null;
        }
        if (!completion.isCompleted) {
          completion.complete();
        }
      },
      onError: (Object error, StackTrace stack) {
        if (identical(_refreshInFlight, completion.future)) {
          _refreshInFlight = null;
        }
        if (!completion.isCompleted) {
          completion.completeError(error, stack);
        }
      },
    );
    return completion.future;
  }

  Future<void> _performRefresh() async {
    final generation = _workspaceGeneration;
    final expandedIds = _state.nodes
        .where((node) => node.expanded)
        .map((node) => node.node.id)
        .toList(growable: false);
    if (expandedIds.isEmpty) {
      return;
    }

    final gateway = await _currentGateway();
    final results = <GraphRefreshItem>[];
    for (var offset = 0; offset < expandedIds.length; offset += 200) {
      final end = (offset + 200 < expandedIds.length)
          ? offset + 200
          : expandedIds.length;
      final batch = expandedIds.sublist(offset, end);
      final response = await gateway.refreshGraph(batch);
      results.addAll(response.results);
    }

    // Do not publish a partial result. Every network request above completed
    // before this single merge and persistence transition.
    if (generation != _workspaceGeneration) return;
    final next = mergeRefresh(_state, results);
    await _persistAndSet(next);
  }

  @override
  void clearDeleted() {
    final next = clearDeletedWorkspace(_state);
    final workspaceChanged = !_sameWorkspace(_state, next);
    final selectionChanged = _state.selectedNodeId != next.selectedNodeId;
    if (!workspaceChanged && !selectionChanged) {
      return;
    }
    _state = next;
    if (workspaceChanged) {
      unawaited(_queuePersistence(next).catchError((Object _) {}));
    }
  }

  @override
  Future<void> clearWorkspace() async {
    _workspaceGeneration++;
    _refreshInFlight = null;
    final next = _stateFor(
      _state,
      nodes: const <WorkspaceNode>[],
      edges: const <WorkspaceEdge>[],
      selectedNodeId: null,
    );
    await _persistAndSet(next, markFetched: false);
  }

  Future<void> _persistAndSet(
    ExploreWorkspaceState next, {
    bool markFetched = true,
  }) {
    _fetchedAt = markFetched ? DateTime.now().toUtc() : _fetchedAt;
    _state = next;
    return _queuePersistence(next);
  }

  Future<void> _queuePersistence(ExploreWorkspaceState state) {
    final workspace = _workspaceFromState(state, fetchedAt: _fetchedAt);
    final write = _pendingPersistence.then<void>(
      (_) => _workspaces.save(_brainId, workspace),
      onError: (_, __) => _workspaces.save(_brainId, workspace),
    );
    // clearDeleted has no Future in the public contract. Consume a write
    // failure so it cannot become an unhandled asynchronous error.
    _pendingPersistence = write.then<void>(
      (_) {},
      onError: (_, __) {},
    );
    return write;
  }
}

/// Loads a persistence-backed controller without a transport call.
Future<ExploreWorkspaceController> loadExploreWorkspaceController({
  required String brainId,
  required GraphWorkspaceRepository workspaces,
  required BrainGateway gateway,
}) async {
  return ExploreWorkspaceControllerImpl.load(
    brainId: brainId,
    workspaces: workspaces,
    gateway: gateway,
  );
}

/// Merges a successful single-node read into [state].
///
/// This function has no side effects. It preserves list order, marks the
/// opened node expanded, and retains existing edge identity.
ExploreWorkspaceState mergeOpenedNode(
  ExploreWorkspaceState state,
  String requestedId,
  GraphNodeDetail detail,
) {
  final openedId = detail.node.id.isEmpty ? requestedId : detail.node.id;
  final nodes = List<WorkspaceNode>.of(state.nodes);
  final edges = List<WorkspaceEdge>.of(state.edges);

  _upsertNode(
    nodes,
    detail.node,
    status: WorkspaceItemStatus.loaded,
    expanded: true,
    forceExpanded: true,
  );

  final returnedEdgeIds = <String>{};
  for (final connection in detail.connections) {
    returnedEdgeIds.add(connection.edge.id);
    _upsertNode(
      nodes,
      connection.node,
      status: _statusForReturnedNode(nodes, connection.node.id),
      expanded: _expandedFor(nodes, connection.node.id),
    );
    _upsertEdge(
      edges,
      connection.edge,
      status: WorkspaceItemStatus.loaded,
    );
  }

  // A successful detail read is also a refresh of the opened node. Keep the
  // cached edge records, but mark connections absent from the response.
  _markAbsentConnectionsMissing(
    edges,
    openedId,
    returnedEdgeIds,
  );

  return _stateFor(
    state,
    nodes: nodes,
    edges: edges,
    selectedNodeId: openedId,
  );
}

/// Merges all successful batch-refresh results into one state transition.
///
/// Missing records and removed connections retain their cached projections so
/// the UI can render them as dimmed until the user clears deleted items.
ExploreWorkspaceState mergeRefresh(
  ExploreWorkspaceState state,
  Iterable<GraphRefreshItem> results,
) {
  final nodes = List<WorkspaceNode>.of(state.nodes);
  final edges = List<WorkspaceEdge>.of(state.edges);
  final resultList = List<GraphRefreshItem>.of(results);
  final found = <GraphRefreshFound>[];
  final missing = <GraphRefreshMissing>[];

  for (final result in resultList) {
    if (result is GraphRefreshFound) {
      found.add(result);
    } else if (result is GraphRefreshMissing) {
      missing.add(result);
    }
  }

  // First apply found data. A later missing result can then dim a node or edge
  // returned as a connection from another refreshed node.
  for (final result in found) {
    _mergeFoundRefresh(nodes, edges, result);
  }

  for (final result in missing) {
    _markNodeMissing(nodes, edges, result.id);
  }

  return _stateFor(
    state,
    nodes: nodes,
    edges: edges,
  );
}

/// Removes confirmed-missing items while retaining all other cached data.
ExploreWorkspaceState clearDeletedWorkspace(ExploreWorkspaceState state) {
  final removedNodeIds = state.nodes
      .where((node) => node.status == WorkspaceItemStatus.missing)
      .map((node) => node.node.id)
      .toSet();
  final nodes = state.nodes
      .where((node) => node.status != WorkspaceItemStatus.missing)
      .toList(growable: false);
  final edges = state.edges
      .where(
        (edge) =>
            edge.status != WorkspaceItemStatus.missing &&
            !removedNodeIds.contains(edge.edge.from) &&
            !removedNodeIds.contains(edge.edge.to),
      )
      .toList(growable: false);
  final nodeIds = nodes.map((node) => node.node.id).toSet();
  final selected = state.selectedNodeId;
  final selectedNodeId =
      selected != null && nodeIds.contains(selected) ? selected : null;

  return _stateFor(
    state,
    nodes: nodes,
    edges: edges,
    selectedNodeId: selectedNodeId,
  );
}

Workspace _workspaceFromState(
  ExploreWorkspaceState state, {
  required DateTime? fetchedAt,
}) {
  return Workspace(
    nodes: List<WorkspaceNode>.unmodifiable(state.nodes),
    edges: List<WorkspaceEdge>.unmodifiable(state.edges),
    fetchedAt: fetchedAt,
  );
}

ExploreWorkspaceState _stateFromWorkspace(Workspace workspace) {
  final nodes = _uniqueNodes(workspace.nodes);
  final edges = _uniqueEdges(workspace.edges);
  return ExploreWorkspaceState(
    status: _workspaceStatus(nodes, edges),
    nodes: nodes,
    edges: edges,
  );
}

Workspace _emptyWorkspace() => const Workspace(nodes: [], edges: []);

ExploreWorkspaceState _stateFor(
  ExploreWorkspaceState previous, {
  Iterable<WorkspaceNode>? nodes,
  Iterable<WorkspaceEdge>? edges,
  Object? selectedNodeId = _keepSelection,
}) {
  final nextNodes = nodes ?? previous.nodes;
  final nextEdges = edges ?? previous.edges;
  final nextSelection = identical(selectedNodeId, _keepSelection)
      ? previous.selectedNodeId
      : selectedNodeId as String?;
  return ExploreWorkspaceState(
    status: _workspaceStatus(nextNodes, nextEdges),
    nodes: nextNodes,
    edges: nextEdges,
    selectedNodeId: nextSelection,
  );
}

const _keepSelection = Object();

WorkspaceItemStatus _workspaceStatus(
  Iterable<WorkspaceNode> nodes,
  Iterable<WorkspaceEdge> edges,
) {
  if (nodes.any((node) => node.status == WorkspaceItemStatus.missing) ||
      edges.any((edge) => edge.status == WorkspaceItemStatus.missing)) {
    return WorkspaceItemStatus.missing;
  }
  if (nodes.any((node) => node.status == WorkspaceItemStatus.newItem) ||
      edges.any((edge) => edge.status == WorkspaceItemStatus.newItem)) {
    return WorkspaceItemStatus.newItem;
  }
  return WorkspaceItemStatus.loaded;
}

List<WorkspaceNode> _uniqueNodes(Iterable<WorkspaceNode> source) {
  final output = <WorkspaceNode>[];
  final indexes = <String, int>{};
  for (final node in source) {
    final index = indexes[node.node.id];
    if (index == null) {
      indexes[node.node.id] = output.length;
      output.add(node);
    } else {
      output[index] = node;
    }
  }
  return output;
}

List<WorkspaceEdge> _uniqueEdges(Iterable<WorkspaceEdge> source) {
  final output = <WorkspaceEdge>[];
  final indexes = <String, int>{};
  for (final edge in source) {
    final index = indexes[edge.edge.id];
    if (index == null) {
      indexes[edge.edge.id] = output.length;
      output.add(edge);
    } else {
      output[index] = edge;
    }
  }
  return output;
}

WorkspaceNode? _findNode(Iterable<WorkspaceNode> nodes, String id) {
  for (final node in nodes) {
    if (node.node.id == id) {
      return node;
    }
  }
  return null;
}

WorkspaceEdge? _findEdge(Iterable<WorkspaceEdge> edges, String id) {
  for (final edge in edges) {
    if (edge.edge.id == id) {
      return edge;
    }
  }
  return null;
}

void _upsertNode(
  List<WorkspaceNode> nodes,
  GraphNode node, {
  required WorkspaceItemStatus status,
  required bool expanded,
  bool forceExpanded = false,
}) {
  final index = nodes.indexWhere((entry) => entry.node.id == node.id);
  if (index == -1) {
    nodes.add(
      WorkspaceNode(
        node: node,
        status: status,
        expanded: expanded,
      ),
    );
    return;
  }

  final previous = nodes[index];
  nodes[index] = WorkspaceNode(
    node: node,
    status: status,
    expanded: forceExpanded ? true : previous.expanded,
  );
}

WorkspaceItemStatus _statusForReturnedNode(
  List<WorkspaceNode> nodes,
  String id,
) {
  final existing = _findNode(nodes, id);
  if (existing == null || existing.status == WorkspaceItemStatus.missing) {
    return existing == null
        ? WorkspaceItemStatus.newItem
        : WorkspaceItemStatus.loaded;
  }
  return existing.status;
}

bool _expandedFor(List<WorkspaceNode> nodes, String id) {
  return _findNode(nodes, id)?.expanded ?? false;
}

void _upsertEdge(
  List<WorkspaceEdge> edges,
  LinkedEdge edge, {
  required WorkspaceItemStatus status,
}) {
  final index = edges.indexWhere((entry) => entry.edge.id == edge.id);
  if (index == -1) {
    edges.add(WorkspaceEdge(edge: edge, status: status));
    return;
  }

  final previous = edges[index];
  final nextStatus = previous.status == WorkspaceItemStatus.missing
      ? WorkspaceItemStatus.loaded
      : status;
  edges[index] = WorkspaceEdge(edge: edge, status: nextStatus);
}

void _markAbsentConnectionsMissing(
  List<WorkspaceEdge> edges,
  String nodeId,
  Set<String> returnedEdgeIds,
) {
  for (var index = 0; index < edges.length; index++) {
    final current = edges[index];
    final incident = current.edge.from == nodeId || current.edge.to == nodeId;
    if (incident && !returnedEdgeIds.contains(current.edge.id)) {
      edges[index] = WorkspaceEdge(
        edge: current.edge,
        status: WorkspaceItemStatus.missing,
      );
    }
  }
}

void _mergeFoundRefresh(
  List<WorkspaceNode> nodes,
  List<WorkspaceEdge> edges,
  GraphRefreshFound result,
) {
  final nodeId = result.id;
  _upsertNode(
    nodes,
    result.node,
    status: WorkspaceItemStatus.loaded,
    expanded: true,
    forceExpanded: false,
  );

  final returnedEdgeIds = <String>{};
  final existingEdgeIds = edges.map((edge) => edge.edge.id).toSet();
  for (final connection in result.connections) {
    returnedEdgeIds.add(connection.edge.id);
    final existingNode = _findNode(nodes, connection.node.id);
    final nodeStatus = existingNode == null
        ? WorkspaceItemStatus.newItem
        : existingNode.status == WorkspaceItemStatus.missing
            ? WorkspaceItemStatus.loaded
            : existingNode.status;
    _upsertNode(
      nodes,
      connection.node,
      status: nodeStatus,
      expanded: existingNode?.expanded ?? false,
    );
    _upsertEdge(
      edges,
      connection.edge,
      status: existingEdgeIds.contains(connection.edge.id)
          ? WorkspaceItemStatus.loaded
          : WorkspaceItemStatus.newItem,
    );
  }

  _markAbsentConnectionsMissing(edges, nodeId, returnedEdgeIds);
}

void _markNodeMissing(
  List<WorkspaceNode> nodes,
  List<WorkspaceEdge> edges,
  String id,
) {
  final nodeIndex = nodes.indexWhere((node) => node.node.id == id);
  if (nodeIndex != -1) {
    final node = nodes[nodeIndex];
    nodes[nodeIndex] = WorkspaceNode(
      node: node.node,
      status: WorkspaceItemStatus.missing,
      expanded: node.expanded,
    );
  }
  for (var index = 0; index < edges.length; index++) {
    final edge = edges[index];
    if (edge.edge.from == id || edge.edge.to == id) {
      edges[index] = WorkspaceEdge(
        edge: edge.edge,
        status: WorkspaceItemStatus.missing,
      );
    }
  }
}

bool _sameWorkspace(
  ExploreWorkspaceState left,
  ExploreWorkspaceState right,
) {
  if (left.nodes.length != right.nodes.length ||
      left.edges.length != right.edges.length) {
    return false;
  }
  for (var index = 0; index < left.nodes.length; index++) {
    final a = left.nodes[index];
    final b = right.nodes[index];
    if (a.node.id != b.node.id ||
        a.status != b.status ||
        a.expanded != b.expanded ||
        !_sameGraphNode(a.node, b.node)) {
      return false;
    }
  }
  for (var index = 0; index < left.edges.length; index++) {
    final a = left.edges[index];
    final b = right.edges[index];
    if (a.edge.id != b.edge.id ||
        a.status != b.status ||
        !_sameLinkedEdge(a.edge, b.edge)) {
      return false;
    }
  }
  return true;
}

bool _sameGraphNode(GraphNode left, GraphNode right) {
  return left.id == right.id &&
      left.table == right.table &&
      left.content == right.content &&
      left.name == right.name &&
      left.type == right.type &&
      left.description == right.description &&
      left.summary == right.summary &&
      left.freshnessAt == right.freshnessAt;
}

bool _sameLinkedEdge(LinkedEdge left, LinkedEdge right) {
  return left.id == right.id &&
      left.table == right.table &&
      left.from == right.from &&
      left.to == right.to &&
      left.context == right.context &&
      left.freshnessAt == right.freshnessAt;
}
