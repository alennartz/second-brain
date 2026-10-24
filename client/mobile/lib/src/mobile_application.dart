import 'dart:async';

import 'package:flutter/material.dart';

import 'gateway/brain_gateway.dart';
import 'gateway/errors.dart';
import 'persistence/settings_store.dart';
import 'screens/ask_screen.dart';
import 'screens/capture_screen.dart';
import 'screens/recall_result_screen.dart';
import 'screens/server_settings_screen.dart';

/// Public application boundary with injected transport, storage, and keys.
final class MobileApplication extends StatelessWidget {
  const MobileApplication({
    super.key,
    required this.settingsStore,
    required this.gatewayForBaseUrl,
    required this.createIdempotencyKey,
  });

  final SettingsStore settingsStore;
  final BrainGateway Function(String baseUrl) gatewayForBaseUrl;
  final String Function() createIdempotencyKey;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: _mobileTheme,
      home: _ApplicationBootstrap(
        settingsStore: settingsStore,
        gatewayForBaseUrl: gatewayForBaseUrl,
        createIdempotencyKey: createIdempotencyKey,
      ),
    );
  }
}

final ThemeData _mobileTheme = ThemeData(
  useMaterial3: true,
  colorScheme: ColorScheme.fromSeed(
    seedColor: const Color(0xFF8A5A2B),
    brightness: Brightness.light,
  ).copyWith(
    surface: const Color(0xFFFFFDF9),
    primary: const Color(0xFF8A5A2B),
    onPrimary: Colors.white,
  ),
  scaffoldBackgroundColor: const Color(0xFFFFFDF9),
  inputDecorationTheme: const InputDecorationTheme(
    filled: true,
    fillColor: Color(0xFFFFFDFA),
  ),
  elevatedButtonTheme: ElevatedButtonThemeData(
    style: ElevatedButton.styleFrom(
      minimumSize: const Size.fromHeight(52),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
  ),
  navigationBarTheme: const NavigationBarThemeData(
    height: 76,
  ),
);

final class _ApplicationBootstrap extends StatefulWidget {
  const _ApplicationBootstrap({
    required this.settingsStore,
    required this.gatewayForBaseUrl,
    required this.createIdempotencyKey,
  });

  final SettingsStore settingsStore;
  final BrainGateway Function(String baseUrl) gatewayForBaseUrl;
  final String Function() createIdempotencyKey;

  @override
  State<_ApplicationBootstrap> createState() => _ApplicationBootstrapState();
}

final class _ApplicationBootstrapState extends State<_ApplicationBootstrap> {
  String? _baseUrl;
  PendingCapture? _pendingCapture;
  BrainGateway? _gateway;
  String? _healthNotice;
  Object? _startupError;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    unawaited(_loadConfiguration());
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator(value: 0.32)),
      );
    }
    if (_startupError != null) {
      return _StartupError(error: _startupError!);
    }
    final baseUrl = _baseUrl;
    final gateway = _gateway;
    if (baseUrl == null || gateway == null) {
      return ServerSettingsScreen(
        isSetup: true,
        initialUrl: '',
        settingsStore: widget.settingsStore,
        gatewayForBaseUrl: widget.gatewayForBaseUrl,
        onSaved: _finishSetup,
      );
    }
    return _ConfiguredApplication(
      baseUrl: baseUrl,
      gateway: gateway,
      settingsStore: widget.settingsStore,
      createIdempotencyKey: widget.createIdempotencyKey,
      initialDraft: _pendingCapture,
      healthNotice: _healthNotice,
      gatewayForBaseUrl: widget.gatewayForBaseUrl,
    );
  }

  Future<void> _loadConfiguration() async {
    try {
      final baseUrl = await widget.settingsStore.loadBaseUrl();
      final pendingCapture = await widget.settingsStore.loadPendingCapture();
      if (!mounted) return;
      setState(() {
        _baseUrl = baseUrl;
        _pendingCapture = pendingCapture;
        _gateway = baseUrl == null
            ? null
            : widget.gatewayForBaseUrl(baseUrl);
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _startupError = error;
        _loading = false;
      });
    }
  }

  void _finishSetup(
    String baseUrl,
    BrainGateway gateway,
    Object? healthFailure,
  ) {
    if (!mounted) return;
    setState(() {
      _baseUrl = baseUrl;
      _gateway = gateway;
      _healthNotice = healthFailure == null
          ? null
          : 'URL saved. The server did not respond to /health. You can continue and try again later.';
    });
  }
}

final class _ConfiguredApplication extends StatefulWidget {
  const _ConfiguredApplication({
    required this.baseUrl,
    required this.gateway,
    required this.settingsStore,
    required this.createIdempotencyKey,
    required this.initialDraft,
    required this.healthNotice,
    required this.gatewayForBaseUrl,
  });

  final String baseUrl;
  final BrainGateway gateway;
  final SettingsStore settingsStore;
  final String Function() createIdempotencyKey;
  final PendingCapture? initialDraft;
  final String? healthNotice;
  final BrainGateway Function(String baseUrl) gatewayForBaseUrl;

  @override
  State<_ConfiguredApplication> createState() => _ConfiguredApplicationState();
}

final class _ConfiguredApplicationState extends State<_ConfiguredApplication> {
  late String _baseUrl;
  late BrainGateway _gateway;
  String? _healthNotice;
  int _selectedTab = 0;
  bool _routeOpen = false;

  @override
  void initState() {
    super.initState();
    _baseUrl = widget.baseUrl;
    _gateway = widget.gateway;
    _healthNotice = widget.healthNotice;
  }

  @override
  Widget build(BuildContext context) {
    final shell = IndexedStack(
      index: _selectedTab,
      children: [
        CaptureScreen(
          gateway: _gateway,
          settingsStore: widget.settingsStore,
          createIdempotencyKey: widget.createIdempotencyKey,
          initialDraft: widget.initialDraft,
          healthNotice: _healthNotice,
          onOpenSettings: _openSettings,
        ),
        AskScreen(
          gateway: _gateway,
          onOpenSettings: _openSettings,
          onAsk: _openResult,
        ),
      ],
    );
    return Scaffold(
      resizeToAvoidBottomInset: true,
      body: Offstage(offstage: _routeOpen, child: shell),
      bottomNavigationBar: _routeOpen
          ? null
          : NavigationBar(
              selectedIndex: _selectedTab,
              onDestinationSelected: (index) {
                setState(() => _selectedTab = index);
              },
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.edit_note_outlined),
                  selectedIcon: Icon(Icons.edit_note),
                  label: 'Capture',
                ),
                NavigationDestination(
                  icon: Icon(Icons.search_outlined),
                  selectedIcon: Icon(Icons.search),
                  label: 'Ask',
                ),
              ],
            ),
    );
  }

  Future<void> _openSettings() async {
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() => _routeOpen = true);
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => ServerSettingsScreen(
          initialUrl: _baseUrl,
          settingsStore: widget.settingsStore,
          gatewayForBaseUrl: widget.gatewayForBaseUrl,
          onSaved: _updateServer,
        ),
      ),
    );
    if (mounted) setState(() => _routeOpen = false);
  }

  void _updateServer(
    String baseUrl,
    BrainGateway gateway,
    Object? healthFailure,
  ) {
    if (!mounted) return;
    setState(() {
      _baseUrl = baseUrl;
      _gateway = gateway;
      _healthNotice = healthFailure == null
          ? null
          : 'URL saved. The server did not respond to /health. You can try again later.';
    });
  }

  void _openResult(String question) {
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() => _routeOpen = true);
    unawaited(
      Navigator.of(context)
          .push<void>(
            MaterialPageRoute<void>(
              builder: (_) => RecallResultScreen(
                gateway: _gateway,
                question: question,
              ),
            ),
          )
          .then((_) {
            if (mounted) setState(() => _routeOpen = false);
          }),
    );
  }
}

final class _StartupError extends StatelessWidget {
  const _StartupError({required this.error});

  final Object error;

  @override
  Widget build(BuildContext context) {
    final message = error is BrainClientException
        ? error.message
        : 'Could not load mobile settings.';
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(message, textAlign: TextAlign.center),
        ),
      ),
    );
  }
}
