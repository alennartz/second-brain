import 'package:flutter/widgets.dart';

import 'gateway/brain_gateway.dart';
import 'persistence/settings_store.dart';

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
    throw UnimplementedError('not implemented');
  }
}
