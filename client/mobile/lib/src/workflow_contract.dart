import 'gateway/brain_gateway.dart';
import 'persistence/mobile_store.dart';
import 'persistence/repositories.dart';
import 'explore/explore_controller.dart';
import 'mobile_workflow.dart';
import 'sync/sync_engine.dart';

export 'mobile_workflow.dart';
export 'persistence/mobile_store.dart'
    show LegacyMobileData, MobileStore, openMobileStore;

SyncEngine createSyncEngine(MobileStore store) =>
    SyncEngineImpl(profiles: store.profiles, outbox: store.outbox);

Future<ExploreWorkspaceController> createExploreController({
  required String brainId,
  required GraphWorkspaceRepository workspaces,
  required BrainGateway gateway,
}) =>
    ExploreWorkspaceControllerImpl.load(
      brainId: brainId,
      workspaces: workspaces,
      gateway: gateway,
    );

MobileWorkflow createMobileWorkflow({
  required MobileStore store,
  required GatewayForProfile gatewayFor,
  required DateTime Function() now,
  required String Function() newKey,
}) =>
    MobileWorkflowImpl(
      store: store,
      gatewayFor: gatewayFor,
      now: now,
      newKey: newKey,
    );
