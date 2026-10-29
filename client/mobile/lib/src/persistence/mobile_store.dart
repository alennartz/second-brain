// Host tests use sqflite_common_ffi, which remains a dev dependency by design.
// ignore_for_file: depend_on_referenced_packages

import 'dart:convert';
import 'dart:io';

import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:uuid/uuid.dart';

import 'answer_snapshot_repository.dart';
import 'brain_profile_repository.dart';
import 'capture_outbox_repository.dart';
import 'graph_workspace_repository.dart';
import 'host_secret_store.dart';
import 'models.dart';
import 'repositories.dart';
import 'settings_store.dart';

/// Legacy values migrate once into one brain and retain their capture identity.
final class LegacyMobileData {
  const LegacyMobileData({required this.profile, this.pending});

  final BrainProfileDraft profile;
  final OutboxEntry? pending;
}

/// Durable repositories. Reopening the same path preserves all records.
abstract interface class MobileStore {
  BrainProfileRepository get profiles;
  CaptureOutboxRepository get outbox;
  AnswerSnapshotRepository get answers;
  GraphWorkspaceRepository get workspaces;
  Future<void> close();
}

/// Opens SQLite-backed repositories and performs the optional legacy migration.
///
/// [settingsStore] is a bridge for the old SharedPreferences-backed shell. The
/// bridge is read only when [legacy] is absent and a configuration exists. An
/// explicit [legacy] value is useful for tests and callers that already loaded
/// the old values.
Future<MobileStore> openMobileStore(
  String path, {
  LegacyMobileData? legacy,
  SecretStore? secretStore,
  SettingsStore? settingsStore,
  DateTime Function()? migrationClock,
}) async {
  _configureDatabaseFactory();
  final secrets = secretStore ?? _defaultSecretStore(path);
  final database = await openDatabase(
    path,
    version: 1,
    onCreate: _createSchema,
  );
  final store = _SqliteMobileStore(database, secrets);
  final migrated = legacy ??
      await _readLegacyData(settingsStore, migrationClock ?? _nowUtc);
  try {
    await store.migrate(migrated, migrationClock ?? _nowUtc);
    return store;
  } catch (_) {
    await store.close();
    rethrow;
  }
}

void _configureDatabaseFactory() {
  if (Platform.isAndroid || Platform.isIOS) return;
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;
}

SecretStore _defaultSecretStore(String path) {
  if (Platform.isAndroid || Platform.isIOS) {
    return const FlutterSecureSecretStore();
  }
  return HostSecretStore(path);
}

Future<void> _createSchema(Database database, int version) async {
  await database.execute('''
    CREATE TABLE mobile_metadata (
      key TEXT PRIMARY KEY NOT NULL,
      value TEXT NOT NULL
    )
  ''');
  await database.execute('''
    CREATE TABLE brain_profiles (
      id TEXT PRIMARY KEY NOT NULL,
      name TEXT NOT NULL,
      base_url TEXT NOT NULL,
      status INTEGER NOT NULL DEFAULT 0
    )
  ''');
  await database.execute('''
    CREATE TABLE capture_outbox (
      id TEXT PRIMARY KEY NOT NULL,
      brain_id TEXT NOT NULL,
      text TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      captured_at TEXT NOT NULL,
      state INTEGER NOT NULL DEFAULT 0
    )
  ''');
  await database.execute('''
    CREATE TABLE answer_snapshots (
      id TEXT PRIMARY KEY NOT NULL,
      brain_id TEXT NOT NULL,
      question TEXT NOT NULL,
      answer TEXT NOT NULL,
      answered_at TEXT NOT NULL,
      evidence_json TEXT NOT NULL
    )
  ''');
  await database.execute('''
    CREATE TABLE graph_workspaces (
      brain_id TEXT PRIMARY KEY NOT NULL,
      workspace_json TEXT NOT NULL
    )
  ''');
  await database.execute(
    'CREATE INDEX capture_outbox_brain_idx ON capture_outbox (brain_id)',
  );
  await database.execute(
    'CREATE INDEX answer_snapshots_brain_idx ON answer_snapshots (brain_id)',
  );
}

Future<LegacyMobileData?> _readLegacyData(
  SettingsStore? settingsStore,
  DateTime Function() migrationClock,
) async {
  if (settingsStore == null) return null;
  final configuration = await settingsStore.loadServerConfiguration();
  if (configuration == null) return null;
  final pending = await settingsStore.loadPendingCapture();
  final profile = BrainProfileDraft(
    name: 'Home',
    baseUrl: configuration.baseUrl,
    accessClientId: configuration.accessClientId,
    accessClientSecret: configuration.accessClientSecret,
  );
  if (pending == null) return LegacyMobileData(profile: profile);
  return LegacyMobileData(
    profile: profile,
    pending: OutboxEntry(
      id: const Uuid().v4(),
      brainId: 'legacy',
      text: pending.text,
      idempotencyKey: pending.idempotencyKey,
      capturedAt: pending.capturedAt ?? migrationClock().toIso8601String(),
    ),
  );
}

DateTime _nowUtc() => DateTime.now().toUtc();

final class _SqliteMobileStore implements MobileStore {
  _SqliteMobileStore(this.database, SecretStore secretStore)
      : profiles = SqliteBrainProfileRepository(database, secretStore),
        outbox = SqliteCaptureOutboxRepository(database),
        answers = SqliteAnswerSnapshotRepository(database),
        workspaces = SqliteGraphWorkspaceRepository(database),
        _secretStore = secretStore;

  final Database database;
  final SecretStore _secretStore;
  @override
  final SqliteBrainProfileRepository profiles;
  @override
  final SqliteCaptureOutboxRepository outbox;
  @override
  final SqliteAnswerSnapshotRepository answers;
  @override
  final SqliteGraphWorkspaceRepository workspaces;
  Future<void>? _closeFuture;

  @override
  Future<void> close() => _closeFuture ??= database.close();

  Future<void> migrate(
    LegacyMobileData? legacy,
    DateTime Function() migrationClock,
  ) async {
    if (legacy == null) return;
    final marker = await database.query(
      'mobile_metadata',
      columns: ['value'],
      where: 'key = ?',
      whereArgs: [_migrationKey],
      limit: 1,
    );
    if (marker.isNotEmpty) return;

    final profileId = const Uuid().v4();
    final pending = legacy.pending;
    final outboxId = pending == null || pending.id.isEmpty
        ? const Uuid().v4()
        : pending.id;
    final capturedAt = pending == null
        ? null
        : pending.capturedAt.isEmpty
            ? migrationClock().toIso8601String()
            : pending.capturedAt;

    // SQLite records and the marker commit in one transaction. Credentials
    // use a separate store and therefore never enter this transaction.
    await database.transaction((transaction) async {
      await transaction.insert('brain_profiles', {
        'id': profileId,
        'name': legacy.profile.name,
        'base_url': legacy.profile.baseUrl,
        'status': 0,
      });
      if (pending != null) {
        await transaction.insert('capture_outbox', {
          'id': outboxId,
          'brain_id': profileId,
          'text': pending.text,
          'idempotency_key': pending.idempotencyKey,
          'captured_at': capturedAt,
          'state': _stateValue(pending.state),
        });
      }
      await transaction.insert(
        'mobile_metadata',
        {'key': _activeProfileKey, 'value': profileId},
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
      await transaction.insert('mobile_metadata', {
        'key': _migrationKey,
        'value': '1',
      });
    });

    await _saveCredentials(
      profileId,
      legacy.profile.accessClientId,
      legacy.profile.accessClientSecret,
    );
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
      await _secretStore.delete(_credentialsKey(id));
      return;
    }
    await _secretStore.write(
      _credentialsKey(id),
      jsonEncode({'client_id': cleanId, 'client_secret': cleanSecret}),
    );
  }

  static const _activeProfileKey = 'active_brain_profile_id';
  static const _migrationKey = 'legacy_settings_migrated';

  static String _credentialsKey(String id) =>
      'second_brain_mobile.profile.$id.access_credentials';

  static int _stateValue(OutboxState state) => switch (state) {
        OutboxState.pending => 0,
        OutboxState.edited => 1,
        OutboxState.conflict => 2,
      };
}
