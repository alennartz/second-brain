import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/src/explore/explore_controller.dart';
import 'package:second_brain_mobile/src/gateway/models.dart';
import 'package:second_brain_mobile/src/persistence/models.dart';
import 'package:second_brain_mobile/src/screens/graph_node_detail_screen.dart';
import 'package:second_brain_mobile/src/widgets/evidence_cards.dart';
import 'package:second_brain_mobile/src/widgets/memory_labels.dart';

const _planId = 'note:database-plan-731';
const _gardenId = 'entity:database-garden-842';
const _layoutId = 'note:database-layout-953';
const _untitledId = 'private_nodes:database-untitled-386';

const _plan = GraphNode(
  id: _planId,
  table: 'note',
  name: 'Seed plan',
  summary: 'Spring planting',
  content: 'Plant seeds near the shed. Keep the path clear.',
);
const _garden = GraphNode(
  id: _gardenId,
  table: 'entity',
  name: 'Garden',
);
const _layout = GraphNode(
  id: _layoutId,
  table: 'note',
  summary: 'Shed layout',
  content: 'Leave room for tools.',
);
const _gardenLink = LinkedEdge(
  id: 'located_in:database-edge-164',
  table: 'located_in',
  from: _planId,
  to: _gardenId,
  context: '  Plant vegetables here.\nLeave a path.  ',
);
const _layoutLink = LinkedEdge(
  id: 'supports_plan:database-edge-275',
  table: 'supports_plan',
  from: _layoutId,
  to: _planId,
  context: 'The shed layout guides planting.',
);
const _untitled = GraphNode(
  id: _untitledId,
  table: 'private_nodes',
  name: '   ',
  summary: '\n',
  content: '  ',
);
const _unknownLink = LinkedEdge(
  id: 'related_to:database-edge-497',
  table: 'related_to',
  from: _planId,
  to: 'entity:database-unloaded-508',
  context: 'A connection saved without its target.',
);
const _chunk = IntakeChunk(
  id: 'intake_chunk:database-chunk-619',
  intakeId: 'intake:database-intake-720',
  chunkPosition: 1,
  totalChunks: 3,
  content: 'Remember to water the seedlings.',
  source: 'mobile',
  hints: ['weekly watering'],
  isUnprocessed: true,
);

void main() {
  test('Memory titles prefer names, summaries, and the first content sentence',
      () {
    expect(memoryTitle(_plan), 'Seed plan');
    expect(memoryTitle(_layout), 'Shed layout');
    expect(
      memoryTitle(const GraphNode(
        id: 'note:database-content-only',
        table: 'note',
        name: ' ',
        summary: '\n',
        content: '  Behind the shed. Keep the gate clear.  ',
      )),
      'Behind the shed',
    );
    expect(
      memoryTitle(const GraphNode(
        id: 'entity:database-spaces',
        table: 'entity',
        name: ' Garden ',
      )),
      'Garden',
    );
    expect(memoryTitle(_untitled), 'Untitled memory');
    expect(
      memoryTitle(const GraphNode(id: 'note:database-empty', table: 'note')),
      'Untitled memory',
    );
    expect(connectedMemoryTitle(null), 'Connected memory');
    expect(connectedMemoryTitle(_untitled), 'Connected memory');
    expect(connectedMemoryTitle(_garden), 'Garden');
  });

  test('Content titles remain short', () {
    final content = '${List.filled(40, 'Plant seeds').join(' ')}. Water them.';
    final title = memoryTitle(GraphNode(
      id: 'note:database-long-content',
      table: 'note',
      content: content,
    ));
    expect(title, startsWith('Plant seeds'));
    expect(title.length, lessThanOrEqualTo(120));
    expect(title, isNot(contains('Water them')));
  });

  test('Memory kinds and relationship titles use human language', () {
    expect(memoryKind(_plan), 'Note');
    expect(memoryKind(_garden), 'Concept');
    expect(memoryKind(_untitled), 'Memory');
    expect(
      relationshipTitle(const LinkedEdge(
        id: 'related_to:database-title',
        table: '  related__to   ',
        from: _planId,
        to: _gardenId,
        context: 'This context is not the relationship name.',
      )),
      'Related to',
    );
    expect(
      relationshipTitle(const LinkedEdge(
        id: 'database-empty-relationship',
        table: ' ',
        from: _planId,
        to: _gardenId,
      )),
      'Connection',
    );
  });

  testWidgets('Detail uses connection names and preserves content and context',
      (tester) async {
    await _show(
        tester,
        const GraphNodeDetailScreen(
          node: _plan,
          connections: [
            GraphConnection(edge: _gardenLink, node: _garden),
            GraphConnection(edge: _layoutLink, node: _layout),
          ],
        ));

    expect(find.text('Seed plan'), findsOneWidget);
    expect(find.text('Note'), findsOneWidget);
    expect(find.textContaining('Garden'), findsOneWidget);
    expect(find.textContaining('Shed layout'), findsOneWidget);
    expect(find.textContaining('Located in'), findsOneWidget);
    expect(find.textContaining('Supports plan'), findsOneWidget);
    expect(find.text(_plan.content!), findsOneWidget);
    expect(find.text(_gardenLink.context!), findsOneWidget);
    expect(find.text(_layoutLink.context!), findsOneWidget);
    expect(find.text(_plan.table), findsNothing);
    _expectNoIds([
      _plan.id,
      _garden.id,
      _layout.id,
      _gardenLink.id,
      _layoutLink.id,
    ]);
  });

  testWidgets('Detail resolves workspace and supplied connection names',
      (tester) async {
    final controller = _LoadedWorkspace(
      nodes: const [
        WorkspaceNode(node: _plan),
        WorkspaceNode(node: _garden),
      ],
      edges: const [
        WorkspaceEdge(edge: _gardenLink, status: WorkspaceItemStatus.newItem),
        WorkspaceEdge(edge: _layoutLink, status: WorkspaceItemStatus.missing),
        WorkspaceEdge(edge: _unknownLink),
      ],
    );
    await _show(
        tester,
        GraphNodeDetailScreen(
          controller: controller,
          nodeId: _plan.id,
          connections: const [
            GraphConnection(edge: _layoutLink, node: _layout)
          ],
        ));

    expect(find.textContaining('Garden'), findsOneWidget);
    expect(find.textContaining('Shed layout'), findsOneWidget);
    expect(find.textContaining('Connected memory'), findsOneWidget);
    expect(find.text('New'), findsOneWidget);
    expect(find.text('Missing'), findsOneWidget);
    expect(find.text(_gardenLink.context!), findsOneWidget);
    expect(find.text(_unknownLink.context!), findsOneWidget);
    expect(tester.takeException(), isNull);
    _expectNoIds([
      _plan.id,
      _garden.id,
      _layout.id,
      _gardenLink.id,
      _layoutLink.id,
      _unknownLink.id,
      _unknownLink.to,
    ]);
  });

  testWidgets('Detail uses human fallbacks when metadata is absent',
      (tester) async {
    const neighbor = GraphNode(
      id: 'private_nodes:database-neighbor-831',
      table: 'private_nodes',
    );
    const link = LinkedEdge(
      id: 'private_edges:database-fallback-942',
      table: ' ',
      from: _untitledId,
      to: 'private_nodes:database-neighbor-831',
    );
    await _show(
        tester,
        const GraphNodeDetailScreen(
          node: _untitled,
          connections: [GraphConnection(edge: link, node: neighbor)],
        ));

    expect(find.text('Untitled memory'), findsOneWidget);
    expect(find.text('Memory'), findsWidgets);
    expect(find.textContaining(RegExp(r'^Connection(?:\W|$)')), findsOneWidget);
    expect(find.textContaining('Connected memory'), findsOneWidget);
    expect(find.text(_untitled.table), findsNothing);
    _expectNoIds([_untitled.id, neighbor.id, link.id]);
  });

  testWidgets('Evidence uses names and retains chunk content and provenance',
      (tester) async {
    await _show(
        tester,
        const Scaffold(
          body: SingleChildScrollView(
            child: EvidenceCards(evidence: [
              GraphNodeEvidence(node: _plan, links: [_gardenLink, _layoutLink]),
              GraphNodeEvidence(node: _garden, links: []),
              GraphNodeEvidence(node: _layout, links: []),
              UnprocessedEvidence(chunk: _chunk),
            ]),
          ),
        ));

    expect(find.text('Seed plan'), findsOneWidget);
    expect(find.text('Garden'), findsOneWidget);
    expect(find.text('Shed layout'), findsOneWidget);
    expect(find.text('Note'), findsWidgets);
    expect(find.text('Concept'), findsOneWidget);
    expect(find.textContaining('Located in'), findsOneWidget);
    expect(find.textContaining('Supports plan'), findsOneWidget);
    expect(find.textContaining('Connected memory'), findsNothing);
    expect(find.text(_plan.content!), findsOneWidget);
    expect(find.text(_gardenLink.context!), findsOneWidget);
    expect(find.text(_chunk.content), findsOneWidget);
    expect(find.text('Unprocessed'), findsOneWidget);
    expect(find.textContaining('mobile'), findsOneWidget);
    expect(find.textContaining('chunk 2 of 3'), findsOneWidget);
    expect(find.textContaining(_chunk.hints.single), findsOneWidget);
    expect(find.text(_plan.table), findsNothing);
    expect(find.text(_garden.table), findsNothing);
    _expectNoIds([
      _plan.id,
      _garden.id,
      _layout.id,
      _gardenLink.id,
      _layoutLink.id,
      _chunk.id,
      _chunk.intakeId,
    ]);
  });

  testWidgets('Evidence handles untitled and unloaded memories without IDs',
      (tester) async {
    const link = LinkedEdge(
      id: 'related_to:database-absent-053',
      table: 'related_to',
      from: _untitledId,
      to: 'entity:database-unloaded-164',
      context: 'Preserve this useful explanation.',
    );
    const contentNode = GraphNode(
      id: 'note:database-content-275',
      table: 'note',
      content: 'Water seedlings daily. Keep the soil moist.',
    );
    await _show(
        tester,
        const Scaffold(
          body: SingleChildScrollView(
            child: EvidenceCards(evidence: [
              GraphNodeEvidence(node: _untitled, links: [link]),
              GraphNodeEvidence(node: contentNode, links: []),
            ]),
          ),
        ));

    expect(find.text('Untitled memory'), findsOneWidget);
    expect(find.text('Memory'), findsOneWidget);
    expect(find.text('Water seedlings daily'), findsOneWidget);
    expect(find.text(contentNode.content!), findsOneWidget);
    expect(find.textContaining('Related to'), findsOneWidget);
    expect(find.textContaining('Connected memory'), findsOneWidget);
    expect(find.text(link.context!), findsOneWidget);
    expect(find.text(_untitled.table), findsNothing);
    _expectNoIds([_untitled.id, contentNode.id, link.id, link.to]);
  });

  testWidgets('Evidence keeps the full content behind a short title',
      (tester) async {
    final content = '${List.filled(40, 'Plant seeds').join(' ')}. Water them.';
    await _show(
        tester,
        Scaffold(
          body: SingleChildScrollView(
            child: EvidenceCards(evidence: [
              GraphNodeEvidence(
                node: GraphNode(
                  id: 'note:database-full-content-386',
                  table: 'note',
                  content: content,
                ),
                links: const [],
              ),
            ]),
          ),
        ));

    expect(find.text(content), findsOneWidget);
    _expectNoIds(['note:database-full-content-386']);
  });
}

Future<void> _show(WidgetTester tester, Widget screen) async {
  await tester.binding.setSurfaceSize(const Size(480, 1200));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(home: screen));
  await tester.pumpAndSettle();
}

void _expectNoIds(Iterable<String> ids) {
  for (final id in ids) {
    expect(find.textContaining(id, findRichText: true), findsNothing);
  }
}

final class _LoadedWorkspace implements ExploreWorkspaceController {
  _LoadedWorkspace({
    required List<WorkspaceNode> nodes,
    required List<WorkspaceEdge> edges,
  }) : _state = ExploreWorkspaceState(
          status: WorkspaceItemStatus.loaded,
          nodes: nodes,
          edges: edges,
        );

  ExploreWorkspaceState _state;

  @override
  ExploreWorkspaceState get state => _state;

  @override
  void selectNode(String recordId) {
    _state = ExploreWorkspaceState(
      status: _state.status,
      nodes: _state.nodes,
      edges: _state.edges,
      selectedNodeId: recordId,
    );
  }

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw StateError('This view must use loaded memory data.');
}
