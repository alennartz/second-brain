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

  /// Keeps the idempotency key and retains conflicts when editing.
  Future<void> updateText(String id, String text);

  Future<void> markAccepted(String id);

  /// Removes an entry only when the delivered version is still stored.
  Future<bool> markAcceptedIfUnchanged(
    String id, {
    required String sentKey,
    required String sentText,
  });

  /// The original request was accepted. The edited text remains recoverable.
  Future<void> markConflict(String id);

  /// Creates a deliberate new capture with a new idempotency key.
  Future<void> requeueAsNew(String id);

  /// Deletes a retained conflict without resubmitting it.
  Future<void> discardConflict(String id);
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
