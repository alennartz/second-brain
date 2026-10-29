import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'android_contract_fixtures.dart';

void main() {
  late Directory root;
  late MobileStore store;
  late String path;
  setUp(() async {
    root = await Directory.systemTemp.createTemp('brain-contract-');
    addTearDown(() => root.delete(recursive: true));
    path = '${root.path}/mobile.db';
    store = await openMobileStore(path);
    addTearDown(() => store.close());
  });

  test(
      'profiles save offline, preserve connection history and own their address',
      () async {
    final home = await addBrain(store);
    expect((await store.profiles.list()).single.status,
        BrainProfileStatus.neverConnected);
    await store.profiles.markConnected(home);
    final other = await addBrain(store,
        profile: const BrainProfileDraft(
            name: 'Work', baseUrl: 'https://work.test'));
    await store.profiles.updateAddress(home, 'https://new.test');
    await store.profiles.use(home);
    final profile = (await store.profiles.active())!;
    expect(profile.id, home);
    expect(profile.baseUrl, 'https://new.test');
    expect(profile.status, BrainProfileStatus.connected);
    expect(profile.accessClientId, isNull);
    expect(profile.accessClientSecret, isNull);
    expect((await store.profiles.list()).map((p) => p.id),
        containsAll([home, other]));
  });

  test(
      'outbox keeps edited text, key, time and brain through conflicts and reopen',
      () async {
    final home = await addBrain(store);
    final entry = await store.outbox
        .enqueue(home, 'Original', 'key', '2026-01-01T00:00:00Z');
    await store.outbox.updateText(entry.id, 'Edited');
    expect((await store.outbox.pendingAll()).single.state, OutboxState.edited);
    await store.outbox.markConflict(entry.id);
    await store.close();
    store = await openMobileStore(path);
    final saved = (await store.outbox.pendingAll()).single;
    expect(saved.text, 'Edited');
    expect(saved.idempotencyKey, 'key');
    expect(saved.capturedAt, entry.capturedAt);
    expect(saved.brainId, home);
    expect(saved.state, OutboxState.conflict);
    await store.outbox.requeueAsNew(saved.id);
    final retry = (await store.outbox.pendingAll()).single;
    expect(retry.idempotencyKey, isNot('key'));
    expect(retry.text, 'Edited');
    expect(retry.brainId, home);
    expect(retry.state, OutboxState.pending);
    await store.outbox.markAccepted(retry.id);
    expect(await store.outbox.pendingAll(), isEmpty);
  });

  test('snapshots retain displayed evidence and IDs independently per brain',
      () async {
    final home = await addBrain(store);
    final other = await addBrain(store,
        profile: const BrainProfileDraft(
            name: 'Work', baseUrl: 'https://work.test'));
    final snapshot = AnswerSnapshot(
        id: 'answer:1',
        question: 'Garden?',
        answer: 'Behind shed',
        answeredAt: DateTime.utc(2026),
        evidence: const [evidence]);
    await store.answers.save(home, snapshot);
    await store.close();
    store = await openMobileStore(path);
    final saved = (await store.answers.find(home, 'Garden')).single;
    expect(saved.id, snapshot.id);
    expect(saved.question, snapshot.question);
    expect(saved.answer, snapshot.answer);
    expect(saved.answeredAt, snapshot.answeredAt);
    final item = saved.evidence.single as GraphNodeEvidence;
    expect(item.node.name, 'Garden');
    expect(item.node.id, garden.id);
    expect(item.links.single.to, layout.id);
    expect(await store.answers.find(other, 'Garden'), isEmpty);
    expect(await store.answers.find(home, 'absent'), isEmpty);
    await store.answers.delete(saved.id);
    expect(await store.answers.find(home, ''), isEmpty);
  });

  test('workspace records and flags survive reopen without object identity',
      () async {
    final home = await addBrain(store);
    final other = await addBrain(store,
        profile: const BrainProfileDraft(
            name: 'Work', baseUrl: 'https://work.test'));
    final fetched = DateTime.utc(2026);
    await store.workspaces.save(
        home,
        Workspace(nodes: const [
          WorkspaceNode(node: garden, expanded: true),
          WorkspaceNode(node: layout, status: WorkspaceItemStatus.missing)
        ], edges: const [
          WorkspaceEdge(edge: edge, status: WorkspaceItemStatus.newItem)
        ], fetchedAt: fetched));
    await store.close();
    store = await openMobileStore(path);
    final saved = (await store.workspaces.load(home))!;
    expect(saved.nodes.first.node.id, garden.id);
    expect(saved.nodes.first.expanded, isTrue);
    expect(saved.nodes.last.status, WorkspaceItemStatus.missing);
    expect(saved.edges.single.edge.id, edge.id);
    expect(saved.edges.single.status, WorkspaceItemStatus.newItem);
    expect(saved.fetchedAt, fetched);
    expect(await store.workspaces.load(other), isNull);
  });

  test('legacy migration preserves profile, key and capture time exactly once',
      () async {
    await store.close();
    const legacy = LegacyMobileData(
        profile: draft,
        pending: OutboxEntry(
            id: 'legacy',
            brainId: 'legacy',
            text: 'Draft',
            idempotencyKey: 'old-key',
            capturedAt: '2025-12-01T01:02:03Z'));
    store = await openMobileStore(path, legacy: legacy);
    final profile = (await store.profiles.active())!;
    expect(profile.baseUrl, draft.baseUrl);
    expect(profile.accessClientId, draft.accessClientId);
    final entry = (await store.outbox.pendingAll()).single;
    expect(entry.brainId, profile.id);
    expect(entry.text, 'Draft');
    expect(entry.idempotencyKey, 'old-key');
    expect(entry.capturedAt, legacy.pending!.capturedAt);
    await store.close();
    store = await openMobileStore(path, legacy: legacy);
    expect(await store.profiles.list(), hasLength(1));
    expect(await store.outbox.pendingAll(), hasLength(1));
  });
}
