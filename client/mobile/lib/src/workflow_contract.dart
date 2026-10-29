import 'gateway/brain_gateway.dart';
import 'gateway/models.dart';
import 'persistence/models.dart';
import 'persistence/mobile_store.dart';
import 'persistence/repositories.dart';
import 'explore/explore_controller.dart';
import 'sync/sync_engine.dart';

export 'persistence/mobile_store.dart'
    show LegacyMobileData, MobileStore, openMobileStore;

SyncEngine createSyncEngine(MobileStore store) =>
    throw UnimplementedError('not implemented');

Future<ExploreWorkspaceController> createExploreController({
  required String brainId,
  required GraphWorkspaceRepository workspaces,
  required BrainGateway gateway,
}) =>
    throw UnimplementedError('not implemented');

/// Foreground journeys. Time and capture identity come from injected sources.
/// Capture returns after durable enqueue, without waiting for transport.
/// Ask saves successful answers before returning. Reopen reads only local data.
/// Graph links always use their source brain, not the active brain.
abstract interface class MobileWorkflow {
  String get composerText;
  void compose(String text);
  Future<OutboxEntry> capture();
  Future<SyncReport> appOpened();
  Future<SyncReport> appResumed();
  Future<AnswerSnapshot> ask(String question);
  Future<AnswerSnapshot> reopenAnswer(String brainId, String snapshotId);
  Future<GraphNodeDetail> openGraphLink(String brainId, String nodeId);

  /// Returns cached controller state without waiting for network refresh.
  /// Refreshes expanded nodes once per brain during this workflow's lifetime.
  Future<ExploreWorkspaceController> visitExplore(String brainId);
}

MobileWorkflow createMobileWorkflow({
  required MobileStore store,
  required GatewayForProfile gatewayFor,
  required DateTime Function() now,
  required String Function() newKey,
}) =>
    throw UnimplementedError('not implemented');
