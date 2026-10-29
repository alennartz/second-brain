import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'brain_gateway.dart';
import 'errors.dart';
import 'models.dart';

/// Production gateway adapter for the brain server REST API.
final class HttpBrainGateway implements BrainGraphGateway {
  HttpBrainGateway({
    required this.baseUrl,
    required this.client,
    this.healthTimeout = const Duration(seconds: 5),
    this.requestTimeout = const Duration(minutes: 5),
    Duration? stageIntakeTimeout,
  }) : stageIntakeTimeout = stageIntakeTimeout ??
        (requestTimeout == const Duration(minutes: 5)
            ? const Duration(minutes: 5)
            : requestTimeout);

  /// A normalized absolute HTTP or HTTPS server URL.
  final String baseUrl;

  /// The HTTP transport. Tests inject a deterministic client.
  final http.Client client;

  /// The bounded timeout used for health checks.
  final Duration healthTimeout;

  /// The bounded timeout used for recall requests.
  final Duration requestTimeout;

  /// The bounded timeout used for server-side intake staging.
  final Duration stageIntakeTimeout;

  @override
  Future<void> checkHealth() async {
    final response = await _send(
      () => client.get(_endpoint('health')),
      timeout: healthTimeout,
    );
    final body = _decodeObject(response, endpoint: 'health');
    if (body['status'] != 'ok') {
      throw const MalformedResponseException(
        'Health response did not contain status ok',
      );
    }
  }

  @override
  Future<IngestReceipt> stageIntake(
    String text, {
    required String idempotencyKey,
    required String capturedAt,
  }) async {
    final response = await _send(
      () => client.post(
        _endpoint('ingest'),
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: jsonEncode({
          'text': text,
          'hints': <String>[],
          'source': 'mobile',
          'captured_at': capturedAt,
        }),
      ),
      timeout: stageIntakeTimeout,
    );
    final body = _decodeObject(response, endpoint: 'ingest');
    final chunksStored = body['chunks_stored'];
    if (chunksStored is! int) {
      throw const MalformedResponseException(
        'Intake response chunks_stored must be an integer',
      );
    }
    return IngestReceipt(chunksStored: chunksStored);
  }

  @override
  Future<MemorySearchResult> searchMemory(String query, {int? limit}) {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<GraphNodeDetail> getGraph(String recordId) {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<GraphRefreshResult> refreshGraph(List<String> recordIds) {
    throw UnimplementedError('not implemented');
  }

  @override
  Future<RecallResult> recall(String question) async {
    final response = await _send(
      () => client.post(
        _endpoint('recall'),
        headers: const {
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'question': question,
          'hints': <String>[],
        }),
      ),
      timeout: requestTimeout,
    );
    final body = _decodeObject(response, endpoint: 'recall');
    return _decodeRecall(body);
  }

  Uri _endpoint(String path) {
    final normalized = baseUrl.trim().replaceFirst(RegExp(r'/+$'), '');
    return Uri.parse('$normalized/$path');
  }

  Future<http.Response> _send(
    Future<http.Response> Function() request, {
    required Duration timeout,
  }) async {
    try {
      final response = await request().timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpStatusException(
          statusCode: response.statusCode,
          message: 'Brain server returned HTTP ${response.statusCode}',
          body: _responseText(response),
        );
      }
      return response;
    } on BrainClientException {
      rethrow;
    } on TimeoutException {
      throw const NetworkException('The request timed out');
    } on Object catch (error) {
      throw NetworkException('The request failed: $error');
    }
  }

  String _responseText(http.Response response) {
    return utf8.decode(response.bodyBytes);
  }

  Map<String, dynamic> _decodeObject(
    http.Response response, {
    required String endpoint,
  }) {
    final decoded = _decodeJson(_responseText(response), endpoint: endpoint);
    if (decoded is! Map<String, dynamic>) {
      throw MalformedResponseException(
        '$endpoint response must be a JSON object',
      );
    }
    return decoded;
  }

  Object? _decodeJson(String body, {required String endpoint}) {
    try {
      return jsonDecode(body);
    } on FormatException catch (error) {
      throw MalformedResponseException(
        '$endpoint response was not valid JSON: ${error.message}',
      );
    }
  }

  RecallResult _decodeRecall(Map<String, dynamic> body) {
    final answer = body['answer'];
    if (answer is! String) {
      throw const MalformedResponseException(
        'Recall response answer must be a string',
      );
    }

    if (!body.containsKey('context')) {
      throw const MalformedResponseException(
        'Recall response context must be an object or null',
      );
    }
    final rawContext = body['context'];
    if (rawContext == null) {
      return RecallResult(answer: answer, evidence: const []);
    }
    if (rawContext is! Map<String, dynamic>) {
      throw const MalformedResponseException(
        'Recall response context must be an object or null',
      );
    }

    final nodes = _decodeNodes(rawContext['nodes']);
    final edges = _decodeEdges(rawContext['edges']);
    final chunks = _decodeChunks(rawContext['unprocessed']);
    return RecallResult(
      answer: answer,
      evidence: _projectEvidence(nodes: nodes, edges: edges, chunks: chunks),
    );
  }

  List<GraphNode> _decodeNodes(Object? rawNodes) {
    if (rawNodes is! List<Object?>) {
      throw const MalformedResponseException(
        'Recall context nodes must be an array',
      );
    }
    return rawNodes.map((rawNode) {
      final node = _requireObject(rawNode, 'graph node');
      final id = _requiredString(node, 'id', 'graph node');
      final table = _requiredString(node, 'table', 'graph node');
      return GraphNode(
        id: id,
        table: table,
        content: _optionalString(node, 'content', 'graph node'),
        name: _optionalString(node, 'name', 'graph node'),
        type: _optionalString(node, 'type', 'graph node'),
        description: _optionalString(node, 'description', 'graph node'),
        summary: _optionalString(node, 'summary', 'graph node'),
        freshnessAt: _optionalString(node, 'freshness_at', 'graph node'),
      );
    }).toList(growable: false);
  }

  List<LinkedEdge> _decodeEdges(Object? rawEdges) {
    if (rawEdges is! List<Object?>) {
      throw const MalformedResponseException(
        'Recall context edges must be an array',
      );
    }
    return rawEdges.map((rawEdge) {
      final edge = _requireObject(rawEdge, 'graph edge');
      return LinkedEdge(
        id: _requiredString(edge, 'id', 'graph edge'),
        table: _requiredString(edge, 'table', 'graph edge'),
        from: _requiredString(edge, 'from', 'graph edge'),
        to: _requiredString(edge, 'to', 'graph edge'),
        context: _optionalString(edge, 'context', 'graph edge'),
        freshnessAt: _optionalString(edge, 'freshness_at', 'graph edge'),
      );
    }).toList(growable: false);
  }

  List<IntakeChunk> _decodeChunks(Object? rawChunks) {
    if (rawChunks is! List<Object?>) {
      throw const MalformedResponseException(
        'Recall context unprocessed must be an array',
      );
    }
    return rawChunks.map((rawChunk) {
      final chunk = _requireObject(rawChunk, 'unprocessed chunk');
      final hints = chunk['hints'];
      if (hints is! List<Object?> || hints.any((hint) => hint is! String)) {
        throw const MalformedResponseException(
          'Unprocessed chunk hints must be an array of strings',
        );
      }
      final chunkIndex = chunk['chunk_index'];
      final totalChunks = chunk['total_chunks'];
      final unprocessed = chunk['unprocessed'];
      if (chunkIndex is! int || totalChunks is! int || unprocessed is! bool) {
        throw const MalformedResponseException(
          'Unprocessed chunk positions and marker have invalid types',
        );
      }
      return IntakeChunk(
        id: _requiredString(chunk, 'id', 'unprocessed chunk'),
        intakeId: _requiredString(chunk, 'intake_id', 'unprocessed chunk'),
        chunkPosition: chunkIndex,
        totalChunks: totalChunks,
        content: _requiredString(chunk, 'content', 'unprocessed chunk'),
        source: _requiredString(chunk, 'source', 'unprocessed chunk'),
        hints: List<String>.unmodifiable(hints.cast<String>()),
        isUnprocessed: unprocessed,
        capturedAt: _optionalString(chunk, 'captured_at', 'unprocessed chunk'),
      );
    }).toList(growable: false);
  }

  List<EvidenceItem> _projectEvidence({
    required List<GraphNode> nodes,
    required List<LinkedEdge> edges,
    required List<IntakeChunk> chunks,
  }) {
    final cards = <String, _GraphEvidenceBuilder>{};
    final orderedCards = <_GraphEvidenceBuilder>[];
    for (final node in nodes) {
      final card = _GraphEvidenceBuilder(node);
      cards[node.id] = card;
      orderedCards.add(card);
    }

    for (final edge in edges) {
      final target = cards[edge.to] ?? cards[edge.from];
      if (target != null) {
        target.links.add(edge);
        continue;
      }

      final orphan = cards.putIfAbsent(edge.to, () {
        final card = _GraphEvidenceBuilder(
          GraphNode(id: edge.to, table: _tableFromRecordId(edge.to)),
        );
        orderedCards.add(card);
        return card;
      });
      orphan.links.add(edge);
    }

    return [
      ...orderedCards.map(
        (card) => GraphNodeEvidence(
          node: card.node,
          links: List<LinkedEdge>.unmodifiable(card.links),
        ),
      ),
      ...chunks.map((chunk) => UnprocessedEvidence(chunk: chunk)),
    ];
  }

  Map<String, dynamic> _requireObject(Object? value, String label) {
    if (value is! Map<String, dynamic>) {
      throw MalformedResponseException('$label must be a JSON object');
    }
    return value;
  }

  String _requiredString(
    Map<String, dynamic> object,
    String field,
    String label,
  ) {
    final value = object[field];
    if (value is! String) {
      throw MalformedResponseException('$label $field must be a string');
    }
    return value;
  }

  String? _optionalString(
    Map<String, dynamic> object,
    String field,
    String label,
  ) {
    final value = object[field];
    if (value == null) return null;
    if (value is! String) {
      throw MalformedResponseException('$label $field must be a string');
    }
    return value;
  }

  String _tableFromRecordId(String id) {
    final separator = id.indexOf(':');
    return separator < 0 ? id : id.substring(0, separator);
  }
}

final class _GraphEvidenceBuilder {
  _GraphEvidenceBuilder(this.node);

  final GraphNode node;
  final List<LinkedEdge> links = [];
}
