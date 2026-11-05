import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import 'shell.dart';

/// Who is online now, refreshed every 15 seconds while the tab is open.
class LiveScreen extends StatefulWidget {
  const LiveScreen({super.key});

  @override
  State<LiveScreen> createState() => _LiveScreenState();
}

class _LiveScreenState extends State<LiveScreen> {
  Map<String, dynamic>? data;
  String? error;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (mounted && TickerMode.valuesOf(context).enabled && ModalRoute.of(context)?.isCurrent != false) load();
    });
  }

  bool _wasOn = true;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final on = TickerMode.valuesOf(context).enabled;
    if (on && !_wasOn) load();
    _wasOn = on;
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final d = await context.read<Session>().api.get('/api/m/live');
      if (mounted) setState(() {
        data = d;
        error = null;
      });
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  Future<void> disconnect(Map o) async {
    final user = o['user'] as String? ?? '';
    if (user.isEmpty || !await confirm(context, S.t('Disconnect {user}?', {'user': user}), yes: S.t('Disconnect'), danger: true)) return;
    if (!mounted) return;
    final r = await attempt(context, () => context.read<Session>().api.post('/api/m/live/disconnect', {'username': user}));
    if (r != null && mounted) {
      toast(context, S.t('Disconnected.'));
      load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final d = data;
    return Scaffold(
      appBar: AppBar(title: Text(S.t('Live')), actions: const [SiteButton()]),
      body: d == null
          ? (error != null ? ErrorView(message: error!, onRetry: load) : const Center(child: CircularProgressIndicator()))
          : RefreshIndicator(
              onRefresh: load,
              child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
                Row(children: [
                  Expanded(child: _Mini(label: S.t('Online now'), value: '${d['stats']['online']}', color: kGood, pulse: true)),
                  const SizedBox(width: 10),
                  Expanded(child: _Mini(label: S.t('Data today'), value: bytes((d['stats']['down_today'] as num) + (d['stats']['up_today'] as num)), color: kAccent)),
                  const SizedBox(width: 10),
                  Expanded(child: _Mini(label: S.t('Sold today'), value: compactMoney((d['stats']['online_revenue_today'] as num) + (d['stats']['cash_revenue_today'] as num)), color: kGold)),
                ]),
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(S.t('Updated every 15 seconds'), textAlign: TextAlign.center, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: Theme.of(context).colorScheme.outline)),
                ),
                SectionTitle('${S.t('Online now')} (${(d['online'] as List).length})'),
                if ((d['online'] as List).isEmpty)
                  Card(child: EmptyView(icon: Icons.wifi_off_rounded, text: S.t('Nobody is online right now.')))
                else
                  for (final o in d['online'] as List) _OnlineCard(o: o as Map, onDisconnect: s.can('change') && (o['user'] as String? ?? '').isNotEmpty ? () => disconnect(o) : null),
                if ((d['events'] as List).isNotEmpty) ...[
                  SectionTitle(S.t('Activity')),
                  Card(
                    child: Column(children: [
                      for (final e in (d['events'] as List).take(15))
                        ListTile(
                          dense: true,
                          leading: Icon(_eventIcon(e['type'] as String?), size: 20, color: _eventColor(e['type'] as String?)),
                          title: Text('${e['text']}', maxLines: 2, overflow: TextOverflow.ellipsis),
                          trailing: Text(ago(e['at'] as String?), style: Theme.of(context).textTheme.labelSmall),
                        ),
                    ]),
                  ),
                ],
              ]),
            ),
    );
  }

  static IconData _eventIcon(String? t) => switch (t) {
        'paid' => Icons.payments_outlined,
        'payment' => Icons.hourglass_top_rounded,
        'login' || 'start' => Icons.login_rounded,
        'stop' => Icons.logout_rounded,
        _ => Icons.error_outline,
      };

  static Color _eventColor(String? t) => switch (t) {
        'paid' => kGood,
        'payment' => kWarn,
        'login' || 'start' => kAccent,
        'stop' => Colors.grey,
        _ => kBad,
      };
}

class _Mini extends StatelessWidget {
  const _Mini({required this.label, required this.value, required this.color, this.pulse = false});
  final String label, value;
  final Color color;
  final bool pulse;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              if (pulse) Container(width: 8, height: 8, margin: const EdgeInsets.only(right: 6), decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
              Flexible(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.labelSmall)),
            ]),
            const SizedBox(height: 6),
            FittedBox(child: Text(value, style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: color))),
          ]),
        ),
      );
}

class _OnlineCard extends StatelessWidget {
  const _OnlineCard({required this.o, this.onDisconnect});
  final Map o;
  final VoidCallback? onDisconnect;

  @override
  Widget build(BuildContext context) {
    final expires = parseIso(o['expires'] as String?);
    final left = expires?.difference(DateTime.now());
    final title = (o['user'] as String?)?.isNotEmpty == true ? o['user'] as String : (o['mac'] as String? ?? '');
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              CircleAvatar(
                radius: 18,
                backgroundColor: kGood.withValues(alpha: 0.12),
                child: Icon(o['kind'] == 'voucher' ? Icons.confirmation_number_outlined : Icons.smartphone_rounded, color: kGood, size: 18),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontFamily: 'monospace')),
                  Text([if (o['phone'] != null) localPhone(o['phone'] as String), if ((o['plan'] as String? ?? '').isNotEmpty) o['plan']].join(' · '),
                      style: Theme.of(context).textTheme.bodySmall),
                ]),
              ),
              if (onDisconnect != null) IconButton(onPressed: onDisconnect, icon: const Icon(Icons.power_settings_new_rounded, color: kBad), tooltip: S.t('Disconnect')),
            ]),
            const SizedBox(height: 10),
            Wrap(spacing: 14, runSpacing: 6, children: [
              _Fact(Icons.south_rounded, bytes(o['down'] as num?)),
              _Fact(Icons.north_rounded, bytes(o['up'] as num?)),
              _Fact(Icons.schedule_rounded, secondsLeft((o['seconds'] as num? ?? 0).toInt())),
              if (left != null && !left.isNegative) _Fact(Icons.hourglass_bottom_rounded, '${S.t('Time left')}: ${secondsLeft(left.inSeconds)}'),
              if ((o['router'] as String? ?? '').isNotEmpty) _Fact(Icons.router_outlined, '${o['router']}'),
            ]),
          ]),
        ),
      ),
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact(this.icon, this.text);
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 14, color: Theme.of(context).colorScheme.outline),
        const SizedBox(width: 4),
        Text(text, style: Theme.of(context).textTheme.bodySmall),
      ]);
}
