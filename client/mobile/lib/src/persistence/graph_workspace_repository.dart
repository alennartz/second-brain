import 'package:sqflite/sqflite.dart';

import 'codecs.dart';
import 'models.dart';
import 'repositories.dart';

/// SQLite adapter for [GraphWorkspaceRepository].
final class SqliteGraphWorkspaceRepository implements GraphWorkspaceRepository {
  SqliteGraphWorkspaceRepository(this.database);

  final Database database;

  @override
  Future<Workspace?> load(String brainId) async {
    final rows = await database.query(
      'graph_workspaces',
      columns: ['workspace_json'],
      where: 'brain_id = ?',
      whereArgs: [brainId],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    final encoded = rows.single['workspace_json'];
    if (encoded is! String) {
      throw const FormatException('workspace storage is malformed');
    }
    return decodeWorkspaceJson(encoded);
  }

  @override
  Future<void> save(String brainId, Workspace workspace) async {
    await database.insert(
      'graph_workspaces',
      {
        'brain_id': brainId,
        'workspace_json': encodeWorkspaceJson(workspace),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }
}
