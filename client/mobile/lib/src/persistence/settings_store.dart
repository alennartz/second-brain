import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The server endpoint and optional Cloudflare Access service-token pair.
final class ServerConfiguration {
  const ServerConfiguration({
    required this.baseUrl,
    this.accessClientId,
    this.accessClientSecret,
  });

  final String baseUrl;
  final String? accessClientId;
  final String? accessClientSecret;

  bool get hasAccessCredentials =>
      accessClientId?.trim().isNotEmpty == true &&
      accessClientSecret?.trim().isNotEmpty == true;
}

/// One failed or edited Capture draft retained for explicit retry.
final class PendingCapture {
  const PendingCapture({required this.text, required this.idempotencyKey, this.capturedAt});

  final String text;
  final String idempotencyKey;
  final String? capturedAt;
}

/// A platform-backed store for values that must not live in preferences.
abstract interface class SecretStore {
  Future<String?> read(String key);

  Future<void> write(String key, String value);

  Future<void> delete(String key);
}

/// Android Keystore-backed implementation of [SecretStore].
final class FlutterSecureSecretStore implements SecretStore {
  const FlutterSecureSecretStore({
    this.storage = const FlutterSecureStorage(),
  });

  final FlutterSecureStorage storage;

  @override
  Future<String?> read(String key) => storage.read(key: key);

  @override
  Future<void> write(String key, String value) {
    return storage.write(key: key, value: value);
  }

  @override
  Future<void> delete(String key) => storage.delete(key: key);
}

/// Durable settings and pending Capture storage owned by the application shell.
abstract interface class SettingsStore {
  Future<ServerConfiguration?> loadServerConfiguration();

  Future<void> saveServerConfiguration(ServerConfiguration value);

  Future<PendingCapture?> loadPendingCapture();

  Future<void> savePendingCapture(PendingCapture value);

  Future<void> clearPendingCapture();
}

extension SettingsStoreUrlAccess on SettingsStore {
  Future<ServerConfiguration?> loadConfiguration() {
    return loadServerConfiguration();
  }

  Future<void> saveConfiguration(ServerConfiguration value) {
    return saveServerConfiguration(value);
  }

  Future<String?> loadBaseUrl() async {
    return (await loadServerConfiguration())?.baseUrl;
  }

  Future<void> saveBaseUrl(String value) async {
    await saveServerConfiguration(ServerConfiguration(baseUrl: value));
  }
}

/// Shared Preferences adapter for [SettingsStore].
final class SharedPreferencesSettingsStore implements SettingsStore {
  const SharedPreferencesSettingsStore(
    this.preferences, {
    required this.secretStore,
  });

  static const _baseUrlKey = 'second_brain_mobile.base_url';
  static const _accessCredentialsKey = 'second_brain_mobile.access_credentials';
  static const _pendingCaptureKey = 'second_brain_mobile.pending_capture';

  final SharedPreferences preferences;
  final SecretStore secretStore;

  @override
  Future<ServerConfiguration?> loadServerConfiguration() async {
    final baseUrl = preferences.getString(_baseUrlKey);
    if (baseUrl == null) return null;
    final credentials = await _loadAccessCredentials(baseUrl);
    return ServerConfiguration(
      baseUrl: baseUrl,
      accessClientId: credentials?.clientId,
      accessClientSecret: credentials?.clientSecret,
    );
  }

  @override
  Future<void> saveServerConfiguration(ServerConfiguration value) async {
    await _saveAccessCredentials(value);
    await preferences.setString(_baseUrlKey, value.baseUrl);
  }

  Future<String?> loadBaseUrl() async {
    return (await loadServerConfiguration())?.baseUrl;
  }

  Future<void> saveBaseUrl(String value) async {
    await saveServerConfiguration(ServerConfiguration(baseUrl: value));
  }

  @override
  Future<PendingCapture?> loadPendingCapture() async {
    final encoded = preferences.getString(_pendingCaptureKey);
    if (encoded == null) return null;

    try {
      final decoded = jsonDecode(encoded);
      if (decoded is! Map<String, dynamic>) return null;
      final text = decoded['text'];
      final idempotencyKey = decoded['idempotency_key'];
      final capturedAt = decoded['captured_at'];
      if (text is! String || idempotencyKey is! String) return null;
      return PendingCapture(
        text: text,
        idempotencyKey: idempotencyKey,
        capturedAt: capturedAt is String ? capturedAt : null,
      );
    } on FormatException {
      return null;
    }
  }

  @override
  Future<void> savePendingCapture(PendingCapture value) async {
    final encoded = jsonEncode({
      'text': value.text,
      'idempotency_key': value.idempotencyKey,
      if (value.capturedAt != null) 'captured_at': value.capturedAt,
    });
    await preferences.setString(_pendingCaptureKey, encoded);
  }

  @override
  Future<void> clearPendingCapture() async {
    await preferences.remove(_pendingCaptureKey);
  }

  Future<({String clientId, String clientSecret})?> _loadAccessCredentials(
    String baseUrl,
  ) async {
    final encoded = await secretStore.read(_accessCredentialsKey);
    if (encoded == null) return null;

    try {
      final decoded = jsonDecode(encoded);
      if (decoded is! Map<String, dynamic> || decoded['base_url'] != baseUrl) {
        return null;
      }
      final rawClientId = decoded['client_id'];
      final rawClientSecret = decoded['client_secret'];
      if (rawClientId is! String || rawClientSecret is! String) {
        return null;
      }
      final clientId = _nonBlank(rawClientId);
      final clientSecret = _nonBlank(rawClientSecret);
      if (clientId == null || clientSecret == null) return null;
      return (clientId: clientId, clientSecret: clientSecret);
    } on FormatException {
      return null;
    }
  }

  Future<void> _saveAccessCredentials(ServerConfiguration value) async {
    if (!value.hasAccessCredentials) {
      await secretStore.delete(_accessCredentialsKey);
      return;
    }
    await secretStore.write(
      _accessCredentialsKey,
      jsonEncode({
        'base_url': value.baseUrl,
        'client_id': value.accessClientId!.trim(),
        'client_secret': value.accessClientSecret!.trim(),
      }),
    );
  }
}

String? _nonBlank(String? value) {
  final trimmed = value?.trim();
  return trimmed == null || trimmed.isEmpty ? null : trimmed;
}
