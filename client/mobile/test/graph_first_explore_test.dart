import 'dart:async';
import 'dart:ui' show SemanticsAction;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/src/explore/explore_controller.dart';
import 'package:second_brain_mobile/src/explore/graph_canvas.dart';
import 'package:second_brain_mobile/src/gateway/brain_gateway.dart';
import 'package:second_brain_mobile/src/gateway/models.dart';
import 'package:second_brain_mobile/src/persistence/models.dart';
import 'package:second_brain_mobile/src/persistence/repositories.dart';
import 'package:second_brain_mobile/src/screens/explore_screen.dart';
import 'package:second_brain_mobile/src/screens/graph_node_detail_screen.dart';

const garden = GraphNode(
  id: 'entity:private-garden-id',
  table: 'entity',
  name: 'Garden',
);
const soil = GraphNode(
  id: 'entity:private-soil-id',
  table: 'entity',
  name: 'Soil',
);
const compost = GraphNode(
  id: 'note:private-compost-id',
  table: 'note',
  summary: 'Compost',
);
const gardenSoil = LinkedEdge(
  id: 'references:private-edge-id',
  table: 'references',
  from: 'entity:private-garden-id',
  to: 'entity:private-soil-id',
);
const soilCompost = LinkedEdge(
  id: 'relates_to:private-compost-edge-id',
  table: 'relates_to',
  from: 'entity:private-soil-id',
  to: 'note:private-compost-id',
);

void main() {
  Future<ExploreWorkspaceControllerImpl> launch(
      WidgetTester tester, _Gateway gateway,
      {Workspace? initialWorkspace, bool startRefresh = false}) async {
    await tester.binding.setSurfaceSize(const Size(390, 750));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final controller = ExploreWorkspaceControllerImpl(
      brainId: 'home',
      workspaces: _Workspaces(),
      gateway: gateway,
      initialWorkspace: initialWorkspace,
    );
    if (startRefresh) unawaited(controller.refresh());
    await tester.pumpWidget(MaterialApp(
      home: ExploreScreen(controller: controller, gateway: gateway),
    ));
    return controller;
  }

  Future<void> search(WidgetTester tester) async {
    await tester.enterText(find.byType(TextField), 'garden');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pump();
  }

  testWidgets('search shows named matches on the map before refresh completes',
      (tester) async {
    final gateway = _Gateway()..refreshGate = Completer<GraphRefreshResult>();
    await launch(tester, gateway);
    await search(tester);
    await tester.pump(const Duration(milliseconds: 100));
    expect(
        find.descendant(
            of: find.byType(GraphCanvas), matching: find.text('Garden')),
        findsOneWidget);
    final map = find.byType(GraphCanvas);
    final match = find.descendant(of: map, matching: find.text('Garden'));
    expect(tester.getRect(map).contains(tester.getCenter(match)), isTrue);
    expect(find.text('Graph results'), findsNothing);
    expect(find.byType(GraphNodeDetailScreen), findsNothing);
    expect(tester.takeException(), isNull);
    gateway.refreshGate!.complete(_Gateway.connections);
    await tester.pumpAndSettle();
    expect(
        find.descendant(
            of: find.byType(GraphCanvas), matching: find.text('Soil')),
        findsOneWidget);
    expect(visibleText(tester), isNot(contains('private-')));
  });

  testWidgets(
      'failed refresh keeps search matches and hides server identifiers',
      (tester) async {
    final gateway = _Gateway()..refreshGate = Completer<GraphRefreshResult>();
    await launch(tester, gateway);
    await search(tester);
    await tester.pump(const Duration(milliseconds: 100));
    gateway.refreshGate!
        .completeError(StateError('Missing note:private-server-id'));
    await tester.pumpAndSettle();
    expect(
        find.descendant(
            of: find.byType(GraphCanvas), matching: find.text('Garden')),
        findsOneWidget);
    expect(visibleText(tester), isNot(contains('private-server-id')));
    expect(find.byType(LinearProgressIndicator), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a search refreshes new matches after an older refresh',
      (tester) async {
    final gateway = _Gateway()
      ..oldRefreshGate = Completer<GraphRefreshResult>();
    final controller = await launch(tester, gateway,
        initialWorkspace: const Workspace(
            nodes: [WorkspaceNode(node: soil, expanded: true)], edges: []),
        startRefresh: true);
    await search(tester);
    await tester.pump(const Duration(milliseconds: 100));
    gateway.oldRefreshGate!.complete(const GraphRefreshResult(results: [
      GraphRefreshFound(
          id: 'entity:private-soil-id', node: soil, connections: []),
    ]));
    await tester.pumpAndSettle();
    expect(controller.state.edges.any((item) => item.edge.id == gardenSoil.id),
        isTrue);
    expect(tester.takeException(), isNull);
  });

  test('the latest node selection survives out-of-order responses', () async {
    final gateway = _Gateway();
    final firstReply = Completer<GraphNodeDetail>();
    final secondReply = Completer<GraphNodeDetail>();
    gateway.nodeReads[garden.id] = firstReply;
    gateway.nodeReads[soil.id] = secondReply;
    final controller = ExploreWorkspaceControllerImpl(
        brainId: 'home', workspaces: _Workspaces(), gateway: gateway);
    final first = controller.openNode(garden.id);
    final second = controller.openNode(soil.id);
    secondReply.complete(const GraphNodeDetail(node: soil, connections: []));
    await second;
    firstReply.complete(const GraphNodeDetail(node: garden, connections: []));
    await first;
    expect(controller.state.selectedNodeId, soil.id);
    expect(controller.state.nodes.map((item) => item.node.id),
        containsAll([garden.id, soil.id]));
  });

  testWidgets('clearing the workspace cancels a pending search',
      (tester) async {
    final gateway = _Gateway()..searchGate = Completer<MemorySearchResult>();
    final controller = await launch(tester, gateway,
        initialWorkspace: const Workspace(
            nodes: [WorkspaceNode(node: soil, expanded: true)], edges: []));
    await search(tester);
    await tester.tap(find.byTooltip('Workspace options'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('Clear workspace'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.widgetWithText(FilledButton, 'Clear workspace'));
    await tester.pump();
    gateway.searchGate!
        .complete(const MemorySearchResult(nodes: [garden], unprocessed: []));
    await tester.pumpAndSettle();
    expect(controller.state.nodes, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('the empty graph stays usable with the keyboard open',
      (tester) async {
    tester.view.physicalSize = const Size(390, 750);
    tester.view.devicePixelRatio = 1;
    tester.view.viewInsets = const FakeViewPadding(bottom: 400);
    addTearDown(tester.view.reset);
    await launch(tester, _Gateway());
    await tester.enterText(find.byType(TextField), 'garden');
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('graph opens as a full-screen route with move controls',
      (tester) async {
    await launch(
      tester,
      _Gateway(),
      initialWorkspace: const Workspace(
        nodes: [WorkspaceNode(node: garden, expanded: true)],
        edges: [],
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Full-screen graph'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Exit full-screen graph'), findsOneWidget);
    expect(find.byTooltip('Move nodes'), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
    await tester.tap(find.byTooltip('Exit full-screen graph'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Full-screen graph'), findsOneWidget);
  });

  testWidgets('connections expose an accessibility tap action', (tester) async {
    final semantics = tester.ensureSemantics();
    try {
      await launch(tester, _Gateway());
      await search(tester);
      await tester.pumpAndSettle();
      final connection = find.bySemanticsLabel(RegExp(r'^References → Soil'));
      expect(
          tester
              .getSemantics(connection)
              .getSemanticsData()
              .hasAction(SemanticsAction.tap),
          isTrue);
    } finally {
      semantics.dispose();
    }
  });

  testWidgets('following a connection stays on the map; details are explicit',
      (tester) async {
    await launch(tester, _Gateway());
    await search(tester);
    await tester.pumpAndSettle();
    await tester.tap(find.byWidgetPredicate((widget) =>
        widget is Tooltip &&
        (widget.message?.startsWith('References → Soil') ?? false)));
    await tester.pumpAndSettle();
    expect(find.byType(GraphNodeDetailScreen), findsNothing);
    expect(
        find.descendant(
            of: find.byType(GraphCanvas), matching: find.text('Compost')),
        findsOneWidget);
    expect(visibleText(tester), isNot(contains('private-')));
    await tester.tap(find.text('Details'));
    await tester.pumpAndSettle();
    expect(find.byType(GraphNodeDetailScreen), findsOneWidget);
    expect(visibleText(tester), isNot(contains('private-')));
    expect(tester.takeException(), isNull);
  });
}

String visibleText(WidgetTester tester) => tester
    .widgetList<Text>(find.byType(Text))
    .map((widget) => widget.data ?? widget.textSpan?.toPlainText() ?? '')
    .join('\n');

final class _Workspaces implements GraphWorkspaceRepository {
  Workspace? saved;
  @override
  Future<Workspace?> load(String brainId) async => saved;
  @override
  Future<void> save(String brainId, Workspace workspace) async {
    saved = workspace;
  }
}

final class _Gateway implements BrainGraphGateway {
  Completer<GraphRefreshResult>? refreshGate;
  Completer<GraphRefreshResult>? oldRefreshGate;
  Completer<MemorySearchResult>? searchGate;
  final nodeReads = <String, Completer<GraphNodeDetail>>{};
  static const connections = GraphRefreshResult(results: [
    GraphRefreshFound(
        id: 'entity:private-garden-id',
        node: garden,
        connections: [
          GraphConnection(edge: gardenSoil, node: soil),
        ]),
  ]);
  @override
  Future<MemorySearchResult> searchMemory(String query, {int? limit}) =>
      searchGate?.future ??
      Future.value(const MemorySearchResult(nodes: [garden], unprocessed: []));
  @override
  Future<GraphRefreshResult> refreshGraph(List<String> ids) =>
      !ids.contains(garden.id) && oldRefreshGate != null
          ? oldRefreshGate!.future
          : refreshGate?.future ?? Future.value(connections);
  @override
  Future<GraphNodeDetail> getGraph(String recordId) async {
    final pending = nodeReads[recordId];
    if (pending != null) return pending.future;
    return recordId == soil.id
        ? const GraphNodeDetail(node: soil, connections: [
            GraphConnection(edge: gardenSoil, node: garden),
            GraphConnection(edge: soilCompost, node: compost),
          ])
        : const GraphNodeDetail(node: garden, connections: [
            GraphConnection(edge: gardenSoil, node: soil),
          ]);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
