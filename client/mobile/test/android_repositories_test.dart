import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

const profileDraft = BrainProfileDraft(
  name: 'Home Brain',
  baseUrl: 'https://brain.example.test',
);

const outboxEntry = OutboxEntry(
  id: 'outbox:1',
  brainId: 'brain:home',
  text: 'Offline thought',
  idempotencyKey: 'capture-key',
  capturedAt: '2026-01-01T00:00:00Z',
);

final snapshot = AnswerSnapshot(
  question: 'Where is the garden?',
  answer: 'Behind the shed.',
  answeredAt: DateTime(2026, 1, 1),
  evidence: const <EvidenceItem>[],
);

const workspace = Workspace(nodes: <WorkspaceNode>[], edges: <WorkspaceEdge>[]);

void main() {
  test('adding a profile starts it as never connected and permits switching',
      () async {
    const repository = BrainProfileRepositoryStub();

    await repository.add(profileDraft);
    await repository.markConnected('brain:home');
    await repository.use('brain:home');

    expect(await repository.active(), isNotNull);
    expect(
        (await repository.list()).single.status, BrainProfileStatus.connected);
  });

  test('changing a profile address clears its Access credentials', () async {
    const repository = BrainProfileRepositoryStub();

    await repository.updateAddress('brain:home', 'https://new.example.test');

    expect((await repository.list()).single.accessClientId, isNull);
    expect((await repository.list()).single.accessClientSecret, isNull);
  });

  test('outbox enqueue preserves the idempotency key and capture time',
      () async {
    const repository = CaptureOutboxRepositoryStub();

    final saved = await repository.enqueue(
      outboxEntry.brainId,
      outboxEntry.text,
      outboxEntry.idempotencyKey,
      outboxEntry.capturedAt,
    );

    expect(saved.idempotencyKey, outboxEntry.idempotencyKey);
    expect(saved.capturedAt, outboxEntry.capturedAt);
  });

  test('editing an outbox entry keeps its key and marks it edited', () async {
    const repository = CaptureOutboxRepositoryStub();

    await repository.updateText(outboxEntry.id, 'Edited thought');

    final pending = (await repository.pendingAll()).single;
    expect(pending.idempotencyKey, outboxEntry.idempotencyKey);
    expect(pending.state, OutboxState.edited);
  });

  test('accepted entries leave the pending outbox', () async {
    const repository = CaptureOutboxRepositoryStub();

    await repository.markAccepted(outboxEntry.id);

    expect(await repository.pendingAll(), isEmpty);
  });

  test('conflicts retain the edited entry for recovery', () async {
    const repository = CaptureOutboxRepositoryStub();

    await repository.markConflict(outboxEntry.id);

    expect((await repository.pendingAll()).single.state, OutboxState.conflict);
  });

  test('requeueing an entry creates a deliberate new capture key', () async {
    const repository = CaptureOutboxRepositoryStub();

    await repository.requeueAsNew(outboxEntry.id);

    final entries = await repository.pendingAll();
    expect(entries, hasLength(1));
    expect(entries.single.idempotencyKey, isNot(outboxEntry.idempotencyKey));
  });

  test('only successful Ask results are saved as self-contained snapshots',
      () async {
    const repository = AnswerSnapshotRepositoryStub();

    await repository.save('brain:home', snapshot);

    final saved = (await repository.find('brain:home', 'garden')).single;
    expect(saved.answer, snapshot.answer);
    expect(saved.evidence, isEmpty);
  });

  test('snapshot deletion does not require live graph records', () async {
    const repository = AnswerSnapshotRepositoryStub();

    await repository.delete('snapshot:1');

    expect(await repository.find('brain:home', 'garden'), isEmpty);
  });

  test('workspaces save and load per Brain profile', () async {
    const repository = GraphWorkspaceRepositoryStub();

    await repository.save('brain:home', workspace);

    expect(await repository.load('brain:home'), same(workspace));
  });
}
