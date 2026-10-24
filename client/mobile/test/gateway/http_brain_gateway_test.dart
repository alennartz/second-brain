import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

http.Response jsonResponse(Object body, {int statusCode = 200}) {
  return http.Response(
    jsonEncode(body),
    statusCode,
    headers: {'content-type': 'application/json'},
  );
}

HttpBrainGateway gatewayFor(
  Future<http.Response> Function(http.Request) handler,
) {
  return HttpBrainGateway(
    baseUrl: 'https://brain.example.test/',
    client: MockClient(handler),
  );
}

void main() {
  test('health checks GET /health and accepts a successful ok response', () async {
    final requests = <http.Request>[];
    final gateway = gatewayFor((request) async {
      requests.add(request);
      return jsonResponse({'status': 'ok'});
    });

    await gateway.checkHealth();

    expect(requests, hasLength(1));
    expect(requests.single.method, 'GET');
    expect(requests.single.url.toString(), 'https://brain.example.test/health');
  });

  test('health rejects a successful response without status ok', () async {
    final gateway = gatewayFor(
      (_) async => jsonResponse({'status': 'degraded'}),
    );

    await expectLater(
      gateway.checkHealth(),
      throwsA(isA<MalformedResponseException>()),
    );
  });

  test('staging sends the mobile payload and idempotency key', () async {
    final requests = <http.Request>[];
    final gateway = gatewayFor((request) async {
      requests.add(request);
      return jsonResponse({'chunks_stored': 2});
    });

    final receipt = await gateway.stageIntake(
      'A thought from the phone',
      idempotencyKey: 'capture-key-1',
    );

    expect(receipt.chunksStored, 2);
    expect(requests.single.method, 'POST');
    expect(requests.single.url.toString(), 'https://brain.example.test/ingest');
    expect(requests.single.headers['Idempotency-Key'], 'capture-key-1');
    expect(jsonDecode(requests.single.body), {
      'text': 'A thought from the phone',
      'hints': <String>[],
      'source': 'mobile',
    });
  });

  test('staging maps a non-success response to a typed HTTP exception', () async {
    final gateway = gatewayFor(
      (_) async => jsonResponse(
        {'detail': 'duplicate idempotency key'},
        statusCode: 409,
      ),
    );

    await expectLater(
      gateway.stageIntake('duplicate', idempotencyKey: 'capture-key-1'),
      throwsA(
        isA<HttpStatusException>().having(
          (error) => error.statusCode,
          'status code',
          409,
        ),
      ),
    );
  });

  test('recall sends the question and projects grouped graph and raw evidence',
      () async {
    final requests = <http.Request>[];
    final gateway = gatewayFor((request) async {
      requests.add(request);
      return jsonResponse({
        'answer': 'The garden decision is in the south beds.',
        'context': {
          'nodes': [
            {
              'id': 'entity:garden',
              'table': 'entity',
              'name': 'Garden plot',
            },
          ],
          'edges': [
            {
              'id': 'references:1',
              'table': 'references',
              'from': 'note:layout',
              'to': 'entity:garden',
              'context': 'The layout applies to this plot.',
            },
            {
              'id': 'relates_to:2',
              'table': 'relates_to',
              'from': 'entity:garden',
              'to': 'note:soil',
              'context': 'The plot has a soil test.',
            },
            {
              'id': 'relates_to:3',
              'table': 'relates_to',
              'from': 'note:missing',
              'to': 'entity:orphan',
              'context': 'No endpoint node was returned.',
            },
          ],
          'unprocessed': [
            {
              'id': 'intake_chunk:1',
              'intake_id': 'intake:1',
              'chunk_index': 0,
              'total_chunks': 1,
              'content': 'A recent raw thought.',
              'source': 'mobile',
              'hints': ['garden'],
              'unprocessed': true,
            },
          ],
        },
      });
    });

    final result = await gateway.recall('Where is the garden decision?');

    expect(requests.single.method, 'POST');
    expect(requests.single.url.toString(), 'https://brain.example.test/recall');
    expect(jsonDecode(requests.single.body), {
      'question': 'Where is the garden decision?',
      'hints': <String>[],
    });
    expect(result.answer, 'The garden decision is in the south beds.');
    expect(result.evidence, hasLength(3));

    final graph = result.evidence.whereType<GraphNodeEvidence>().firstWhere(
      (item) => item.node.id == 'entity:garden',
    );
    expect(graph.links, hasLength(2));
    expect(
      graph.links.map((link) => link.to),
      containsAll(<String>['entity:garden', 'note:soil']),
    );
    expect(
      graph.links.map((link) => link.context),
      containsAll(<String>[
        'The layout applies to this plot.',
        'The plot has a soil test.',
      ]),
    );

    final orphan = result.evidence.whereType<GraphNodeEvidence>().firstWhere(
      (item) => item.node.id == 'entity:orphan',
    );
    expect(orphan.links, hasLength(1));
    expect(orphan.links.single.id, 'relates_to:3');

    final raw = result.evidence.whereType<UnprocessedEvidence>().single;
    expect(raw.chunk.id, 'intake_chunk:1');
    expect(raw.chunk.intakeId, 'intake:1');
    expect(raw.chunk.chunkPosition, 0);
    expect(raw.chunk.hints, ['garden']);
    expect(raw.chunk.isUnprocessed, isTrue);
  });

  test('recall returns empty evidence when the response context is null', () async {
    final gateway = gatewayFor(
      (_) async => jsonResponse({
        'answer': 'There is no matching memory.',
        'context': null,
      }),
    );

    final result = await gateway.recall('Something unknown');

    expect(result.answer, 'There is no matching memory.');
    expect(result.evidence, isEmpty);
  });

  test('recall maps transport failures to a typed network exception', () async {
    final gateway = gatewayFor((_) async {
      throw http.ClientException('server unavailable');
    });

    await expectLater(
      gateway.recall('Will this request reach the server?'),
      throwsA(isA<NetworkException>()),
    );
  });

  test('recall rejects malformed JSON with a typed response exception', () async {
    final gateway = gatewayFor(
      (_) async => http.Response('{"answer":', 200),
    );

    await expectLater(
      gateway.recall('Question with a malformed response'),
      throwsA(isA<MalformedResponseException>()),
    );
  });
}
