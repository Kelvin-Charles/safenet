import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/session.dart';
import '../../core/strings.dart';
import 'customers.dart';
import 'home.dart';
import 'live.dart';
import 'more.dart';
import 'vouchers.dart';

class BusinessShell extends StatefulWidget {
  const BusinessShell({super.key});

  @override
  State<BusinessShell> createState() => _BusinessShellState();
}

class _BusinessShellState extends State<BusinessShell> {
  int tab = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final tabs = <(IconData, IconData, String, Widget)>[
      (Icons.space_dashboard_outlined, Icons.space_dashboard_rounded, S.t('Home'), HomeScreen(onTab: (i) => setState(() => tab = i))),
      (Icons.sensors_outlined, Icons.sensors_rounded, S.t('Live'), const LiveScreen()),
      (Icons.confirmation_number_outlined, Icons.confirmation_number_rounded, S.t('Vouchers'), const VouchersScreen()),
      if (s.can('customers')) (Icons.people_outline_rounded, Icons.people_rounded, S.t('Customers'), const CustomersScreen()),
      (Icons.grid_view_outlined, Icons.grid_view_rounded, S.t('More'), const MoreScreen()),
    ];
    if (tab >= tabs.length) tab = 0;
    return Scaffold(
      body: IndexedStack(index: tab, children: [
        // only the open tab ticks (Live refreshes only while it is on screen)
        for (var i = 0; i < tabs.length; i++)
          TickerMode(enabled: i == tab, child: KeyedSubtree(key: ValueKey('${tabs[i].$3}-${s.api.siteId}'), child: tabs[i].$4)),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() => tab = i),
        destinations: [for (final t in tabs) NavigationDestination(icon: Icon(t.$1), selectedIcon: Icon(t.$2), label: t.$3)],
      ),
    );
  }
}

/// The site picker in the top bar (hidden for one site or a partner limited to a site).
class SiteButton extends StatelessWidget {
  const SiteButton({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    if (s.sites.length < 2 || s.me?['fixed_site'] != null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ActionChip(
        avatar: const Icon(Icons.place_outlined, size: 18),
        label: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 120), child: Text(s.siteName, overflow: TextOverflow.ellipsis)),
        onPressed: () => showModalBottomSheet(
          context: context,
          builder: (c) => SafeArea(
            child: ListView(shrinkWrap: true, children: [
              Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 8), child: Text(S.t('Site'), style: Theme.of(c).textTheme.titleMedium)),
              for (final site in [<String, dynamic>{'id': null, 'name': S.t('All sites')}, ...s.sites])
                ListTile(
                  leading: Icon(site['id'] == null ? Icons.public : Icons.place_outlined),
                  title: Text(site['name'] as String),
                  trailing: s.api.siteId == site['id'] ? const Icon(Icons.check_circle, color: Colors.green) : null,
                  onTap: () {
                    s.pickSite(site['id'] as int?);
                    Navigator.pop(c);
                  },
                ),
            ]),
          ),
        ),
      ),
    );
  }
}
