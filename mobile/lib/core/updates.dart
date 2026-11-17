import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:in_app_update/in_app_update.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../ui/widgets.dart';
import 'strings.dart';

/// New versions of the app: when one is in the store, opening the app offers it.
///   Android: Google Play's own update screen (the person taps Update; Play installs it and reopens the app).
///   iPhone: Apple doesn't let apps update themselves, so a message opens the App Store page to update.
/// Checked when the app opens and when it comes back after a while; nothing to set up on the server.
class AppUpdates {
  static final navigatorKey = GlobalKey<NavigatorState>();
  static DateTime? _last;
  static bool _busy = false;

  static Future<void> check() async {
    if (_busy || (_last != null && DateTime.now().difference(_last!) < const Duration(hours: 6))) return;
    _busy = true;
    _last = DateTime.now();
    try {
      if (Platform.isAndroid) {
        await _android();
      } else if (Platform.isIOS) {
        await _ios();
      }
    } catch (e) {
      debugPrint('update check: $e');                 // e.g. installed from an APK, not from Play: no Play updates
    } finally {
      _busy = false;
    }
  }

  static Future<void> _android() async {
    final info = await InAppUpdate.checkForUpdate();
    final available = info.updateAvailability == UpdateAvailability.updateAvailable ||
        info.updateAvailability == UpdateAvailability.developerTriggeredUpdateInProgress;     // an update left half way
    if (available && info.immediateUpdateAllowed) {
      await InAppUpdate.performImmediateUpdate();
    } else if (available && info.flexibleUpdateAllowed) {
      await InAppUpdate.startFlexibleUpdate();
      await InAppUpdate.completeFlexibleUpdate();
    }
  }

  static Future<void> _ios() async {
    final pkg = await PackageInfo.fromPlatform();
    final r = await http
        .get(Uri.parse('https://itunes.apple.com/lookup?bundleId=${pkg.packageName}&country=tz&t=${DateTime.now().millisecondsSinceEpoch}'))
        .timeout(const Duration(seconds: 15));
    final results = (jsonDecode(r.body) as Map)['results'] as List? ?? [];
    if (results.isEmpty) return;
    final store = '${results.first['version']}';
    final url = '${results.first['trackViewUrl']}';
    if (!_newer(store, pkg.version)) return;
    final prefs = await SharedPreferences.getInstance();
    final skipped = prefs.getString('update_later');          // "1.2.0|2026-11-17": asked today already
    final today = DateTime.now().toIso8601String().substring(0, 10);
    if (skipped == '$store|$today') return;
    final context = navigatorKey.currentContext;
    if (context == null || !context.mounted) return;
    final yes = await confirm(context, S.t('A new version of SafeNet ({v}) is ready. Update now?', {'v': store}), yes: S.t('Update'));
    if (yes) {
      await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    } else {
      await prefs.setString('update_later', '$store|$today');
    }
  }

  /// "1.10.0" is newer than "1.9.2".
  static bool _newer(String a, String b) {
    List<int> parts(String v) => v.split('.').map((x) => int.tryParse(x.replaceAll(RegExp(r'\D'), '')) ?? 0).toList();
    final x = parts(a), y = parts(b);
    for (var i = 0; i < 3; i++) {
      final p = i < x.length ? x[i] : 0, q = i < y.length ? y[i] : 0;
      if (p != q) return p > q;
    }
    return false;
  }
}
