import 'models.dart';

/// REST operations exposed to the mobile application shell and screens.
abstract interface class BrainGateway {
  /// Confirms that the configured server is healthy.
  Future<void> checkHealth();

  /// Stages [text] and returns the number of stored chunks.
  Future<IngestReceipt> stageIntake(
    String text, {
    required String idempotencyKey,
    required String capturedAt,
  });

  /// Recalls an answer and its grouped evidence for [question].
  Future<RecallResult> recall(String question);
}

/// Extended graph operations used by Explore and Answer history.
///
/// The base gateway remains source-compatible with the Capture and Ask
/// surfaces while the client migrates to the expanded contract.
abstract interface class BrainGraphGateway extends BrainGateway {
  Future<MemorySearchResult> searchMemory(String query, {int? limit});

  Future<GraphNodeDetail> getGraph(String recordId);

  Future<GraphRefreshResult> refreshGraph(List<String> recordIds);
}

/// Adapter methods for callers that receive the original gateway type.
///
/// Implementations of [BrainGraphGateway] provide the operations directly.
/// A gateway that has not adopted the expanded contract fails explicitly.
extension BrainGatewayGraphOperations on BrainGateway {
  Future<MemorySearchResult> searchMemory(String query, {int? limit}) {
    final gateway = this;
    if (gateway is BrainGraphGateway) {
      return gateway.searchMemory(query, limit: limit);
    }
    return Future<MemorySearchResult>.error(
      StateError('not implemented'),
    );
  }

  Future<GraphNodeDetail> getGraph(String recordId) {
    final gateway = this;
    if (gateway is BrainGraphGateway) {
      return gateway.getGraph(recordId);
    }
    return Future<GraphNodeDetail>.error(
      StateError('not implemented'),
    );
  }

  Future<GraphRefreshResult> refreshGraph(List<String> recordIds) {
    final gateway = this;
    if (gateway is BrainGraphGateway) {
      return gateway.refreshGraph(recordIds);
    }
    return Future<GraphRefreshResult>.error(
      StateError('not implemented'),
    );
  }
}
