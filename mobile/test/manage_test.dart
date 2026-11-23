import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:safenet_app/core/api.dart';
import 'package:safenet_app/core/session.dart';
import 'package:safenet_app/core/strings.dart';
import 'package:safenet_app/screens/business/live.dart';
import 'package:safenet_app/screens/business/manage/reyee.dart';
import 'package:safenet_app/screens/business/manage/wallet.dart';
import 'package:safenet_app/screens/business/more.dart';

class FakeApi extends Api {
  final posts = <(String, Map<String, dynamic>?)>[];

  @override
  Future<Map<String, dynamic>> get(String path, [Map<String, dynamic>? query]) async {
    if (path.contains('/wallet/deposit/')) return {'reference': 'DP1', 'status': 'paid', 'pays': 5129, 'phone': '255684000111', 'balance': 15000};
    if (path == '/api/m/live') {
      return {
        'stats': {'online': 1, 'down_today': 1, 'up_today': 1, 'online_revenue_today': 0, 'cash_revenue_today': 0},
        'online': [{'user': '10825881', 'kind': 'voucher', 'plan': 'Day', 'mac': '06:5A:00:00:00:07', 'router': 'Reyee · Volcano Site', 'reyee_site': 18, 'down': 1, 'up': 1, 'seconds': 5}],
        'events': [], 'reyee': [{'id': 18, 'name': 'Volcano Site'}],
      };
    }
    if (path == '/api/m/wallet') {
      return {'platform': true, 'ready': true, 'currency': 'TZS', 'balance': 10000.0, 'unspent': 3000.0, 'least': 1000, 'most': 1000000, 'sms_price': 30.0,
        'phone': '0684 000 111', 'fee_percent': 2.5,
        'deposits': [{'reference': 'DP1', 'amount': 5000.0, 'fee': 129.0, 'pays': 5129.0, 'phone': '255684000111', 'status': 'failed', 'message': 'No PIN entered', 'created': '2026-11-23T08:00:00Z'}]};
    }
    return {
      'site': {'id': 18, 'name': 'Volcano Site'}, 'error': null, 'trial_minutes': null,
      'aps': [{'name': 'AP one with quite a long name', 'model': 'RAP6262', 'sn': 'G1AP1', 'ip': '192.168.1.2', 'online': true, 'last_online': null},
        {'name': 'AP two', 'model': 'RAP6262', 'sn': 'G1AP2', 'ip': '', 'online': false, 'last_online': '2026-11-23T08:00:00Z'}],
      'wifi': [{'id': '500', 'name': 'Volcano WiFi', 'secure': false, 'enable': true, 'hidden': false}],
      'portals': [{'name': 'Login', 'wifi': ['Volcano WiFi'], 'auth': ['Voucher', 'One-Click (free)'], 'one_click': true}],
      'blocked': [{'mac': '06:5a:00:00:00:08', 'name': 'Note'}],
      'guests': [{'mac': '06:5a:00:00:00:07', 'ip': '', 'code': '', 'state': '', 'free': true, 'since': null, 'signal': -60},
        {'mac': '06:5a:00:00:00:09', 'ip': '', 'code': '10825881', 'state': 'expired', 'free': false, 'since': '2026-11-23T08:00:00Z', 'signal': null}],
    };
  }

  @override
  Future<Map<String, dynamic>> post(String path, [Map<String, dynamic>? body]) async {
    posts.add((path, body));
    return {'ok': true, 'message': 'Done', 'reference': 'DP1', 'status': 'pending', 'pays': 5129, 'phone': '255684000111'};
  }
}

class FakeSession extends Session {
  @override
  final FakeApi api = FakeApi();
}

Future<FakeSession> show(WidgetTester t, Widget screen) async {
  t.view.physicalSize = const Size(360, 3200);       // a narrow phone; tall, so everything is built
  t.view.devicePixelRatio = 1;
  addTearDown(t.view.reset);
  final s = FakeSession()
    ..kind = Kind.business
    ..me = {
      'user': {'username': 'owner', 'role': 'owner'},
      'tenant': {'name': 'Volcano', 'currency': 'TZS', 'payment_mode': 'platform'},
      'sites': [{'id': 18, 'name': 'Volcano Site', 'reyee': true}],
      'can': {'money': true, 'customers': true, 'packages': true, 'change': true, 'withdraw': true, 'sms': true, 'expenses': true},
    };
  await t.pumpWidget(ChangeNotifierProvider<Session>.value(value: s, child: MaterialApp(home: screen)));
  await t.pump(const Duration(milliseconds: 500));
  return s;
}

void main() {
  setUp(() => S.lang = 'en');

  testWidgets('Reyee: shows everything and restarts after asking', (t) async {
    final s = await show(t, const ReyeeScreen(siteId: 18, siteName: 'Volcano Site'));
    for (final x in ['Volcano WiFi', 'Free (One-Click)', 'Disconnect free logins', 'Unblock', '10825881']) {
      expect(find.text(x), findsWidgets, reason: x);
    }
    await t.tap(find.text('Restart'));
    await t.pump(const Duration(milliseconds: 500));
    expect(s.api.posts, isEmpty);
    await t.tap(find.text('Restart').last);
    await t.pump(const Duration(milliseconds: 500));
    expect(s.api.posts.single.$2, {'action': 'reboot', 'sn': 'G1AP1'});
    await t.pump(const Duration(seconds: 6));
  });

  testWidgets('Reyee: saving the Wi-Fi', (t) async {
    final s = await show(t, const ReyeeScreen(siteId: 18, siteName: 'Volcano Site'));
    await t.tap(find.text('Volcano WiFi').first);
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await t.tap(find.text('Save Wi-Fi'));
    await t.pump(const Duration(seconds: 1));
    expect(s.api.posts.single.$2, {'action': 'wifi', 'ssid_id': '500', 'name': 'Volcano WiFi', 'security': 'open', 'password': '', 'enable': true, 'hidden': false});
    await t.pump(const Duration(seconds: 6));
  });

  testWidgets('Wallet: the fee, then a deposit until it is paid', (t) async {
    final s = await show(t, const WalletScreen(amount: 5000));
    await t.pump(const Duration(milliseconds: 500));
    expect(find.textContaining('TZS 5,129'), findsOneWidget);
    await t.tap(find.widgetWithText(GestureDetector, 'Deposit').last);
    await t.pump(const Duration(seconds: 1));
    expect(s.api.posts.single.$2, {'amount': '5000', 'phone': '0684 000 111'});
    expect(find.text('Enter your PIN on your phone'), findsOneWidget);
    await t.pump(const Duration(seconds: 4));
    await t.pump();
    expect(find.text('Your balance is now TZS 15,000.'), findsOneWidget);
  });

  testWidgets('Live and More lead there', (t) async {
    final s = await show(t, const LiveScreen());
    expect(find.text('Manage access points'), findsOneWidget);
    await t.tap(find.byTooltip('Disconnect'));
    await t.pump(const Duration(milliseconds: 500));
    await t.tap(find.text('Log out'));
    await t.pump(const Duration(milliseconds: 500));
    expect(s.api.posts.single.$2, {'action': 'kick', 'mac': '06:5A:00:00:00:07'});
    await t.pump(const Duration(seconds: 6));
    await t.pumpWidget(const SizedBox());
    await show(t, const MoreScreen());
    expect(find.text('Wallet'), findsOneWidget);
    expect(find.text('Reyee access points'), findsOneWidget);
  });
}
