import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:safenet_app/core/session.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('light by default, even when nothing is saved', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final s = Session();
    expect(s.themeMode, ThemeMode.light);
    await s.load();
    expect(s.themeMode, ThemeMode.light);
  });

  test('the choice is saved, and signing out keeps it', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final s = Session();
    await s.load();
    var told = 0;
    s.addListener(() => told++);
    await s.setThemeMode(ThemeMode.dark);
    expect(told, greaterThan(0));

    final again = Session();
    await again.load();
    expect(again.themeMode, ThemeMode.dark);

    await again.signOut();
    final afterSignOut = Session();
    await afterSignOut.load();
    expect(afterSignOut.themeMode, ThemeMode.dark);

    await afterSignOut.setThemeMode(ThemeMode.light);
    final back = Session();
    await back.load();
    expect(back.themeMode, ThemeMode.light);
  });
}
