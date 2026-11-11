import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import 'manage/expenses.dart';
import 'manage/finance_report.dart';
import 'manage/offers.dart';
import 'manage/packages.dart';
import 'manage/plans.dart';
import 'manage/settings.dart';
import 'manage/sites.dart';
import 'manage/sms.dart';
import 'manage/team.dart';
import 'web_page.dart';
import '../../ui/kit.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final me = s.me ?? {};
    final user = me['user'] as Map? ?? {};
    final tenant = me['tenant'] as Map? ?? {};
    void push(Widget w) => Navigator.push(context, MaterialPageRoute(builder: (_) => w));
    void web(String title, String path) => openWeb(context, title, path);
    final admin = s.can('customers');
    final change = s.can('change');
    final groups = <(String, List<_Tile>)>[
      (S.t('Sell'), [
        if (admin) _Tile(Icons.inventory_2_rounded, S.t('Packages'), kAccent, () => push(const PackagesScreen())),
        if (admin) _Tile(Icons.local_offer_rounded, S.t('Offers'), Colors.pink, () => push(const OffersScreen())),
        if (admin && s.can('sms')) _Tile(Icons.sms_rounded, S.t('SMS to customers'), Colors.teal, () => push(const SmsScreen())),
        if (admin) _Tile(Icons.healing_rounded, S.t('Outage make-up'), kWarn, () => web(S.t('Make up for an outage'), '/vouchers/outage')),
        if (change) _Tile(Icons.print_rounded, S.t('Print vouchers'), Colors.blueGrey, () => web(S.t('Print vouchers'), '/vouchers/print')),
      ]),
      (S.t('Money'), [
        _Tile(Icons.receipt_long_rounded, S.t('Payments'), kGood, () => push(const PaymentsScreen())),
        if (s.can('money')) _Tile(Icons.account_balance_wallet_rounded, S.t('Earnings'), kGold, () => push(const EarningsScreen())),
        if (s.can('withdraw')) _Tile(Icons.call_made_rounded, S.t('Withdraw'), Colors.green.shade800, () => web(S.t('Withdraw'), '/earnings')),
        if (s.can('expenses')) _Tile(Icons.receipt_long_outlined, S.t('Expenses'), kBad, () => push(const ExpensesScreen())),
        if (s.can('expenses')) _Tile(Icons.picture_as_pdf_rounded, S.t('Financial report'), Colors.deepPurple, () => push(const FinanceReportScreen())),
        _Tile(Icons.bar_chart_rounded, S.t('Reports'), Colors.indigo, () => web(S.t('Reports'), '/accounting')),
      ]),
      (S.t('Network'), [
        _Tile(Icons.hub_rounded, S.t('Sites & devices'), Colors.indigo, () => push(const SitesScreen())),
        if (admin) _Tile(Icons.speed_rounded, S.t('Speed plans'), Colors.orange, () => push(const PlansScreen())),
        if (change) _Tile(Icons.badge_rounded, S.t('Customer accounts'), Colors.cyan.shade700, () => web(S.t('Accounts (customers)'), '/users')),
        if (admin) _Tile(Icons.palette_rounded, S.t('Login page'), Colors.deepPurple, () => web(S.t('Login page design'), '/portal')),
        _Tile(Icons.history_toggle_off_rounded, S.t('Login log'), Colors.brown, () => web(S.t('Login log'), '/auth-logs')),
      ]),
      (S.t('Business'), [
        if (admin) _Tile(Icons.groups_rounded, S.t('Team'), Colors.brown, () => push(const TeamScreen())),
        if (admin) _Tile(Icons.tune_rounded, S.t('Settings'), Colors.blueGrey, () => push(const SettingsScreen())),
        if (s.can('withdraw')) _Tile(Icons.workspace_premium_rounded, S.t('SafeNet plan'), Sn.brand(context), () => web(S.t('SafeNet plan'), '/billing')),
        _Tile(Icons.menu_book_rounded, S.t('Setup guides'), Colors.teal.shade700, () => web(S.t('Setup guides'), '/docs')),
      ]),
    ];
    return Scaffold(
      appBar: SnAppBar(
        title: Text(S.t('More')),
        actions: [
          SnIconButton(
            icon: const Icon(Icons.logout_rounded),
            tooltip: S.t('Sign out'),
            onPressed: () async {
              if (await confirm(context, S.t('Sign out?'), yes: S.t('Sign out'), danger: true)) s.signOut();
            },
          ),
        ],
      ),
      body: ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
          children: [
            // business card
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(22),
                gradient: const LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)], begin: Alignment.topLeft, end: Alignment.bottomRight),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  CircleAvatar(
                    radius: 24,
                    backgroundColor: Colors.white,
                    child: Text(((tenant['name'] as String?) ?? 'S').characters.first.toUpperCase(),
                        style: const TextStyle(color: kNavy, fontWeight: FontWeight.w900, fontSize: 20)),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${tenant['name'] ?? ''}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 17)),
                      Text('${user['username'] ?? ''} · ${user['role'] ?? ''}', style: const TextStyle(color: Colors.white70)),
                    ]),
                  ),
                  if (tenant['status'] == 'trial') const Pill('TRIAL', color: kGold),
                ]),
                if (tenant['guest_app'] != null) ...[
                  const SizedBox(height: 14),
                  Container(
                    padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
                    decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
                    child: Row(children: [
                      const Icon(Icons.link_rounded, color: Colors.white70, size: 18),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text('${tenant['guest_app']}'.replaceFirst('https://', ''),
                            maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 13)),
                      ),
                      SnIconButton(
                        icon: const Icon(Icons.copy_rounded, color: Colors.white, size: 18),
                        onPressed: () {
                          Clipboard.setData(ClipboardData(text: '${tenant['guest_app']}'));
                          toast(context, S.t('Copied'));
                        },
                      ),
                      SnIconButton(
                        icon: const Icon(Icons.share_rounded, color: Colors.white, size: 18),
                        onPressed: () => SharePlus.instance.share(ShareParams(text: '${tenant['guest_app']}')),
                      ),
                    ]),
                  ),
                  Padding(
                    padding: const EdgeInsets.only(top: 6, left: 2),
                    child: Text(S.t('Your guest app link'), style: const TextStyle(color: Colors.white60, fontSize: 11)),
                  ),
                ],
              ]),
            ),
            for (final g in groups)
              if (g.$2.isNotEmpty) ...[
                SectionTitle(g.$1),
                GridView.count(
                  crossAxisCount: 3,
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  mainAxisSpacing: 10,
                  crossAxisSpacing: 10,
                  childAspectRatio: 0.98,
                  padding: EdgeInsets.zero,
                  children: g.$2,
                ),
              ],
            SectionTitle(S.t('Language')),
            SnCard(
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: SnSegmented<String>(
                  segments: const [
                    ButtonSegment(value: 'sw', label: Text('Kiswahili'), icon: Text('🇹🇿')),
                    ButtonSegment(value: 'en', label: Text('English'), icon: Text('🇬🇧')),
                  ],
                  selected: {S.lang},
                  showSelectedIcon: false,
                  onSelectionChanged: (v) => s.setLanguage(v.first),
                ),
              ),
            ),
            SectionTitle(S.t('Appearance')),
            SnCard(
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: SnSegmented<ThemeMode>(
                  segments: [
                    ButtonSegment(value: ThemeMode.light, label: Text(S.t('Light')), icon: const Icon(Icons.light_mode_rounded)),
                    ButtonSegment(value: ThemeMode.dark, label: Text(S.t('Dark')), icon: const Icon(Icons.dark_mode_rounded)),
                  ],
                  selected: {s.themeMode},
                  showSelectedIcon: false,
                  onSelectionChanged: (v) => s.setThemeMode(v.first),
                ),
              ),
            ),
            const PoweredBy(),
          ]),
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile(this.icon, this.label, this.color, this.onTap);
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => SnCard(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  gradient: LinearGradient(colors: [color.withValues(alpha: 0.18), color.withValues(alpha: 0.08)]),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Icon(icon, color: color, size: 26),
              ),
              const SizedBox(height: 8),
              Text(label, textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5, height: 1.15)),
            ]),
          ),
        ),
      );
}

// ---------------------------------------------------------------- payments
class PaymentsScreen extends StatefulWidget {
  const PaymentsScreen({super.key, this.status = ''});
  final String status;

  @override
  State<PaymentsScreen> createState() => _PaymentsScreenState();
}

class _PaymentsScreenState extends State<PaymentsScreen> {
  late String status = widget.status;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: SnAppBar(title: Text(S.t('Payments'))),
      body: Column(children: [
        SizedBox(
          height: 48,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
            for (final f in ['', 'paid', 'pending', 'failed'])
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: SnChip(label: Text(f.isEmpty ? S.t('All') : S.t(f)), selected: status == f, onSelected: (_) => setState(() => status = f)),
              ),
          ]),
        ),
        Expanded(
          child: Loader<Map<String, dynamic>>(
            reloadKey: status,
            load: () => s.api.get('/api/m/payments', {'status': status}),
            builder: (context, d, reload) => RefreshIndicator(
              onRefresh: reload,
              child: (d['items'] as List).isEmpty
                  ? ListView(children: [EmptyView(icon: Icons.receipt_long_outlined, text: S.t('None yet.'))])
                  : ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
                      for (final p in d['items'] as List)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: SnCard(
                            child: SnTile(
                              title: Text('${p['package']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                              subtitle: Text([
                                localPhone(p['phone'] as String?),
                                if (p['name'] != null) p['name'],
                                when(p['created'] as String?),
                                if (p['code'] != null) '#${p['code']}',
                                if (p['site'] != null) p['site'],
                              ].join(' · ')),
                              trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                                Text(money(p['amount'] as num, d['currency'] as String), style: const TextStyle(fontWeight: FontWeight.w700)),
                                const SizedBox(height: 4),
                                Pill(S.t(p['status'] as String), color: stateColor(p['status'] as String)),
                              ]),
                            ),
                          ),
                        ),
                    ]),
            ),
          ),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------------- earnings
class EarningsScreen extends StatelessWidget {
  const EarningsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: SnAppBar(title: Text(S.t('Earnings & withdrawals'))),
      body: Loader<Map<String, dynamic>>(
        load: () => s.api.get('/api/m/earnings'),
        builder: (context, d, reload) {
          final cur = d['currency'] as String;
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
              if (d['platform'] == true)
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    gradient: const LinearGradient(colors: [Color(0xFF0B7A3B), kGood]),
                  ),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(S.t('SafeNet Pay balance'), style: const TextStyle(color: Colors.white70)),
                    const SizedBox(height: 6),
                    Text(money(d['balance'] as num, cur), style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.w800)),
                    if (s.can('withdraw')) ...[
                      const SizedBox(height: 14),
                      SnButton.icon(variant: SnVariant.light, size: SnSize.medium,
                        onPressed: () => openWeb(context, S.t('Withdraw'), '/earnings'),
                        icon: const Icon(Icons.call_made_rounded),
                        label: Text(S.t('Withdraw')),
                      ),
                    ],
                  ]),
                ),
              const SizedBox(height: 12),
              GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 1.35,
                children: [
                  StatTile(icon: Icons.trending_up_rounded, label: S.t('Earned'), value: money(d['earned'] as num, cur), color: kGood),
                  StatTile(icon: Icons.call_made_rounded, label: S.t('Withdrawn'), value: money(d['withdrawn'] as num, cur), color: kAccent),
                  StatTile(icon: Icons.sms_outlined, label: S.t('SMS sent'), value: '${d['sms']['count']}', sub: money(d['sms']['amount'] as num, cur), color: Colors.teal),
                  StatTile(icon: Icons.percent_rounded, label: S.t('Fees'), value: money(d['fees'] as num, cur), sub: '${d['fee_percent']}%', color: kWarn),
                ],
              ),
              SectionTitle(S.t('Withdrawals')),
              SnCard(
                child: (d['withdrawals'] as List).isEmpty
                    ? EmptyView(icon: Icons.account_balance_outlined, text: S.t('None yet.'))
                    : Column(children: [
                        for (final w in d['withdrawals'] as List)
                          SnTile(
                            title: Text(money(w['amount'] as num, cur), style: const TextStyle(fontWeight: FontWeight.w700)),
                            subtitle: Text([when(w['created'] as String?), if (w['phone'] != null) localPhone(w['phone'] as String)].join(' · ')),
                            trailing: Pill('${w['status']}', color: w['status'] == 'paid' ? kGood : (w['status'] == 'failed' ? kBad : kWarn)),
                          ),
                      ]),
              ),
            ]),
          );
        },
      ),
    );
  }
}

