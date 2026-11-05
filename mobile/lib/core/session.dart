import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api.dart';
import 'strings.dart';

enum Kind { none, business, guest }

/// Who is signed in (a business account or a Wi-Fi customer), their token, and the site picked.
class Session extends ChangeNotifier {
  Session() {
    api.onSignedOut = signOut;
  }

  static const _store = FlutterSecureStorage();
  final Api api = Api();
  Kind kind = Kind.none;
  Map<String, dynamic>? me; // business: /api/m/me
  String? guestPhone;
  bool ready = false;

  String get lang => S.lang;

  Future<void> load() async {
    final token = await _store.read(key: 'token');
    final k = await _store.read(key: 'kind');
    final site = await _store.read(key: 'site');
    S.lang = await _store.read(key: 'lang') ?? 'sw';
    if (token != null && k != null) {
      api.token = token;
      api.siteId = int.tryParse(site ?? '');
      kind = k == 'guest' ? Kind.guest : Kind.business;
      guestPhone = await _store.read(key: 'phone');
      if (kind == Kind.business) {
        try {
          me = await api.get('/api/m/me');
          _fixSite();
        } on ApiError catch (e) {
          if (e.signedOut) await _clear();
        }
      }
    }
    ready = true;
    notifyListeners();
  }

  Future<void> signInBusiness(String username, String password) async {
    final r = await api.post('/api/m/login', {'username': username, 'password': password});
    api.token = r['token'] as String;
    me = Map<String, dynamic>.from(r['me'] as Map);
    kind = Kind.business;
    final userLang = me?['user']?['language'] as String?;
    if (userLang != null) S.lang = userLang;
    _fixSite();
    await _store.write(key: 'token', value: api.token);
    await _store.write(key: 'kind', value: 'business');
    await _store.write(key: 'lang', value: S.lang);
    notifyListeners();
  }

  /// What the sign-in screen offers (registering, SMS sign-in); fetched once.
  Map<String, dynamic>? config;

  Future<Map<String, dynamic>> loadConfig() async {
    try {
      config ??= await api.get('/api/m/config');
    } catch (_) {}
    return config ?? {'signup': true, 'sms_login': true};
  }

  Future<Map<String, dynamic>> sendCode(String phone) => api.post('/api/m/guest/send-code', {'phone': phone});

  Future<void> signInPhone(String phone, String otp) => _guest({'phone': phone, 'otp': otp});

  Future<void> signInVoucher(String code) => _guest({'code': code});

  Future<void> _guest(Map<String, dynamic> body) async {
    final r = await api.post('/api/m/guest/login', body);
    api.token = r['token'] as String;
    guestPhone = r['phone'] as String?;
    kind = Kind.guest;
    await _store.write(key: 'token', value: api.token);
    await _store.write(key: 'kind', value: 'guest');
    await _store.write(key: 'phone', value: guestPhone ?? '');
    notifyListeners();
  }

  Future<Map<String, dynamic>> register(Map<String, dynamic> body) => api.post('/api/m/signup', body);

  Future<void> resendEmail(String email) => api.post('/api/m/resend', {'email': email});

  void _fixSite() {
    final fixed = me?['fixed_site'] as int?;
    if (fixed != null) api.siteId = fixed;
    final ids = ((me?['sites'] as List?) ?? []).map((s) => s['id']).toSet();
    if (api.siteId != null && !ids.contains(api.siteId)) api.siteId = null;
  }

  List<Map<String, dynamic>> get sites =>
      ((me?['sites'] as List?) ?? []).map((s) => Map<String, dynamic>.from(s as Map)).toList();

  String get siteName {
    if (api.siteId == null) return S.t('All sites');
    return sites.firstWhere((s) => s['id'] == api.siteId, orElse: () => {'name': S.t('All sites')})['name'] as String;
  }

  bool can(String what) => me?['can']?[what] == true;
  String get currency => (me?['tenant']?['currency'] as String?) ?? 'TZS';

  Future<void> pickSite(int? id) async {
    api.siteId = id;
    await _store.write(key: 'site', value: id?.toString() ?? '');
    notifyListeners();
  }

  Future<void> setLanguage(String value) async {
    S.lang = value;
    await _store.write(key: 'lang', value: value);
    if (kind == Kind.business) {
      try {
        await api.post('/api/m/language', {'lang': value});
      } catch (_) {}
    }
    notifyListeners();
  }

  Future<void> signOut() async {
    await _clear();
    notifyListeners();
  }

  Future<void> _clear() async {
    api.token = null;
    api.siteId = null;
    me = null;
    guestPhone = null;
    kind = Kind.none;
    for (final k in ['token', 'kind', 'site', 'phone']) {
      await _store.delete(key: k);
    }
  }
}
