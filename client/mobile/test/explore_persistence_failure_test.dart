import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

import 'android_contract_fixtures.dart';

void main() {
  test('failed workspace saves restore the last durable projection', () async {
    final repository = FailingWorkspaces();
    final controller = ExploreWorkspaceControllerImpl(
      brainId: 'home',
      workspaces: repository,
      gateway: ControlledGateway(),
    );
    await controller.openNode(garden.id);
    repository.fail = true;

    await expectLater(controller.clearWorkspace(), throwsStateError);
    expect(controller.state.nodes.map((item) => item.node.id),
        contains(garden.id));
    expect((await repository.load('home'))!.nodes.map((item) => item.node.id),
        contains(garden.id));

    repository.fail = false;
    await controller.clearWorkspace();
    expect(controller.state.nodes, isEmpty);
    expect((await repository.load('home'))!.nodes, isEmpty);
  });

  test('failed initial node save leaves an empty workspace', () async {
    final repository = FailingWorkspaces()..fail = true;
    final controller = ExploreWorkspaceControllerImpl(
      brainId: 'home',
      workspaces: repository,
      gateway: ControlledGateway(),
    );
    await expectLater(controller.openNode(garden.id), throwsStateError);
    expect(controller.state.nodes, isEmpty);
    expect(await repository.load('home'), isNull);
  });
}

final class FailingWorkspaces implements GraphWorkspaceRepository {
  bool fail = false;
  Workspace? workspace;

  @override
  Future<Workspace?> load(String brainId) async => workspace;

  @override
  Future<void> save(String brainId, Workspace workspace) async {
    if (fail) throw StateError('Storage unavailable');
    this.workspace = workspace;
  }
}
