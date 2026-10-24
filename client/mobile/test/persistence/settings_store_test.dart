import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late SharedPreferences preferences;
  late SettingsStore store;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    preferences = await SharedPreferences.getInstance();
    store = SharedPreferencesSettingsStore(preferences);
  });

  test('stores and loads the configured server URL', () async {
    await store.saveBaseUrl('https://brain.example.test');

    expect(await store.loadBaseUrl(), 'https://brain.example.test');
  });

  test('loads no URL before setup has saved one', () async {
    expect(await store.loadBaseUrl(), isNull);
  });

  test('persists a pending Capture draft with its idempotency key', () async {
    const draft = PendingCapture(
      text: 'Keep this thought when the server is down',
      idempotencyKey: 'capture-key-2',
    );

    await store.savePendingCapture(draft);
    final loaded = await store.loadPendingCapture();

    expect(loaded, isNotNull);
    expect(loaded!.text, draft.text);
    expect(loaded.idempotencyKey, draft.idempotencyKey);
  });

  test('returns no pending Capture draft when none is stored', () async {
    expect(await store.loadPendingCapture(), isNull);
  });

  test('clears a pending Capture draft after successful staging', () async {
    await store.savePendingCapture(
      const PendingCapture(text: 'Already staged', idempotencyKey: 'capture-key-3'),
    );

    await store.clearPendingCapture();

    expect(await store.loadPendingCapture(), isNull);
  });
}
