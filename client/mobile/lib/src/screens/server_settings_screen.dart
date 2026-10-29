import 'dart:async';

import 'package:flutter/material.dart';

import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../persistence/models.dart';
import '../persistence/repositories.dart';
import '../persistence/settings_store.dart';
import '../widgets/app_logo.dart';

/// A callback emitted after a legacy server configuration is saved and health
/// is checked.
typedef ServerConfigurationSaved = void Function(
  ServerConfiguration configuration,
  BrainGateway gateway,
  Object? healthFailure,
);

/// A callback emitted after a durable Brain profile is saved and health is
/// checked. A health failure does not roll back the saved profile.
typedef BrainProfileSaved = void Function(
  BrainProfile profile,
  Object? healthFailure,
);

/// First-launch setup, Brain profile creation, and editable server settings.
///
/// The [settingsStore] path keeps the pre-profile application contract alive.
/// The [profileRepository] path is used by the durable mobile application.
final class ServerSettingsScreen extends StatefulWidget {
  const ServerSettingsScreen({
    super.key,
    this.initialConfiguration,
    this.initialProfile,
    this.initialUrl = '',
    this.initialName = '',
    this.settingsStore,
    this.profileRepository,
    this.gatewayForProfile,
    this.gatewayForConfiguration,
    this.gatewayForBaseUrl,
    this.onSaved,
    this.onProfileSaved,
    this.isSetup = false,
  });

  final ServerConfiguration? initialConfiguration;
  final BrainProfile? initialProfile;
  final String initialUrl;
  final String initialName;
  final SettingsStore? settingsStore;
  final BrainProfileRepository? profileRepository;
  final BrainGateway Function(BrainProfile)? gatewayForProfile;
  final BrainGateway Function(ServerConfiguration)? gatewayForConfiguration;
  final BrainGateway Function(String)? gatewayForBaseUrl;
  final ServerConfigurationSaved? onSaved;
  final BrainProfileSaved? onProfileSaved;
  final bool isSetup;

  BrainGateway Function(ServerConfiguration)
      get resolvedGatewayForConfiguration {
    final factory = gatewayForConfiguration;
    if (factory != null) return factory;
    final legacyFactory = gatewayForBaseUrl;
    if (legacyFactory != null) {
      return (configuration) {
        if (configuration.hasAccessCredentials) {
          throw StateError(
            'The URL-only gateway factory cannot use Access credentials',
          );
        }
        return legacyFactory(configuration.baseUrl);
      };
    }
    throw StateError('A gateway factory is required');
  }

  @override
  State<ServerSettingsScreen> createState() => _ServerSettingsScreenState();
}

final class _ServerSettingsScreenState extends State<ServerSettingsScreen> {
  late final TextEditingController _nameController;
  late final TextEditingController _urlController;
  late final TextEditingController _accessClientIdController;
  late final TextEditingController _accessClientSecretController;
  String? _validationError;
  String? _accessValidationError;
  String? _saveError;
  Object? _healthFailure;
  bool _saving = false;
  bool _healthOk = false;

  bool get _profileMode => widget.profileRepository != null;

  bool get _addingProfile => _profileMode && widget.initialProfile == null;

  @override
  void initState() {
    super.initState();
    final profile = widget.initialProfile;
    final configuration = widget.initialConfiguration;
    _nameController = TextEditingController(
      text: widget.initialName.isNotEmpty
          ? widget.initialName
          : profile?.name ?? '',
    );
    _urlController = TextEditingController(
      text: widget.initialUrl.isNotEmpty
          ? widget.initialUrl
          : profile?.baseUrl ?? configuration?.baseUrl ?? '',
    );
    _accessClientIdController = TextEditingController(
      text: profile?.accessClientId ?? configuration?.accessClientId ?? '',
    );
    _accessClientSecretController = TextEditingController(
      text: profile?.accessClientSecret ??
          configuration?.accessClientSecret ??
          '',
    );
  }

  @override
  void dispose() {
    _nameController.dispose();
    _urlController.dispose();
    _accessClientIdController.dispose();
    _accessClientSecretController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final content = SafeArea(
      child: Column(
        children: [
          if (!widget.isSetup)
            AppBar(
              automaticallyImplyLeading: true,
              title: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  AppLogo(size: 40),
                  SizedBox(width: 8),
                  Text('Settings'),
                ],
              ),
            ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 24),
              child: _buildForm(context),
            ),
          ),
          _buildAction(),
        ],
      ),
    );

    return Scaffold(
      resizeToAvoidBottomInset: true,
      body: content,
    );
  }

  Widget _buildForm(BuildContext context) {
    final title = _profileMode
        ? (_addingProfile ? 'Add brain' : 'Update address')
        : (widget.isSetup
            ? 'Connect to your Second Brain'
            : 'Server connection');
    final description = _profileMode
        ? (_addingProfile
            ? 'Save a Brain profile now. It can connect later.'
            : 'Change the server address for this Brain. Local captures stay with it.')
        : (widget.isSetup
            ? 'Enter your server address once. You can change it later in Settings.'
            : 'Change the server address used for Capture and Ask.');

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (widget.isSetup) ...[
          const AppLogo(size: 144),
          const SizedBox(height: 20),
        ],
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 8),
        Text(description),
        const SizedBox(height: 24),
        if (_addingProfile) ...[
          TextField(
            controller: _nameController,
            enabled: !_saving,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(
              labelText: 'Brain name',
              hintText: 'Personal',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 14),
        ],
        if (!_addingProfile && _profileMode) ...[
          Text(
            'Brain: ${widget.initialProfile!.name}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 14),
        ],
        TextField(
          controller: _urlController,
          enabled: !_saving,
          keyboardType: TextInputType.url,
          textInputAction: TextInputAction.done,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: _profileMode ? 'Server address' : 'Server URL',
            hintText: 'http://192.168.1.20:8000',
            errorText: _validationError,
            border: const OutlineInputBorder(),
          ),
          onSubmitted: (_) {
            if (!_saving) unawaited(_saveConfiguration());
          },
          onChanged: _handleUrlChanged,
        ),
        const SizedBox(height: 18),
        Text(
          'Cloudflare Access service-token credentials are optional. Enter both values or leave both blank.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _accessClientIdController,
          enabled: !_saving,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: 'Access Client ID (optional)',
            hintText: 'Client ID from Cloudflare Zero Trust',
            border: OutlineInputBorder(),
          ),
          onChanged: (_) {
            if (_accessValidationError != null || _saveError != null) {
              setState(() {
                _accessValidationError = null;
                _saveError = null;
              });
            }
          },
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _accessClientSecretController,
          enabled: !_saving,
          autocorrect: false,
          enableSuggestions: false,
          obscureText: true,
          decoration: InputDecoration(
            labelText: 'Access Client Secret (optional)',
            hintText: 'Client secret from Cloudflare Zero Trust',
            border: const OutlineInputBorder(),
            errorText: _accessValidationError,
          ),
          onChanged: (_) {
            if (_accessValidationError != null || _saveError != null) {
              setState(() {
                _accessValidationError = null;
                _saveError = null;
              });
            }
          },
        ),
        const SizedBox(height: 10),
        Text(
          'The app checks /health after it saves.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (_healthOk) ...[
          const SizedBox(height: 18),
          _Notice(
            icon: Icons.check_circle_outline,
            color: Colors.green.shade700,
            message: 'Server is healthy. Your connection is ready.',
          ),
        ],
        if (_healthFailure != null) ...[
          const SizedBox(height: 18),
          _Notice(
            icon: Icons.warning_amber_outlined,
            color: Colors.orange.shade800,
            message:
                'Configuration saved, but the server did not respond. You can continue and try again later.',
          ),
        ],
        if (_saveError != null) ...[
          const SizedBox(height: 18),
          _Notice(
            icon: Icons.error_outline,
            color: Theme.of(context).colorScheme.error,
            message: _saveError!,
          ),
        ],
      ],
    );
  }

  Widget _buildAction() {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
        child: SizedBox(
          width: double.infinity,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ElevatedButton(
                onPressed: _saving ? null : _saveConfiguration,
                child: Text(_saving ? 'Checking…' : 'Save'),
              ),
              if (_profileMode)
                TextButton(
                  onPressed: _saving
                      ? null
                      : () {
                          if (Navigator.of(context).canPop()) {
                            Navigator.of(context).pop();
                          }
                        },
                  child: const Text('Cancel'),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _saveConfiguration() async {
    final normalized = normalizeServerUrl(_urlController.text);
    if (normalized == null) {
      setState(() {
        _validationError =
            'Enter a full URL that starts with http:// or https://.';
        _accessValidationError = null;
        _saveError = null;
        _healthFailure = null;
        _healthOk = false;
      });
      return;
    }

    final accessClientId = _trimmedOrNull(_accessClientIdController.text);
    final accessClientSecret =
        _trimmedOrNull(_accessClientSecretController.text);
    if ((accessClientId == null) != (accessClientSecret == null)) {
      setState(() {
        _validationError = null;
        _accessValidationError =
            'Enter both Access Client ID and Access Client Secret, or leave both blank.';
        _saveError = null;
        _healthFailure = null;
        _healthOk = false;
      });
      return;
    }
    if (accessClientId != null && Uri.parse(normalized).scheme != 'https') {
      setState(() {
        _validationError = null;
        _accessValidationError =
            'Cloudflare Access credentials require an HTTPS server URL.';
        _saveError = null;
        _healthFailure = null;
        _healthOk = false;
      });
      return;
    }
    if (_addingProfile && _nameController.text.trim().isEmpty) {
      setState(() {
        _saveError = 'Enter a name for this Brain.';
        _healthFailure = null;
        _healthOk = false;
      });
      return;
    }

    final configuration = ServerConfiguration(
      baseUrl: normalized,
      accessClientId: accessClientId,
      accessClientSecret: accessClientSecret,
    );

    FocusManager.instance.primaryFocus?.unfocus();
    setState(() {
      _saving = true;
      _validationError = null;
      _accessValidationError = null;
      _saveError = null;
      _healthFailure = null;
      _healthOk = false;
    });

    try {
      if (_profileMode) {
        await _saveProfile(configuration);
      } else {
        await _saveLegacyConfiguration(configuration);
      }
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveError = _errorMessage(error);
      });
    }
  }

  Future<void> _saveLegacyConfiguration(
    ServerConfiguration configuration,
  ) async {
    final settingsStore = widget.settingsStore;
    if (settingsStore == null) {
      throw StateError('A settings store is required');
    }
    late final BrainGateway gateway;
    gateway = widget.resolvedGatewayForConfiguration(configuration);
    await settingsStore.saveServerConfiguration(configuration);
    final healthFailure = await _checkHealth(gateway);
    widget.onSaved?.call(configuration, gateway, healthFailure);
    if (!mounted) return;
    setState(() {
      _saving = false;
      _healthFailure = healthFailure;
      _healthOk = healthFailure == null;
    });
  }

  Future<void> _saveProfile(ServerConfiguration configuration) async {
    final repository = widget.profileRepository!;
    final credentials = configuration.hasAccessCredentials
        ? (
            clientId: configuration.accessClientId!.trim(),
            clientSecret: configuration.accessClientSecret!.trim(),
          )
        : null;
    final initial = widget.initialProfile;
    if (initial == null) {
      final name = _nameController.text.trim();
      final existing = await repository.list();
      if (existing.any((profile) => profile.name == name)) {
        throw StateError('A Brain with that name already exists.');
      }
      await repository.add(
        BrainProfileDraft(
          name: name,
          baseUrl: configuration.baseUrl,
          accessClientId: credentials?.clientId,
          accessClientSecret: credentials?.clientSecret,
        ),
      );
    } else {
      await repository.updateAddress(
        initial.id,
        configuration.baseUrl,
        credentials: credentials,
      );
    }

    var profile = await _findProfile(repository, initial?.id, configuration);
    final gateway = widget.gatewayForProfile?.call(profile) ??
        widget.resolvedGatewayForConfiguration(configuration);
    final healthFailure = await _checkHealth(gateway);
    if (healthFailure == null) {
      await repository.markConnected(profile.id);
      profile = await _findProfile(repository, profile.id, configuration);
    }

    widget.onProfileSaved?.call(profile, healthFailure);
    if (!mounted) return;
    setState(() {
      _saving = false;
      _healthFailure = healthFailure;
      _healthOk = healthFailure == null;
    });
    // Add and update forms return to the profile list after the durable write.
    // The first-launch setup is the root route, so it stays visible while the
    // bootstrap switches to the newly saved profile.
    if (Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
    }
  }

  Future<BrainProfile> _findProfile(
    BrainProfileRepository repository,
    String? id,
    ServerConfiguration configuration,
  ) async {
    final profiles = await repository.list();
    if (id != null) {
      for (final profile in profiles) {
        if (profile.id == id) return profile;
      }
    }
    final name = _nameController.text.trim();
    for (final profile in profiles.reversed) {
      if (profile.name == name && profile.baseUrl == configuration.baseUrl) {
        return profile;
      }
    }
    throw StateError('Saved Brain profile could not be loaded.');
  }

  Future<Object?> _checkHealth(BrainGateway gateway) async {
    try {
      await gateway.checkHealth();
      return null;
    } on Object catch (error) {
      return error;
    }
  }

  void _handleUrlChanged(String value) {
    final previousConfiguration = widget.initialConfiguration;
    final previousProfile = widget.initialProfile;
    final previousUrl =
        previousProfile?.baseUrl ?? previousConfiguration?.baseUrl;
    final hadCredentials = previousProfile?.accessClientId != null &&
            previousProfile?.accessClientSecret != null ||
        previousConfiguration?.hasAccessCredentials == true;
    final normalized = normalizeServerUrl(value);
    if (hadCredentials &&
        previousUrl != null &&
        normalized != null &&
        normalized != previousUrl) {
      _accessClientIdController.clear();
      _accessClientSecretController.clear();
    }
    if (_validationError != null || _saveError != null) {
      setState(() {
        _validationError = null;
        _saveError = null;
      });
    }
  }
}

String? _trimmedOrNull(String value) {
  final trimmed = value.trim();
  return trimmed.isEmpty ? null : trimmed;
}

/// Normalizes a user-entered server URL and rejects non-web absolute URLs.
String? normalizeServerUrl(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty || trimmed.contains(RegExp(r'\s'))) return null;
  final uri = Uri.tryParse(trimmed);
  if (uri == null || !uri.isAbsolute) return null;
  if (uri.scheme != 'http' && uri.scheme != 'https') return null;
  if (uri.host.isEmpty || uri.hasQuery || uri.hasFragment) return null;
  return trimmed.replaceFirst(RegExp(r'/+$'), '');
}

String _errorMessage(Object error) {
  if (error is BrainClientException) return error.message;
  final message = error.toString();
  return message.startsWith('Bad state: ') ? message.substring(11) : message;
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
