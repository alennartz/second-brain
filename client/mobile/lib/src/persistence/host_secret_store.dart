import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:uuid/uuid.dart';

import 'settings_store.dart';

/// Durable host-side secret storage used when Android secure storage is absent.
///
/// The file sits beside the SQLite database and is never included in SQLite.
/// Android uses [FlutterSecureSecretStore] instead.
final class HostSecretStore implements SecretStore {
  HostSecretStore(String databasePath)
      : _file = File('$databasePath.secrets.json');

  final File _file;
  Future<void> _tail = Future<void>.value();

  @override
  Future<String?> read(String key) {
    return _serialise(() async {
      final values = await _readValues();
      return values[key];
    });
  }

  @override
  Future<void> write(String key, String value) {
    return _serialise(() async {
      final values = await _readValues();
      values[key] = value;
      await _writeValues(values);
    });
  }

  @override
  Future<void> delete(String key) {
    return _serialise(() async {
      final values = await _readValues();
      values.remove(key);
      await _writeValues(values);
    });
  }

  Future<Map<String, String>> _readValues() async {
    if (!await _file.exists()) return <String, String>{};
    try {
      final decoded = jsonDecode(await _file.readAsString());
      if (decoded is! Map) return <String, String>{};
      return <String, String>{
        for (final entry in decoded.entries)
          if (entry.key is String && entry.value is String)
            entry.key as String: entry.value as String,
      };
    } on FormatException {
      return <String, String>{};
    } on FileSystemException {
      return <String, String>{};
    }
  }

  Future<void> _writeValues(Map<String, String> values) async {
    await _file.parent.create(recursive: true);
    if (Platform.isWindows) {
      throw UnsupportedError('Inject a secure SecretStore on Windows');
    }
    final temporary = File('${_file.path}.${const Uuid().v4()}.tmp');
    await temporary.create();
    final permissions = await Process.run('chmod', ['600', temporary.path]);
    if (permissions.exitCode != 0) {
      await temporary.delete();
      throw FileSystemException('Cannot protect host credentials', _file.path);
    }
    await temporary.writeAsString(jsonEncode(values), flush: true);
    try {
      await temporary.rename(_file.path);
    } on FileSystemException {
      // Windows cannot replace an existing file with rename. Remove the old
      // file and retry; the operation is still serialized by this instance.
      if (await _file.exists()) await _file.delete();
      await temporary.rename(_file.path);
    }
  }

  Future<T> _serialise<T>(Future<T> Function() operation) {
    final result = _tail.then((_) => operation());
    _tail = result.then<void>((_) {}, onError: (_, __) {});
    return result;
  }
}

/// Compatibility name for callers that describe the implementation by format.
typedef FileSecretStore = HostSecretStore;
