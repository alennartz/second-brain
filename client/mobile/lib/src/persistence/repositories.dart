import 'models.dart';

/// Stores Brain profiles and the active profile selection.
abstract interface class BrainProfileRepository {
  Future<List<BrainProfile>> list();

  Future<BrainProfile?> active();

  /// Adds a profile in the [BrainProfileStatus.neverConnected] state.
  Future<void> add(BrainProfileDraft draft);

  /// Replaces the address and clears Access credentials.
  ///
  /// A supplied credential pair replaces the old pair after it is cleared.
  Future<void> updateAddress(
    String id,
    String url, {
    ({String clientId, String clientSecret})? credentials,
  });

  Future<void> markConnected(String id);

  Future<void> use(String id);
}

/// Stores Capture entries for every Brain profile.
abstract interface class CaptureOutboxRepository {
  Future<List<OutboxEntry>> pendingAll();

  Future<OutboxEntry> enqueue(
    String brainId,
    String text,
    String idempotencyKey,
    String capturedAt,
  );

  /// Keeps the idempotency key and marks the entry as edited.
  Future<void> updateText(String id, String text);

  Future<void> markAccepted(String id);

  /// The original request was accepted. The edited text remains recoverable.
  Future<void> markConflict(String id);

  /// Creates a deliberate new capture with a new idempotency key.
  Future<void> requeueAsNew(String id);
}

/// Stores successful Ask snapshots without reading live graph records.
abstract interface class AnswerSnapshotRepository {
  Future<void> save(String brainId, AnswerSnapshot snapshot);

  Future<List<AnswerSnapshot>> find(String brainId, String query);

  Future<void> delete(String id);
}

/// Stores one Explore workspace per Brain profile.
abstract interface class GraphWorkspaceRepository {
  Future<Workspace?> load(String brainId);

  Future<void> save(String brainId, Workspace workspace);
}

/// Interface-only repository stubs used until the sqflite adapter is added.
final class BrainProfileRepositoryStub implements BrainProfileRepository {
  const BrainProfileRepositoryStub();

  @override
  Future<List<BrainProfile>> list() =>
      throw UnimplementedError('not implemented');

  @override
  Future<BrainProfile?> active() => throw UnimplementedError('not implemented');

  @override
  Future<void> add(BrainProfileDraft draft) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> updateAddress(
    String id,
    String url, {
    ({String clientId, String clientSecret})? credentials,
  }) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> markConnected(String id) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> use(String id) => throw UnimplementedError('not implemented');
}

final class CaptureOutboxRepositoryStub implements CaptureOutboxRepository {
  const CaptureOutboxRepositoryStub();

  @override
  Future<List<OutboxEntry>> pendingAll() =>
      throw UnimplementedError('not implemented');

  @override
  Future<OutboxEntry> enqueue(
    String brainId,
    String text,
    String idempotencyKey,
    String capturedAt,
  ) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> updateText(String id, String text) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> markAccepted(String id) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> markConflict(String id) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> requeueAsNew(String id) =>
      throw UnimplementedError('not implemented');
}

final class AnswerSnapshotRepositoryStub implements AnswerSnapshotRepository {
  const AnswerSnapshotRepositoryStub();

  @override
  Future<void> save(String brainId, AnswerSnapshot snapshot) =>
      throw UnimplementedError('not implemented');

  @override
  Future<List<AnswerSnapshot>> find(String brainId, String query) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> delete(String id) => throw UnimplementedError('not implemented');
}

final class GraphWorkspaceRepositoryStub implements GraphWorkspaceRepository {
  const GraphWorkspaceRepositoryStub();

  @override
  Future<Workspace?> load(String brainId) =>
      throw UnimplementedError('not implemented');

  @override
  Future<void> save(String brainId, Workspace workspace) =>
      throw UnimplementedError('not implemented');
}
