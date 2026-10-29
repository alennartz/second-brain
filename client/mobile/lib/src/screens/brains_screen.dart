import 'dart:async';

import 'package:flutter/material.dart';

import '../gateway/brain_gateway.dart';
import '../persistence/models.dart';
import '../persistence/repositories.dart';
import 'server_settings_screen.dart';

/// Named Brain profile management and active-profile switching.
final class BrainsScreen extends StatefulWidget {
  const BrainsScreen({
    super.key,
    required this.profiles,
    required this.gatewayForProfile,
    this.onActiveChanged,
  });

  final BrainProfileRepository profiles;
  final BrainGateway Function(BrainProfile) gatewayForProfile;
  final ValueChanged<BrainProfile>? onActiveChanged;

  @override
  State<BrainsScreen> createState() => _BrainsScreenState();
}

final class _BrainsScreenState extends State<BrainsScreen> {
  List<BrainProfile> _profiles = const [];
  String? _activeId;
  String? _notice;
  Object? _loadError;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    unawaited(_reload());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Brains')),
      body: _buildBody(context),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('Could not load Brain profiles.'),
              const SizedBox(height: 12),
              OutlinedButton(
                onPressed: () => unawaited(_reload()),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
      children: [
        const Text('Your connections'),
        if (_notice != null) ...[
          const SizedBox(height: 12),
          _Notice(message: _notice!),
        ],
        const SizedBox(height: 8),
        if (_profiles.isEmpty)
          const _EmptyBrains()
        else
          for (final profile in _profiles) _profileCard(context, profile),
        const SizedBox(height: 12),
        ElevatedButton.icon(
          onPressed: _addBrain,
          icon: const Icon(Icons.add),
          label: const Text('Add brain'),
        ),
      ],
    );
  }

  Widget _profileCard(BuildContext context, BrainProfile profile) {
    final active = profile.id == _activeId;
    final connected = profile.status == BrainProfileStatus.connected;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 5),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    active ? '${profile.name} · active' : profile.name,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                Icon(
                  active ? Icons.check_circle : Icons.circle_outlined,
                  size: 18,
                  color: active
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.outline,
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(profile.baseUrl),
            const SizedBox(height: 4),
            Text(
              connected ? 'Connected before' : 'Never connected',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                OutlinedButton(
                  onPressed: active ? null : () => _use(profile),
                  child: const Text('Use this brain'),
                ),
                OutlinedButton(
                  onPressed: () => _updateBrain(profile),
                  child: const Text('Update address'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _addBrain() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => ServerSettingsScreen(
          isSetup: true,
          profileRepository: widget.profiles,
          gatewayForProfile: widget.gatewayForProfile,
          onProfileSaved: (profile, healthFailure) {
            _setSaveNotice(healthFailure);
          },
        ),
      ),
    );
    if (mounted) await _reload();
  }

  Future<void> _updateBrain(BrainProfile profile) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => ServerSettingsScreen(
          initialProfile: profile,
          profileRepository: widget.profiles,
          gatewayForProfile: _gatewayForExistingProfile(profile),
          onProfileSaved: (saved, healthFailure) {
            _setSaveNotice(healthFailure);
          },
        ),
      ),
    );
    if (mounted) await _reload();
  }

  Future<void> _use(BrainProfile profile) async {
    try {
      await widget.profiles.use(profile.id);
      final active = await _findProfile(profile.id);
      if (!mounted) return;
      setState(() => _activeId = active.id);
      widget.onActiveChanged?.call(active);
      setState(() =>
          _notice = 'Brain changed. Local captures stay with their Brain.');
      if (Navigator.of(context).canPop()) {
        Navigator.of(context).pop();
      }
    } on Object {
      if (!mounted) return;
      setState(() => _notice = 'Could not switch Brain.');
    }
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
      final active = await widget.profiles.active();
      if (!mounted) return;
      setState(() {
        _profiles = profiles;
        _activeId = active?.id;
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

  Future<BrainProfile> _findProfile(String id) async {
    final profiles = await widget.profiles.list();
    for (final profile in profiles) {
      if (profile.id == id) return profile;
    }
    throw StateError('unknown Brain profile: $id');
  }

  BrainGateway Function(BrainProfile) _gatewayForExistingProfile(
    BrainProfile original,
  ) {
    return (saved) => widget.gatewayForProfile(
          BrainProfile(
            id: original.id,
            name: original.name,
            baseUrl: saved.baseUrl,
            accessClientId: saved.accessClientId,
            accessClientSecret: saved.accessClientSecret,
            status: saved.status,
          ),
        );
  }

  void _setSaveNotice(Object? healthFailure) {
    if (!mounted) return;
    setState(() {
      _notice = healthFailure == null
          ? 'Brain saved.'
          : 'Brain saved. The server did not respond. You can use it and retry later.';
    });
  }
}

final class _EmptyBrains extends StatelessWidget {
  const _EmptyBrains();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Icon(
              Icons.hub_outlined,
              size: 42,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 10),
            const Text('Add a Brain to start capturing.'),
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
