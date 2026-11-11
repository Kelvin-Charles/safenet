import 'dart:typed_data';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/kit.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';
import 'expenses.dart';

/// The financial report for a period: income statement, payback, sites, packages; shared or opened as a PDF.
class FinanceReportScreen extends StatefulWidget {
  const FinanceReportScreen({super.key});

  @override
  State<FinanceReportScreen> createState() => _FinanceReportScreenState();
}

class _FinanceReportScreenState extends State<FinanceReportScreen> {
  String period = 'this_month';
  String? from, to;
  bool sharing = false;

  Map<String, dynamic> get query => {'period': period, if (period == 'custom') 'from': from, if (period == 'custom') 'to': to};

  Future<String?> pickMonth(String? current, String title) async {
    final now = DateTime.now();
    final init = current != null ? DateTime.parse('$current-01') : now;
    final v = await showDatePicker(context: context, initialDate: init, firstDate: DateTime(2015), lastDate: now,
        initialDatePickerMode: DatePickerMode.year, helpText: title);
    return v == null ? null : DateFormat('yyyy-MM').format(v);
  }

  Future<void> choosePeriod(List periods) async {
    final picked = await showSnSheet<String>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final p in periods)
            SnTile(
              title: Text('${p['name']}'),
              trailing: p['id'] == period ? const Icon(Icons.check_circle_rounded, color: kAccent) : null,
              onTap: () => Navigator.pop(c, p['id'] as String),
            ),
        ]),
      ),
    );
    if (picked == null || !mounted) return;
    if (picked == 'custom') {
      final a = await pickMonth(from, S.t('From'));
      if (a == null || !mounted) return;
      final b = await pickMonth(to ?? a, S.t('To'));
      if (b == null) return;
      setState(() {
        period = 'custom';
        from = a;
        to = b;
      });
    } else {
      setState(() => period = picked);
    }
  }

  Future<void> sharePdf(Map d) async {
    setState(() => sharing = true);
    final s = context.read<Session>();
    final bytes = await attempt(context, () => s.api.getBytes('/api/m/reports/finance.pdf', query));
    if (!mounted) return;
    setState(() => sharing = false);
    if (bytes == null) return;
    final name = 'financial-report-${'${d['business']}'.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '-')}-${d['start']}'
        '${d['end'] != d['start'] ? '-${d['end']}' : ''}.pdf';
    await SharePlus.instance.share(ShareParams(
      files: [XFile.fromData(Uint8List.fromList(bytes), mimeType: 'application/pdf', name: name)],
      fileNameOverrides: [name],
      subject: '${S.t('Financial report')} · ${d['business']} · ${d['title']}',
    ));
  }

  Future<void> openPdf() async {
    final s = context.read<Session>();
    final q = Uri(queryParameters: {...query.map((k, v) => MapEntry(k, '$v')), 'view': '1'}).query;
    final r = await attempt(context, () => s.api.post('/api/m/web-link', {'path': '/reports/finance.pdf?$q'}));
    if (r == null) return;
    await launchUrl(Uri.parse(r['url'] as String), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Loader<Map<String, dynamic>>(
      reloadKey: '$period/$from/$to/${s.api.siteId}',
      load: () => s.api.get('/api/m/reports/finance', query),
      builder: (context, d, reload) {
        final cur = d['currency'] as String;
        final t = d['totals'] as Map;
        final net = (t['net'] as num).toDouble();
        final months = d['months'] as List;
        final periodName = (d['periods'] as List).firstWhere((p) => p['id'] == d['period'], orElse: () => {'name': ''})['name'];
        return Scaffold(
          appBar: SnAppBar(title: Text(S.t('Financial report'))),
          bottomNavigationBar: SafeArea(
            top: false,
            child: Container(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surface,
                border: Border(top: BorderSide(color: Sn.line(context))),
              ),
              child: Row(children: [
                SnIconButton(tinted: true, size: 52, tooltip: S.t('Open PDF'), onPressed: openPdf, icon: const Icon(Icons.open_in_new_rounded)),
                const SizedBox(width: 10),
                Expanded(
                  child: SnButton.icon(
                    onPressed: sharing ? null : () => sharePdf(d),
                    icon: sharing ? const SizedBox(width: 20, height: 20, child: SnSpinner(strokeWidth: 2.5)) : const Icon(Icons.picture_as_pdf_rounded),
                    label: Text(S.t('Share or save PDF')),
                  ),
                ),
              ]),
            ),
          ),
          body: RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
              // the report's cover: business, period, site
              SnPressable(
                onTap: () => choosePeriod(d['periods'] as List),
                child: Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(borderRadius: BorderRadius.circular(22), gradient: Sn.gradient),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(S.t('Financial report').toUpperCase(), style: const TextStyle(color: Colors.white70, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w700)),
                        const SizedBox(height: 4),
                        Text('${d['business']}', style: const TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.w800)),
                        const SizedBox(height: 2),
                        Text([if (d['site'] != null) d['site'], d['title']].join(' · '), style: const TextStyle(color: Colors.white)),
                      ]),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                      decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(12)),
                      child: Row(mainAxisSize: MainAxisSize.min, children: [
                        const Icon(Icons.date_range_rounded, color: Colors.white, size: 18),
                        const SizedBox(width: 6),
                        Text('$periodName', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 12.5)),
                      ]),
                    ),
                  ]),
                ),
              ),
              const SizedBox(height: 12),
              GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 1.08,
                children: [
                  StatTile(icon: Icons.south_west_rounded, label: S.t('Money in'), value: money(t['sales'] as num, cur), color: kGood,
                      sub: _change(d, 'sales', true), subColor: _tone(context, d, 'sales', true)),
                  StatTile(icon: Icons.north_east_rounded, label: S.t('Money out'), value: money(t['out'] as num, cur), color: kBad,
                      sub: _change(d, 'out', false), subColor: _tone(context, d, 'out', false)),
                  StatTile(icon: net >= 0 ? Icons.trending_up_rounded : Icons.trending_down_rounded,
                      label: net >= 0 ? S.t('Net profit') : S.t('Net loss'), value: money(net, cur), color: net >= 0 ? kGood : kBad,
                      sub: _change(d, 'net', true), subColor: _tone(context, d, 'net', true)),
                  StatTile(icon: Icons.percent_rounded, label: S.t('Profit margin'), value: t['margin'] != null ? '${t['margin']}%' : '-',
                      color: kAccent),
                ],
              ),
              if (months.length > 1) ...[
                SectionTitle(S.t('Money in and out by month ({currency})', {'currency': cur})),
                SnCard(child: Padding(padding: const EdgeInsets.fromLTRB(8, 16, 14, 8), child: SizedBox(height: 200, child: _InOutChart(months: months)))),
              ],
              SectionTitle(S.t('Income statement')),
              _Statement(d: d),
              SectionTitle(S.t('Investment and payback')),
              PaybackCard(p: d['payback'] as Map, currency: cur),
              if ((d['sites'] as List).isNotEmpty) ...[
                SectionTitle(S.t('Sites compared')),
                SnCard(
                  child: Column(children: [
                    for (final x in d['sites'] as List)
                      SnTile(
                        dense: true,
                        title: Text('${x['name']}', style: TextStyle(fontWeight: FontWeight.w600, color: x['other'] == true ? Sn.muted(context) : null)),
                        subtitle: Text('${S.t('Money in')} ${compactMoney(x['sales'] as num)} · ${S.t('Money out')} ${compactMoney(x['out'] as num)}'),
                        trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                          Text(money(x['net'] as num, cur), style: TextStyle(fontWeight: FontWeight.w700, color: (x['net'] as num) >= 0 ? kGood : kBad)),
                          if (x['margin'] != null) Text('${x['margin']}%', style: TextStyle(fontSize: 11, color: Sn.muted(context))),
                        ]),
                      ),
                  ]),
                ),
              ],
              if ((d['packages'] as List).isNotEmpty) ...[
                SectionTitle(S.t('Sales by package')),
                SnCard(
                  child: Column(children: [
                    for (final p in d['packages'] as List)
                      SnTile(
                        dense: true,
                        title: Text('${p['name']}'),
                        subtitle: Text(S.t('{n} sold', {'n': p['count']})),
                        trailing: Text(money(p['amount'] as num, cur), style: const TextStyle(fontWeight: FontWeight.w700)),
                      ),
                  ]),
                ),
              ],
              SectionTitle(S.t('Expense details')),
              SnCard(
                child: (d['items'] as List).isEmpty
                    ? EmptyView(icon: Icons.receipt_long_outlined, text: S.t('No expenses in this period.'))
                    : Column(children: [for (final e in d['items'] as List) ExpenseTile(e: e as Map, currency: cur)]),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 14, 4, 0),
                child: Text(
                    S.t('Money in is what customers paid: mobile-money payments when they were paid, and cash vouchers when they were first used. Money out is the expenses recorded in SafeNet plus what SafeNet charged (payment fees, SMS and the SafeNet plan). Payback counts everything from the first month.'),
                    style: TextStyle(fontSize: 11.5, color: Sn.muted(context))),
              ),
            ]),
          ),
        );
      },
    );
  }

  /// Green when the change is good (more money in, less out), red when bad.
  static Color _tone(BuildContext c, Map d, String key, bool goodUp) {
    final v = (d['compare'] as Map)[key] as num?;
    if (v == null || v == 0) return Sn.muted(c);
    return (v > 0) == goodUp ? kGood : kBad;
  }

  static String? _change(Map d, String key, bool goodUp) {
    final c = (d['compare'] as Map)[key];
    if (c == null) return null;
    return '${(c as num) > 0 ? '+' : ''}$c% ${S.t('vs the period before')}';
  }
}

class _Statement extends StatelessWidget {
  const _Statement({required this.d});
  final Map d;

  @override
  Widget build(BuildContext context) {
    final t = d['totals'] as Map;
    final cur = d['currency'] as String;
    final net = (t['net'] as num).toDouble();
    Widget section(String text) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
          child: Text(text, style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12, letterSpacing: 0.8, color: Sn.brand(context))),
        );
    Widget line(String k, num v, {bool total = false}) => Container(
          padding: EdgeInsets.fromLTRB(total ? 16 : 28, 6, 16, 6),
          decoration: total ? BoxDecoration(border: Border(top: BorderSide(color: Sn.ink(context), width: 1.2))) : null,
          child: Row(children: [
            Expanded(child: Text(k, style: TextStyle(fontWeight: total ? FontWeight.w800 : FontWeight.w400))),
            Text(NumberFormat.decimalPattern('en').format(v.round()), style: TextStyle(fontWeight: total ? FontWeight.w800 : FontWeight.w500)),
          ]),
        );
    return SnCard(
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Text(S.t('Amounts in {currency}', {'currency': cur}), style: TextStyle(fontSize: 12, color: Sn.muted(context))),
        ),
        section(S.t('INCOME')),
        line(S.t('Mobile-money sales'), t['online'] as num),
        line(S.t('Cash vouchers'), t['cash'] as num),
        line(S.t('Total income'), t['sales'] as num, total: true),
        section(S.t('EXPENSES')),
        for (final c in d['by_category'] as List) line('${c['name']}', c['amount'] as num),
        if ((t['fees'] as num) > 0) line(S.t('SafeNet payment fees'), t['fees'] as num),
        if ((t['sms'] as num) > 0) line(S.t('SMS to customers'), t['sms'] as num),
        if ((t['plan'] as num) > 0) line(S.t('SafeNet plan'), t['plan'] as num),
        if ((d['by_category'] as List).isEmpty && (t['safenet'] as num) == 0) line(S.t('No expenses recorded'), 0),
        line(S.t('Total expenses'), t['out'] as num, total: true),
        const SizedBox(height: 8),
        Container(
          color: net >= 0 ? kGood : kBad,
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Row(children: [
            Expanded(child: Text(net >= 0 ? S.t('NET PROFIT') : S.t('NET LOSS'), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 16))),
            Text(money(net, cur), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 16)),
          ]),
        ),
      ]),
    );
  }
}

class _InOutChart extends StatelessWidget {
  const _InOutChart({required this.months});
  final List months;

  @override
  Widget build(BuildContext context) {
    final rows = months.length > 12 ? months.sublist(months.length - 12) : months;
    final c = Theme.of(context).colorScheme;
    var top = 1.0;
    for (final m in rows) {
      for (final k in ['sales', 'out']) {
        final v = (m[k] as num).toDouble();
        if (v > top) top = v;
      }
    }
    final w = rows.length > 8 ? 6.0 : 10.0;
    return BarChart(BarChartData(
      maxY: top * 1.15,
      gridData: FlGridData(show: true, drawVerticalLine: false,
          getDrawingHorizontalLine: (_) => FlLine(color: c.outlineVariant.withValues(alpha: 0.4), strokeWidth: 1)),
      borderData: FlBorderData(show: false),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(),
        rightTitles: const AxisTitles(),
        leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 40,
            getTitlesWidget: (v, m) => v == m.max ? const SizedBox.shrink() : Text(compactMoney(v), style: TextStyle(fontSize: 10, color: c.outline)))),
        bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, getTitlesWidget: (v, m) {
          final k = '${rows[v.toInt()]['month']}';
          return Padding(padding: const EdgeInsets.only(top: 6), child: Text('${k.substring(5)}/${k.substring(2, 4)}', style: TextStyle(fontSize: 9.5, color: c.outline)));
        })),
      ),
      barTouchData: BarTouchData(
        touchTooltipData: BarTouchTooltipData(
          getTooltipItem: (g, _, rod, i) => BarTooltipItem(
              '${rows[g.x]['label']}\n${i == 0 ? S.t('Money in') : S.t('Money out')}: ${compactMoney(rod.toY)}',
              const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 12)),
        ),
      ),
      barGroups: [
        for (var i = 0; i < rows.length; i++)
          BarChartGroupData(x: i, barsSpace: 3, barRods: [
            BarChartRodData(toY: (rows[i]['sales'] as num).toDouble(), width: w, color: kGood, borderRadius: const BorderRadius.vertical(top: Radius.circular(4))),
            BarChartRodData(toY: (rows[i]['out'] as num).toDouble(), width: w, color: kBad, borderRadius: const BorderRadius.vertical(top: Radius.circular(4))),
          ]),
      ],
    ));
  }
}
