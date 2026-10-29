import '../gateway/brain_gateway.dart';
import '../persistence/models.dart';

/// Counts the outcomes observed during one foreground sync pass.
final class SyncReport {
  const SyncReport({
    required this.accepted,
    required this.conflicts,
    required this.pending,
  });

  final int accepted;
  final int conflicts;
  final int pending;
}

typedef GatewayForProfile = BrainGateway Function(BrainProfile profile);

/// Retries every profile's outbox on app open and resume.
abstract interface class SyncEngine {
  Future<SyncReport> syncAll(GatewayForProfile gatewayFor);
}

/// Interface-only sync engine stub.
final class SyncEngineStub implements SyncEngine {
  const SyncEngineStub();

  @override
  Future<SyncReport> syncAll(GatewayForProfile gatewayFor) {
    throw UnimplementedError('not implemented');
  }
}

/// Convenience operation matching the workflow contract.
Future<SyncReport> syncAll(GatewayForProfile gatewayFor) {
  throw UnimplementedError('not implemented');
}
