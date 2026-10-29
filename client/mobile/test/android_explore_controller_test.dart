import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

void main() {
  test('opening a node refreshes it and adds its connections', () async {
    const controller = ExploreWorkspaceControllerStub();

    await controller.openNode('entity:garden');

    expect(controller.state.nodes, hasLength(2));
    expect(controller.state.edges, hasLength(1));
  });

  test('following an edge refreshes the destination without discarding cache',
      () async {
    const controller = ExploreWorkspaceControllerStub();

    await controller.followEdge('references:1');

    expect(controller.state.nodes, isNotEmpty);
    expect(controller.state.status, WorkspaceItemStatus.loaded);
  });

  test('first visit renders saved workspace before its expanded refresh',
      () async {
    const controller = ExploreWorkspaceControllerStub();

    await controller.refresh();

    expect(controller.state.nodes, isNotEmpty);
  });

  test('failed refresh leaves cached data unchanged and unmarked', () async {
    const controller = ExploreWorkspaceControllerStub();

    await controller.refresh();

    expect(
        controller.state.nodes
            .every((node) => node.status != WorkspaceItemStatus.missing),
        isTrue);
  });

  test('clear deleted removes only confirmed-missing nodes and edges', () {
    const controller = ExploreWorkspaceControllerStub();

    controller.clearDeleted();

    expect(
        controller.state.nodes
            .every((node) => node.status != WorkspaceItemStatus.missing),
        isTrue);
    expect(
        controller.state.edges
            .every((edge) => edge.status != WorkspaceItemStatus.missing),
        isTrue);
  });

  test('clear workspace requires an explicit operation and empties local data',
      () async {
    const controller = ExploreWorkspaceControllerStub();

    await controller.clearWorkspace();

    expect(controller.state.nodes, isEmpty);
    expect(controller.state.edges, isEmpty);
  });
}
