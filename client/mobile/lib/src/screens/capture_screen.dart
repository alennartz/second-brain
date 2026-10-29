import 'dart:async';

import 'package:flutter/material.dart';

import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../persistence/settings_store.dart';
import '../mobile_workflow.dart';
import '../widgets/app_logo.dart';

/// Returns the local capture time with its numeric UTC offset.
String captureTimeNow() {
  final now = DateTime.now();
  final offset = now.timeZoneOffset;
  final sign = offset.isNegative ? '-' : '+';
  final minutes = offset.inMinutes.abs();
  final hoursText = (minutes ~/ 60).toString().padLeft(2, '0');
  final minutesText = (minutes % 60).toString().padLeft(2, '0');
  return '${now.toIso8601String()}$sign$hoursText:$minutesText';
}

/// The Capture composer and its durable retry state.
///
/// The legacy [settingsStore] path remains available for clients that have not
/// moved to the durable workflow. Production uses [workflow], which writes an
/// outbox record before it clears the composer and starts foreground delivery.
final class CaptureScreen extends StatefulWidget {
  const CaptureScreen({
    super.key,
    required this.gateway,
    this.settingsStore,
    required this.createIdempotencyKey,
    required this.onOpenSettings,
    this.initialDraft,
    this.createCaptureTime,
    this.healthNotice,
    this.onCaptureSucceeded,
    this.workflow,
    this.activeBrainName,
    this.outboxCount = 0,
    this.onOpenOutbox,
    this.onOpenBrains,
    this.onCaptureSaved,
  });

  final BrainGateway gateway;
  final SettingsStore? settingsStore;
  final String Function() createIdempotencyKey;
  final VoidCallback onOpenSettings;
  final PendingCapture? initialDraft;
  final String Function()? createCaptureTime;
  final String? healthNotice;
  final VoidCallback? onCaptureSucceeded;

  /// The local-first journey. When set, [settingsStore] is not used.
  final MobileWorkflow? workflow;
  final String? activeBrainName;
  final int outboxCount;
  final VoidCallback? onOpenOutbox;
  final VoidCallback? onOpenBrains;
  final VoidCallback? onCaptureSaved;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

enum _CapturePhase { idle, sending, failed }

final class _CaptureScreenState extends State<CaptureScreen> {
  late final TextEditingController _controller;
  String? _currentKey;
  String? _currentCaptureTime;
  String _lastObservedText = '';
  String _lastPersistedText = '';
  String? _failureMessage;
  String? _acknowledgement;
  _CapturePhase _phase = _CapturePhase.idle;
  bool _ignoreChanges = false;
  int _draftRevision = 0;
  Future<void> _storageTail = Future<void>.value();

  bool get _usesWorkflow => widget.workflow != null;

  @override
  void initState() {
    super.initState();
    final draft = widget.initialDraft;
    final initialText =
        _usesWorkflow ? widget.workflow!.composerText : draft?.text ?? '';
    _currentKey = draft?.idempotencyKey;
    _currentCaptureTime = draft?.capturedAt;
    _lastObservedText = initialText;
    _lastPersistedText = draft?.text ?? '';
    _controller = TextEditingController(text: initialText)
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
    final actionLabel = _phase == _CapturePhase.failed
        ? 'Retry'
        : (_usesWorkflow ? 'Save thought' : 'Capture');

    return Column(
      children: [
        AppBar(
          leading: const Padding(
            padding: EdgeInsets.all(8),
            child: AppLogo(size: 40),
          ),
          title: const Text('Capture'),
          actions: _headerActions(),
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
                      message: _usesWorkflow
                          ? 'Not saved. $_failureMessage Your text is still here.'
                          : 'Not captured. $_failureMessage Your draft is safe. Retry will not store it twice.',
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
                      hintText: "What's on your mind?",
                      border: OutlineInputBorder(),
                      alignLabelWithHint: true,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    _usesWorkflow
                        ? 'Saved on your phone first, then sent to ${widget.activeBrainName ?? 'your Brain'}. '
                            'You can continue offline.'
                        : 'Use your keyboard mic to dictate.',
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
                child: Text(isSending ? 'Saving…' : actionLabel),
              ),
            ),
          ),
        ),
      ],
    );
  }

  List<Widget> _headerActions() {
    if (_usesWorkflow) {
      return [
        IconButton(
          onPressed: widget.onOpenOutbox,
          tooltip: 'Outbox',
          icon: _OutboxIcon(count: widget.outboxCount),
        ),
        IconButton(
          onPressed: widget.onOpenBrains,
          tooltip: 'Brains',
          icon: const Icon(Icons.hub_outlined),
        ),
      ];
    }
    return [
      IconButton(
        onPressed: widget.onOpenSettings,
        tooltip: 'Settings',
        icon: const Icon(Icons.settings_outlined),
      ),
    ];
  }

  void _textChanged() {
    if (_ignoreChanges || !mounted) return;
    final text = _controller.text;
    if (text == _lastObservedText) return;
    _lastObservedText = text;

    if (_usesWorkflow) {
      widget.workflow!.compose(text);
      setState(() {
        if (_phase == _CapturePhase.failed) {
          _phase = _CapturePhase.idle;
          _failureMessage = null;
          _acknowledgement = null;
        }
      });
      return;
    }

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
    _currentCaptureTime = null;
    _lastPersistedText = text;
    unawaited(
      _queueDraft(PendingCapture(text: text, idempotencyKey: key))
          .catchError((_) {}),
    );
  }

  Future<void> _submitCapture() async {
    if (_phase == _CapturePhase.sending) return;
    if (_usesWorkflow) {
      await _saveWithWorkflow();
      return;
    }
    await _submitLegacyCapture();
  }

  Future<void> _saveWithWorkflow() async {
    final text = _controller.text;
    if (text.trim().isEmpty) return;
    setState(() {
      _phase = _CapturePhase.sending;
      _failureMessage = null;
      _acknowledgement = null;
    });
    try {
      widget.workflow!.compose(text);
      await widget.workflow!.capture();
      if (!mounted) return;
      _ignoreChanges = true;
      _controller.clear();
      _ignoreChanges = false;
      _lastObservedText = '';
      _lastPersistedText = '';
      setState(() {
        _phase = _CapturePhase.idle;
        _acknowledgement =
            'Saved on this phone. It will sync when the Brain is available.';
      });
      widget.onCaptureSaved?.call();
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _phase = _CapturePhase.failed;
        _failureMessage = _messageFor(error);
        _acknowledgement = null;
      });
    }
  }

  Future<void> _submitLegacyCapture() async {
    final text = _controller.text;
    if (text.trim().isEmpty) return;

    final key = _currentKey ?? widget.createIdempotencyKey();
    _currentKey = key;
    _currentCaptureTime ??=
        widget.createCaptureTime?.call() ?? captureTimeNow();
    _lastPersistedText = text;
    final draft = PendingCapture(
      text: text,
      idempotencyKey: key,
      capturedAt: _currentCaptureTime,
    );
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
        capturedAt: _currentCaptureTime!,
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
      _currentCaptureTime = null;
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
    final settingsStore = widget.settingsStore;
    if (settingsStore == null) return Future<void>.value();
    final revision = ++_draftRevision;
    final previous = _storageTail;
    final next = previous.then<void>((_) async {
      if (revision != _draftRevision) return;
      if (draft == null) {
        await settingsStore.clearPendingCapture();
      } else {
        await settingsStore.savePendingCapture(draft);
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

final class _OutboxIcon extends StatelessWidget {
  const _OutboxIcon({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        const Icon(Icons.inventory_2_outlined),
        if (count > 0)
          Positioned(
            right: -8,
            top: -8,
            child: Container(
              constraints: const BoxConstraints(minWidth: 18, minHeight: 18),
              padding: const EdgeInsets.symmetric(horizontal: 4),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.error,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                '$count',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 10,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
      ],
    );
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
