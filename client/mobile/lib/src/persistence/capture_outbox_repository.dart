import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import 'models.dart';
import 'repositories.dart';

/// SQLite adapter for [CaptureOutboxRepository].
final class SqliteCaptureOutboxRepository implements CaptureOutboxRepository {
  SqliteCaptureOutboxRepository(this.database);

  final Database database;
  final Uuid _uuid = const Uuid();

  @override
  Future<List<OutboxEntry>> pendingAll() async {
    final rows = await database.query('capture_outbox', orderBy: 'rowid ASC');
    return List<OutboxEntry>.unmodifiable(rows.map(_entryFromRow));
  }

  @override
  Future<OutboxEntry> enqueue(
    String brainId,
    String text,
    String idempotencyKey,
    String capturedAt,
  ) async {
    final entry = OutboxEntry(
      id: _uuid.v4(),
      brainId: brainId,
      text: text,
      idempotencyKey: idempotencyKey,
      capturedAt: capturedAt,
    );
    await database.insert('capture_outbox', _rowFor(entry));
    return entry;
  }

  @override
  Future<void> updateText(String id, String text) async {
    final changed = await database.update(
      'capture_outbox',
      {'text': text, 'state': _stateValue(OutboxState.edited)},
      where: 'id = ?',
      whereArgs: [id],
    );
    if (changed == 0) throw StateError('unknown Capture entry: $id');
  }

  @override
  Future<void> markAccepted(String id) async {
    await database.delete(
      'capture_outbox',
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  @override
  Future<void> markConflict(String id) async {
    final changed = await database.update(
      'capture_outbox',
      {'state': _stateValue(OutboxState.conflict)},
      where: 'id = ?',
      whereArgs: [id],
    );
    if (changed == 0) throw StateError('unknown Capture entry: $id');
  }

  @override
  Future<void> requeueAsNew(String id) async {
    final changed = await database.update(
      'capture_outbox',
      {
        'idempotency_key': _uuid.v4(),
        'state': _stateValue(OutboxState.pending),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    if (changed == 0) throw StateError('unknown Capture entry: $id');
  }

  static Map<String, Object?> _rowFor(OutboxEntry entry) => {
        'id': entry.id,
        'brain_id': entry.brainId,
        'text': entry.text,
        'idempotency_key': entry.idempotencyKey,
        'captured_at': entry.capturedAt,
        'state': _stateValue(entry.state),
      };

  static OutboxEntry _entryFromRow(Map<String, Object?> row) => OutboxEntry(
        id: _string(row['id'], 'outbox id'),
        brainId: _string(row['brain_id'], 'outbox brain'),
        text: _string(row['text'], 'outbox text'),
        idempotencyKey: _string(row['idempotency_key'], 'outbox key'),
        capturedAt: _string(row['captured_at'], 'outbox capture time'),
        state: _stateFrom(row['state']),
      );

  static int _stateValue(OutboxState state) => switch (state) {
        OutboxState.pending => 0,
        OutboxState.edited => 1,
        OutboxState.conflict => 2,
      };

  static OutboxState _stateFrom(Object? value) {
    final raw = value is int ? value : int.tryParse('$value');
    return switch (raw) {
      1 => OutboxState.edited,
      2 => OutboxState.conflict,
      _ => OutboxState.pending,
    };
  }

  static String _string(Object? value, String field) {
    if (value is String) return value;
    throw FormatException('$field must be a string');
  }
}

typedef SqfliteCaptureOutboxRepository = SqliteCaptureOutboxRepository;
