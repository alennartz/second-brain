import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

HttpBrainGateway gateway() => HttpBrainGateway(
      baseUrl: 'https://brain.example.test',
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({'nodes': <Object>[], 'unprocessed': <Object>[]}),
          200,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );

void main() {
  test('searchMemory returns graph nodes and separate unprocessed chunks',
      () async {
    final result = await gateway().searchMemory('garden', limit: 20);

    expect(result.nodes, hasLength(1));
    expect(result.nodes.single.id, 'entity:garden');
    expect(result.unprocessed.single.id, 'intake_chunk:1');
  });

  test('getGraph returns one node and its directed connections', () async {
    final result = await gateway().getGraph('entity:garden');

    expect(result.node.id, 'entity:garden');
    expect(result.connections.single.edge.id, 'references:1');
    expect(result.connections.single.node.id, 'note:layout');
  });

  test(
      'refreshGraph returns found and confirmed-missing results in input order',
      () async {
    final result = await gateway().refreshGraph([
      'entity:garden',
      'entity:deleted',
    ]);

    expect(result.results, hasLength(2));
    expect(result.results.first, isA<GraphRefreshFound>());
    expect(result.results.last, isA<GraphRefreshMissing>());
  });
}
