import '../persistence/models.dart';

/// The current in-memory workspace projection.
final class ExploreWorkspaceState {
  const ExploreWorkspaceState({
    required this.status,
    required this.nodes,
    required this.edges,
    this.selectedNodeId,
  });

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

/// Interface-only controller stub.
final class ExploreWorkspaceControllerStub
    implements ExploreWorkspaceController {
  const ExploreWorkspaceControllerStub();

  @override
  ExploreWorkspaceState get state =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> get refreshCompleted =>
      throw UnimplementedError('not implemented');

  @override
  void selectNode(String recordId) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> openNode(String recordId) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> followEdge(String edgeId) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> refresh() => throw UnimplementedError('not implemented');

  @override
  void clearDeleted() => throw UnimplementedError('not implemented');

  @override
  Future<void> clearWorkspace() => throw UnimplementedError('not implemented');
}
