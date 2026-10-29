import 'dart:async';

import 'explore/explore_controller.dart';
import 'gateway/brain_gateway.dart';
import 'gateway/models.dart';
import 'persistence/models.dart';
import 'persistence/mobile_store.dart';
import 'sync/sync_engine.dart';

/// Owns the durable Capture and one-shot Ask journeys for one app launch.
///
/// The workflow keeps only transient composer text and Explore controllers in
/// memory. Capture entries, Ask snapshots, and workspaces belong to [store].
abstract interface class MobileWorkflow {
  String get composerText;

  void compose(String text);

  Future<OutboxEntry> capture();

  Future<SyncReport> appOpened();

  Future<SyncReport> appResumed();

  Future<AnswerSnapshot> ask(String question);

  Future<AnswerSnapshot> reopenAnswer(String brainId, String snapshotId);

  Future<GraphNodeDetail> openGraphLink(String brainId, String nodeId);

  /// Returns cached controller state without waiting for a network refresh.
  ///
  /// The first visit for a brain schedules one automatic refresh of its
  /// expanded nodes. Later visits reuse the same controller for this workflow.
  Future<ExploreWorkspaceController> visitExplore(String brainId);
}

/// Concrete implementation of the foreground mobile journeys.
final class MobileWorkflowImpl implements MobileWorkflow {
  MobileWorkflowImpl({
    required MobileStore store,
    required GatewayForProfile gatewayFor,
    required DateTime Function() now,
    required String Function() newKey,
    SyncEngine? syncEngine,
  })  : _store = store,
        _gatewayFor = gatewayFor,
        _now = now,
        _newKey = newKey,
        _syncEngine = syncEngine ??
            SyncEngineImpl(profiles: store.profiles, outbox: store.outbox);

  final MobileStore _store;
  final GatewayForProfile _gatewayFor;
  final DateTime Function() _now;
  final String Function() _newKey;
  final SyncEngine _syncEngine;

  String _composerText = '';
  final Map<String, Future<ExploreWorkspaceController>> _exploreControllers =
      <String, Future<ExploreWorkspaceController>>{};
  final Set<String> _autoRefreshBrains = <String>{};

  // Foreground sync calls are serialized. A Capture can start delivery without
  // delaying the durable enqueue, while app-open and resume observe a stable
  // pass after earlier delivery completes.
  Future<void> _syncTail = Future<void>.value();

  @override
  String get composerText => _composerText;

  @override
  void compose(String text) {
    _composerText = text;
  }

  @override
  Future<OutboxEntry> capture() async {
    final text = _composerText;
    if (text.trim().isEmpty) {
      throw StateError('Capture text cannot be empty');
    }

    final profile = await _activeProfile();
    final entry = await _store.outbox.enqueue(
      profile.id,
      text,
      _newKey(),
      _now().toIso8601String(),
    );

    // Reset only after the durable write succeeds. Delivery starts in the
    // background, so a slow or offline gateway never blocks the composer.
    if (_composerText == text) {
      _composerText = '';
    }
    _startSync();
    return entry;
  }

  @override
  Future<SyncReport> appOpened() => _runSync();

  @override
  Future<SyncReport> appResumed() => _runSync();

  @override
  Future<AnswerSnapshot> ask(String question) async {
    // Resolve the source before transport. A later profile switch cannot move
    // the snapshot or its graph links to a different Brain.
    final profile = await _activeProfile();
    final gateway = _gatewayFor(profile);
    final result = await gateway.recall(question);
    final snapshot = AnswerSnapshot(
      id: _newKey(),
      question: question,
      answer: result.answer,
      answeredAt: _now(),
      evidence: List<EvidenceItem>.unmodifiable(result.evidence),
    );
    await _store.answers.save(profile.id, snapshot);
    return snapshot;
  }

  @override
  Future<AnswerSnapshot> reopenAnswer(
    String brainId,
    String snapshotId,
  ) async {
    // Snapshot reopening is local-only by contract. The gateway factory is
    // intentionally absent from this path.
    final snapshots = await _store.answers.find(brainId, '');
    for (final snapshot in snapshots) {
      if (snapshot.id == snapshotId) return snapshot;
    }
    throw StateError('Unknown answer snapshot: $snapshotId');
  }

  @override
  Future<GraphNodeDetail> openGraphLink(String brainId, String nodeId) async {
    final profile = await _profileById(brainId);
    return _gatewayFor(profile).getGraph(nodeId);
  }

  @override
  Future<ExploreWorkspaceController> visitExplore(String brainId) {
    final cached = _exploreControllers[brainId];
    if (cached != null) return cached;

    final loading = _loadExplore(brainId);
    _exploreControllers[brainId] = loading;
    // A failed local load must not poison this workflow's cache forever. The
    // caller still receives the original error from [loading].
    loading.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {
        if (identical(_exploreControllers[brainId], loading)) {
          _exploreControllers.remove(brainId);
        }
      },
    );
    return loading;
  }

  Future<ExploreWorkspaceController> _loadExplore(String brainId) async {
    final profile = await _profileById(brainId);
    final controller = await ExploreWorkspaceControllerImpl.load(
      brainId: brainId,
      workspaces: _store.workspaces,
      gateway: _gatewayFor(profile),
    );

    if (_autoRefreshBrains.add(brainId)) {
      final refresh = controller.refresh();
      // The cached controller remains usable when transport is offline. The
      // caller can inspect [refreshCompleted] when it needs the outcome.
      unawaited(
        refresh.then<void>(
          (_) {},
          onError: (Object _, StackTrace __) {},
        ),
      );
    }
    return controller;
  }

  Future<BrainProfile> _activeProfile() async {
    final profile = await _store.profiles.active();
    if (profile == null) {
      throw StateError('No active Brain profile');
    }
    return profile;
  }

  Future<BrainProfile> _profileById(String brainId) async {
    final profiles = await _store.profiles.list();
    for (final profile in profiles) {
      if (profile.id == brainId) return profile;
    }
    throw StateError('Unknown Brain profile: $brainId');
  }

  void _startSync() {
    final sync = _runSync();
    unawaited(
      sync.then<void>(
        (_) {},
        onError: (Object _, StackTrace __) {},
      ),
    );
  }

  Future<SyncReport> _runSync() {
    final previous = _syncTail;
    final next = previous.then<SyncReport>(
      (_) => _syncEngine.syncAll(_gatewayFor),
    );
    _syncTail = next.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    return next;
  }
}
