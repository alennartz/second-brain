import 'dart:async';

import 'package:flutter/material.dart';

import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../persistence/settings_store.dart';

/// The Capture composer and its durable retry state.
final class CaptureScreen extends StatefulWidget {
  const CaptureScreen({
    super.key,
    required this.gateway,
    required this.settingsStore,
    required this.createIdempotencyKey,
    required this.onOpenSettings,
    this.initialDraft,
    this.healthNotice,
    this.onCaptureSucceeded,
  });

  final BrainGateway gateway;
  final SettingsStore settingsStore;
  final String Function() createIdempotencyKey;
  final VoidCallback onOpenSettings;
  final PendingCapture? initialDraft;
  final String? healthNotice;
  final VoidCallback? onCaptureSucceeded;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

enum _CapturePhase { idle, sending, failed }

final class _CaptureScreenState extends State<CaptureScreen> {
  late final TextEditingController _controller;
  String? _currentKey;
  String _lastObservedText = '';
  String _lastPersistedText = '';
  String? _failureMessage;
  String? _acknowledgement;
  _CapturePhase _phase = _CapturePhase.idle;
  bool _ignoreChanges = false;
  int _draftRevision = 0;
  Future<void> _storageTail = Future<void>.value();

  @override
  void initState() {
    super.initState();
    final draft = widget.initialDraft;
    _currentKey = draft?.idempotencyKey;
    _lastObservedText = draft?.text ?? '';
    _lastPersistedText = draft?.text ?? '';
    _controller = TextEditingController(text: draft?.text ?? '')
      ..addListener(_textChanged);
  }

  @override
  void dispose() {
    _controller
      ..removeListener(_textChanged)
      ..dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isSending = _phase == _CapturePhase.sending;
    final hasText = _controller.text.trim().isNotEmpty;
    final actionLabel = _phase == _CapturePhase.failed ? 'Retry' : 'Capture';

    return Column(
      children: [
        AppBar(
          title: const Text('Capture'),
          actions: [
            IconButton(
              onPressed: widget.onOpenSettings,
              tooltip: 'Settings',
              icon: const Icon(Icons.settings_outlined),
            ),
          ],
        ),
        Expanded(
          child: SafeArea(
            top: false,
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (widget.healthNotice != null) ...[
                    _Notice(
                      icon: Icons.warning_amber_outlined,
                      color: Colors.orange.shade800,
                      message: widget.healthNotice!,
                    ),
                    const SizedBox(height: 14),
                  ],
                  if (_failureMessage != null) ...[
                    _Notice(
                      icon: Icons.error_outline,
                      color: Theme.of(context).colorScheme.error,
                      message:
                          'Not captured. $_failureMessage Your draft is safe. Retry will not store it twice.',
                    ),
                    const SizedBox(height: 14),
                  ],
                  if (_acknowledgement != null) ...[
                    _Notice(
                      icon: Icons.check_circle_outline,
                      color: Colors.green.shade700,
                      message: _acknowledgement!,
                    ),
                    const SizedBox(height: 14),
                  ],
                  TextField(
                    controller: _controller,
                    readOnly: isSending,
                    minLines: 3,
                    maxLines: 8,
                    keyboardType: TextInputType.multiline,
                    textInputAction: TextInputAction.newline,
                    decoration: const InputDecoration(
                      hintText: 'What\'s on your mind?',
                      border: OutlineInputBorder(),
                      alignLabelWithHint: true,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    'Use your keyboard mic to dictate.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            child: SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: isSending || !hasText ? null : _submitCapture,
                child: Text(isSending ? 'Capturing…' : actionLabel),
              ),
            ),
          ),
        ),
      ],
    );
  }

  void _textChanged() {
    if (_ignoreChanges || !mounted) return;
    final text = _controller.text;
    if (text == _lastObservedText) return;
    _lastObservedText = text;
    setState(() {
      if (_phase == _CapturePhase.failed) {
        _phase = _CapturePhase.idle;
        _failureMessage = null;
        _acknowledgement = null;
      }
    });

    final hasExistingDraft = _currentKey != null;
    if (!hasExistingDraft || text == _lastPersistedText) return;

    final key = widget.createIdempotencyKey();
    _currentKey = key;
    _lastPersistedText = text;
    unawaited(
      _queueDraft(PendingCapture(text: text, idempotencyKey: key))
          .catchError((_) {}),
    );
  }

  Future<void> _submitCapture() async {
    if (_phase == _CapturePhase.sending) return;
    final text = _controller.text;
    if (text.trim().isEmpty) return;

    final key = _currentKey ?? widget.createIdempotencyKey();
    _currentKey = key;
    _lastPersistedText = text;
    final draft = PendingCapture(text: text, idempotencyKey: key);
    setState(() {
      _phase = _CapturePhase.sending;
      _failureMessage = null;
      _acknowledgement = null;
    });

    try {
      await _queueDraft(draft);
      if (!mounted) return;
      final receipt = await widget.gateway.stageIntake(
        text,
        idempotencyKey: key,
      );
      await _queueDraft(null);
      if (!mounted) return;
      widget.onCaptureSucceeded?.call();
      _ignoreChanges = true;
      _controller.clear();
      _ignoreChanges = false;
      _lastObservedText = '';
      _lastPersistedText = '';
      _currentKey = null;
      setState(() {
        _phase = _CapturePhase.idle;
        _acknowledgement =
            'Captured. Stored as ${receipt.chunksStored} ${receipt.chunksStored == 1 ? 'chunk' : 'chunks'}.';
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _phase = _CapturePhase.failed;
        _failureMessage = _messageFor(error);
        _acknowledgement = null;
      });
    }
  }

  Future<void> _queueDraft(PendingCapture? draft) {
    final revision = ++_draftRevision;
    final previous = _storageTail;
    final next = previous.then<void>((_) async {
      if (revision != _draftRevision) return;
      if (draft == null) {
        await widget.settingsStore.clearPendingCapture();
      } else {
        await widget.settingsStore.savePendingCapture(draft);
      }
    });
    _storageTail = next.catchError((_) {});
    return next;
  }

  String _messageFor(Object error) {
    if (error is BrainClientException) return error.message;
    return 'The request failed.';
  }
}

final class _Notice extends StatelessWidget {
  const _Notice({
    required this.icon,
    required this.color,
    required this.message,
  });

  final IconData icon;
  final Color color;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withAlpha(24),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 10),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}
