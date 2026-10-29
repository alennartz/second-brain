import 'dart:convert';

import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import 'models.dart';
import 'repositories.dart';
import 'settings_store.dart';

/// SQLite adapter for [BrainProfileRepository].
final class SqliteBrainProfileRepository implements BrainProfileRepository {
  SqliteBrainProfileRepository(this.database, this.secretStore);

  final Database database;
  final SecretStore secretStore;
  final Uuid _uuid = const Uuid();

  @override
  Future<List<BrainProfile>> list() async {
    final rows = await database.query('brain_profiles', orderBy: 'rowid ASC');
    final profiles = <BrainProfile>[];
    for (final row in rows) {
      profiles.add(await _hydrate(row));
    }
    return List<BrainProfile>.unmodifiable(profiles);
  }

  @override
  Future<BrainProfile?> active() async {
    final rows = await database.query(
      'mobile_metadata',
      columns: ['value'],
      where: 'key = ?',
      whereArgs: [_activeProfileKey],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    final id = rows.single['value'];
    if (id is! String) return null;
    final profiles = await database.query(
      'brain_profiles',
      where: 'id = ?',
      whereArgs: [id],
      limit: 1,
    );
    if (profiles.isEmpty) return null;
    return _hydrate(profiles.single);
  }

  @override
  Future<void> add(BrainProfileDraft draft) async {
    final id = _uuid.v4();
    await database.insert('brain_profiles', {
      'id': id,
      'name': draft.name,
      'base_url': draft.baseUrl,
      'status': _statusValue(BrainProfileStatus.neverConnected),
    });
    await _saveCredentials(id, draft.accessClientId, draft.accessClientSecret);
  }

  @override
  Future<void> updateAddress(
    String id,
    String url, {
    ({String clientId, String clientSecret})? credentials,
  }) async {
    final changed = await database.update(
      'brain_profiles',
      {'base_url': url},
      where: 'id = ?',
      whereArgs: [id],
    );
    if (changed == 0) throw StateError('unknown Brain profile: $id');

    // Clear before writing the replacement. This prevents stale credentials
    // from surviving an address change when the replacement is incomplete.
    await secretStore.delete(_credentialsKey(id));
    final clientId = credentials?.clientId.trim();
    final clientSecret = credentials?.clientSecret.trim();
    if (clientId == null || clientSecret == null ||
        clientId.isEmpty || clientSecret.isEmpty) {
      return;
    }
    await _writeCredentials(id, clientId, clientSecret);
  }

  @override
  Future<void> markConnected(String id) async {
    final changed = await database.update(
      'brain_profiles',
      {'status': _statusValue(BrainProfileStatus.connected)},
      where: 'id = ?',
      whereArgs: [id],
    );
    if (changed == 0) throw StateError('unknown Brain profile: $id');
  }

  @override
  Future<void> use(String id) async {
    final rows = await database.query(
      'brain_profiles',
      columns: ['id'],
      where: 'id = ?',
      whereArgs: [id],
      limit: 1,
    );
    if (rows.isEmpty) throw StateError('unknown Brain profile: $id');
    await database.insert(
      'mobile_metadata',
      {'key': _activeProfileKey, 'value': id},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<BrainProfile> _hydrate(Map<String, Object?> row) async {
    final id = _string(row['id'], 'profile id');
    final credentials = await _readCredentials(id);
    return BrainProfile(
      id: id,
      name: _string(row['name'], 'profile name'),
      baseUrl: _string(row['base_url'], 'profile address'),
      accessClientId: credentials?.clientId,
      accessClientSecret: credentials?.clientSecret,
      status: _statusFrom(row['status']),
    );
  }

  Future<({String clientId, String clientSecret})?> _readCredentials(
    String id,
  ) async {
    final encoded = await secretStore.read(_credentialsKey(id));
    if (encoded == null) return null;
    try {
      final decoded = jsonDecode(encoded);
      if (decoded is! Map) return null;
      final clientId = decoded['client_id'];
      final clientSecret = decoded['client_secret'];
      if (clientId is! String || clientSecret is! String) return null;
      final cleanId = clientId.trim();
      final cleanSecret = clientSecret.trim();
      if (cleanId.isEmpty || cleanSecret.isEmpty) return null;
      return (clientId: cleanId, clientSecret: cleanSecret);
    } on FormatException {
      return null;
    }
  }

  Future<void> _saveCredentials(
    String id,
    String? clientId,
    String? clientSecret,
  ) async {
    final cleanId = clientId?.trim();
    final cleanSecret = clientSecret?.trim();
    if (cleanId == null || cleanSecret == null ||
        cleanId.isEmpty || cleanSecret.isEmpty) {
      await secretStore.delete(_credentialsKey(id));
      return;
    }
    await _writeCredentials(id, cleanId, cleanSecret);
  }

  Future<void> _writeCredentials(
    String id,
    String clientId,
    String clientSecret,
  ) {
    return secretStore.write(
      _credentialsKey(id),
      jsonEncode({'client_id': clientId, 'client_secret': clientSecret}),
    );
  }

  static const _activeProfileKey = 'active_brain_profile_id';

  static String _credentialsKey(String id) =>
      'second_brain_mobile.profile.$id.access_credentials';

  static int _statusValue(BrainProfileStatus status) => switch (status) {
        BrainProfileStatus.neverConnected => 0,
        BrainProfileStatus.connected => 1,
      };

  static BrainProfileStatus _statusFrom(Object? value) {
    final raw = value is int ? value : int.tryParse('$value');
    return raw == 1
        ? BrainProfileStatus.connected
        : BrainProfileStatus.neverConnected;
  }

  static String _string(Object? value, String field) {
    if (value is String) return value;
    throw FormatException('$field must be a string');
  }
}

/// Short name for callers that use the storage technology in the type name.
typedef SqfliteBrainProfileRepository = SqliteBrainProfileRepository;
