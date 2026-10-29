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
    this.freshnessAt,
  });

  final String id;
  final String table;
  final String? content;
  final String? name;
  final String? type;
  final String? description;
  final String? summary;
  final String? freshnessAt;
}

/// A directed edge attached to a graph evidence node.
final class LinkedEdge {
  const LinkedEdge({
    required this.id,
    required this.table,
    required this.from,
    required this.to,
    this.context,
    this.freshnessAt,
  });

  final String id;
  final String table;
  final String from;
  final String to;
  final String? context;
  final String? freshnessAt;
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
    this.capturedAt,
  });

  final String id;
  final String intakeId;
  final int chunkPosition;
  final int totalChunks;
  final String content;
  final String source;
  final List<String> hints;
  final bool isUnprocessed;
  final String? capturedAt;
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

/// Hybrid search projections returned without an answer-generation step.
final class MemorySearchResult {
  const MemorySearchResult({required this.nodes, required this.unprocessed});

  final List<GraphNode> nodes;
  final List<IntakeChunk> unprocessed;
}

/// One node and its immediate graph connections.
final class GraphNodeDetail {
  const GraphNodeDetail({required this.node, required this.connections});

  final GraphNode node;
  final List<GraphConnection> connections;
}

/// A directed graph connection in a node detail or refresh result.
final class GraphConnection {
  const GraphConnection({required this.edge, required this.node});

  final LinkedEdge edge;
  final GraphNode node;
}

/// One item returned by a batch graph refresh.
sealed class GraphRefreshItem {
  const GraphRefreshItem({required this.id});

  final String id;
}

final class GraphRefreshFound extends GraphRefreshItem {
  const GraphRefreshFound({
    required super.id,
    required this.node,
    required this.connections,
  });

  final GraphNode node;
  final List<GraphConnection> connections;
}

final class GraphRefreshMissing extends GraphRefreshItem {
  const GraphRefreshMissing({required super.id});
}

/// Results for every requested graph record, in request order.
final class GraphRefreshResult {
  const GraphRefreshResult({required this.results});

  final List<GraphRefreshItem> results;
}
