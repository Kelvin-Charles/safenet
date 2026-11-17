import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api.dart';

/// Push notifications (Firebase Cloud Messaging). The Firebase settings come from the SafeNet server
/// (/api/m/push/config, set up on Platform: Notifications), so the app needs no Firebase files of its own;
/// they are kept on the phone so a notification tapped while the app was closed can be opened at once.
class Push {
  static const _store = FlutterSecureStorage();
  static const _channel = AndroidNotificationChannel('alerts', 'Alerts',
      description: 'Sales, devices offline, withdrawals and other SafeNet alerts', importance: Importance.high);
  static final _local = FlutterLocalNotificationsPlugin();

  /// Unread alerts (the bell on Home).
  static final unread = ValueNotifier<int>(0);

  /// Opens the screen an alert points to (set by the business screens); a tap before that waits here.
  static void Function(String? link)? _onOpen;
  static String? _pending;
  static bool _hasPending = false;

  static String? token;
  static bool _listening = false;
  static StreamSubscription<String>? _refresh;

  static set onOpen(void Function(String? link)? f) {
    _onOpen = f;
    if (f != null && _hasPending) {
      _hasPending = false;
      f(_pending);
    }
  }

  static void _open(String? link) {
    if (_onOpen != null) {
      _onOpen!(link);
    } else {
      _pending = link;
      _hasPending = true;
    }
  }

  static Future<FirebaseOptions?> _options(Api api) async {
    Map<String, dynamic>? cfg;
    try {
      cfg = await api.get('/api/m/push/config');
      await _store.write(key: 'push_cfg', value: jsonEncode(cfg));
    } catch (_) {
      try {
        cfg = jsonDecode(await _store.read(key: 'push_cfg') ?? 'null') as Map<String, dynamic>?;
      } catch (_) {}
    }
    if (cfg == null || cfg['enabled'] != true) return null;
    final app = cfg[Platform.isIOS ? 'ios' : 'android'] as Map?;
    if (app == null) return null;
    return FirebaseOptions(
      apiKey: '${app['api_key']}',
      appId: '${app['app_id']}',
      messagingSenderId: '${app['sender_id']}',
      projectId: '${cfg['project_id']}',
      iosBundleId: 'com.safezonetz.safenetApp',
    );
  }

  /// After a business account signs in (and each start while signed in): ask to allow notifications and
  /// register this phone. Quietly does nothing when push isn't set up on the server or the person said no.
  static Future<void> start(Api api) async {
    try {
      final options = await _options(api);
      if (options == null) return;
      if (Firebase.apps.isEmpty) await Firebase.initializeApp(options: options);
      final fm = FirebaseMessaging.instance;
      await _listen(fm);
      final perm = await fm.requestPermission();
      if (perm.authorizationStatus == AuthorizationStatus.denied) return;
      if (Platform.isIOS) {
        // the Firebase token needs Apple's token first, which can take a moment after allowing
        for (var i = 0; i < 10 && await fm.getAPNSToken() == null; i++) {
          await Future.delayed(const Duration(seconds: 1));
        }
      }
      // registration tokens: what the server's FCM v1 "token" field takes (the newer installation IDs aren't used yet)
      // ignore: deprecated_member_use
      token = await fm.getToken();
      await _register(api);
      // ignore: deprecated_member_use
      _refresh ??= fm.onTokenRefresh.listen((t) {
        token = t;
        _register(api);
      });
    } catch (e) {
      debugPrint('push: $e');
    }
  }

  static Future<void> _register(Api api) async {
    if (token == null || api.token == null) return;
    try {
      await api.post('/api/m/push/register', {'token': token, 'platform': Platform.isIOS ? 'ios' : 'android'});
    } catch (_) {}
  }

  /// Signing out: this phone stops getting the account's notifications.
  static Future<void> stop(Api api) async {
    final t = token;
    unread.value = 0;
    if (t == null) return;
    try {
      await api.post('/api/m/push/unregister', {'token': t});
    } catch (_) {}
  }

  static Future<void> _listen(FirebaseMessaging fm) async {
    if (_listening) return;
    _listening = true;
    if (Platform.isAndroid) {
      await _local.initialize(
        settings: const InitializationSettings(android: AndroidInitializationSettings('ic_stat_safenet')),
        onDidReceiveNotificationResponse: (r) => _open(r.payload),
      );
      await _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()?.createNotificationChannel(_channel);
    } else {
      await fm.setForegroundNotificationPresentationOptions(alert: true, badge: true, sound: true);
    }
    // app open: Android doesn't show it by itself, so show it; the bell counts it either way
    FirebaseMessaging.onMessage.listen((m) {
      unread.value++;
      final n = m.notification;
      if (Platform.isAndroid && n != null) {
        _local.show(
          id: m.hashCode & 0x7fffffff,
          title: n.title,
          body: n.body,
          notificationDetails: NotificationDetails(
            android: AndroidNotificationDetails(_channel.id, _channel.name,
                channelDescription: _channel.description, importance: Importance.high, priority: Priority.high, icon: 'ic_stat_safenet'),
          ),
          payload: m.data['link'] as String?,
        );
      }
    });
    FirebaseMessaging.onMessageOpenedApp.listen((m) => _open(m.data['link'] as String?));
    final first = await fm.getInitialMessage();
    if (first != null) _open(first.data['link'] as String?);
  }

  /// Refresh the bell's count from the server.
  static Future<void> refreshCount(Api api) async {
    try {
      final r = await api.get('/api/m/alerts/count');
      unread.value = (r['unread'] as num?)?.toInt() ?? 0;
    } catch (_) {}
  }
}
