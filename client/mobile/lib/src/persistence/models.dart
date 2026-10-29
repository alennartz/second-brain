import '../gateway/models.dart';

/// Connection state for one configured Brain profile.
enum BrainProfileStatus { neverConnected, connected }

/// A saved server profile. Profiles own independent outboxes and workspaces.
final class BrainProfile {
  const BrainProfile({
    required this.id,
    required this.name,
    required this.baseUrl,
    this.accessClientId,
    this.accessClientSecret,
    this.status = BrainProfileStatus.neverConnected,
  });

  final String id;
  final String name;
  final String baseUrl;
  final String? accessClientId;
  final String? accessClientSecret;
  final BrainProfileStatus status;
}

/// Fields needed to add a Brain profile.
final class BrainProfileDraft {
  const BrainProfileDraft({
    required this.name,
    required this.baseUrl,
    this.accessClientId,
    this.accessClientSecret,
  });

  final String name;
  final String baseUrl;
  final String? accessClientId;
  final String? accessClientSecret;
}

enum OutboxState { pending, edited, conflict }

/// One durable Capture outbox entry.
final class OutboxEntry {
  const OutboxEntry({
    required this.id,
    required this.brainId,
    required this.text,
    required this.idempotencyKey,
    required this.capturedAt,
    this.state = OutboxState.pending,
  });

  final String id;
  final String brainId;
  final String text;
  final String idempotencyKey;
  final String capturedAt;
  final OutboxState state;
}

/// A self-contained successful Ask result.
final class AnswerSnapshot {
  const AnswerSnapshot({
    required this.question,
    required this.answer,
    required this.answeredAt,
    required this.evidence,
  });

  final String question;
  final String answer;
  final DateTime answeredAt;
  final List<EvidenceItem> evidence;
}

enum WorkspaceItemStatus { loaded, missing, newItem }

/// A node saved in an Explore workspace.
final class WorkspaceNode {
  const WorkspaceNode({
    required this.node,
    this.status = WorkspaceItemStatus.loaded,
    this.expanded = false,
  });

  final GraphNode node;
  final WorkspaceItemStatus status;
  final bool expanded;
}

/// An edge saved in an Explore workspace.
final class WorkspaceEdge {
  const WorkspaceEdge({
    required this.edge,
    this.status = WorkspaceItemStatus.loaded,
  });

  final LinkedEdge edge;
  final WorkspaceItemStatus status;
}

/// Persisted Explore canvas data and refresh timestamp.
final class Workspace {
  const Workspace({
    required this.nodes,
    required this.edges,
    this.fetchedAt,
  });

  final List<WorkspaceNode> nodes;
  final List<WorkspaceEdge> edges;
  final DateTime? fetchedAt;
}
