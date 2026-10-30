import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/src/explore/explore_controller.dart';
import 'package:second_brain_mobile/src/explore/graph_canvas.dart';
import 'package:second_brain_mobile/src/gateway/brain_gateway.dart';
import 'package:second_brain_mobile/src/gateway/models.dart';
import 'package:second_brain_mobile/src/persistence/models.dart';
import 'package:second_brain_mobile/src/screens/explore_screen.dart';

void main() {
  for (final destination in [1, 3, 4]) {
    testWidgets('Parallel edges remain tappable toward node $destination',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1000, 700));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final nodes = List.generate(
        5,
        (index) => WorkspaceNode(
          node:
              GraphNode(id: 'entity:$index', table: 'entity', name: 'N$index'),
        ),
      );
      final selected = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: GraphCanvas(
            height: 560,
            state: ExploreWorkspaceState(
              status: WorkspaceItemStatus.loaded,
              nodes: nodes,
              edges: [
                WorkspaceEdge(
                  edge: LinkedEdge(
                    id: 'references:a',
                    table: 'references',
                    from: 'entity:0',
                    to: 'entity:$destination',
                    context: 'First connection',
                  ),
                ),
                WorkspaceEdge(
                  edge: LinkedEdge(
                    id: 'references:b',
                    table: 'references',
                    from: 'entity:$destination',
                    to: 'entity:0',
                    context: 'Second connection',
                  ),
                ),
              ],
            ),
            onSelectEdge: selected.add,
          ),
        ),
      ));
      final first = find.byTooltip('First connection → N$destination');
      final second = find.byTooltip('Second connection → N0');
      expect(tester.getRect(first).overlaps(tester.getRect(second)), isFalse);
      await tester.tap(first);
      await tester.tap(second);
      expect(selected, ['references:a', 'references:b']);
    });
  }

  testWidgets('Empty submission does not strand an active search',
      (tester) async {
    final gateway = _SearchGateway();
    await tester.pumpWidget(MaterialApp(
      home: ExploreScreen(controller: _EmptyController(), gateway: gateway),
    ));
    await tester.enterText(find.byType(TextField), 'garden');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pump();
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    await tester.enterText(find.byType(TextField), '   ');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pump();
    gateway.result
        .complete(const MemorySearchResult(nodes: [], unprocessed: []));
    await tester.pumpAndSettle();
    expect(find.byType(LinearProgressIndicator), findsNothing);
  });
}

final class _SearchGateway implements BrainGraphGateway {
  final result = Completer<MemorySearchResult>();

  @override
  Future<MemorySearchResult> searchMemory(String query, {int? limit}) =>
      result.future;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

final class _EmptyController implements ExploreWorkspaceController {
  @override
  ExploreWorkspaceState get state => ExploreWorkspaceState(
        status: WorkspaceItemStatus.loaded,
        nodes: const [],
        edges: const [],
      );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
