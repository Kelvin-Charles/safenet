import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/format.dart';
import '../../core/push.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/kit.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import 'manage/sites.dart';
import 'more.dart';
import 'web_page.dart';

(IconData, Color) alertLook(String? kind) => switch (kind) {
      'sale' => (Icons.payments_rounded, kGood),
      'daily' => (Icons.insights_rounded, kAccent),
      'device' => (Icons.router_rounded, kWarn),
      'withdrawal' => (Icons.call_made_rounded, Colors.green.shade800),
      'billing' => (Icons.workspace_premium_rounded, kGold),
      'failed' => (Icons.error_rounded, kBad),
      'platform' => (Icons.admin_panel_settings_rounded, Colors.deepPurple),
      _ => (Icons.campaign_rounded, Colors.indigo),
    };

/// Open what an alert is about (also used when a notification is tapped).
void openAlertLink(BuildContext context, String? link) {
  final s = context.read<Session>();
  void push(Widget w) => Navigator.push(context, MaterialPageRoute(builder: (_) => w));
  switch (link) {
    case 'payments':
      push(const PaymentsScreen());
    case 'earnings' when s.can('money'):
      push(const EarningsScreen());
    case 'sites':
      push(const SitesScreen());
    case 'billing' when s.can('withdraw'):
      openWeb(context, S.t('SafeNet plan'), '/billing');
    case 'dashboard':
      Navigator.popUntil(context, (r) => r.isFirst);
    default:
      push(const AlertsScreen());
  }
}

/// The bell on Home, with the number of unread alerts.
class AlertsBell extends StatefulWidget {
  const AlertsBell({super.key});

  @override
  State<AlertsBell> createState() => _AlertsBellState();
}

class _AlertsBellState extends State<AlertsBell> {
  @override
  void initState() {
    super.initState();
    Push.refreshCount(context.read<Session>().api);
  }

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<int>(
        valueListenable: Push.unread,
        builder: (context, n, _) => SnIconButton(
          tooltip: S.t('Alerts'),
          icon: Badge(
            isLabelVisible: n > 0,
            label: Text(n > 99 ? '99+' : '$n'),
            child: Icon(n > 0 ? Icons.notifications_active_rounded : Icons.notifications_none_rounded),
          ),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const AlertsScreen())),
        ),
      );
}

class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});

  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> {
  final items = <Map<String, dynamic>>[];
  bool loading = true, more = false, pushOn = true;
  String? error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool next = false}) async {
    final s = context.read<Session>();
    try {
      final r = await s.api.get('/api/m/alerts', {if (next && items.isNotEmpty) 'before': items.last['id']});
      if (!mounted) return;
      setState(() {
        if (!next) items.clear();
        items.addAll(((r['items'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)));
        more = r['more'] == true;
        pushOn = r['push'] == true;
        Push.unread.value = (r['unread'] as num?)?.toInt() ?? 0;
        loading = false;
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => (loading = false, error = '$e'));
    }
  }

  Future<void> _read(Map<String, dynamic>? item) async {
    final s = context.read<Session>();
    if (item != null && item['read'] == true) return;
    setState(() {
      for (final i in items) {
        if (item == null || i['id'] == item['id']) i['read'] = true;
      }
    });
    try {
      final r = await s.api.post('/api/m/alerts/read', {if (item != null) 'id': item['id']});
      Push.unread.value = (r['unread'] as num?)?.toInt() ?? 0;
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final unread = items.any((i) => i['read'] != true);
    return Scaffold(
      appBar: SnAppBar(title: Text(S.t('Alerts')), actions: [
        if (unread) SnIconButton(icon: const Icon(Icons.done_all_rounded), tooltip: S.t('Mark all read'), onPressed: () => _read(null)),
        SnIconButton(
          icon: const Icon(Icons.tune_rounded),
          tooltip: S.t('Notifications'),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const AlertSettingsScreen())),
        ),
        const SizedBox(width: 8),
      ]),
      body: loading
          ? const Center(child: SnSpinner())
          : error != null
              ? ErrorView(message: error!, onRetry: () => _load())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
                    if (!pushOn)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: SnCard(
                          color: kWarn.withValues(alpha: 0.12),
                          child: SnTile(
                            leading: const Icon(Icons.notifications_paused_rounded, color: kWarn),
                            title: Text(S.t('Alerts show here for now. Notifications on the phone are coming soon.')),
                          ),
                        ),
                      ),
                    if (items.isEmpty) EmptyView(icon: Icons.notifications_none_rounded, text: S.t('No alerts yet. Sales, devices going offline and withdrawals will show here.')),
                    for (final a in items) _AlertCard(a: a, onTap: () {
                      _read(a);
                      if (a['link'] != null) openAlertLink(context, a['link'] as String?);
                    }),
                    if (more)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Center(child: SnButton(variant: SnVariant.ghost, size: SnSize.medium, onPressed: () => _load(next: true), child: Text(S.t('Show more')))),
                      ),
                  ]),
                ),
    );
  }
}

class _AlertCard extends StatelessWidget {
  const _AlertCard({required this.a, required this.onTap});
  final Map<String, dynamic> a;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = alertLook(a['kind'] as String?);
    final read = a['read'] == true;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: SnCard(
        color: read ? null : color.withValues(alpha: 0.07),
        child: SnTile(
          onTap: onTap,
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          leading: CircleAvatar(backgroundColor: color.withValues(alpha: 0.14), child: Icon(icon, color: color, size: 22)),
          title: Text('${a['title']}', style: TextStyle(fontWeight: read ? FontWeight.w600 : FontWeight.w800)),
          subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if ('${a['body'] ?? ''}'.isNotEmpty) Text('${a['body']}'),
            const SizedBox(height: 2),
            Text(ago(a['at'] as String?), style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.outline)),
          ]),
          trailing: read ? null : Container(width: 9, height: 9, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        ),
      ),
    );
  }
}

/// Which alerts this person gets (in the list and as notifications on the phone).
class AlertSettingsScreen extends StatefulWidget {
  const AlertSettingsScreen({super.key});

  @override
  State<AlertSettingsScreen> createState() => _AlertSettingsScreenState();
}

class _AlertSettingsScreenState extends State<AlertSettingsScreen> {
  int key = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: SnAppBar(title: Text(S.t('Notifications'))),
      body: Loader<Map<String, dynamic>>(
        reloadKey: key,
        load: () => s.api.get('/api/m/alerts/settings'),
        builder: (context, d, reload) => ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 4, 4, 12),
            child: Text(
              d['push'] == true
                  ? (d['phones'] as int? ?? 0) > 0
                      ? S.t('This phone gets a notification for the alerts turned on. All of them also show in Alerts.')
                      : S.t('Allow notifications for SafeNet in the phone settings to get them on this phone.')
                  : S.t('Alerts show in the app for now. Notifications on the phone are coming soon.'),
              style: TextStyle(color: Theme.of(context).colorScheme.outline),
            ),
          ),
          SnCard(
            child: Column(children: [
              for (final k in (d['kinds'] as List).cast<Map>())
                SnSwitchTile(
                  secondary: Icon(alertLook(k['kind'] as String).$1, color: alertLook(k['kind'] as String).$2),
                  title: Text('${k['name']}'),
                  subtitle: Text('${k['about']}'),
                  value: k['on'] == true,
                  onChanged: (v) async {
                    setState(() => k['on'] = v);
                    final r = await attempt(context, () => s.api.post('/api/m/alerts/settings', {k['kind'] as String: v}));
                    if (r == null && context.mounted) setState(() => key++);
                  },
                ),
            ]),
          ),
        ]),
      ),
    );
  }
}
