import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../gateway/models.dart';
import '../mobile_workflow.dart';
import '../persistence/models.dart';
import '../widgets/evidence_cards.dart';

/// Isolated one-shot recall result route.
///
/// The legacy route receives [gateway] and asks the server directly. The
/// durable route receives [workflow], which saves a successful answer as a
/// self-contained local snapshot before this screen renders it. A supplied
/// [snapshot] is always read locally and never refetches an answer.
final class RecallResultScreen extends StatefulWidget {
  const RecallResultScreen({
    super.key,
    this.gateway,
    this.question,
    this.workflow,
    this.snapshot,
    this.answerSnapshot,
    this.sourceBrainId,
    this.onOpenHistory,
    this.onOpenGraphNode,
    this.onOpenGraph,
  });

  final BrainGateway? gateway;
  final String? question;
  final MobileWorkflow? workflow;
  final AnswerSnapshot? snapshot;
  final AnswerSnapshot? answerSnapshot;
  final String? sourceBrainId;
  final VoidCallback? onOpenHistory;
  final ValueChanged<GraphNode>? onOpenGraphNode;
  final ValueChanged<GraphNode>? onOpenGraph;

  @override
  State<RecallResultScreen> createState() => _RecallResultScreenState();
}

enum _RecallPhase { loading, failed, complete }

final class _RecallResultScreenState extends State<RecallResultScreen> {
  _RecallPhase _phase = _RecallPhase.loading;
  RecallResult? _result;
  AnswerSnapshot? _snapshot;
  Object? _failure;
  int _requestGeneration = 0;

  @override
  void initState() {
    super.initState();
    final snapshot = widget.snapshot ?? widget.answerSnapshot;
    if (snapshot != null) {
      _snapshot = snapshot;
      _result = RecallResult(
        answer: snapshot.answer,
        evidence: snapshot.evidence,
      );
      _phase = _RecallPhase.complete;
    } else {
      unawaited(_requestRecall());
    }
  }

  @override
  void dispose() {
    _requestGeneration++;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      resizeToAvoidBottomInset: true,
      appBar: AppBar(
        leading: IconButton(
          onPressed: () => Navigator.of(context).maybePop(),
          tooltip: 'Back',
          icon: const Icon(Icons.arrow_back),
        ),
        title: const Text('Answer'),
        actions: [
          if (widget.onOpenHistory != null)
            IconButton(
              onPressed: widget.onOpenHistory,
              tooltip: 'Answer history',
              icon: const Icon(Icons.history),
            ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
          child: _buildBody(context),
        ),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    return switch (_phase) {
      _RecallPhase.loading => const _LoadingState(),
      _RecallPhase.failed => _FailureState(
          error: _messageFor(_failure),
          onRetry: _requestRecall,
        ),
      _RecallPhase.complete => _CompleteState(
          question: _question,
          result: _result!,
          snapshot: _snapshot,
          onOpenGraphNode: widget.onOpenGraphNode ?? widget.onOpenGraph,
        ),
    };
  }

  Future<void> _requestRecall() async {
    final generation = ++_requestGeneration;
    if (!mounted) return;
    setState(() {
      _phase = _RecallPhase.loading;
      _result = null;
      _snapshot = null;
      _failure = null;
    });
    try {
      final workflow = widget.workflow;
      final question = _question;
      if (question.trim().isEmpty) {
        throw StateError('An answer question is required');
      }
      final result = workflow == null
          ? await _recallThroughGateway(question)
          : await workflow.ask(question);
      if (!mounted || generation != _requestGeneration) return;
      if (result is AnswerSnapshot) {
        setState(() {
          _phase = _RecallPhase.complete;
          _snapshot = result;
          _result = RecallResult(
            answer: result.answer,
            evidence: result.evidence,
          );
        });
      } else if (result is RecallResult) {
        setState(() {
          _phase = _RecallPhase.complete;
          _result = result;
        });
      } else {
        throw StateError('Unsupported answer result');
      }
    } on Object catch (error) {
      if (!mounted || generation != _requestGeneration) return;
      setState(() {
        _phase = _RecallPhase.failed;
        _failure = error;
      });
    }
  }

  String get _question =>
      widget.question ??
      widget.snapshot?.question ??
      widget.answerSnapshot?.question ??
      '';

  Future<Object> _recallThroughGateway(String question) async {
    final gateway = widget.gateway;
    if (gateway == null) {
      throw StateError('A gateway or workflow is required');
    }
    return gateway.recall(question);
  }

  String _messageFor(Object? error) {
    if (error is BrainClientException) return error.message;
    return 'The request failed. Try again.';
  }
}

final class _LoadingState extends StatelessWidget {
  const _LoadingState();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.only(top: 24),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 16),
            Text('Searching your memory…'),
          ],
        ),
      ),
    );
  }
}

final class _FailureState extends StatelessWidget {
  const _FailureState({required this.error, required this.onRetry});

  final String error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 40),
      child: Column(
        children: [
          Icon(
            Icons.cloud_off_outlined,
            size: 52,
            color: Theme.of(context).colorScheme.error,
          ),
          const SizedBox(height: 14),
          Text('Could not reach your memory',
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          Text(error, textAlign: TextAlign.center),
          const SizedBox(height: 20),
          ElevatedButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

final class _CompleteState extends StatelessWidget {
  const _CompleteState({
    required this.question,
    required this.result,
    required this.snapshot,
    this.onOpenGraphNode,
  });

  final String question;
  final RecallResult result;
  final AnswerSnapshot? snapshot;
  final ValueChanged<GraphNode>? onOpenGraphNode;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          question,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 12),
        MarkdownBody(
          data: result.answer,
          selectable: true,
          styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
            p: Theme.of(context).textTheme.bodyLarge?.copyWith(height: 1.55),
          ),
        ),
        if (snapshot != null) ...[
          const SizedBox(height: 8),
          Text(
            'Answer saved on this phone · ${_formatDate(snapshot!.answeredAt)}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
        if (result.evidence.isNotEmpty)
          EvidenceCards(
            evidence: result.evidence,
            onOpenGraphNode: onOpenGraphNode,
          ),
      ],
    );
  }

  String _formatDate(DateTime value) {
    final local = value.toLocal();
    final month = local.month.toString().padLeft(2, '0');
    final day = local.day.toString().padLeft(2, '0');
    return '${local.year}-$month-$day';
  }
}
