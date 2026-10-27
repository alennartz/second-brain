import 'package:flutter/material.dart';

/// The shared Second Brain mark used in the app shell and setup flow.
final class AppLogo extends StatelessWidget {
  const AppLogo({super.key, this.size = 40});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Image.asset(
      'assets/brain_logo.png',
      width: size,
      height: size,
      fit: BoxFit.contain,
      filterQuality: FilterQuality.high,
      semanticLabel: 'Second Brain logo',
    );
  }
}
