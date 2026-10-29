import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'android_contract_fixtures.dart';

void main() {
  late Directory root;
  late MobileStore store;
  late String home;
  late ControlledGateway gateway;
  setUp(() async {
    root = await Directory.systemTemp.createTemp('explore-contract-');
    addTearDown(() => root.delete(recursive: true));
    store = await openMobileStore('${root.path}/mobile.db');
    addTearDown(() => store.close());
    home = await addBrain(store);
    gateway = ControlledGateway();
    await store.workspaces.save(
        home,
        const Workspace(nodes: [
          WorkspaceNode(node: garden, expanded: true),
          WorkspaceNode(node: layout)
        ], edges: [
          WorkspaceEdge(edge: edge)
        ]));
  });
  Future<ExploreWorkspaceController> controller() => createExploreController(
      brainId: home, workspaces: store.workspaces, gateway: gateway);

  test(
      'opening and following nodes merges directed connections and preserves existing nodes',
      () async {
    final c = await controller();
    await c.openNode(garden.id);
    expect(c.state.nodes.map((n) => n.node.id),
        containsAll([garden.id, layout.id]));
    expect(c.state.edges.map((e) => e.edge.id), contains(edge.id));
    gateway.nodeDetail = const GraphNodeDetail(node: layout, connections: []);
    await c.followEdge(edge.id);
    expect(c.state.nodes.singleWhere((n) => n.node.id == layout.id).expanded,
        isTrue);
    expect(c.state.nodes.map((n) => n.node.id), contains(garden.id));
  });
  test(
      'refresh adds edges without expanding unloaded destinations and reuses loaded destinations',
      () async {
    const newNode = GraphNode(id: 'entity:new', table: 'entity', name: 'New');
    const newEdge = LinkedEdge(
        id: 'references:2',
        table: 'references',
        from: 'entity:garden',
        to: 'entity:new');
    gateway.refreshResult = const GraphRefreshResult(results: [
      GraphRefreshFound(id: 'entity:garden', node: garden, connections: [
        GraphConnection(edge: edge, node: layout),
        GraphConnection(edge: newEdge, node: newNode)
      ])
    ]);
    final c = await controller();
    await c.refresh();
    expect(c.state.edges.map((e) => e.edge.id),
        containsAll([edge.id, newEdge.id]));
    expect(c.state.nodes.where((n) => n.node.id == layout.id), hasLength(1));
    expect(
        c.state.nodes
            .where((n) => n.node.id == newNode.id)
            .every((n) => !n.expanded),
        isTrue);
    expect(c.state.edges.singleWhere((e) => e.edge.id == newEdge.id).status,
        WorkspaceItemStatus.newItem);
  });
  test('failed refresh retains cached node and edge content and status',
      () async {
    final c = await controller();
    gateway.failure = const NetworkException('offline');
    try {
      await c.refresh();
    } on BrainClientException {/* cached state remains available */}
    expect(c.state.nodes.map((n) => n.node.id),
        containsAll([garden.id, layout.id]));
    expect(c.state.nodes.every((n) => n.status == WorkspaceItemStatus.loaded),
        isTrue);
    expect(c.state.edges.single.edge.id, edge.id);
    expect(c.state.edges.single.status, WorkspaceItemStatus.loaded);
  });
  test(
      'confirmed missing nodes and absent edges stay dimmed until local clear-deleted',
      () async {
    gateway.refreshResult = const GraphRefreshResult(
        results: [GraphRefreshMissing(id: 'entity:garden')]);
    final c = await controller();
    await c.refresh();
    expect(c.state.nodes.singleWhere((n) => n.node.id == garden.id).status,
        WorkspaceItemStatus.missing);
    expect(c.state.edges.single.status, WorkspaceItemStatus.missing);
    gateway.failure = StateError('clear must remain local');
    c.clearDeleted();
    expect(c.state.nodes.map((n) => n.node.id), [layout.id]);
    expect(c.state.edges, isEmpty);
  });
  test(
      'found refresh marks removed connections missing rather than erasing cached edges',
      () async {
    gateway.refreshResult = const GraphRefreshResult(results: [
      GraphRefreshFound(id: 'entity:garden', node: garden, connections: [])
    ]);
    final c = await controller();
    await c.refresh();
    expect(c.state.edges.single.edge.id, edge.id);
    expect(c.state.edges.single.status, WorkspaceItemStatus.missing);
    expect(c.state.nodes.singleWhere((n) => n.node.id == layout.id).status,
        WorkspaceItemStatus.loaded);
  });
  test('canvas and detail share selected node and loaded data', () async {
    final c = await controller();
    c.selectNode(layout.id);
    expect(c.state.selectedNodeId, layout.id);
    expect(
        c.state.nodes
            .singleWhere((n) => n.node.id == c.state.selectedNodeId)
            .node
            .content,
        layout.content);
    c.selectNode(garden.id);
    expect(c.state.selectedNodeId, garden.id);
    expect(c.state.edges.single.edge.to, layout.id);
  });
  test('explicit clear persists an empty workspace without server requests',
      () async {
    final c = await controller();
    gateway.failure = StateError('offline');
    await c.clearWorkspace();
    expect(c.state.nodes, isEmpty);
    expect(c.state.edges, isEmpty);
    final reopened = await controller();
    expect(reopened.state.nodes, isEmpty);
    expect(reopened.state.edges, isEmpty);
  });
}
