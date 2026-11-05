import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import 'buy.dart';
import 'here_banner.dart';
import 'history.dart';

/// A Wi-Fi customer's own view: codes with time and data left, where they connect, what they spent.
class GuestHome extends StatelessWidget {
  const GuestHome({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: AppBar(title: Text(S.t('My Wi-Fi')), actions: [
        PopupMenuButton<String>(
          onSelected: (v) async {
            if (v == 'lang') {
              s.setLanguage(S.lang == 'sw' ? 'en' : 'sw');
            } else if (await confirm(context, S.t('Sign out?'), yes: S.t('Sign out'), danger: true)) {
              s.signOut();
            }
          },
          itemBuilder: (_) => [
            PopupMenuItem(value: 'lang', child: Text(S.lang == 'sw' ? 'English' : 'Kiswahili')),
            PopupMenuItem(value: 'out', child: Text(S.t('Sign out'))),
          ],
        ),
      ]),
      body: Loader<Map<String, dynamic>>(
        reloadKey: S.lang,
        load: () => s.api.get('/api/m/guest/home'),
        builder: (context, d, reload) {
          final codes = d['codes'] as List;
          final active = codes.where((c) => c['state'] == 'active' || c['state'] == 'unused').toList();
          final cur = (d['businesses'] as List).isNotEmpty ? (d['businesses'] as List).first['currency'] as String : 'TZS';
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
              Text(d['phone'] != null ? localPhone(d['phone'] as String) : S.t('Code {code}', {'code': d['code']}), style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Theme.of(context).colorScheme.outline)),
              const SizedBox(height: 10),
              const HereBanner(),
              if (active.isEmpty)
                Card(child: EmptyView(icon: Icons.wifi_off_rounded, text: S.t('No codes yet.')))
              else
                for (final c in active) _CodeCard(c: c as Map),
              if ((d['businesses'] as List).isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: FilledButton.icon(
                    icon: const Icon(Icons.shopping_bag_rounded),
                    label: Text(S.t('Buy a package')),
                    onPressed: () async {
                      final list = (d['businesses'] as List).cast<Map>();
                      final b = list.length == 1
                          ? list.first
                          : await showModalBottomSheet<Map>(
                              context: context,
                              builder: (c) => SafeArea(
                                child: Column(mainAxisSize: MainAxisSize.min, children: [
                                  Text(S.t('Where?'), style: Theme.of(c).textTheme.titleMedium),
                                  const SizedBox(height: 8),
                                  for (final x in list)
                                    ListTile(
                                      leading: const CircleAvatar(backgroundColor: kNavy, child: Icon(Icons.wifi_rounded, color: Colors.white, size: 20)),
                                      title: Text('${x['name']}'),
                                      subtitle: (x['sites'] as List).isNotEmpty ? Text((x['sites'] as List).join(' · ')) : null,
                                      onTap: () => Navigator.pop(c, x),
                                    ),
                                ]),
                              ),
                            );
                      if (b == null || !context.mounted) return;
                      final bought = await Navigator.push<bool>(
                          context, MaterialPageRoute(builder: (_) => BuyScreen(businessId: b['id'] as int, name: b['name'] as String)));
                      if (bought == true) reload();
                    },
                  ),
                ),
              const SizedBox(height: 4),
              Row(children: [
                Expanded(child: StatTile(icon: Icons.payments_outlined, label: S.t('Total spent'), value: money(d['spent'] as num, cur), color: kGood)),
                const SizedBox(width: 12),
                Expanded(child: StatTile(icon: Icons.data_usage_rounded, label: S.t('Data used'), value: bytes(d['data'] as num), color: kAccent)),
              ]),
              SectionTitle(S.t('Where you connect')),
              for (final b in d['businesses'] as List)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Row(children: [
                          CircleAvatar(backgroundColor: kNavy, child: const Icon(Icons.wifi_rounded, color: Colors.white, size: 20)),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text('${b['name']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                              if ((b['sites'] as List).isNotEmpty)
                                Text((b['sites'] as List).join(' · '), style: Theme.of(context).textTheme.bodySmall),
                            ]),
                          ),
                          if ((b['active'] as int) > 0) Pill(S.t('Active'), color: kGood),
                        ]),
                        const SizedBox(height: 10),
                        Row(children: [
                          _Fig(S.t('Spent'), money(b['spent'] as num, b['currency'] as String)),
                          _Fig(S.t('Purchases'), '${b['purchases']}'),
                          if (b['last'] != null) _Fig(S.t('Last purchase'), ago(b['last'] as String?)),
                        ]),
                        const SizedBox(height: 10),
                        Row(children: [
                          Expanded(
                            child: FilledButton.icon(
                              style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
                              onPressed: () async {
                                final bought = await Navigator.push<bool>(context,
                                    MaterialPageRoute(builder: (_) => BuyScreen(businessId: b['id'] as int, name: b['name'] as String)));
                                if (bought == true) reload();
                              },
                              icon: const Icon(Icons.shopping_cart_outlined, size: 18),
                              label: Text(S.t('Buy more')),
                            ),
                          ),
                          if (b['support'] != null) ...[
                            const SizedBox(width: 8),
                            OutlinedButton.icon(
                              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
                              onPressed: () => launchUrl(Uri.parse('tel:${b['support']}')),
                              icon: const Icon(Icons.support_agent_rounded, size: 18),
                              label: Text(S.t('Support')),
                            ),
                          ],
                        ]),
                      ]),
                    ),
                  ),
                ),
              if ((d['places'] as List? ?? []).isNotEmpty) ...[
                SectionTitle(S.t('Your Wi-Fi places')),
                for (final p in d['places'] as List)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: PlaceCard(
                      p: p as Map,
                      onTap: () => Navigator.push(context, MaterialPageRoute(
                          builder: (_) => HistoryScreen(history: d['history'] as List, places: d['places'] as List, place: p))),
                    ),
                  ),
              ],
              SectionTitle(S.t('History'),
                  trailing: (d['history'] as List).length > 5
                      ? TextButton(
                          onPressed: () => Navigator.push(context, MaterialPageRoute(
                              builder: (_) => HistoryScreen(history: d['history'] as List, places: d['places'] as List? ?? []))),
                          child: Text(S.t('See all ({n})', {'n': (d['history'] as List).length})),
                        )
                      : null),
              Card(
                child: (d['history'] as List).isEmpty
                    ? EmptyView(icon: Icons.receipt_long_outlined, text: S.t('None yet.'))
                    : Column(children: [for (final h in (d['history'] as List).take(5)) PurchaseTile(h: h as Map)]),
              ),
              const PoweredBy(),
            ]),
          );
        },
      ),
    );
  }
}

class _Fig extends StatelessWidget {
  const _Fig(this.label, this.value);
  final String label, value;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: Theme.of(context).colorScheme.outline)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w700)),
        ]),
      );
}

class _CodeCard extends StatelessWidget {
  const _CodeCard({required this.c});
  final Map c;

  @override
  Widget build(BuildContext context) {
    final started = c['state'] == 'active';
    final left = (c['seconds_left'] as num? ?? 0).toInt();
    final total = (c['total_seconds'] as num? ?? 1).toInt();
    final frac = started && total > 0 ? (left / total).clamp(0.0, 1.0) : 1.0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(24),
          gradient: const LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)], begin: Alignment.topLeft, end: Alignment.bottomRight),
        ),
        child: Row(children: [
          SizedBox(
            width: 92,
            height: 92,
            child: Stack(alignment: Alignment.center, children: [
              SizedBox.expand(
                child: CircularProgressIndicator(
                  value: frac.toDouble(),
                  strokeWidth: 8,
                  strokeCap: StrokeCap.round,
                  backgroundColor: Colors.white12,
                  color: frac < 0.15 ? kWarn : const Color(0xFF6EE7A8),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(12),
                child: FittedBox(
                  child: Text(started ? secondsLeft(left) : S.t('Not started'),
                      textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800)),
                ),
              ),
            ]),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${c['package']}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 16)),
              Text([c['business'], if (c['site'] != null) c['site']].join(' · '), style: const TextStyle(color: Colors.white70, fontSize: 12)),
              const SizedBox(height: 8),
              Text('#${c['code']}', style: const TextStyle(color: Colors.white, fontFamily: 'monospace', letterSpacing: 1.5, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text('${S.t('Data used')}: ${bytes((c['down'] as num) + (c['up'] as num))}', style: const TextStyle(color: Colors.white70, fontSize: 12)),
              if ((c['made_up'] as num? ?? 0) > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(S.t('Make-up for an outage: +{time}', {'time': minutesLabel((c['made_up'] as num).toInt())}),
                      style: const TextStyle(color: kGold, fontSize: 12, fontWeight: FontWeight.w600)),
                ),
              if (c['gift'] == true)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(S.t('Free code after an outage'), style: const TextStyle(color: kGold, fontSize: 12, fontWeight: FontWeight.w600)),
                ),
              if (c['online'] is int && (c['online'] as int) > 0)
                Padding(padding: const EdgeInsets.only(top: 6), child: Pill(S.t('Online'), color: const Color(0xFF6EE7A8))),
            ]),
          ),
        ]),
      ),
    );
  }
}
