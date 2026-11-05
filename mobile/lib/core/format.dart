import 'package:intl/intl.dart';

import 'strings.dart';

final _num = NumberFormat.decimalPattern('en');

String money(num? v, [String currency = 'TZS']) => '$currency ${_num.format((v ?? 0).round())}';

String compactMoney(num? v) {
  final x = (v ?? 0).toDouble();
  if (x >= 1e6) return '${(x / 1e6).toStringAsFixed(x >= 1e7 ? 0 : 1)}M';
  if (x >= 1e3) return '${(x / 1e3).toStringAsFixed(x >= 1e4 ? 0 : 1)}K';
  return x.round().toString();
}

String bytes(num? b) {
  var x = (b ?? 0).toDouble();
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var i = 0;
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024;
    i++;
  }
  return '${x.toStringAsFixed(i >= 2 && x < 100 ? 1 : 0)} ${units[i]}';
}

/// 90 -> "1h 30m" / "saa 1 dk 30"; 2880 -> "2 days" / "siku 2".
String minutesLabel(int m) {
  final sw = S.lang == 'sw';
  if (m >= 1440 && m % 1440 == 0) {
    final d = m ~/ 1440;
    return sw ? 'siku $d' : '$d day${d == 1 ? '' : 's'}';
  }
  final d = m ~/ 1440, h = (m % 1440) ~/ 60, min = m % 60;
  final parts = <String>[];
  if (d > 0) parts.add(sw ? 'siku $d' : '${d}d');
  if (h > 0) parts.add(sw ? 'saa $h' : '${h}h');
  if (min > 0 && d == 0) parts.add(sw ? 'dk $min' : '${min}m');
  return parts.isEmpty ? (sw ? 'dk 0' : '0m') : parts.join(' ');
}

String secondsLeft(int s) => minutesLabel((s / 60).ceil());

DateTime? parseIso(String? s) => s == null ? null : DateTime.tryParse(s)?.toLocal();

String when(String? iso) {
  final d = parseIso(iso);
  if (d == null) return '—';
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final day = DateTime(d.year, d.month, d.day);
  final time = DateFormat('HH:mm').format(d);
  if (day == today) return '${S.t('Today')} $time';
  if (today.difference(day).inDays == 1) return '${S.lang == 'sw' ? 'Jana' : 'Yesterday'} $time';
  return DateFormat('d MMM, HH:mm').format(d);
}

String ago(String? iso) {
  final d = parseIso(iso);
  if (d == null) return '';
  final s = DateTime.now().difference(d).inSeconds;
  final sw = S.lang == 'sw';
  if (s < 60) return sw ? 'sasa hivi' : 'just now';
  if (s < 3600) return sw ? 'dk ${s ~/ 60} zilizopita' : '${s ~/ 60}m ago';
  if (s < 86400) return sw ? 'saa ${s ~/ 3600} zilizopita' : '${s ~/ 3600}h ago';
  return when(iso);
}

/// 255712345678 -> 0712 345 678
String localPhone(String? p) {
  if (p == null || p.isEmpty) return '';
  var x = p.startsWith('255') && p.length == 12 ? '0${p.substring(3)}' : p;
  if (x.length == 10) x = '${x.substring(0, 4)} ${x.substring(4, 7)} ${x.substring(7)}';
  return x;
}
