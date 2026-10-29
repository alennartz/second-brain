import 'dart:async';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import 'second_brain_mobile.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final preferences = await SharedPreferences.getInstance();
  final settingsStore = SharedPreferencesSettingsStore(
    preferences,
    secretStore: const FlutterSecureSecretStore(),
  );
  final databasePath = '${await getDatabasesPath()}/second_brain_mobile.db';
  final store = await openMobileStore(
    databasePath,
    settingsStore: settingsStore,
  );
  runApp(
    _ProductionApplication(
      store: store,
      settingsStore: settingsStore,
    ),
  );
}

final class _ProductionApplication extends StatefulWidget {
  const _ProductionApplication({
    required this.store,
    required this.settingsStore,
  });

  final MobileStore store;
  final SettingsStore settingsStore;

  @override
  State<_ProductionApplication> createState() => _ProductionApplicationState();
}

final class _ProductionApplicationState extends State<_ProductionApplication> {
  late final http.Client _client;
  late final Uuid _uuid;

  @override
  void initState() {
    super.initState();
    _client = http.Client();
    _uuid = const Uuid();
  }

  @override
  void dispose() {
    _client.close();
    unawaited(widget.store.close());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MobileApplication(
      store: widget.store,
      settingsStore: widget.settingsStore,
      gatewayForProfile: (profile) => HttpBrainGateway(
        configuration: ServerConfiguration(
          baseUrl: profile.baseUrl,
          accessClientId: profile.accessClientId,
          accessClientSecret: profile.accessClientSecret,
        ),
        client: _client,
      ),
      createIdempotencyKey: _uuid.v4,
    );
  }
}
