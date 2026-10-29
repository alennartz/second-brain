import 'package:sqflite/sqflite.dart';

import 'codecs.dart';
import 'models.dart';
import 'repositories.dart';

/// SQLite adapter for [AnswerSnapshotRepository].
final class SqliteAnswerSnapshotRepository implements AnswerSnapshotRepository {
  SqliteAnswerSnapshotRepository(this.database);

  final Database database;

  @override
  Future<void> save(String brainId, AnswerSnapshot snapshot) async {
    await database.insert(
      'answer_snapshots',
      {
        'id': snapshot.id,
        'brain_id': brainId,
        'question': snapshot.question,
        'answer': snapshot.answer,
        'answered_at': snapshot.answeredAt.toIso8601String(),
        'evidence_json': encodeEvidenceJson(snapshot.evidence),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<List<AnswerSnapshot>> find(String brainId, String query) async {
    final rows = await database.query(
      'answer_snapshots',
      where: 'brain_id = ?',
      whereArgs: [brainId],
      orderBy: 'answered_at DESC, rowid DESC',
    );
    final needle = query.toLowerCase();
    return List<AnswerSnapshot>.unmodifiable(rows.where((row) {
      if (needle.isEmpty) return true;
      final question = _string(row['question'], 'snapshot question');
      final answer = _string(row['answer'], 'snapshot answer');
      return question.toLowerCase().contains(needle) ||
          answer.toLowerCase().contains(needle);
    }).map(_snapshotFromRow));
  }

  @override
  Future<void> delete(String id) async {
    await database.delete(
      'answer_snapshots',
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  static AnswerSnapshot _snapshotFromRow(Map<String, Object?> row) {
    final encodedEvidence = row['evidence_json'];
    final answeredAt = row['answered_at'];
    if (encodedEvidence is! String || answeredAt is! String) {
      throw const FormatException('snapshot storage is malformed');
    }
    return AnswerSnapshot(
      id: _string(row['id'], 'snapshot id'),
      question: _string(row['question'], 'snapshot question'),
      answer: _string(row['answer'], 'snapshot answer'),
      answeredAt: DateTime.parse(answeredAt),
      evidence: decodeEvidenceJson(encodedEvidence),
    );
  }

  static String _string(Object? value, String field) {
    if (value is String) return value;
    throw FormatException('$field must be a string');
  }
}

typedef SqfliteAnswerSnapshotRepository = SqliteAnswerSnapshotRepository;
