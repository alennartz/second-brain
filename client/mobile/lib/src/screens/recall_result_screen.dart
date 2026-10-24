import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../gateway/models.dart';
import '../widgets/evidence_cards.dart';

enum _RecallPhase { loading, failed, complete }

/// Isolated one-shot recall result route.
final class RecallResultScreen extends StatefulWidget {
  const RecallResultScreen({
    super.key,
    required this.gateway,
    required this.question,
  });

  final BrainGateway gateway;
  final String question;

  @override
  State<RecallResultScreen> createState() => _RecallResultScreenState();
}

final class _RecallResultScreenState extends State<RecallResultScreen> {
  _RecallPhase _phase = _RecallPhase.loading;
  RecallResult? _result;
  Object? _failure;
  int _requestGeneration = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_requestRecall());
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
      _RecallPhase.complete => _CompleteState(result: _result!),
    };
  }

  Future<void> _requestRecall() async {
    final generation = ++_requestGeneration;
    setState(() {
      _phase = _RecallPhase.loading;
      _result = null;
      _failure = null;
    });
    try {
      final result = await widget.gateway.recall(widget.question);
      if (!mounted || generation != _requestGeneration) return;
      setState(() {
        _phase = _RecallPhase.complete;
        _result = result;
      });
    } on Object catch (error) {
      if (!mounted || generation != _requestGeneration) return;
      setState(() {
        _phase = _RecallPhase.failed;
        _failure = error;
      });
    }
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
            CircularProgressIndicator(value: 0.32),
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
  const _CompleteState({required this.result});

  final RecallResult result;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        MarkdownBody(
          data: result.answer,
          selectable: true,
          styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
            p: Theme.of(context).textTheme.bodyLarge?.copyWith(height: 1.55),
          ),
        ),
        if (result.evidence.isNotEmpty)
          EvidenceCards(evidence: result.evidence),
      ],
    );
  }
}
