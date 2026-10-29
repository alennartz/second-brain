import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../persistence/settings_store.dart';
import 'brain_gateway.dart';
import 'errors.dart';
import 'models.dart';

/// Production gateway adapter for the brain server REST API.
final class HttpBrainGateway implements BrainGraphGateway {
  HttpBrainGateway({
    ServerConfiguration? configuration,
    String? baseUrl,
    required this.client,
    this.healthTimeout = const Duration(seconds: 5),
    this.requestTimeout = const Duration(minutes: 5),
    Duration? stageIntakeTimeout,
  })  : configuration = configuration ??
            ServerConfiguration(
              baseUrl: baseUrl ??
                  (throw ArgumentError.notNull('configuration or baseUrl')),
            ),
        stageIntakeTimeout = stageIntakeTimeout ??
            (requestTimeout == const Duration(minutes: 5)
                ? const Duration(minutes: 5)
                : requestTimeout);

  /// The complete server endpoint and optional Access credentials.
  final ServerConfiguration configuration;

  /// A normalized absolute HTTP or HTTPS server URL.
  String get baseUrl => configuration.baseUrl;

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
      () => client.get(_endpoint('health'), headers: _requestHeaders()),
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
        headers: _requestHeaders({
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        }),
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
  Future<MemorySearchResult> searchMemory(String query, {int? limit}) async {
    final response = await _send(
      () => client.post(
        _endpoint('search'),
        headers: _requestHeaders(const {
          'Content-Type': 'application/json',
        }),
        body: jsonEncode({
          'query': query,
          if (limit != null) 'limit': limit,
        }),
      ),
      timeout: requestTimeout,
    );
    final body = _decodeObject(response, endpoint: 'search');
    return MemorySearchResult(
      nodes: _decodeNodes(
        body['nodes'],
        label: 'Search response nodes',
        requireTable: false,
      ),
      unprocessed: _decodeChunks(
        body['unprocessed'],
        label: 'Search response unprocessed',
        requireMarker: false,
      ),
    );
  }

  @override
  Future<GraphNodeDetail> getGraph(String recordId) async {
    final response = await _send(
      () => client.get(
        _endpoint('graph/${Uri.encodeComponent(recordId)}'),
        headers: _requestHeaders(),
      ),
      timeout: requestTimeout,
    );
    final body = _decodeObject(response, endpoint: 'graph');
    return GraphNodeDetail(
      node: _decodeNode(
        body['node'],
        label: 'Graph response node',
        requireTable: false,
      ),
      connections: _decodeConnections(
        body['connections'],
        label: 'Graph response connections',
      ),
    );
  }

  @override
  Future<GraphRefreshResult> refreshGraph(List<String> recordIds) async {
    final response = await _send(
      () => client.post(
        _endpoint('graph/refresh'),
        headers: _requestHeaders(const {
          'Content-Type': 'application/json',
        }),
        body: jsonEncode({'ids': recordIds}),
      ),
      timeout: requestTimeout,
    );
    final body = _decodeObject(response, endpoint: 'graph refresh');
    final rawResults = body['results'];
    if (rawResults is! List<Object?>) {
      throw const MalformedResponseException(
        'Graph refresh response results must be an array',
      );
    }
    final results = rawResults.map(_decodeRefreshItem).toList(growable: false);
    return GraphRefreshResult(results: results);
  }

  @override
  Future<RecallResult> recall(String question) async {
    final response = await _send(
      () => client.post(
        _endpoint('recall'),
        headers: _requestHeaders(const {
          'Content-Type': 'application/json',
        }),
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

  Map<String, String> _requestHeaders([Map<String, String>? headers]) {
    final result = <String, String>{...?headers};
    final accessClientId = _nonBlank(configuration.accessClientId);
    final accessClientSecret = _nonBlank(configuration.accessClientSecret);
    if (accessClientId == null || accessClientSecret == null) return result;
    final scheme = Uri.tryParse(baseUrl)?.scheme;
    if (scheme != 'https') {
      throw const ConfigurationException(
        'Cloudflare Access credentials require an HTTPS server URL',
      );
    }
    result['CF-Access-Client-Id'] = accessClientId;
    result['CF-Access-Client-Secret'] = accessClientSecret;
    return result;
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

    final nodes = _decodeNodes(
      rawContext['nodes'],
      label: 'Recall context nodes',
      requireTable: true,
    );
    final edges = _decodeEdges(
      rawContext['edges'],
      label: 'Recall context edges',
    );
    final chunks = _decodeChunks(
      rawContext['unprocessed'],
      label: 'Recall context unprocessed',
      requireMarker: true,
    );
    return RecallResult(
      answer: answer,
      evidence: _projectEvidence(nodes: nodes, edges: edges, chunks: chunks),
    );
  }

  List<GraphNode> _decodeNodes(
    Object? rawNodes, {
    required String label,
    required bool requireTable,
  }) {
    if (rawNodes is! List<Object?>) {
      throw MalformedResponseException('$label must be an array');
    }
    return rawNodes
        .map(
          (rawNode) => _decodeNode(
            rawNode,
            label: 'Graph node',
            requireTable: requireTable,
          ),
        )
        .toList(growable: false);
  }

  GraphNode _decodeNode(
    Object? rawNode, {
    required String label,
    required bool requireTable,
  }) {
    final node = _requireObject(rawNode, label);
    final id = _requiredString(node, 'id', label);
    final table = _decodeNodeTable(
      node,
      id: id,
      label: label,
      requireTable: requireTable,
    );
    return GraphNode(
      id: id,
      table: table,
      content: _optionalString(node, 'content', label),
      name: _optionalString(node, 'name', label),
      type: _optionalString(node, 'type', label),
      description: _optionalString(node, 'description', label),
      summary: _optionalString(node, 'summary', label),
      freshnessAt: _optionalString(node, 'freshness_at', label),
    );
  }

  String _decodeNodeTable(
    Map<String, dynamic> node, {
    required String id,
    required String label,
    required bool requireTable,
  }) {
    if (requireTable) return _requiredString(node, 'table', label);
    if (!node.containsKey('table')) return _tableFromRecordId(id);
    return _requiredString(node, 'table', label);
  }

  List<LinkedEdge> _decodeEdges(
    Object? rawEdges, {
    required String label,
  }) {
    if (rawEdges is! List<Object?>) {
      throw MalformedResponseException('$label must be an array');
    }
    return rawEdges
        .map(
          (rawEdge) => _decodeEdge(
            rawEdge,
            label: 'Graph edge',
          ),
        )
        .toList(growable: false);
  }

  LinkedEdge _decodeEdge(Object? rawEdge, {required String label}) {
    final edge = _requireObject(rawEdge, label);
    return LinkedEdge(
      id: _requiredString(edge, 'id', label),
      table: _requiredString(edge, 'table', label),
      from: _requiredString(edge, 'from', label),
      to: _requiredString(edge, 'to', label),
      context: _optionalString(edge, 'context', label),
      freshnessAt: _optionalString(edge, 'freshness_at', label),
    );
  }

  List<GraphConnection> _decodeConnections(
    Object? rawConnections, {
    required String label,
  }) {
    if (rawConnections is! List<Object?>) {
      throw MalformedResponseException('$label must be an array');
    }
    return rawConnections.map((rawConnection) {
      final connection = _requireObject(rawConnection, 'Graph connection');
      return GraphConnection(
        edge: _decodeEdge(connection['edge'], label: 'Graph connection edge'),
        node: _decodeNode(
          connection['node'],
          label: 'Graph connection node',
          requireTable: false,
        ),
      );
    }).toList(growable: false);
  }

  List<IntakeChunk> _decodeChunks(
    Object? rawChunks, {
    required String label,
    required bool requireMarker,
  }) {
    if (rawChunks is! List<Object?>) {
      throw MalformedResponseException('$label must be an array');
    }
    return rawChunks.map((rawChunk) {
      final chunk = _requireObject(rawChunk, 'Unprocessed chunk');
      final hints = chunk['hints'];
      if (hints is! List<Object?> || hints.any((hint) => hint is! String)) {
        throw const MalformedResponseException(
          'Unprocessed chunk hints must be an array of strings',
        );
      }
      final chunkIndex = chunk['chunk_index'];
      final totalChunks = chunk['total_chunks'];
      final marker = chunk['unprocessed'];
      if (chunkIndex is! int ||
          totalChunks is! int ||
          (requireMarker && marker is! bool)) {
        throw const MalformedResponseException(
          'Unprocessed chunk positions and marker have invalid types',
        );
      }
      return IntakeChunk(
        id: _requiredString(chunk, 'id', 'Unprocessed chunk'),
        intakeId: _requiredString(chunk, 'intake_id', 'Unprocessed chunk'),
        chunkPosition: chunkIndex,
        totalChunks: totalChunks,
        content: _requiredString(chunk, 'content', 'Unprocessed chunk'),
        source: _requiredString(chunk, 'source', 'Unprocessed chunk'),
        hints: List<String>.unmodifiable(hints.cast<String>()),
        isUnprocessed: requireMarker ? marker as bool : true,
        capturedAt: _optionalString(
          chunk,
          'captured_at',
          'Unprocessed chunk',
        ),
      );
    }).toList(growable: false);
  }

  GraphRefreshItem _decodeRefreshItem(Object? rawResult) {
    final result = _requireObject(rawResult, 'Graph refresh result');
    final id = _requiredString(result, 'id', 'Graph refresh result');
    final status = _requiredString(result, 'status', 'Graph refresh result');
    switch (status) {
      case 'missing':
        return GraphRefreshMissing(id: id);
      case 'found':
        return GraphRefreshFound(
          id: id,
          node: _decodeNode(
            result['node'],
            label: 'Graph refresh node',
            requireTable: false,
          ),
          connections: _decodeConnections(
            result['connections'],
            label: 'Graph refresh connections',
          ),
        );
      default:
        throw const MalformedResponseException(
          'Graph refresh result status must be found or missing',
        );
    }
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

String? _nonBlank(String? value) {
  final trimmed = value?.trim();
  return trimmed == null || trimmed.isEmpty ? null : trimmed;
}
