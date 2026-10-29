import 'dart:async';

import 'package:flutter/material.dart';

import '../persistence/models.dart';
import '../persistence/repositories.dart';
import '../sync/sync_engine.dart';

/// Combined pending-capture view for every saved Brain profile.
final class OutboxScreen extends StatefulWidget {
  const OutboxScreen({
    super.key,
    required this.outbox,
    required this.profiles,
    this.retryPending,
    this.onChanged,
  });

  final CaptureOutboxRepository outbox;
  final BrainProfileRepository profiles;
  final Future<SyncReport> Function()? retryPending;
  final VoidCallback? onChanged;

  @override
  State<OutboxScreen> createState() => _OutboxScreenState();
}

final class _OutboxScreenState extends State<OutboxScreen> {
  List<BrainProfile> _profiles = const [];
  List<OutboxEntry> _entries = const [];
  Object? _loadError;
  String? _notice;
  bool _loading = true;
  bool _retrying = false;

  @override
  void initState() {
    super.initState();
    unawaited(_reload());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Outbox')),
      body: _buildBody(context),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_loadError != null) {
      return _ErrorBody(
        message: 'Could not load saved captures.',
        onRetry: () => unawaited(_reload()),
      );
    }

    final grouped = _groupEntries();
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        children: [
          Text(
            'Captures waiting to reach your Brains.',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _retrying || _entries.isEmpty
                      ? null
                      : _retryPendingEntries,
                  icon: _retrying
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.refresh),
                  label: Text(_retrying ? 'Retrying…' : 'Retry pending'),
                ),
              ),
            ],
          ),
          if (_notice != null) ...[
            const SizedBox(height: 12),
            _Notice(message: _notice!),
          ],
          const SizedBox(height: 8),
          if (_entries.isEmpty)
            const _EmptyOutbox()
          else
            for (final group in grouped.entries) ...[
              Padding(
                padding: const EdgeInsets.only(top: 16, bottom: 4),
                child: Text(
                  group.key,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              for (final entry in group.value)
                _EntryCard(
                  entry: entry,
                  onEdit: () => unawaited(_edit(entry)),
                  onDiscard: entry.state == OutboxState.conflict
                      ? () => unawaited(_discard(entry))
                      : null,
                  onRequeue: entry.state == OutboxState.conflict
                      ? () => unawaited(_requeue(entry))
                      : null,
                ),
            ],
        ],
      ),
    );
  }

  Map<String, List<OutboxEntry>> _groupEntries() {
    final names = <String, String>{
      for (final profile in _profiles) profile.id: profile.name,
    };
    final grouped = <String, List<OutboxEntry>>{};
    for (final entry in _entries) {
      final name = names[entry.brainId] ?? 'Unknown Brain';
      grouped.putIfAbsent(name, () => <OutboxEntry>[]).add(entry);
    }
    return grouped;
  }

  Future<void> _reload() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _loadError = null;
      });
    }
    try {
      final profiles = await widget.profiles.list();
      final entries = await widget.outbox.pendingAll();
      if (!mounted) return;
      setState(() {
        _profiles = profiles;
        _entries = entries;
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loadError = error;
        _loading = false;
      });
    }
  }

  Future<void> _retryPendingEntries() async {
    final retry = widget.retryPending;
    if (retry == null) {
      setState(() => _notice = 'Sync is not available yet.');
      return;
    }
    setState(() {
      _retrying = true;
      _notice = null;
    });
    try {
      final report = await retry();
      if (!mounted) return;
      setState(() {
        _notice = _syncMessage(report);
        _retrying = false;
      });
      widget.onChanged?.call();
      await _reload();
    } on Object {
      if (!mounted) return;
      setState(() {
        _retrying = false;
        _notice = 'Retry failed. Saved captures remain on this phone.';
      });
    }
  }

  Future<void> _edit(OutboxEntry entry) async {
    final editedText = await showDialog<String>(
      context: context,
      builder: (context) => _EditCaptureDialog(entry: entry),
    );
    if (editedText == null || editedText == entry.text) return;
    final trimmed = editedText.trim();
    if (trimmed.isEmpty) {
      setState(() => _notice = 'Capture text cannot be empty.');
      return;
    }
    try {
      await widget.outbox.updateText(entry.id, editedText);
      widget.onChanged?.call();
      if (!mounted) return;
      setState(() => _notice = 'Edit saved on this phone.');
      await _reload();
    } on Object {
      if (!mounted) return;
      setState(() => _notice = 'Could not save the edit.');
    }
  }

  Future<void> _discard(OutboxEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Discard retained edit?'),
        content: const Text(
            'Delete this edit from this phone? The original capture remains accepted.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Discard'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.outbox.discardConflict(entry.id);
      widget.onChanged?.call();
      if (!mounted) return;
      setState(() => _notice = 'Retained edit discarded.');
      await _reload();
    } on Object {
      if (!mounted) return;
      setState(() => _notice = 'Could not discard the edit.');
    }
  }

  Future<void> _requeue(OutboxEntry entry) async {
    try {
      await widget.outbox.requeueAsNew(entry.id);
      widget.onChanged?.call();
      if (!mounted) return;
      setState(() => _notice = 'Edit queued as a new capture.');
      await _reload();
    } on Object {
      if (!mounted) return;
      setState(() => _notice = 'Could not queue the edit.');
    }
  }

  String _syncMessage(SyncReport report) {
    final parts = <String>[];
    if (report.accepted > 0) {
      parts.add('${report.accepted} accepted');
    }
    if (report.conflicts > 0) {
      parts.add('${report.conflicts} need review');
    }
    if (report.pending > 0) {
      parts.add('${report.pending} still pending');
    }
    return parts.isEmpty
        ? 'Outbox checked.'
        : 'Outbox checked: ${parts.join(', ')}.';
  }
}

final class _EntryCard extends StatelessWidget {
  const _EntryCard({
    required this.entry,
    required this.onEdit,
    this.onRequeue,
    this.onDiscard,
  });

  final OutboxEntry entry;
  final VoidCallback onEdit;
  final VoidCallback? onRequeue;
  final VoidCallback? onDiscard;

  @override
  Widget build(BuildContext context) {
    final conflict = entry.state == OutboxState.conflict;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 5),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(entry.text),
            const SizedBox(height: 8),
            Text(
              _stateLabel(entry.state),
              style: TextStyle(
                color: conflict
                    ? Theme.of(context).colorScheme.error
                    : Theme.of(context).colorScheme.onSurfaceVariant,
                fontSize: 13,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              'Captured ${entry.capturedAt}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                OutlinedButton(onPressed: onEdit, child: const Text('Edit')),
                if (onDiscard != null)
                  TextButton(
                      onPressed: onDiscard, child: const Text('Discard')),
                if (onRequeue != null)
                  ElevatedButton(
                    onPressed: onRequeue,
                    child: const Text('Capture edit as new'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _stateLabel(OutboxState state) => switch (state) {
        OutboxState.pending => 'Waiting to sync',
        OutboxState.edited => 'Edited · waiting to sync',
        OutboxState.conflict => 'Original accepted. Edited text needs review.',
      };
}

final class _EditCaptureDialog extends StatefulWidget {
  const _EditCaptureDialog({required this.entry});

  final OutboxEntry entry;

  @override
  State<_EditCaptureDialog> createState() => _EditCaptureDialogState();
}

final class _EditCaptureDialogState extends State<_EditCaptureDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.entry.text);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Edit capture'),
      content: TextField(
        controller: _controller,
        autofocus: true,
        minLines: 3,
        maxLines: 8,
        decoration: const InputDecoration(
          labelText: 'Capture text',
          border: OutlineInputBorder(),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: () => Navigator.of(context).pop(_controller.text),
          child: const Text('Save edit'),
        ),
      ],
    );
  }
}

final class _EmptyOutbox extends StatelessWidget {
  const _EmptyOutbox();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Icon(
              Icons.check_circle_outline,
              size: 42,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 10),
            const Text('No pending captures.'),
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

final class _ErrorBody extends StatelessWidget {
  const _ErrorBody({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}
