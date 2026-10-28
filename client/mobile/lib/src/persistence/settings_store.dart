import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// One failed or edited Capture draft retained for explicit retry.
final class PendingCapture {
  const PendingCapture({required this.text, required this.idempotencyKey, this.capturedAt});

  final String text;
  final String idempotencyKey;
  final String? capturedAt;
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

  static const _baseUrlKey = 'second_brain_mobile.base_url';
  static const _pendingCaptureKey = 'second_brain_mobile.pending_capture';

  final SharedPreferences preferences;

  @override
  Future<String?> loadBaseUrl() async {
    return preferences.getString(_baseUrlKey);
  }

  @override
  Future<void> saveBaseUrl(String value) async {
    await preferences.setString(_baseUrlKey, value);
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
}
