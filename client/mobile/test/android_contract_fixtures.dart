import 'dart:async';

import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const garden = GraphNode(id: 'entity:garden', table: 'entity', name: 'Garden');
const layout =
    GraphNode(id: 'note:layout', table: 'note', content: 'Behind shed');
const edge = LinkedEdge(
    id: 'references:1',
    table: 'references',
    from: 'entity:garden',
    to: 'note:layout');
const evidence = GraphNodeEvidence(node: garden, links: [edge]);
const detail = GraphNodeDetail(
    node: garden, connections: [GraphConnection(edge: edge, node: layout)]);
const draft = BrainProfileDraft(
    name: 'Home',
    baseUrl: 'https://home.test',
    accessClientId: 'id',
    accessClientSecret: 'secret');

final DatabaseFactory _testDatabaseFactory = (() {
  sqfliteFfiInit();
  return databaseFactoryFfi;
})();

Future<MobileStore> openTestMobileStore(
  String path, {
  LegacyMobileData? legacy,
}) {
  return openMobileStore(
    path,
    legacy: legacy,
    databaseFactory: _testDatabaseFactory,
    secretStore: HostSecretStore(path),
  );
}

final class ControlledGateway implements BrainGraphGateway {
  Object? failure;
  Completer<GraphRefreshResult>? refreshGate;
  Completer<IngestReceipt>? intakeGate;
  GraphRefreshResult refreshResult = const GraphRefreshResult(results: []);
  GraphNodeDetail nodeDetail = detail;
  final delivered = <({String text, String key, String time})>[];
  final refreshRequests = <List<String>>[];
  @override
  Future<void> checkHealth() async {
    if (failure != null) throw failure!;
  }

  @override
  Future<IngestReceipt> stageIntake(String text,
      {required String idempotencyKey, required String capturedAt}) async {
    delivered.add((text: text, key: idempotencyKey, time: capturedAt));
    if (failure != null) throw failure!;
    if (intakeGate != null) return intakeGate!.future;
    return const IngestReceipt(chunksStored: 1);
  }

  @override
  Future<RecallResult> recall(String question) async {
    if (failure != null) throw failure!;
    return const RecallResult(answer: 'Behind shed', evidence: [evidence]);
  }

  @override
  Future<MemorySearchResult> searchMemory(String query, {int? limit}) async =>
      const MemorySearchResult(nodes: [garden], unprocessed: []);
  @override
  Future<GraphNodeDetail> getGraph(String recordId) async {
    if (failure != null) throw failure!;
    return nodeDetail;
  }

  @override
  Future<GraphRefreshResult> refreshGraph(List<String> recordIds) async {
    refreshRequests.add(List.of(recordIds));
    if (failure != null) throw failure!;
    if (refreshGate != null) return refreshGate!.future;
    return refreshResult;
  }
}

Future<String> addBrain(MobileStore store,
    {BrainProfileDraft profile = draft}) async {
  await store.profiles.add(profile);
  final id = (await store.profiles.list())
      .singleWhere((p) => p.name == profile.name)
      .id;
  await store.profiles.use(id);
  return id;
}
