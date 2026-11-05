import 'dart:convert';

import 'package:http/http.dart' as http;

import 'strings.dart';

/// SafeNet server. Build with --dart-define=SAFENET_URL=https://... to point the app elsewhere (e.g. a test server).
const String kServer = String.fromEnvironment('SAFENET_URL', defaultValue: 'https://radius.safezonetz.com');

class ApiError implements Exception {
  ApiError(this.message, [this.status = 0, this.data = const {}]);
  final String message;
  final int status;
  final Map<String, dynamic> data;

  /// Per-field problems from the server (e.g. {'email': '...'}).
  Map<String, String> get fields => ((data['fields'] as Map?) ?? {}).map((k, v) => MapEntry('$k', '$v'));
  bool get signedOut => status == 401;
  @override
  String toString() => message;
}

/// Talks to the SafeNet mobile API (/api/m/...). Every call sends the sign-in token and the site picked.
class Api {
  Api({this.token, this.siteId, this.onSignedOut});

  String? token;
  int? siteId;
  void Function()? onSignedOut;
  final http.Client _client = http.Client();

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        if (siteId != null) 'X-Site-Id': '$siteId',
        'Accept-Language': S.lang,
      };

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final q = <String, String>{};
    query?.forEach((k, v) {
      if (v != null && '$v'.isNotEmpty) q[k] = '$v';
    });
    return Uri.parse('$kServer$path').replace(queryParameters: q.isEmpty ? null : q);
  }

  Future<Map<String, dynamic>> get(String path, [Map<String, dynamic>? query]) =>
      _send(() => _client.get(_uri(path, query), headers: _headers));

  Future<Map<String, dynamic>> post(String path, [Map<String, dynamic>? body]) =>
      _send(() => _client.post(_uri(path), headers: _headers, body: jsonEncode(body ?? {})));

  Future<Map<String, dynamic>> delete(String path) => _send(() => _client.delete(_uri(path), headers: _headers));

  Future<Map<String, dynamic>> _send(Future<http.Response> Function() call) async {
    http.Response r;
    try {
      r = await call().timeout(const Duration(seconds: 30));
    } catch (_) {
      throw ApiError('No connection to SafeNet. Check your internet and try again.');
    }
    Map<String, dynamic> data = {};
    try {
      final decoded = jsonDecode(utf8.decode(r.bodyBytes));
      if (decoded is Map<String, dynamic>) data = decoded;
    } catch (_) {}
    if (r.statusCode >= 200 && r.statusCode < 300) return data;
    if (r.statusCode == 401 && token != null) onSignedOut?.call();
    throw ApiError((data['error'] as String?) ?? 'Something went wrong (${r.statusCode}). Try again.', r.statusCode, data);
  }
}
