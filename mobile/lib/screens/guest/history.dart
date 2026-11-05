import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/format.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';

/// A purchase row: package, business and site, when, code, amount.
class PurchaseTile extends StatelessWidget {
  const PurchaseTile({super.key, required this.h, this.showPlace = true});
  final Map h;
  final bool showPlace;

  @override
  Widget build(BuildContext context) => ListTile(
        leading: CircleAvatar(
          backgroundColor: (h['from'] != null ? Colors.pink : kGood).withValues(alpha: 0.12),
          child: Icon(h['from'] != null ? Icons.card_giftcard_rounded : Icons.wifi_rounded, color: h['from'] != null ? Colors.pink : kGood, size: 20),
        ),
        title: Text('${h['package']}', style: const TextStyle(fontWeight: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text([
          if (showPlace) [h['business'], if (h['site'] != null) h['site']].join(' · '),
          when(h['at'] as String?),
          if (h['code'] != null) '#${h['code']}',
          if (h['offer'] != null) '🎁 ${h['offer']}',
          if (h['for'] != null) S.t('For {phone}', {'phone': localPhone(h['for'] as String)}),
          if (h['from'] != null) S.t('From a friend'),
        ].join('\n'), style: Theme.of(context).textTheme.bodySmall),
        isThreeLine: showPlace,
        trailing: Text(h['from'] != null ? S.t('Gift') : money(h['amount'] as num, (h['currency'] as String?) ?? 'TZS'),
            style: const TextStyle(fontWeight: FontWeight.w800)),
      );
}

/// One SafeNet site the customer uses: business, site, what they spent there, when they were last there.
class PlaceCard extends StatelessWidget {
  const PlaceCard({super.key, required this.p, required this.onTap});
  final Map p;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Row(children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: Colors.indigo.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(14)),
                child: const Icon(Icons.place_rounded, color: Colors.indigo),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${p['site'] ?? p['business']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                  Text('${p['business']}', style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 4),
                  Text(
                    [S.t('bought {n}×', {'n': p['purchases']}), if (p['last'] != null) '${S.t('Last')}: ${ago(p['last'] as String?)}'].join(' · '),
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                ]),
              ),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text(money(p['spent'] as num, (p['currency'] as String?) ?? 'TZS'), style: const TextStyle(fontWeight: FontWeight.w800)),
                if ((p['active'] as int? ?? 0) > 0) ...[const SizedBox(height: 4), Pill(S.t('Active'), color: kGood)],
              ]),
              const Icon(Icons.chevron_right_rounded),
            ]),
          ),
        ),
      );
}

/// Every purchase, at every SafeNet business and site, with a filter per site and grouped by month.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key, required this.history, required this.places, this.place});
  final List history;
  final List places;
  final Map? place;

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  late Map? place = widget.place;

  bool _at(Map h, Map p) => h['business_id'] == p['business_id'] && h['site_id'] == p['site_id'];

  @override
  Widget build(BuildContext context) {
    final rows = widget.history.cast<Map>().where((h) => place == null || _at(h, place!)).toList();
    final paid = rows.where((h) => h['from'] == null);
    final total = paid.fold<num>(0, (a, h) => a + (h['amount'] as num));
    final cur = rows.isNotEmpty ? (rows.first['currency'] as String? ?? 'TZS') : 'TZS';
    final months = <String, List<Map>>{};
    for (final h in rows) {
      final d = parseIso(h['at'] as String?);
      months.putIfAbsent(d == null ? '—' : DateFormat('MMMM yyyy').format(d), () => []).add(h);
    }
    return Scaffold(
      appBar: AppBar(title: Text(S.t('History'))),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
        if (widget.places.length > 1)
          SizedBox(
            height: 44,
            child: ListView(scrollDirection: Axis.horizontal, children: [
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(label: Text(S.t('All places')), selected: place == null, onSelected: (_) => setState(() => place = null)),
              ),
              for (final p in widget.places.cast<Map>())
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    avatar: const Icon(Icons.place_outlined, size: 16),
                    label: Text('${p['site'] ?? p['business']}'),
                    selected: place != null && _at(place!, p),
                    onSelected: (_) => setState(() => place = p),
                  ),
                ),
            ]),
          ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            gradient: const LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)]),
          ),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(place == null ? S.t('Everywhere') : '${place!['site'] ?? ''} · ${place!['business']}',
                    style: const TextStyle(color: Colors.white70), maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 4),
                Text(money(total, cur), style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w900)),
                Text(S.t('{n} purchases', {'n': paid.length}), style: const TextStyle(color: Colors.white70, fontSize: 12)),
              ]),
            ),
            const Icon(Icons.receipt_long_rounded, color: Colors.white54, size: 40),
          ]),
        ),
        if (rows.isEmpty) EmptyView(icon: Icons.receipt_long_outlined, text: S.t('None yet.')),
        for (final m in months.entries) ...[
          SectionTitle(m.key,
              trailing: Text(money(m.value.where((h) => h['from'] == null).fold<num>(0, (a, h) => a + (h['amount'] as num)), cur),
                  style: Theme.of(context).textTheme.labelLarge)),
          Card(child: Column(children: [for (final h in m.value) PurchaseTile(h: h, showPlace: place == null)])),
        ],
      ]),
    );
  }
}
