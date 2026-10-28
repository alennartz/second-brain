import 'models.dart';

/// REST operations exposed to the mobile application shell and screens.
abstract interface class BrainGateway {
  /// Confirms that the configured server is healthy.
  Future<void> checkHealth();

  /// Stages [text] and returns the number of stored chunks.
  Future<IngestReceipt> stageIntake(
    String text, {
    required String idempotencyKey,
    required String capturedAt,
  });

  /// Recalls an answer and its grouped evidence for [question].
  Future<RecallResult> recall(String question);
}
