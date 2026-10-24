import 'package:shared_preferences/shared_preferences.dart';

/// One failed or edited Capture draft retained for explicit retry.
final class PendingCapture {
  const PendingCapture({required this.text, required this.idempotencyKey});

  final String text;
  final String idempotencyKey;
}

/// Durable settings and pending Capture storage owned by the application shell.
abstract interface class SettingsStore {
  Future<String?> loadBaseUrl();

  Future<void> saveBaseUrl(String value);

  Future<PendingCapture?> loadPendingCapture();

  Future<void> savePendingCapture(PendingCapture value);

  Future<void> clearPendingCapture();
}

/// Shared Preferences adapter for [SettingsStore].
final class SharedPreferencesSettingsStore implements SettingsStore {
  const SharedPreferencesSettingsStore(this.preferences);

  final SharedPreferences preferences;

  @override
  Future<String?> loadBaseUrl() {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<void> saveBaseUrl(String value) {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<PendingCapture?> loadPendingCapture() {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<void> savePendingCapture(PendingCapture value) {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<void> clearPendingCapture() {
    throw UnimplementedError('not implemented');
  }
}
