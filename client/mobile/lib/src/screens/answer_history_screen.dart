import 'dart:async';

import 'package:flutter/material.dart';

import '../gateway/models.dart';
import '../mobile_workflow.dart';
import '../persistence/models.dart';
import '../persistence/repositories.dart';
import 'recall_result_screen.dart';

/// Local Answer snapshot history for one Brain profile.
///
/// This screen reads only [AnswerSnapshotRepository]. Opening an entry passes
/// the complete snapshot to the result route, so reopening works offline and
/// never replaces displayed evidence with live graph data.
final class AnswerHistoryScreen extends StatefulWidget {
  const AnswerHistoryScreen({
    super.key,
    this.answers,
    this.repository,
    this.snapshotRepository,
    this.brainId,
    this.brainProfileId,
    this.workflow,
    this.onOpenSnapshot,
    this.onOpenAnswer,
    this.onSnapshotSelected,
    this.onOpenGraphNode,
    this.onDeleted,
  });

  /// Preferred repository parameter.
  final AnswerSnapshotRepository? answers;

  /// Compatibility alias for callers that name repositories explicitly.
  final AnswerSnapshotRepository? repository;
  final AnswerSnapshotRepository? snapshotRepository;
  final String? brainId;
  final String? brainProfileId;
  final MobileWorkflow? workflow;
  final ValueChanged<AnswerSnapshot>? onOpenSnapshot;
  final ValueChanged<AnswerSnapshot>? onOpenAnswer;
  final ValueChanged<AnswerSnapshot>? onSnapshotSelected;
  final ValueChanged<GraphNode>? onOpenGraphNode;
  final VoidCallback? onDeleted;

  @override
  State<AnswerHistoryScreen> createState() => _AnswerHistoryScreenState();
}

final class _AnswerHistoryScreenState extends State<AnswerHistoryScreen> {
  final TextEditingController _queryController = TextEditingController();
  List<AnswerSnapshot> _snapshots = const [];
  Object? _failure;
  String? _notice;
  bool _loading = true;
  int _loadGeneration = 0;

  AnswerSnapshotRepository get _repository =>
      widget.answers ??
      widget.repository ??
      widget.snapshotRepository ??
      (throw StateError('An Answer snapshot repository is required'));

  String get _brainId => widget.brainId ?? widget.brainProfileId ?? '';

  @override
  void initState() {
    super.initState();
    _queryController.addListener(_queryChanged);
    unawaited(_load());
  }

  @override
  void dispose() {
    _queryController
      ..removeListener(_queryChanged)
      ..dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          onPressed: () => Navigator.of(context).maybePop(),
          tooltip: 'Back',
          icon: const Icon(Icons.arrow_back),
        ),
        title: const Text('Answer history'),
      ),
      body: _buildBody(context),
    );
  }

  Widget _buildBody(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
        children: [
          Text(
            'Saved answers on this phone',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _queryController,
            decoration: InputDecoration(
              labelText: 'Search history',
              hintText: 'Find an answer',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _queryController.text.isEmpty
                  ? null
                  : IconButton(
                      onPressed: _queryController.clear,
                      tooltip: 'Clear search',
                      icon: const Icon(Icons.clear),
                    ),
              border: const OutlineInputBorder(),
            ),
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => unawaited(_load()),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: () => unawaited(_load()),
            icon: const Icon(Icons.search),
            label: const Text('Search history'),
          ),
          if (_notice != null) ...[
            const SizedBox(height: 12),
            _Notice(message: _notice!),
          ],
          const SizedBox(height: 12),
          if (_loading) const LinearProgressIndicator(),
          if (_failure != null) _FailureBody(onRetry: () => unawaited(_load())),
          if (!_loading && _snapshots.isEmpty)
            _EmptyHistory(hasQuery: _queryController.text.trim().isNotEmpty)
          else
            ..._snapshots.map((snapshot) => _SnapshotCard(
                  snapshot: snapshot,
                  onOpen: () => _open(snapshot),
                  onDelete: () => _delete(snapshot),
                )),
        ],
      ),
    );
  }

  void _queryChanged() {
    if (!mounted) return;
    setState(() {});
    unawaited(_load());
  }

  Future<void> _load() async {
    final generation = ++_loadGeneration;
    if (mounted) {
      setState(() {
        _loading = true;
        _failure = null;
      });
    }
    try {
      final snapshots = await _repository.find(
        _brainId,
        _queryController.text.trim(),
      );
      if (!mounted || generation != _loadGeneration) return;
      setState(() {
        _snapshots = snapshots;
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted || generation != _loadGeneration) return;
      setState(() {
        _failure = error;
        _loading = false;
      });
    }
  }

  void _open(AnswerSnapshot snapshot) {
    final callback = widget.onOpenSnapshot ??
        widget.onOpenAnswer ??
        widget.onSnapshotSelected;
    if (callback != null) {
      callback(snapshot);
      return;
    }
    Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => RecallResultScreen(
          question: snapshot.question,
          snapshot: snapshot,
          onOpenGraphNode: widget.onOpenGraphNode,
        ),
      ),
    );
  }

  Future<void> _delete(AnswerSnapshot snapshot) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete saved answer?'),
        content: Text('Delete “${snapshot.question}” from this phone?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _repository.delete(snapshot.id);
      if (!mounted) return;
      setState(() => _notice = 'Answer deleted.');
      widget.onDeleted?.call();
      await _load();
    } on Object {
      if (!mounted) return;
      setState(() => _notice = 'Could not delete this answer.');
    }
  }
}

final class _SnapshotCard extends StatelessWidget {
  const _SnapshotCard({
    required this.snapshot,
    required this.onOpen,
    required this.onDelete,
  });

  final AnswerSnapshot snapshot;
  final VoidCallback onOpen;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final answer = snapshot.answer.replaceAll(RegExp(r'\s+'), ' ').trim();
    final preview =
        answer.length > 120 ? '${answer.substring(0, 117)}…' : answer;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 5),
      child: InkWell(
        onTap: onOpen,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 10, 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(
                      snapshot.question,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  IconButton(
                    onPressed: onDelete,
                    tooltip: 'Delete answer',
                    icon: const Icon(Icons.delete_outline),
                  ),
                ],
              ),
              if (preview.isNotEmpty) ...[
                const SizedBox(height: 3),
                Text(
                  preview,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
              const SizedBox(height: 8),
              Text(
                _formatDate(snapshot.answeredAt),
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: onOpen,
                  icon: const Icon(Icons.arrow_forward, size: 17),
                  label: const Text('Open answer'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatDate(DateTime value) {
    final local = value.toLocal();
    return '${local.year}-${local.month.toString().padLeft(2, '0')}-'
        '${local.day.toString().padLeft(2, '0')}';
  }
}

final class _EmptyHistory extends StatelessWidget {
  const _EmptyHistory({required this.hasQuery});

  final bool hasQuery;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Icon(
              Icons.history,
              size: 42,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 10),
            Text(hasQuery ? 'No matching answers.' : 'No saved answers yet.'),
            const SizedBox(height: 5),
            Text(
              hasQuery
                  ? 'Try another search.'
                  : 'Successful answers will appear here.',
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

final class _FailureBody extends StatelessWidget {
  const _FailureBody({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.storage_outlined, size: 48),
            const SizedBox(height: 12),
            const Text('Could not load saved answers.',
                textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

final class _Notice extends StatelessWidget {
  const _Notice({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(message),
    );
  }
}
