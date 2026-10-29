import 'dart:async';

import 'package:flutter/material.dart';

import 'gateway/brain_gateway.dart';
import 'gateway/errors.dart';
import 'gateway/models.dart';
import 'explore/explore_controller.dart';
import 'persistence/models.dart';
import 'persistence/settings_store.dart';
import 'screens/answer_history_screen.dart';
import 'screens/ask_screen.dart';
import 'screens/brains_screen.dart';
import 'screens/capture_screen.dart';
import 'screens/explore_screen.dart';
import 'screens/graph_node_detail_screen.dart';
import 'screens/outbox_screen.dart';
import 'screens/recall_result_screen.dart';
import 'screens/server_settings_screen.dart';
import 'sync/sync_engine.dart';
import 'widgets/app_logo.dart';
import 'workflow_contract.dart';

/// Public application boundary with injected transport, storage, and keys.
///
/// The [settingsStore] constructor path remains source-compatible with the
/// original two-screen client. Production passes [store] and a profile gateway
/// factory, which gives every app launch one durable [MobileWorkflow].
final class MobileApplication extends StatelessWidget {
  const MobileApplication({
    super.key,
    this.settingsStore,
    this.store,
    this.workflow,
    this.gatewayForProfile,
    this.gatewayFor,
    this.gatewayForConfiguration,
    this.gatewayForBaseUrl,
    required this.createIdempotencyKey,
  });

  final SettingsStore? settingsStore;
  final MobileStore? store;
  final MobileWorkflow? workflow;
  final GatewayForProfile? gatewayForProfile;
  final GatewayForProfile? gatewayFor;
  final BrainGateway Function(ServerConfiguration)? gatewayForConfiguration;
  final BrainGateway Function(String)? gatewayForBaseUrl;
  final String Function() createIdempotencyKey;

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

  GatewayForProfile get resolvedGatewayForProfile {
    final factory = gatewayForProfile ?? gatewayFor;
    if (factory != null) return factory;
    final configurationFactory = gatewayForConfiguration;
    if (configurationFactory != null) {
      return (profile) => configurationFactory(
            ServerConfiguration(
              baseUrl: profile.baseUrl,
              accessClientId: profile.accessClientId,
              accessClientSecret: profile.accessClientSecret,
            ),
          );
    }
    final legacyFactory = gatewayForBaseUrl;
    if (legacyFactory != null) {
      return (profile) {
        if (profile.accessClientId?.trim().isNotEmpty == true &&
            profile.accessClientSecret?.trim().isNotEmpty == true) {
          throw StateError(
            'The URL-only gateway factory cannot use Access credentials',
          );
        }
        return legacyFactory(profile.baseUrl);
      };
    }
    throw StateError('A gateway factory is required');
  }

  @override
  Widget build(BuildContext context) {
    final mobileStore = store;
    if (mobileStore != null) {
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: _mobileTheme,
        home: _DurableApplicationBootstrap(
          store: mobileStore,
          workflow: workflow,
          gatewayForProfile: resolvedGatewayForProfile,
          createIdempotencyKey: createIdempotencyKey,
        ),
      );
    }

    final legacySettings = settingsStore;
    if (legacySettings == null) {
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: _mobileTheme,
        home: const _StartupError(
          error: 'A durable mobile store or settings store is required.',
        ),
      );
    }
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: _mobileTheme,
      home: _ApplicationBootstrap(
        settingsStore: legacySettings,
        gatewayForConfiguration: resolvedGatewayForConfiguration,
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
  navigationBarTheme: const NavigationBarThemeData(height: 76),
);

/// Bootstrap for the original SharedPreferences settings path.
final class _ApplicationBootstrap extends StatefulWidget {
  const _ApplicationBootstrap({
    required this.settingsStore,
    required this.gatewayForConfiguration,
    required this.createIdempotencyKey,
  });

  final SettingsStore settingsStore;
  final BrainGateway Function(ServerConfiguration) gatewayForConfiguration;
  final String Function() createIdempotencyKey;

  @override
  State<_ApplicationBootstrap> createState() => _ApplicationBootstrapState();
}

final class _ApplicationBootstrapState extends State<_ApplicationBootstrap> {
  ServerConfiguration? _configuration;
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
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AppLogo(size: 144),
              SizedBox(height: 20),
              CircularProgressIndicator(),
            ],
          ),
        ),
      );
    }
    if (_startupError != null) return _StartupError(error: _startupError!);
    final configuration = _configuration;
    final gateway = _gateway;
    if (configuration == null || gateway == null) {
      return ServerSettingsScreen(
        isSetup: true,
        initialConfiguration: null,
        settingsStore: widget.settingsStore,
        gatewayForConfiguration: widget.gatewayForConfiguration,
        onSaved: _finishSetup,
      );
    }
    return _ConfiguredApplication(
      configuration: configuration,
      gateway: gateway,
      settingsStore: widget.settingsStore,
      createIdempotencyKey: widget.createIdempotencyKey,
      initialDraft: _pendingCapture,
      healthNotice: _healthNotice,
      gatewayForConfiguration: widget.gatewayForConfiguration,
    );
  }

  Future<void> _loadConfiguration() async {
    try {
      final configuration =
          await widget.settingsStore.loadServerConfiguration();
      final pendingCapture = await widget.settingsStore.loadPendingCapture();
      if (!mounted) return;
      setState(() {
        _configuration = configuration;
        _pendingCapture = pendingCapture;
        _gateway = configuration == null
            ? null
            : widget.gatewayForConfiguration(configuration);
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
    ServerConfiguration configuration,
    BrainGateway gateway,
    Object? healthFailure,
  ) {
    if (!mounted) return;
    setState(() {
      _configuration = configuration;
      _gateway = gateway;
      _healthNotice = healthFailure == null
          ? null
          : 'Configuration saved. The server did not respond to /health. You can continue and try again later.';
    });
  }
}

/// Bootstrap and app shell for sqflite-backed profiles and outboxes.
final class _DurableApplicationBootstrap extends StatefulWidget {
  const _DurableApplicationBootstrap({
    required this.store,
    required this.workflow,
    required this.gatewayForProfile,
    required this.createIdempotencyKey,
  });

  final MobileStore store;
  final MobileWorkflow? workflow;
  final GatewayForProfile gatewayForProfile;
  final String Function() createIdempotencyKey;

  @override
  State<_DurableApplicationBootstrap> createState() =>
      _DurableApplicationBootstrapState();
}

final class _DurableApplicationBootstrapState
    extends State<_DurableApplicationBootstrap> {
  late final MobileWorkflow _workflow;
  List<BrainProfile> _profiles = const [];
  BrainProfile? _activeProfile;
  String? _healthNotice;
  Object? _startupError;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _workflow = widget.workflow ??
        createMobileWorkflow(
          store: widget.store,
          gatewayFor: widget.gatewayForProfile,
          now: () => DateTime.now().toUtc(),
          newKey: widget.createIdempotencyKey,
        );
    unawaited(_loadProfiles());
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AppLogo(size: 144),
              SizedBox(height: 20),
              CircularProgressIndicator(),
            ],
          ),
        ),
      );
    }
    if (_startupError != null) return _StartupError(error: _startupError!);
    final active = _activeProfile;
    if (active == null) {
      return ServerSettingsScreen(
        isSetup: true,
        profileRepository: widget.store.profiles,
        gatewayForProfile: widget.gatewayForProfile,
        onProfileSaved: (profile, healthFailure) {
          unawaited(_finishProfileSetup(profile, healthFailure));
        },
      );
    }
    return _DurableConfiguredApplication(
      store: widget.store,
      workflow: _workflow,
      activeProfile: active,
      gatewayForProfile: widget.gatewayForProfile,
      createIdempotencyKey: widget.createIdempotencyKey,
      healthNotice: _healthNotice,
    );
  }

  Future<void> _loadProfiles() async {
    try {
      final profiles = await widget.store.profiles.list();
      var active = await widget.store.profiles.active();
      if (active == null && profiles.length == 1) {
        await widget.store.profiles.use(profiles.single.id);
        active = await widget.store.profiles.active();
      }
      if (active != null) {
        unawaited(
          _workflow.appOpened().then<void>(
                (_) {},
                onError: (Object _, StackTrace __) {},
              ),
        );
      }
      if (!mounted) return;
      setState(() {
        _profiles = profiles;
        _activeProfile = active;
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

  Future<void> _finishProfileSetup(
    BrainProfile profile,
    Object? healthFailure,
  ) async {
    try {
      await widget.store.profiles.use(profile.id);
      final active = await _findProfile(profile.id);
      if (!mounted) return;
      setState(() {
        _profiles = [
          ..._profiles.where((item) => item.id != active.id),
          active,
        ];
        _activeProfile = active;
        _healthNotice = healthFailure == null
            ? null
            : 'Brain saved. The server did not respond. You can continue offline and retry later.';
      });
      unawaited(
        _workflow.appOpened().then<void>(
              (_) {},
              onError: (Object _, StackTrace __) {},
            ),
      );
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _startupError = error);
    }
  }

  Future<BrainProfile> _findProfile(String id) async {
    final profiles = await widget.store.profiles.list();
    for (final profile in profiles) {
      if (profile.id == id) return profile;
    }
    throw StateError('unknown Brain profile: $id');
  }
}

final class _DurableConfiguredApplication extends StatefulWidget {
  const _DurableConfiguredApplication({
    required this.store,
    required this.workflow,
    required this.activeProfile,
    required this.gatewayForProfile,
    required this.createIdempotencyKey,
    required this.healthNotice,
  });

  final MobileStore store;
  final MobileWorkflow workflow;
  final BrainProfile activeProfile;
  final GatewayForProfile gatewayForProfile;
  final String Function() createIdempotencyKey;
  final String? healthNotice;

  @override
  State<_DurableConfiguredApplication> createState() =>
      _DurableConfiguredApplicationState();
}

final class _DurableConfiguredApplicationState
    extends State<_DurableConfiguredApplication> with WidgetsBindingObserver {
  late BrainProfile _activeProfile;
  late BrainGateway _gateway;
  String? _healthNotice;
  int _selectedTab = 0;
  int _outboxCount = 0;
  int _answerCount = 0;
  bool _routeOpen = false;

  @override
  void initState() {
    super.initState();
    _activeProfile = widget.activeProfile;
    _gateway = widget.gatewayForProfile(_activeProfile);
    _healthNotice = widget.healthNotice;
    WidgetsBinding.instance.addObserver(this);
    unawaited(_refreshOutbox());
    unawaited(_refreshAnswerCount());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) return;
    unawaited(_resumeWorkflow());
  }

  @override
  Widget build(BuildContext context) {
    final brainId = _activeProfile.id;
    final brainName = _activeProfile.name;
    final gateway = _gateway;
    final shell = IndexedStack(
      index: _selectedTab,
      children: [
        CaptureScreen(
          gateway: gateway,
          createIdempotencyKey: widget.createIdempotencyKey,
          onOpenSettings: _openBrains,
          workflow: widget.workflow,
          activeBrainName: brainName,
          outboxCount: _outboxCount,
          onOpenOutbox: _openOutbox,
          onOpenBrains: _openBrains,
          healthNotice: _healthNotice,
          onCaptureSaved: () => unawaited(_refreshOutbox()),
        ),
        AskScreen(
          gateway: gateway,
          onOpenSettings: _openBrains,
          onAsk: _openResult,
          onOpenHistory: _openHistory,
          historyCount: _answerCount,
        ),
        _selectedTab == 2
            ? ExploreScreen(
                brainId: brainId,
                brainName: brainName,
                gateway: gateway,
                // The loader runs on the first Explore visit, not while the
                // Capture and Ask tabs are building.
                loadController: () => widget.workflow.visitExplore(brainId),
                onOpenHistory: _openHistory,
              )
            : const SizedBox.shrink(),
      ],
    );
    return Scaffold(
      resizeToAvoidBottomInset: true,
      body: shell,
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
                NavigationDestination(
                  icon: Icon(Icons.account_tree_outlined),
                  selectedIcon: Icon(Icons.account_tree),
                  label: 'Explore',
                ),
              ],
            ),
    );
  }

  Future<void> _openOutbox() async {
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() => _routeOpen = true);
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => OutboxScreen(
          outbox: widget.store.outbox,
          profiles: widget.store.profiles,
          retryPending: _resumeWorkflow,
          onChanged: () => unawaited(_refreshOutbox()),
        ),
      ),
    );
    if (!mounted) return;
    setState(() => _routeOpen = false);
    await _refreshOutbox();
  }

  Future<void> _openBrains() async {
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() => _routeOpen = true);
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => BrainsScreen(
          profiles: widget.store.profiles,
          gatewayForProfile: widget.gatewayForProfile,
          onActiveChanged: _switchActive,
        ),
      ),
    );
    if (!mounted) return;
    setState(() => _routeOpen = false);
    await _reloadActive();
  }

  void _switchActive(BrainProfile profile) {
    if (!mounted) return;
    setState(() {
      _activeProfile = profile;
      _gateway = widget.gatewayForProfile(profile);
      _healthNotice = null;
    });
    unawaited(_refreshAnswerCount());
  }

  Future<void> _reloadActive() async {
    final active = await widget.store.profiles.active();
    if (active == null || !mounted) return;
    setState(() {
      _activeProfile = active;
      _gateway = widget.gatewayForProfile(active);
    });
    await _refreshOutbox();
    await _refreshAnswerCount();
  }

  Future<SyncReport> _resumeWorkflow() async {
    final report = await widget.workflow.appResumed();
    await _refreshOutbox();
    return report;
  }

  Future<void> _refreshAnswerCount() async {
    try {
      final active = await widget.store.answers.find(_activeProfile.id, '');
      if (!mounted) return;
      setState(() => _answerCount = active.length);
    } on Object {
      // History remains available even when its badge cannot be loaded.
    }
  }

  Future<void> _refreshOutbox() async {
    try {
      final entries = await widget.store.outbox.pendingAll();
      if (!mounted) return;
      setState(() => _outboxCount = entries.length);
    } on Object {
      // The outbox icon must not prevent Capture when storage is unavailable.
    }
  }

  Future<void> _openHistory() async {
    FocusManager.instance.primaryFocus?.unfocus();
    final brainId = _activeProfile.id;
    setState(() => _routeOpen = true);
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => AnswerHistoryScreen(
          answers: widget.store.answers,
          brainId: brainId,
          onOpenSnapshot: (snapshot) =>
              _openSnapshotForBrain(brainId, snapshot),
          onOpenGraphNode: (node) =>
              unawaited(_openGraphNode(brainId, node.id)),
        ),
      ),
    );
    if (!mounted) return;
    setState(() => _routeOpen = false);
    unawaited(_refreshAnswerCount());
  }

  void _openSnapshotForBrain(String brainId, AnswerSnapshot snapshot) {
    unawaited(
      Navigator.of(context).push<void>(
        MaterialPageRoute<void>(
          builder: (_) => RecallResultScreen(
            question: snapshot.question,
            snapshot: snapshot,
            sourceBrainId: brainId,
            onOpenHistory: _openHistory,
            onOpenGraphNode: (node) =>
                unawaited(_openGraphNode(brainId, node.id)),
          ),
        ),
      ),
    );
  }

  Future<void> _openGraphNode(String brainId, String nodeId) async {
    try {
      final profiles = await widget.store.profiles.list();
      if (!profiles.any((candidate) => candidate.id == brainId)) {
        throw StateError('Unknown Brain profile: $brainId');
      }
      GraphNodeDetail? detail;
      ExploreWorkspaceController? cachedController;
      try {
        detail = await widget.workflow.openGraphLink(brainId, nodeId);
      } on Object {
        // A previously opened workspace can still render a graph link while
        // the server is offline. The snapshot itself remains local either way.
        cachedController = await widget.workflow.visitExplore(brainId);
        if (!cachedController.state.nodes
            .any((node) => node.node.id == nodeId)) {
          rethrow;
        }
      }
      if (!mounted) return;
      await Navigator.of(context).push<void>(
        MaterialPageRoute<void>(
          builder: (_) => detail == null
              ? GraphNodeDetailScreen(
                  controller: cachedController,
                  nodeId: nodeId,
                )
              : GraphNodeDetailScreen(
                  node: detail.node,
                  connections: detail.connections,
                ),
        ),
      );
    } on Object catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open graph memory: $error')),
      );
    }
  }

  void _openResult(String question) {
    FocusManager.instance.primaryFocus?.unfocus();
    final brainId = _activeProfile.id;
    final gateway = _gateway;
    setState(() => _routeOpen = true);
    unawaited(
      Navigator.of(context)
          .push<void>(
        MaterialPageRoute<void>(
          builder: (_) => RecallResultScreen(
            gateway: gateway,
            workflow: widget.workflow,
            question: question,
            sourceBrainId: brainId,
            onOpenHistory: _openHistory,
            onOpenGraphNode: (node) =>
                unawaited(_openGraphNode(brainId, node.id)),
          ),
        ),
      )
          .then((_) {
        if (!mounted) return;
        setState(() => _routeOpen = false);
        unawaited(_refreshAnswerCount());
      }),
    );
  }
}

/// Original two-screen configured application.
final class _ConfiguredApplication extends StatefulWidget {
  const _ConfiguredApplication({
    required this.configuration,
    required this.gateway,
    required this.settingsStore,
    required this.createIdempotencyKey,
    required this.initialDraft,
    required this.healthNotice,
    required this.gatewayForConfiguration,
  });

  final ServerConfiguration configuration;
  final BrainGateway gateway;
  final SettingsStore settingsStore;
  final String Function() createIdempotencyKey;
  final PendingCapture? initialDraft;
  final String? healthNotice;
  final BrainGateway Function(ServerConfiguration) gatewayForConfiguration;

  @override
  State<_ConfiguredApplication> createState() => _ConfiguredApplicationState();
}

final class _ConfiguredApplicationState extends State<_ConfiguredApplication> {
  late ServerConfiguration _configuration;
  late BrainGateway _gateway;
  String? _healthNotice;
  int _selectedTab = 0;
  bool _routeOpen = false;

  @override
  void initState() {
    super.initState();
    _configuration = widget.configuration;
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
          onOpenSettings: _openSettings,
          initialDraft: widget.initialDraft,
          healthNotice: _healthNotice,
          onCaptureSucceeded: _clearHealthNotice,
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
      body: shell,
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
          initialConfiguration: _configuration,
          settingsStore: widget.settingsStore,
          gatewayForConfiguration: widget.gatewayForConfiguration,
          onSaved: _updateServer,
        ),
      ),
    );
    if (mounted) setState(() => _routeOpen = false);
  }

  void _updateServer(
    ServerConfiguration configuration,
    BrainGateway gateway,
    Object? healthFailure,
  ) {
    if (!mounted) return;
    setState(() {
      _configuration = configuration;
      _gateway = gateway;
      _healthNotice = healthFailure == null
          ? null
          : 'Configuration saved. The server did not respond to /health. You can try again later.';
    });
  }

  void _clearHealthNotice() {
    if (_healthNotice == null || !mounted) return;
    setState(() => _healthNotice = null);
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
        ? (error as BrainClientException).message
        : error.toString();
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const AppLogo(size: 144),
              const SizedBox(height: 20),
              Text(message, textAlign: TextAlign.center),
            ],
          ),
        ),
      ),
    );
  }
}
