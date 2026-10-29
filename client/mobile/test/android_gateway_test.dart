import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

const node = {'id': 'entity:garden', 'table': 'entity', 'name': 'Garden'};
const connection = {
  'edge': {
    'id': 'references:1',
    'table': 'references',
    'from': 'entity:garden',
    'to': 'note:layout'
  },
  'node': {'id': 'note:layout', 'table': 'note', 'content': 'Behind shed'}
};
const searchBody = {
  'nodes': [node],
  'unprocessed': [
    {
      'id': 'intake_chunk:1',
      'intake_id': 'intake:1',
      'chunk_index': 0,
      'total_chunks': 1,
      'content': 'Raw thought',
      'source': 'mobile',
      'hints': <String>[]
    }
  ]
};
const graphBody = {
  'node': node,
  'connections': [connection]
};
const refreshBody = {
  'results': [
    {
      'id': 'entity:garden',
      'status': 'found',
      'node': node,
      'connections': [connection]
    },
    {'id': 'entity:deleted', 'status': 'missing'}
  ]
};

HttpBrainGateway gateway(Object body,
        {void Function(http.Request)? inspect, int status = 200}) =>
    HttpBrainGateway(
        baseUrl: 'https://brain.example.test',
        client: MockClient((request) async {
          inspect?.call(request);
          return http.Response(jsonEncode(body), status,
              headers: {'content-type': 'application/json'});
        }));

void main() {
  test('search sends query and limit to direct search and separates raw chunks',
      () async {
    final result = await gateway(searchBody, inspect: (request) {
      expect(request.method, 'POST');
      expect(request.url.path, '/search');
      expect(jsonDecode(request.body)['query'], 'garden');
      expect(jsonDecode(request.body)['limit'], 20);
    }).searchMemory('garden', limit: 20);
    expect(result.nodes.single.id, 'entity:garden');
    expect(result.nodes.single.name, 'Garden');
    expect(result.unprocessed.single.id, 'intake_chunk:1');
    expect(result.unprocessed.single.content, 'Raw thought');
    expect(result.unprocessed.single.isUnprocessed, isTrue);
  });
  test('empty search results remain empty', () async {
    final result =
        await gateway({'nodes': [], 'unprocessed': []}).searchMemory('absent');
    expect(result.nodes, isEmpty);
    expect(result.unprocessed, isEmpty);
  });
  test('node reads expose directed connection endpoints', () async {
    final result = await gateway(graphBody, inspect: (request) {
      expect(request.method, 'GET');
      expect(Uri.decodeComponent(request.url.path), '/graph/entity:garden');
    }).getGraph('entity:garden');
    expect(result.node.id, 'entity:garden');
    expect(result.connections.single.edge.from, 'entity:garden');
    expect(result.connections.single.edge.to, 'note:layout');
    expect(result.connections.single.node.id, 'note:layout');
  });
  test('batch refresh returns found details and missing results in order',
      () async {
    final result = await gateway(refreshBody, inspect: (request) {
      expect(request.method, 'POST');
      expect(request.url.path, '/graph/refresh');
      expect(
          jsonDecode(request.body)['ids'], ['entity:garden', 'entity:deleted']);
    }).refreshGraph(['entity:garden', 'entity:deleted']);
    expect(
        result.results.map((r) => r.id), ['entity:garden', 'entity:deleted']);
    expect(
        (result.results.first as GraphRefreshFound).connections.single.node.id,
        'note:layout');
    expect(result.results.last, isA<GraphRefreshMissing>());
  });
  for (final operation in ['search', 'graph', 'refresh']) {
    Future<Object> call(HttpBrainGateway g) => switch (operation) {
          'search' => g.searchMemory('garden'),
          'graph' => g.getGraph('entity:garden'),
          _ => g.refreshGraph(['entity:garden']),
        };
    test(
        '$operation propagates unavailable HTTP status without fabricating data',
        () async {
      await expectLater(
          call(gateway({'detail': 'offline'}, status: 503)),
          throwsA(isA<HttpStatusException>()
              .having((e) => e.statusCode, 'status', 503)));
    });
    test('$operation reports malformed successful response', () async {
      await expectLater(call(gateway({'unexpected': true})),
          throwsA(isA<MalformedResponseException>()));
    });
    test('$operation reports transport failure', () async {
      final g = HttpBrainGateway(
          baseUrl: 'https://brain.test',
          client:
              MockClient((_) async => throw http.ClientException('offline')));
      await expectLater(call(g), throwsA(isA<NetworkException>()));
    });
  }
}
