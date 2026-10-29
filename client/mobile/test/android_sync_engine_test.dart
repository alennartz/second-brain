import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'android_contract_fixtures.dart';

void main() {
  late Directory root;
  late MobileStore store;
  setUp(() async {
    root = await Directory.systemTemp.createTemp('sync-contract-');
    addTearDown(() => root.delete(recursive: true));
    store = await openMobileStore('${root.path}/mobile.db');
    addTearDown(() => store.close());
  });
  test(
      'sync delivers active and inactive captures to their own brains with original identity',
      () async {
    final home = await addBrain(store);
    final work = await addBrain(store,
        profile: const BrainProfileDraft(
            name: 'Work', baseUrl: 'https://work.test'));
    final homeGateway = ControlledGateway();
    final workGateway = ControlledGateway();
    await store.outbox
        .enqueue(home, 'Home text', 'home-key', '2026-01-01T00:00:00Z');
    await store.outbox
        .enqueue(work, 'Work text', 'work-key', '2026-01-02T00:00:00Z');
    final report = await createSyncEngine(store)
        .syncAll((p) => p.id == home ? homeGateway : workGateway);
    expect(report.accepted, 2);
    expect(report.pending, 0);
    expect(report.conflicts, 0);
    expect(
        homeGateway.delivered,
        contains((
          text: 'Home text',
          key: 'home-key',
          time: '2026-01-01T00:00:00Z'
        )));
    expect(
        workGateway.delivered,
        contains((
          text: 'Work text',
          key: 'work-key',
          time: '2026-01-02T00:00:00Z'
        )));
    expect(await store.outbox.pendingAll(), isEmpty);
  });
  test('409 retains edited capture and does not automatically submit as new',
      () async {
    final home = await addBrain(store);
    final saved = await store.outbox
        .enqueue(home, 'Original', 'key', '2026-01-01T00:00:00Z');
    await store.outbox.updateText(saved.id, 'Edited');
    final gateway = ControlledGateway()
      ..failure =
          const HttpStatusException(statusCode: 409, message: 'conflict');
    final engine = createSyncEngine(store);
    final report = await engine.syncAll((_) => gateway);
    expect(report.conflicts, 1);
    final retained = (await store.outbox.pendingAll()).single;
    expect(retained.text, 'Edited');
    expect(retained.idempotencyKey, 'key');
    expect(retained.state, OutboxState.conflict);
    gateway.delivered.clear();
    gateway.failure = null;
    await engine.syncAll((_) => gateway);
    expect(gateway.delivered, isEmpty);
    expect(
        (await store.outbox.pendingAll()).single.state, OutboxState.conflict);
  });
  test(
      'transport failure retains capture and next foreground pass retries the same identity',
      () async {
    final home = await addBrain(store);
    await store.outbox.enqueue(home, 'Text', 'key', '2026-01-01T00:00:00Z');
    final gateway = ControlledGateway()
      ..failure = const NetworkException('offline');
    final engine = createSyncEngine(store);
    expect((await engine.syncAll((_) => gateway)).pending, 1);
    expect((await store.outbox.pendingAll()).single.state, OutboxState.pending);
    gateway.failure = null;
    expect((await engine.syncAll((_) => gateway)).accepted, 1);
    expect(
        gateway.delivered
            .every((x) => x.key == 'key' && x.time == '2026-01-01T00:00:00Z'),
        isTrue);
  });
}
