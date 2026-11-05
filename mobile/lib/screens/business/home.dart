import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import 'more.dart';
import 'shell.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.onTab});
  final void Function(int) onTab;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: AppBar(
        title: Text((s.me?['tenant']?['name'] as String?) ?? 'SafeNet'),
        actions: const [SiteButton()],
      ),
      body: Loader<Map<String, dynamic>>(
        reloadKey: s.api.siteId,
        load: () => s.api.get('/api/m/dashboard'),
        builder: (context, d, reload) => RefreshIndicator(
          onRefresh: reload,
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
            _Hero(d: d, currency: s.currency),
            const SizedBox(height: 12),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.45,
              children: [
                StatTile(icon: Icons.sensors_rounded, label: S.t('Online now'), value: '${d['online']}', color: kGood, onTap: () => onTab(1)),
                StatTile(icon: Icons.swap_vert_rounded, label: S.t('Data today'),
                    value: bytes((d['down_today'] as num) + (d['up_today'] as num)), color: kAccent),
                StatTile(icon: Icons.confirmation_number_outlined, label: S.t('Unused codes'), value: '${d['codes']['unused']}',
                    color: Colors.indigo, onTap: () => onTab(2)),
                StatTile(icon: Icons.timelapse_rounded, label: S.t('Codes in use'), value: '${d['codes']['active']}', color: kWarn,
                    onTap: () => onTab(2)),
              ],
            ),
            if ((d['pending_payments'] as int? ?? 0) > 0)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Card(
                  color: kWarn.withValues(alpha: 0.12),
                  child: ListTile(
                    leading: const Icon(Icons.hourglass_top_rounded, color: kWarn),
                    title: Text(S.t('{n} payments still pending', {'n': d['pending_payments']})),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const PaymentsScreen(status: 'pending'))),
                  ),
                ),
              ),
            SectionTitle(S.t('Last 7 days'), trailing: Text(money(_sum(d['week']), s.currency), style: const TextStyle(fontWeight: FontWeight.w600))),
            Card(child: Padding(padding: const EdgeInsets.fromLTRB(8, 20, 16, 8), child: SizedBox(height: 180, child: _WeekChart(week: d['week'] as List)))),
            if ((d['sites'] as List).length > 1) ...[
              SectionTitle(S.t('Sites this month')),
              Card(
                child: Column(children: [
                  for (final site in d['sites'] as List)
                    ListTile(
                      dense: true,
                      leading: const Icon(Icons.place_outlined),
                      title: Text(site['name'] as String),
                      trailing: Text(money(site['month'] as num, s.currency), style: const TextStyle(fontWeight: FontWeight.w600)),
                      onTap: () => s.pickSite(site['id'] as int),
                    ),
                ]),
              ),
            ],
            SectionTitle(S.t('Recent sales'),
                trailing: TextButton(
                    onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const PaymentsScreen())),
                    child: Text(S.t('Payments')))),
            Card(
              child: (d['recent'] as List).isEmpty
                  ? EmptyView(icon: Icons.receipt_long_outlined, text: S.t('No sales yet.'))
                  : Column(children: [
                      for (final p in d['recent'] as List)
                        ListTile(
                          leading: CircleAvatar(backgroundColor: kGood.withValues(alpha: 0.12), child: const Icon(Icons.south_west_rounded, color: kGood, size: 20)),
                          title: Text('${p['package']}', maxLines: 1, overflow: TextOverflow.ellipsis),
                          subtitle: Text('${localPhone(p['phone'] as String?)} · ${ago(p['at'] as String?)}${p['site'] != null ? ' · ${p['site']}' : ''}',
                              maxLines: 1, overflow: TextOverflow.ellipsis),
                          trailing: Text(money(p['amount'] as num, s.currency), style: const TextStyle(fontWeight: FontWeight.w700)),
                        ),
                    ]),
            ),
          ]),
        ),
      ),
    );
  }

  static num _sum(dynamic week) => (week as List).fold<num>(0, (a, x) => a + (x['total'] as num));
}

class _Hero extends StatelessWidget {
  const _Hero({required this.d, required this.currency});
  final Map<String, dynamic> d;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: const LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)], begin: Alignment.topLeft, end: Alignment.bottomRight),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${d['greeting']} 👋', style: t.bodyMedium?.copyWith(color: Colors.white70)),
        const SizedBox(height: 14),
        Text(S.t('Today'), style: t.labelLarge?.copyWith(color: Colors.white70)),
        Text(money(d['today']['total'] as num, currency), style: t.headlineMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
        Text('${d['today']['sales']} ${S.t('sales')} · ${S.t('Online')} ${compactMoney(d['today']['online'] as num)} · ${S.t('Cash vouchers')} ${compactMoney(d['today']['cash'] as num)}',
            style: t.bodySmall?.copyWith(color: Colors.white70)),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: _HeroFigure(label: S.t('This month'), value: money(d['month']['total'] as num, currency))),
          if (d['balance'] != null) Expanded(child: _HeroFigure(label: S.t('SafeNet Pay balance'), value: money(d['balance'] as num, currency))),
        ]),
      ]),
    );
  }
}

class _HeroFigure extends StatelessWidget {
  const _HeroFigure({required this.label, required this.value});
  final String label, value;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(right: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(14)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(color: Colors.white70, fontSize: 12)),
          const SizedBox(height: 4),
          FittedBox(child: Text(value, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 16))),
        ]),
      );
}

class _WeekChart extends StatelessWidget {
  const _WeekChart({required this.week});
  final List week;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final values = [for (final d in week) (d['total'] as num).toDouble()];
    final top = values.fold<double>(0, (a, b) => b > a ? b : a);
    return BarChart(BarChartData(
      maxY: top <= 0 ? 1 : top * 1.2,
      gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          getDrawingHorizontalLine: (_) => FlLine(color: c.outlineVariant.withValues(alpha: 0.4), strokeWidth: 1)),
      borderData: FlBorderData(show: false),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(),
        rightTitles: const AxisTitles(),
        leftTitles: AxisTitles(
            sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 40,
                getTitlesWidget: (v, m) => v == m.max ? const SizedBox.shrink() : Text(compactMoney(v), style: TextStyle(fontSize: 10, color: c.outline)))),
        bottomTitles: AxisTitles(
            sideTitles: SideTitles(
                showTitles: true,
                getTitlesWidget: (v, m) => Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text('${week[v.toInt()]['label']}', style: TextStyle(fontSize: 11, color: c.outline))))),
      ),
      barTouchData: BarTouchData(
        touchTooltipData: BarTouchTooltipData(
          getTooltipItem: (g, _, rod, _) =>
              BarTooltipItem('${week[g.x]['date']}\n${compactMoney(rod.toY)}', const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
        ),
      ),
      barGroups: [
        for (var i = 0; i < values.length; i++)
          BarChartGroupData(x: i, barRods: [
            BarChartRodData(
              toY: values[i],
              width: 18,
              color: i == values.length - 1 ? kAccent : c.primary.withValues(alpha: 0.75),
              borderRadius: const BorderRadius.vertical(top: Radius.circular(6)),
            ),
          ]),
      ],
    ));
  }
}
