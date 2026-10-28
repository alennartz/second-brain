import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

http.Response jsonResponse(Object? body, {int statusCode = 200}) {
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
  test('defaults recall and intake requests to a five-minute timeout', () {
    final gateway = gatewayFor((_) async => jsonResponse({'status': 'ok'}));

    expect(gateway.requestTimeout, const Duration(minutes: 5));
    expect(gateway.stageIntakeTimeout, const Duration(minutes: 5));
  });

  final operations = <String, Future<void> Function(BrainGateway)>{
    'health': (gateway) => gateway.checkHealth(),
    'intake': (gateway) async { await gateway.stageIntake('Thought', idempotencyKey: 'key', capturedAt: '2026-01-01T00:00:00+02:00'); },
    'recall': (gateway) async { await gateway.recall('Question'); },
  };
  for (final operation in operations.entries) {
    test('${operation.key} rejects non-success status', () async {
      final gateway = gatewayFor((_) async => http.Response('Unavailable', 503));
      await expectLater(operation.value(gateway), throwsA(isA<HttpStatusException>().having((error) => error.statusCode, 'status', 503)));
    });
    test('${operation.key} maps transport failure', () async {
      final gateway = gatewayFor((_) async { throw http.ClientException('Unavailable'); });
      await expectLater(operation.value(gateway), throwsA(isA<NetworkException>()));
    });
    test('${operation.key} rejects malformed JSON', () async {
      final gateway = gatewayFor((_) async => http.Response('{', 200));
      await expectLater(operation.value(gateway), throwsA(isA<MalformedResponseException>()));
    });
    testWidgets('${operation.key} applies its bounded timeout', (tester) async {
      final response = Completer<http.Response>();
      final gateway = HttpBrainGateway(
        baseUrl: 'https://brain.example.test',
        client: MockClient((_) => response.future),
        healthTimeout: const Duration(seconds: 1),
        requestTimeout: const Duration(seconds: 2),
      );
      final assertion = expectLater(operation.value(gateway), throwsA(isA<NetworkException>()));
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      if (operation.key != 'health') await tester.pump(const Duration(seconds: 1));
      await assertion;
      response.complete(jsonResponse({'status': 'ok'}));
      await tester.pump();
    });
  }

  for (final body in [null, [], {}, {'chunks_stored': 'two'}, {'chunks_stored': 1.5}]) {
    test('intake rejects invalid receipt $body', () async {
      final gateway = gatewayFor((_) async => jsonResponse(body));
      await expectLater(gateway.stageIntake('Thought', idempotencyKey: 'key', capturedAt: '2026-01-01T00:00:00+02:00'), throwsA(isA<MalformedResponseException>()));
    });
  }
  for (final body in [null, [], {}, {'answer': 42, 'context': null}, {'answer': 'Answer', 'context': 'invalid'}]) {
    test('recall rejects invalid response $body', () async {
      final gateway = gatewayFor((_) async => jsonResponse(body));
      await expectLater(gateway.recall('Question'), throwsA(isA<MalformedResponseException>()));
    });
  }

  test('recall maps empty context to no evidence', () async {
    final gateway = gatewayFor((_) async => jsonResponse({'answer': 'Answer', 'context': {'nodes': [], 'edges': [], 'unprocessed': []}}));
    expect((await gateway.recall('Question')).evidence, isEmpty);
  });

  test('both returned endpoints attach the directed edge once to its to node', () async {
    final gateway = gatewayFor((_) async => jsonResponse({
      'answer': 'Answer',
      'context': {
        'nodes': [
          {'id': 'note:1', 'table': 'note', 'content': 'Content', 'name': 'Name', 'type': 'Type', 'description': 'Description', 'summary': 'Summary'},
          {'id': 'entity:2', 'table': 'entity'},
        ],
        'edges': [{'id': 'references:1', 'table': 'references', 'from': 'note:1', 'to': 'entity:2', 'context': 'Link'}],
        'unprocessed': [],
      },
    }));
    final items = (await gateway.recall('Question')).evidence.whereType<GraphNodeEvidence>().toList();
    expect(items, hasLength(2));
    final from = items.singleWhere((item) => item.node.id == 'note:1');
    expect(from.links, isEmpty);
    expect(from.node.content, 'Content');
    expect(from.node.name, 'Name');
    expect(from.node.type, 'Type');
    expect(from.node.description, 'Description');
    expect(from.node.summary, 'Summary');
    final to = items.singleWhere((item) => item.node.id == 'entity:2');
    expect(to.links, hasLength(1));
    expect(to.links.single.from, 'note:1');
    expect(to.links.single.to, 'entity:2');
    expect(to.links.single.context, 'Link');
  });
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
      capturedAt: '2026-01-01T00:00:00+02:00',
    );

    expect(receipt.chunksStored, 2);
    expect(requests.single.method, 'POST');
    expect(requests.single.url.toString(), 'https://brain.example.test/ingest');
    expect(requests.single.headers['Idempotency-Key'], 'capture-key-1');
    expect(jsonDecode(requests.single.body), {
      'text': 'A thought from the phone',
      'hints': <String>[],
      'source': 'mobile',
      'captured_at': '2026-01-01T00:00:00+02:00',
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
      gateway.stageIntake('duplicate', idempotencyKey: 'capture-key-1', capturedAt: '2026-01-01T00:00:00+02:00'),
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
      (item) => item.links.any((link) => link.id == 'relates_to:3'),
    );
    expect(orphan.node.id, isIn(['note:missing', 'entity:orphan']));
    expect(orphan.links, hasLength(1));
    expect(orphan.links.single.id, 'relates_to:3');

    final raw = result.evidence.whereType<UnprocessedEvidence>().single;
    expect(raw.chunk.id, 'intake_chunk:1');
    expect(raw.chunk.intakeId, 'intake:1');
    expect(raw.chunk.chunkPosition, 0);
    expect(raw.chunk.totalChunks, 1);
    expect(raw.chunk.content, 'A recent raw thought.');
    expect(raw.chunk.source, 'mobile');
    expect(graph.node.table, 'entity');
    expect(graph.node.name, 'Garden plot');
    expect(graph.links.firstWhere((link) => link.id == 'references:1').from, 'note:layout');
    expect(graph.links.firstWhere((link) => link.id == 'references:1').table, 'references');
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
