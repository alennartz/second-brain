import 'package:http/http.dart' as http;

import 'brain_gateway.dart';
import 'models.dart';

/// Production gateway adapter for the brain server REST API.
final class HttpBrainGateway implements BrainGateway {
  HttpBrainGateway({
    required this.baseUrl,
    required this.client,
    this.healthTimeout = const Duration(seconds: 5),
    this.requestTimeout = const Duration(seconds: 30),
  });

  /// A normalized absolute HTTP or HTTPS server URL.
  final String baseUrl;

  /// The HTTP transport. Tests inject a deterministic client.
  final http.Client client;

  /// The bounded timeout used for health checks.
  final Duration healthTimeout;

  /// The bounded timeout used for intake and recall requests.
  final Duration requestTimeout;

  @override
  Future<void> checkHealth() {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<IngestReceipt> stageIntake(
    String text, {
    required String idempotencyKey,
  }) {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<RecallResult> recall(String question) {
    throw UnimplementedError('not implemented');
  }
}
