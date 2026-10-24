import 'dart:async';

import 'package:flutter/material.dart';

import '../gateway/brain_gateway.dart';
import '../gateway/errors.dart';
import '../persistence/settings_store.dart';

/// A callback emitted after a URL is saved and its health check completes.
typedef ServerConfigurationSaved = void Function(
  String baseUrl,
  BrainGateway gateway,
  Object? healthFailure,
);

/// First-launch setup and the editable server settings screen.
final class ServerSettingsScreen extends StatefulWidget {
  const ServerSettingsScreen({
    super.key,
    required this.initialUrl,
    required this.settingsStore,
    required this.gatewayForBaseUrl,
    required this.onSaved,
    this.isSetup = false,
  });

  final String initialUrl;
  final SettingsStore settingsStore;
  final BrainGateway Function(String baseUrl) gatewayForBaseUrl;
  final ServerConfigurationSaved onSaved;
  final bool isSetup;

  @override
  State<ServerSettingsScreen> createState() => _ServerSettingsScreenState();
}

final class _ServerSettingsScreenState extends State<ServerSettingsScreen> {
  late final TextEditingController _urlController;
  String? _validationError;
  String? _saveError;
  Object? _healthFailure;
  bool _saving = false;
  bool _healthOk = false;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.initialUrl);
  }

  @override
  void dispose() {
    _urlController.dispose();
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
              title: const Text('Settings'),
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
    final title = widget.isSetup
        ? 'Connect to your Second Brain'
        : 'Server connection';
    final description = widget.isSetup
        ? 'Enter your server address once. You can change it later in Settings.'
        : 'Change the server address used for Capture and Ask.';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (widget.isSetup) ...[
          const Icon(Icons.hub_outlined, size: 56),
          const SizedBox(height: 20),
        ],
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 8),
        Text(description),
        const SizedBox(height: 24),
        TextField(
          controller: _urlController,
          enabled: !_saving,
          keyboardType: TextInputType.url,
          textInputAction: TextInputAction.done,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: 'Server URL',
            hintText: 'http://192.168.1.20:8000',
            errorText: _validationError,
            border: const OutlineInputBorder(),
          ),
          onSubmitted: (_) {
            if (!_saving) unawaited(_saveConfiguration());
          },
          onChanged: (_) {
            if (_validationError != null || _saveError != null) {
              setState(() {
                _validationError = null;
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
                'URL saved, but the server did not respond. You can continue and try again later.',
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
          child: ElevatedButton(
            onPressed: _saving ? null : _saveConfiguration,
            child: Text(_saving ? 'Checking…' : 'Save'),
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
        _saveError = null;
        _healthFailure = null;
        _healthOk = false;
      });
      return;
    }

    FocusManager.instance.primaryFocus?.unfocus();
    setState(() {
      _saving = true;
      _validationError = null;
      _saveError = null;
      _healthFailure = null;
      _healthOk = false;
    });

    late final BrainGateway gateway;
    try {
      gateway = widget.gatewayForBaseUrl(normalized);
      await widget.settingsStore.saveBaseUrl(normalized);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveError = _errorMessage(error);
      });
      return;
    }

    Object? healthFailure;
    try {
      await gateway.checkHealth();
    } on Object catch (error) {
      healthFailure = error;
    }

    widget.onSaved(normalized, gateway, healthFailure);
    if (!mounted) return;
    setState(() {
      _saving = false;
      _healthFailure = healthFailure;
      _healthOk = healthFailure == null;
    });
  }
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
  return 'Could not save the server URL: $error';
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
