import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

final class MemorySettings implements SettingsStore {
  String? url = 'https://brain.example.test';
  PendingCapture? pending;
  @override
  Future<String?> loadBaseUrl() async => url;
  @override
  Future<void> saveBaseUrl(String value) async { url = value; }
  @override
  Future<PendingCapture?> loadPendingCapture() async => pending;
  @override
  Future<void> savePendingCapture(PendingCapture value) async { pending = value; }
  @override
  Future<void> clearPendingCapture() async { pending = null; }
}

final class FakeBrain implements BrainGateway {
  bool failHealth = false;
  bool failCapture = false;
  final captures = <PendingCapture>[];
  final questions = <String>[];
  Completer<RecallResult>? recallResponse;
  MemorySettings? storage;
  @override
  Future<void> checkHealth() async {
    if (failHealth) throw const NetworkException('Unavailable');
  }
  @override
  Future<IngestReceipt> stageIntake(String text, {required String idempotencyKey}) async {
    captures.add(PendingCapture(text: text, idempotencyKey: idempotencyKey));
    if (storage != null) {
      expect(storage!.pending!.text, text);
      expect(storage!.pending!.idempotencyKey, idempotencyKey);
    }
    if (failCapture) throw const NetworkException('Unavailable');
    return const IngestReceipt(chunksStored: 2);
  }
  @override
  Future<RecallResult> recall(String question) {
    questions.add(question);
    return recallResponse!.future;
  }
}

const answer = RecallResult(answer: '**Remember** the garden.', evidence: [
  GraphNodeEvidence(
    node: GraphNode(id: 'entity:garden', table: 'entity', name: 'Garden'),
    links: [LinkedEdge(id: 'references:1', table: 'references', from: 'note:layout', to: 'entity:garden', context: 'Garden connection')],
  ),
  UnprocessedEvidence(chunk: IntakeChunk(id: 'intake_chunk:1', intakeId: 'intake:1', chunkPosition: 0, totalChunks: 1, content: 'Raw garden thought', source: 'mobile', hints: [], isUnprocessed: true)),
]);

Finder action(String label) => find.ancestor(
  of: find.text(label),
  matching: find.byWidgetPredicate((widget) => widget is ButtonStyleButton),
);

void main() {
  late MemorySettings storage;
  late FakeBrain brain;
  var key = 0;
  Future<void> launch(WidgetTester tester) async {
    await tester.pumpWidget(MobileApplication(
      settingsStore: storage,
      gatewayForBaseUrl: (_) => brain,
      createIdempotencyKey: () => 'key-${++key}',
    ));
    await tester.pumpAndSettle();
  }
  Future<void> submit(WidgetTester tester, String label) async {
    await tester.tap(action(label));
    await tester.pump();
  }
  Future<void> ask(WidgetTester tester) async {
    brain.recallResponse = Completer<RecallResult>();
    await tester.tap(find.text('Ask').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Where is the garden?');
    await submit(tester, 'Ask');
  }
  setUp(() {
    storage = MemorySettings();
    brain = FakeBrain()..storage = storage;
    key = 0;
  });

  testWidgets('setup validates URL and saves it despite failed health', (tester) async {
    storage.url = null;
    brain.failHealth = true;
    await launch(tester);
    await tester.enterText(find.byType(TextField).first, 'not-a-url');
    await submit(tester, 'Save');
    expect(storage.url, isNull);
    await tester.enterText(find.byType(TextField).first, 'https://brain.example.test');
    await submit(tester, 'Save');
    await tester.pumpAndSettle();
    expect(storage.url, 'https://brain.example.test');
    expect(action('Capture'), findsOneWidget);
  });

  testWidgets('opens Capture and persists a key before staging then clears on success', (tester) async {
    await launch(tester);
    expect(action('Capture'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, 'A thought');
    await submit(tester, 'Capture');
    await tester.pumpAndSettle();
    expect(brain.captures.single.text, 'A thought');
    expect(storage.pending, isNull);
    expect(find.textContaining('2'), findsWidgets);
  });

  testWidgets('failure retains draft and Retry uses the same key', (tester) async {
    brain.failCapture = true;
    await launch(tester);
    await tester.enterText(find.byType(TextField).first, 'Do not lose this');
    await submit(tester, 'Capture');
    await tester.pumpAndSettle();
    expect(find.text('Do not lose this'), findsOneWidget);
    final savedKey = storage.pending!.idempotencyKey;
    brain.failCapture = false;
    await submit(tester, 'Retry');
    await tester.pumpAndSettle();
    expect(brain.captures.map((item) => item.idempotencyKey), [savedKey, savedKey]);
    expect(storage.pending, isNull);
  });

  testWidgets('startup restores without submitting and editing rotates persisted key', (tester) async {
    storage.pending = const PendingCapture(text: 'Old thought', idempotencyKey: 'old-key');
    brain.failCapture = true;
    await launch(tester);
    expect(find.text('Old thought'), findsOneWidget);
    expect(brain.captures, isEmpty);
    await tester.enterText(find.byType(TextField).first, 'Edited thought');
    await tester.pumpAndSettle();
    expect(storage.pending!.text, 'Edited thought');
    expect(storage.pending!.idempotencyKey, isNot('old-key'));
    final editedKey = storage.pending!.idempotencyKey;
    await tester.tap(action('Capture').evaluate().isNotEmpty ? action('Capture') : action('Retry'));
    await tester.pumpAndSettle();
    expect(brain.captures.single.idempotencyKey, editedKey);
  });

  testWidgets('Settings hides tabs and saves an edited URL despite failed health', (tester) async {
    await launch(tester);
    await tester.tap(find.byTooltip('Settings'));
    await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsNothing);
    brain.failHealth = true;
    await tester.enterText(find.byType(TextField).first, 'http://other.example.test');
    await submit(tester, 'Save');
    await tester.pumpAndSettle();
    expect(storage.url, 'http://other.example.test');
  });

  testWidgets('Ask opens loading result then grouped expanded evidence with Markdown', (tester) async {
    await launch(tester);
    await ask(tester);
    expect(brain.questions, ['Where is the garden?']);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.byTooltip('Settings'), findsNothing);
    brain.recallResponse!.complete(answer);
    await tester.pumpAndSettle();
    expect(find.textContaining('Garden connection'), findsWidgets);
    expect(find.textContaining('Raw garden thought'), findsWidgets);
    expect(find.textContaining('**Remember**'), findsNothing);
    expect(find.byWidgetPredicate((widget) => widget is RichText && widget.text.toPlainText().contains('Remember')), findsWidgets);
    await tester.tap(find.text('Evidence'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Raw garden thought'), findsNothing);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Where is the garden?'), findsOneWidget);
    expect(find.byType(NavigationBar), findsOneWidget);
  });

  testWidgets('Ask error offers explicit retry and empty evidence has no control', (tester) async {
    await launch(tester);
    await ask(tester);
    brain.recallResponse!.completeError(const NetworkException('Unavailable'));
    await tester.pumpAndSettle();
    expect(action('Retry'), findsOneWidget);
    brain.recallResponse = Completer<RecallResult>();
    await submit(tester, 'Retry');
    expect(brain.questions, ['Where is the garden?', 'Where is the garden?']);
    brain.recallResponse!.complete(const RecallResult(answer: 'No memory found.', evidence: []));
    await tester.pumpAndSettle();
    expect(find.text('Evidence'), findsNothing);
    expect(find.textContaining('No memory found.'), findsWidgets);
  });

  testWidgets('both composers keep submission above the keyboard without overflow', (tester) async {
    tester.view.physicalSize = const Size(400, 700);
    tester.view.devicePixelRatio = 1;
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.reset);
    await launch(tester);
    for (final label in ['Capture', 'Ask']) {
      if (label == 'Ask') {
        await tester.tap(find.text('Ask').last);
        await tester.pumpAndSettle();
      }
      await tester.enterText(find.byType(TextField).first, List.filled(30, 'A long thought').join('\n'));
      await tester.pumpAndSettle();
      final button = action(label);
      expect(tester.getBottomRight(button).dy, lessThanOrEqualTo(400));
      expect(tester.takeException(), isNull);
    }
  });
}
