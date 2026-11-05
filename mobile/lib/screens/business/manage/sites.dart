import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';
import '../web_page.dart';
import '../../../ui/kit.dart';

/// Sites (money and who is online at each) and the health of every device.
class SitesScreen extends StatefulWidget {
  const SitesScreen({super.key});

  @override
  State<SitesScreen> createState() => _SitesScreenState();
}

class _SitesScreenState extends State<SitesScreen> {
  int key = 0;

  Future<void> rename(Map? site) async {
    final c = TextEditingController(text: site?['name'] as String? ?? '');
    final name = await showSnDialog<String>(
      context: context,
      builder: (d) => SnDialog(
        title: Text(site == null ? S.t('New site') : S.t('Rename site')),
        content: SnField(controller: c, autofocus: true, textCapitalization: TextCapitalization.words, decoration: InputDecoration(labelText: S.t('Name'))),
        actions: [
          SnButton(variant: SnVariant.ghost, size: SnSize.small, onPressed: () => Navigator.pop(d), child: Text(S.t('Cancel'))),
          SnButton( onPressed: () => Navigator.pop(d, c.text), child: Text(S.t('Save'))),
        ],
      ),
    );
    if (name == null || !mounted) return;
    final s = context.read<Session>();
    final r = await attempt(context, () => s.api.post(site == null ? '/api/m/sites' : '/api/m/sites/${site['id']}', {'name': name}));
    if (r != null && mounted) {
      try {
        s.me = await s.api.get('/api/m/me');
      } catch (_) {}
      setState(() => key++);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: SnAppBar(title: Text(S.t('Sites & devices')), actions: [
        SnIconButton(icon: const Icon(Icons.open_in_new_rounded), tooltip: S.t('Set up equipment'), onPressed: () => openWeb(context, S.t('Sites & Wi-Fi'), '/sites')),
      ]),
      floatingActionButton: s.can('packages')
          ? SnFab(onPressed: () => rename(null), icon: const Icon(Icons.add_location_alt_outlined), label: Text(S.t('New site')))
          : null,
      body: Loader<Map<String, dynamic>>(
        reloadKey: key,
        load: () => s.api.get('/api/m/sites'),
        builder: (context, d, reload) {
          final devices = d['devices'] as List;
          final cur = d['currency'] as String;
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 96), children: [
              for (final site in d['sites'] as List)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: SnCard(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Row(children: [
                          Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(color: Colors.indigo.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
                            child: const Icon(Icons.place_rounded, color: Colors.indigo),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text('${site['name']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                              if (site['kind'] != null) Text('${site['kind']}', style: Theme.of(context).textTheme.bodySmall),
                            ]),
                          ),
                          if (s.can('packages')) SnIconButton(icon: const Icon(Icons.edit_outlined), onPressed: () => rename(site as Map)),
                        ]),
                        const SizedBox(height: 12),
                        Row(children: [
                          _Fig(Icons.sensors_rounded, '${site['online']}', S.t('Online now'), kGood),
                          _Fig(Icons.today_rounded, compactMoney(site['today'] as num), S.t('Today'), kAccent),
                          _Fig(Icons.calendar_month_rounded, compactMoney(site['month'] as num), S.t('This month'), kGold),
                        ]),
                        const SizedBox(height: 4),
                        Align(
                          alignment: Alignment.centerRight,
                          child: SnButton(variant: SnVariant.ghost, size: SnSize.small,
                            onPressed: () => s.pickSite(site['id'] as int).then((_) {
                              if (context.mounted) Navigator.pop(context);
                            }),
                            child: Text(S.t('Show this site')),
                          ),
                        ),
                      ]),
                    ),
                  ),
                ),
              SectionTitle('${S.t('Devices')} (${devices.length})'),
              if (devices.isEmpty)
                SnCard(child: EmptyView(icon: Icons.router_outlined, text: S.t('No devices connected yet. Tap ↗ above to set up your Wi-Fi equipment.')))
              else
                SnCard(
                  child: Column(children: [
                    for (final x in devices)
                      SnTile(
                        leading: Stack(children: [
                          const Icon(Icons.router_rounded, size: 30),
                          Positioned(
                            right: 0,
                            bottom: 0,
                            child: Container(
                              width: 11,
                              height: 11,
                              decoration: BoxDecoration(
                                color: x['state'] == 'online' ? kGood : x['state'] == 'degraded' ? kWarn : kBad,
                                border: Border.all(color: Theme.of(context).cardTheme.color ?? Colors.white, width: 2),
                              ),
                            ),
                          ),
                        ]),
                        title: Text('${x['name']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                        subtitle: Text([x['kind'], if (x['site'] != null) x['site'], x['last'] != null ? ago(x['last'] as String?) : S.t('never connected')].join(' · ')),
                        trailing: Pill(
                          x['state'] == 'online' ? S.t('Online') : x['state'] == 'degraded' ? S.t('Slow to report') : S.t('Offline'),
                          color: x['state'] == 'online' ? kGood : x['state'] == 'degraded' ? kWarn : kBad,
                        ),
                      ),
                  ]),
                ),
              const SizedBox(height: 8),
              Text(S.t('Totals today: {money}', {'money': money((d['sites'] as List).fold<num>(0, (a, x) => a + (x['today'] as num)), cur)}),
                  textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
            ]),
          );
        },
      ),
    );
  }
}

class _Fig extends StatelessWidget {
  const _Fig(this.icon, this.value, this.label, this.color);
  final IconData icon;
  final String value, label;
  final Color color;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Container(
          margin: const EdgeInsets.only(right: 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: color.withValues(alpha: 0.08), borderRadius: BorderRadius.circular(12)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(height: 4),
            Text(value, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            Text(label, style: Theme.of(context).textTheme.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
      );
}
