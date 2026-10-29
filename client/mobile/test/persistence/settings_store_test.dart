import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'package:shared_preferences/shared_preferences.dart';

final class MemorySecretStore implements SecretStore {
  final values = <String, String>{};

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String value) async {
    values[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    values.remove(key);
  }
}

void main() {
  late SharedPreferences preferences;
  late SettingsStore store;
  late MemorySecretStore secrets;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    preferences = await SharedPreferences.getInstance();
    secrets = MemorySecretStore();
    store = SharedPreferencesSettingsStore(
      preferences,
      secretStore: secrets,
    );
  });

  test('recreated adapter reads the replaced URL and pending draft', () async {
    await store.saveBaseUrl('https://first.example.test');
    await store.saveBaseUrl('https://second.example.test');
    await store.savePendingCapture(
        const PendingCapture(text: 'Old', idempotencyKey: 'old'));
    await store.savePendingCapture(
        const PendingCapture(text: 'New', idempotencyKey: 'new'));
    final recreated = SharedPreferencesSettingsStore(
      preferences,
      secretStore: secrets,
    );
    expect(await recreated.loadBaseUrl(), 'https://second.example.test');
    final loaded = await recreated.loadPendingCapture();
    expect(loaded!.text, 'New');
    expect(loaded.idempotencyKey, 'new');
    await recreated.clearPendingCapture();
    expect(await store.loadPendingCapture(), isNull);
    expect(await store.loadBaseUrl(), 'https://second.example.test');
  });

  test('stores and loads the complete server configuration', () async {
    await store.saveServerConfiguration(
      const ServerConfiguration(
        baseUrl: 'https://brain.example.test',
        accessClientId: 'client-id',
        accessClientSecret: 'client-secret',
      ),
    );

    final loaded = await store.loadServerConfiguration();
    expect(loaded?.baseUrl, 'https://brain.example.test');
    expect(loaded?.accessClientId, 'client-id');
    expect(loaded?.accessClientSecret, 'client-secret');
    expect(
      preferences.getString('second_brain_mobile.access_credentials'),
      isNull,
    );
    final persisted = jsonDecode(
      secrets.values['second_brain_mobile.access_credentials']!,
    ) as Map<String, dynamic>;
    expect(persisted, {
      'base_url': 'https://brain.example.test',
      'client_id': 'client-id',
      'client_secret': 'client-secret',
    });
  });

  test('ignores Access credentials bound to another server', () async {
    await preferences.setString(
      'second_brain_mobile.base_url',
      'https://brain.example.test',
    );
    await secrets.write(
      'second_brain_mobile.access_credentials',
      jsonEncode({
        'base_url': 'https://other.example.test',
        'client_id': 'client-id',
        'client_secret': 'client-secret',
      }),
    );

    final loaded = await store.loadServerConfiguration();

    expect(loaded?.accessClientId, isNull);
    expect(loaded?.accessClientSecret, isNull);
  });

  test('clears old Access credentials when saving a URL without them',
      () async {
    await store.saveServerConfiguration(
      const ServerConfiguration(
        baseUrl: 'https://brain.example.test',
        accessClientId: 'client-id',
        accessClientSecret: 'client-secret',
      ),
    );
    await store.saveServerConfiguration(
      const ServerConfiguration(baseUrl: 'https://other.example.test'),
    );

    final loaded = await store.loadServerConfiguration();
    expect(loaded?.baseUrl, 'https://other.example.test');
    expect(loaded?.accessClientId, isNull);
    expect(loaded?.accessClientSecret, isNull);
    expect(secrets.values, isEmpty);
  });

  test('stores and loads the configured server URL', () async {
    await store.saveBaseUrl('https://brain.example.test');

    expect(await store.loadBaseUrl(), 'https://brain.example.test');
  });

  test('loads no URL before setup has saved one', () async {
    expect(await store.loadBaseUrl(), isNull);
  });

  test('persists a pending Capture draft with its idempotency key and capture time', () async {
    const draft = PendingCapture(
      text: 'Keep this thought when the server is down',
      idempotencyKey: 'capture-key-2',
      capturedAt: '2026-01-01T00:00:00+02:00',
    );

    await store.savePendingCapture(draft);
    final loaded = await store.loadPendingCapture();

    expect(loaded, isNotNull);
    expect(loaded!.text, draft.text);
    expect(loaded.idempotencyKey, draft.idempotencyKey);
    expect(loaded.capturedAt, draft.capturedAt);
  });

  test('returns no pending Capture draft when none is stored', () async {
    expect(await store.loadPendingCapture(), isNull);
  });

  test('clears a pending Capture draft after successful staging', () async {
    await store.savePendingCapture(
      const PendingCapture(
          text: 'Already staged', idempotencyKey: 'capture-key-3'),
    );

    await store.clearPendingCapture();

    expect(await store.loadPendingCapture(), isNull);
  });
}
