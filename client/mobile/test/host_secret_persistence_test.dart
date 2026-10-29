import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  test('injected host secrets survive reopening', () async {
    sqfliteFfiInit();
    final directory = await Directory.systemTemp.createTemp('host-store-');
    addTearDown(() => directory.delete(recursive: true));
    final path = '${directory.path}/brain.db';
    var store = await openMobileStore(path,
        databaseFactory: databaseFactoryFfi,
        secretStore: HostSecretStore(path));
    await store.profiles.add(const BrainProfileDraft(
      name: 'Home',
      baseUrl: 'https://home.test',
      accessClientId: 'client',
      accessClientSecret: 'secret',
    ));
    await store.close();
    store = await openMobileStore(path,
        databaseFactory: databaseFactoryFfi,
        secretStore: HostSecretStore(path));
    addTearDown(store.close);
    final profiles = await store.profiles.list();
    expect(profiles.single.accessClientId, 'client');
    expect(profiles.single.accessClientSecret, 'secret');
  });
}
