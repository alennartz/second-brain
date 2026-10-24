import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import 'second_brain_mobile.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final preferences = await SharedPreferences.getInstance();
  runApp(_ProductionApplication(preferences: preferences));
}

final class _ProductionApplication extends StatefulWidget {
  const _ProductionApplication({required this.preferences});

  final SharedPreferences preferences;

  @override
  State<_ProductionApplication> createState() => _ProductionApplicationState();
}

final class _ProductionApplicationState extends State<_ProductionApplication> {
  late final http.Client _client;
  late final Uuid _uuid;
  late final SettingsStore _settingsStore;

  @override
  void initState() {
    super.initState();
    _client = http.Client();
    _uuid = const Uuid();
    _settingsStore = SharedPreferencesSettingsStore(widget.preferences);
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MobileApplication(
      settingsStore: _settingsStore,
      gatewayForBaseUrl: (baseUrl) => HttpBrainGateway(
        baseUrl: baseUrl,
        client: _client,
      ),
      createIdempotencyKey: _uuid.v4,
    );
  }
}
