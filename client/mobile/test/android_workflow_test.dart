import 'dart:async';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'android_contract_fixtures.dart';

void main() {
  late Directory root;
  late MobileStore store;
  late String home;
  late ControlledGateway gateway;
  late MobileWorkflow workflow;
  final now = DateTime.utc(2026, 1, 1);
  setUp(() async {
    root = await Directory.systemTemp.createTemp('workflow-contract-');
    addTearDown(() => root.delete(recursive: true));
    store = await openTestMobileStore('${root.path}/mobile.db');
    addTearDown(() => store.close());
    home = await addBrain(store);
    gateway = ControlledGateway();
    var sequence = 0;
    workflow = createMobileWorkflow(
        store: store,
        gatewayFor: (_) => gateway,
        now: () => now,
        newKey: () => 'key-${sequence++}');
  });

  test(
      'capture saves durably and clears composer without waiting for the server',
      () async {
    gateway.intakeGate = Completer<IngestReceipt>();
    workflow.compose('Offline thought');
    final entry = await workflow.capture();
    expect(workflow.composerText, isEmpty);
    expect(entry.text, 'Offline thought');
    expect(entry.brainId, home);
    expect(DateTime.parse(entry.capturedAt), now);
    await store.close();
    store = await openTestMobileStore('${root.path}/mobile.db');
    final saved = (await store.outbox.pendingAll()).single;
    expect(saved.text, entry.text);
    expect(saved.idempotencyKey, entry.idempotencyKey);
    gateway.intakeGate!.complete(const IngestReceipt(chunksStored: 1));
  });
  test('app open and resume retry pending captures including inactive brains',
      () async {
    await store.outbox
        .enqueue(home, 'Home text', 'home-key', now.toIso8601String());
    await addBrain(store,
        profile: const BrainProfileDraft(
            name: 'Work', baseUrl: 'https://work.test'));
    gateway.failure = const NetworkException('offline');
    expect((await workflow.appOpened()).pending, 1);
    gateway.failure = null;
    expect((await workflow.appResumed()).accepted, 1);
    expect(gateway.delivered.every((x) => x.key == 'home-key'), isTrue);
    expect(await store.outbox.pendingAll(), isEmpty);
  });
  test(
      'successful Ask saves displayed evidence and reopens offline after restart',
      () async {
    final answer = await workflow.ask('Garden?');
    expect(answer.question, 'Garden?');
    expect(answer.answer, 'Behind shed');
    expect(answer.answeredAt, now);
    expect((await store.answers.find(home, 'Garden')).single.id, answer.id);
    await store.close();
    store = await openTestMobileStore('${root.path}/mobile.db');
    gateway.failure = StateError('no server for snapshot');
    final reopened = createMobileWorkflow(
        store: store,
        gatewayFor: (_) => gateway,
        now: () => now,
        newKey: () => 'unused');
    final saved = await reopened.reopenAnswer(home, answer.id);
    expect(saved.answer, answer.answer);
    expect(saved.question, answer.question);
    expect(saved.answeredAt, answer.answeredAt);
    final shown = saved.evidence.single as GraphNodeEvidence;
    expect(shown.node.name, garden.name);
    expect(shown.links.single.id, edge.id);
    expect(shown.node.id, garden.id);
  });
  test('failed Ask never saves an answer snapshot', () async {
    gateway.failure = const NetworkException('offline');
    await expectLater(
        workflow.ask('Garden?'), throwsA(isA<NetworkException>()));
    expect(await store.answers.find(home, ''), isEmpty);
  });
  test('switching active brain cannot redirect an old answer graph link',
      () async {
    final homeGateway = ControlledGateway();
    final workGateway = ControlledGateway()
      ..nodeDetail = const GraphNodeDetail(
          node: GraphNode(id: 'entity:work', table: 'entity'), connections: []);
    final work = await addBrain(store,
        profile: const BrainProfileDraft(
            name: 'Work', baseUrl: 'https://work.test'));
    final session = createMobileWorkflow(
        store: store,
        gatewayFor: (p) => p.id == home ? homeGateway : workGateway,
        now: () => now,
        newKey: () => 'unused');
    expect((await store.profiles.active())!.id, work);
    expect((await session.openGraphLink(home, garden.id)).node.id, garden.id);
  });
  test(
      'first Explore visit shows cache during refresh and repeats only after relaunch',
      () async {
    await store.workspaces.save(
        home,
        const Workspace(
            nodes: [WorkspaceNode(node: garden, expanded: true)], edges: []));
    gateway.refreshGate = Completer<GraphRefreshResult>();
    final controller = await workflow.visitExplore(home);
    expect(controller.state.nodes.single.node.name, 'Garden');
    gateway.refreshGate!.complete(const GraphRefreshResult(results: [
      GraphRefreshFound(
          id: 'entity:garden',
          node:
              GraphNode(id: 'entity:garden', table: 'entity', name: 'Updated'),
          connections: [])
    ]));
    await controller.refreshCompleted;
    expect(controller.state.nodes.single.node.name, 'Updated');
    gateway.refreshGate = Completer<GraphRefreshResult>();
    final secondVisit = await workflow.visitExplore(home);
    expect(secondVisit.state.nodes.single.node.name, 'Updated');
    gateway.refreshGate!.complete(const GraphRefreshResult(
        results: [GraphRefreshMissing(id: 'entity:garden')]));
    await secondVisit.refreshCompleted;
    expect(secondVisit.state.nodes.single.status,
        isNot(WorkspaceItemStatus.missing));
    final relaunched = createMobileWorkflow(
        store: store,
        gatewayFor: (_) => gateway,
        now: () => now,
        newKey: () => 'unused');
    final thirdVisit = await relaunched.visitExplore(home);
    await thirdVisit.refreshCompleted;
    expect(thirdVisit.state.nodes.single.status, WorkspaceItemStatus.missing);
  });
}
