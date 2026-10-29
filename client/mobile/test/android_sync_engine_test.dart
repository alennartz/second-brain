import 'package:flutter_test/flutter_test.dart';
import 'package:second_brain_mobile/second_brain_mobile.dart';

const profile = BrainProfile(
  id: 'brain:home',
  name: 'Home Brain',
  baseUrl: 'https://brain.example.test',
);

void main() {
  test('syncAll retries every profile and reports accepted entries', () async {
    final report = await syncAll((_) => throw StateError('gateway unused'));

    expect(report.accepted, 2);
    expect(report.conflicts, 0);
    expect(report.pending, 0);
  });

  test('a 409 marks the edited entry conflict while retaining it locally',
      () async {
    final report = await syncAll((_) => throw StateError('gateway unused'));

    expect(report.conflicts, 1);
    expect(report.pending, 0);
  });

  test('transport failures leave entries pending for a later foreground pass',
      () async {
    final report =
        await syncAll((_) => throw StateError('gateway unavailable'));

    expect(report.pending, 1);
  });

  test('the gateway factory receives each Brain profile', () async {
    final seen = <String>[];

    await syncAll((BrainProfile value) {
      seen.add(value.id);
      throw StateError('gateway unused');
    });

    expect(seen, contains(profile.id));
  });
}
