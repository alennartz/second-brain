/// The receipt returned after the server stages an intake.
final class IngestReceipt {
  const IngestReceipt({required this.chunksStored});

  final int chunksStored;
}

/// A node returned as organized graph evidence.
final class GraphNode {
  const GraphNode({
    required this.id,
    required this.table,
    this.content,
    this.name,
    this.type,
    this.description,
    this.summary,
  });

  final String id;
  final String table;
  final String? content;
  final String? name;
  final String? type;
  final String? description;
  final String? summary;
}

/// A directed edge attached to a graph evidence node.
final class LinkedEdge {
  const LinkedEdge({
    required this.id,
    required this.table,
    required this.from,
    required this.to,
    this.context,
  });

  final String id;
  final String table;
  final String from;
  final String to;
  final String? context;
}

/// A source chunk that the server has not organized into the graph.
final class IntakeChunk {
  const IntakeChunk({
    required this.id,
    required this.intakeId,
    required this.chunkPosition,
    required this.totalChunks,
    required this.content,
    required this.source,
    required this.hints,
    required this.isUnprocessed,
  });

  final String id;
  final String intakeId;
  final int chunkPosition;
  final int totalChunks;
  final String content;
  final String source;
  final List<String> hints;
  final bool isUnprocessed;
}

/// Evidence for one organized graph node and its attached connections.
final class GraphNodeEvidence extends EvidenceItem {
  const GraphNodeEvidence({required this.node, required this.links});

  final GraphNode node;
  final List<LinkedEdge> links;
}

/// Evidence for one source chunk that remains unprocessed.
final class UnprocessedEvidence extends EvidenceItem {
  const UnprocessedEvidence({required this.chunk});

  final IntakeChunk chunk;
}

/// One item in the answer's grouped evidence projection.
sealed class EvidenceItem {
  const EvidenceItem();
}

/// A typed answer and the evidence cards projected from the optional context.
final class RecallResult {
  const RecallResult({required this.answer, required this.evidence});

  final String answer;
  final List<EvidenceItem> evidence;
}
