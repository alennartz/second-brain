import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../persistence/models.dart';
import '../persistence/repositories.dart';

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

/// Delivers all retryable entries from the durable profile and outbox
/// repositories.
final class SyncEngineImpl implements SyncEngine {
  const SyncEngineImpl({required this.profiles, required this.outbox});

  final BrainProfileRepository profiles;
  final CaptureOutboxRepository outbox;

  @override
  Future<SyncReport> syncAll(GatewayForProfile gatewayFor) async {
    final savedProfiles = await profiles.list();
    final profilesById = <String, BrainProfile>{
      for (final profile in savedProfiles) profile.id: profile,
    };
    final entries = await outbox.pendingAll();
    final gateways = <String, BrainGateway>{};
    var accepted = 0;
    var conflicts = 0;
    var pending = 0;

    for (final entry in entries) {
      // A conflict represents a key that the server already accepted. Keep
      // the edited text for recovery, but never submit it again implicitly.
      if (entry.state == OutboxState.conflict) continue;

      final profile = profilesById[entry.brainId];
      if (profile == null) {
        // Preserve an entry whose profile was removed or is not yet visible.
        pending++;
        continue;
      }

      try {
        final gateway = gateways.putIfAbsent(
          profile.id,
          () => gatewayFor(profile),
        );
        await gateway.stageIntake(
          entry.text,
          idempotencyKey: entry.idempotencyKey,
          capturedAt: entry.capturedAt,
        );
      } on HttpStatusException catch (error) {
        if (error.statusCode != 409) {
          pending++;
          continue;
        }

        try {
          await outbox.markConflict(entry.id);
          conflicts++;
        } on Object {
          // A failed local transition leaves the entry retryable. The server
          // response cannot be replayed safely as a new capture.
          pending++;
        }
        continue;
      } on Object {
        // Network, configuration, and malformed-response failures all leave
        // the durable entry untouched for the next foreground pass.
        pending++;
        continue;
      }

      try {
        await outbox.markAccepted(entry.id);
        accepted++;
      } on Object {
        // If local deletion fails, retry with the same key. Intake is
        // idempotent, so a later pass cannot create a duplicate chunk set.
        pending++;
      }
    }

    return SyncReport(
      accepted: accepted,
      conflicts: conflicts,
      pending: pending,
    );
  }
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
