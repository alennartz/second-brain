import 'dart:convert';

import '../gateway/models.dart';
import 'models.dart';

/// Encodes a timestamp without dropping its instant or offset.
String? encodeTimestamp(DateTime? value) => value?.toIso8601String();

/// Decodes a stored timestamp. A null value remains null.
DateTime? decodeTimestamp(Object? value) {
  if (value == null) return null;
  if (value is! String) {
    throw const FormatException('timestamp must be a string');
  }
  return DateTime.parse(value);
}

Map<String, dynamic> encodeGraphNode(GraphNode node) => {
      'id': node.id,
      'table': node.table,
      'content': node.content,
      'name': node.name,
      'type': node.type,
      'description': node.description,
      'summary': node.summary,
      'freshness_at': node.freshnessAt,
    };

GraphNode decodeGraphNode(Object? value) {
  final map = _map(value, 'graph node');
  return GraphNode(
    id: _requiredString(map, 'id'),
    table: _requiredString(map, 'table'),
    content: _optionalString(map, 'content'),
    name: _optionalString(map, 'name'),
    type: _optionalString(map, 'type'),
    description: _optionalString(map, 'description'),
    summary: _optionalString(map, 'summary'),
    freshnessAt: _optionalString(map, 'freshness_at'),
  );
}

Map<String, dynamic> encodeLinkedEdge(LinkedEdge edge) => {
      'id': edge.id,
      'table': edge.table,
      'from': edge.from,
      'to': edge.to,
      'context': edge.context,
      'freshness_at': edge.freshnessAt,
    };

LinkedEdge decodeLinkedEdge(Object? value) {
  final map = _map(value, 'linked edge');
  return LinkedEdge(
    id: _requiredString(map, 'id'),
    table: _requiredString(map, 'table'),
    from: _requiredString(map, 'from'),
    to: _requiredString(map, 'to'),
    context: _optionalString(map, 'context'),
    freshnessAt: _optionalString(map, 'freshness_at'),
  );
}

Map<String, dynamic> encodeIntakeChunk(IntakeChunk chunk) => {
      'id': chunk.id,
      'intake_id': chunk.intakeId,
      'chunk_position': chunk.chunkPosition,
      'total_chunks': chunk.totalChunks,
      'content': chunk.content,
      'source': chunk.source,
      'hints': chunk.hints,
      'is_unprocessed': chunk.isUnprocessed,
      'captured_at': chunk.capturedAt,
    };

IntakeChunk decodeIntakeChunk(Object? value) {
  final map = _map(value, 'intake chunk');
  final position = map['chunk_position'];
  final total = map['total_chunks'];
  if (position is! int || total is! int) {
    throw const FormatException('intake chunk positions must be integers');
  }
  final rawHints = map['hints'];
  if (rawHints is! List || !rawHints.every((hint) => hint is String)) {
    throw const FormatException('intake chunk hints must be strings');
  }
  final unprocessed = map['is_unprocessed'];
  if (unprocessed is! bool) {
    throw const FormatException('intake chunk state must be a boolean');
  }
  return IntakeChunk(
    id: _requiredString(map, 'id'),
    intakeId: _requiredString(map, 'intake_id'),
    chunkPosition: position,
    totalChunks: total,
    content: _requiredString(map, 'content'),
    source: _requiredString(map, 'source'),
    hints: List<String>.unmodifiable(rawHints.cast<String>()),
    isUnprocessed: unprocessed,
    capturedAt: _optionalString(map, 'captured_at'),
  );
}

Map<String, dynamic> encodeEvidenceItem(EvidenceItem item) {
  return switch (item) {
    GraphNodeEvidence(:final node, :final links) => {
        'kind': 'graph_node',
        'node': encodeGraphNode(node),
        'links': links.map(encodeLinkedEdge).toList(growable: false),
      },
    UnprocessedEvidence(:final chunk) => {
        'kind': 'unprocessed',
        'chunk': encodeIntakeChunk(chunk),
      },
  };
}

EvidenceItem decodeEvidenceItem(Object? value) {
  final map = _map(value, 'evidence item');
  return switch (map['kind']) {
    'graph_node' => GraphNodeEvidence(
        node: decodeGraphNode(map['node']),
        links: _decodeList(map['links'], decodeLinkedEdge),
      ),
    'unprocessed' =>
      UnprocessedEvidence(chunk: decodeIntakeChunk(map['chunk'])),
    _ => throw const FormatException('unknown evidence item kind'),
  };
}

String encodeEvidenceJson(Iterable<EvidenceItem> evidence) =>
    jsonEncode(evidence.map(encodeEvidenceItem).toList(growable: false));

List<EvidenceItem> decodeEvidenceJson(Object value) {
  final decoded = value is String ? jsonDecode(value) : value;
  if (decoded is! List) {
    throw const FormatException('evidence must be a list');
  }
  return List<EvidenceItem>.unmodifiable(
    decoded.map(decodeEvidenceItem),
  );
}

Map<String, dynamic> encodeWorkspace(Workspace workspace) => {
      'nodes': workspace.nodes
          .map((item) => {
                'node': encodeGraphNode(item.node),
                'status': _encodeWorkspaceStatus(item.status),
                'expanded': item.expanded,
              })
          .toList(growable: false),
      'edges': workspace.edges
          .map((item) => {
                'edge': encodeLinkedEdge(item.edge),
                'status': _encodeWorkspaceStatus(item.status),
              })
          .toList(growable: false),
      'fetched_at': encodeTimestamp(workspace.fetchedAt),
    };

Workspace decodeWorkspace(Object? value) {
  final map = _map(value, 'workspace');
  return Workspace(
    nodes: _decodeList(map['nodes'], (item) {
      final nodeMap = _map(item, 'workspace node');
      final expanded = nodeMap['expanded'];
      if (expanded is! bool) {
        throw const FormatException('workspace node expansion must be boolean');
      }
      return WorkspaceNode(
        node: decodeGraphNode(nodeMap['node']),
        status: _decodeWorkspaceStatus(nodeMap['status']),
        expanded: expanded,
      );
    }),
    edges: _decodeList(map['edges'], (item) {
      final edgeMap = _map(item, 'workspace edge');
      return WorkspaceEdge(
        edge: decodeLinkedEdge(edgeMap['edge']),
        status: _decodeWorkspaceStatus(edgeMap['status']),
      );
    }),
    fetchedAt: decodeTimestamp(map['fetched_at']),
  );
}

String encodeWorkspaceJson(Workspace workspace) =>
    jsonEncode(encodeWorkspace(workspace));

Workspace decodeWorkspaceJson(Object value) {
  final decoded = value is String ? jsonDecode(value) : value;
  return decodeWorkspace(decoded);
}

Map<String, dynamic> _map(Object? value, String label) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  throw FormatException('$label must be an object');
}

String _requiredString(Map<String, dynamic> map, String key) {
  final value = map[key];
  if (value is String) return value;
  throw FormatException('$key must be a string');
}

String? _optionalString(Map<String, dynamic> map, String key) {
  final value = map[key];
  if (value == null) return null;
  if (value is String) return value;
  throw FormatException('$key must be a string or null');
}

List<T> _decodeList<T>(Object? value, T Function(Object?) decode) {
  if (value is! List) throw const FormatException('value must be a list');
  return List<T>.unmodifiable(value.map(decode));
}

String _encodeWorkspaceStatus(WorkspaceItemStatus status) => switch (status) {
      WorkspaceItemStatus.loaded => 'loaded',
      WorkspaceItemStatus.missing => 'missing',
      WorkspaceItemStatus.newItem => 'new',
    };

WorkspaceItemStatus _decodeWorkspaceStatus(Object? value) => switch (value) {
      'loaded' => WorkspaceItemStatus.loaded,
      'missing' => WorkspaceItemStatus.missing,
      'new' => WorkspaceItemStatus.newItem,
      _ => throw const FormatException('unknown workspace item status'),
    };
