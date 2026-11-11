import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/kit.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';
import 'finance_report.dart';

/// What the business spent on its sites, against what they earned (the web Expenses page).
class ExpensesScreen extends StatefulWidget {
  const ExpensesScreen({super.key});

  @override
  State<ExpensesScreen> createState() => _ExpensesScreenState();
}

class _ExpensesScreenState extends State<ExpensesScreen> {
  String period = 'all';
  int key = 0;

  static Map<String, String> get periods => {
        'all': S.t('All time'),
        '12m': S.t('Last 12 months'),
        'year': S.t('This year'),
        'month': S.t('This month'),
        'last_month': S.t('Last month'),
      };

  Future<void> open(Map<String, dynamic> d, [Map? e]) async {
    final saved = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => ExpenseForm(data: d, expense: e)));
    if (saved == true) setState(() => key++);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Loader<Map<String, dynamic>>(
      reloadKey: '$period/$key/${s.api.siteId}',
      load: () => s.api.get('/api/m/expenses', {'period': period}),
      builder: (context, d, reload) {
        final cur = d['currency'] as String;
        final t = d['totals'] as Map;
        final net = (t['net'] as num).toDouble();
        final items = d['items'] as List;
        final cats = d['by_category'] as List;
        final top = cats.isEmpty ? 1.0 : (cats.first['amount'] as num).toDouble();
        return Scaffold(
          appBar: SnAppBar(title: Text(S.t('Expenses')), actions: [
            SnIconButton(
              icon: const Icon(Icons.picture_as_pdf_rounded),
              tooltip: S.t('Financial report'),
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const FinanceReportScreen())),
            ),
          ]),
          floatingActionButton: d['can_edit'] == true
              ? SnFab(onPressed: () => open(d), icon: const Icon(Icons.add_rounded), label: Text(S.t('Add an expense')))
              : null,
          body: RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 96), children: [
              if (d['site'] != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8, left: 4),
                  child: Text(S.t('Site: {site}', {'site': d['site']}), style: TextStyle(color: Sn.muted(context))),
                ),
              SizedBox(
                height: 44,
                child: ListView(scrollDirection: Axis.horizontal, children: [
                  for (final p in periods.entries)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: SnChip(label: Text(p.value), selected: period == p.key, onSelected: (_) => setState(() => period = p.key)),
                    ),
                ]),
              ),
              const SizedBox(height: 8),
              GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 1.2,
                children: [
                  StatTile(icon: Icons.south_west_rounded, label: S.t('Money in'), value: money(t['sales'] as num, cur), color: kGood),
                  StatTile(icon: Icons.receipt_long_rounded, label: S.t('Your expenses'), value: money(t['spent'] as num, cur), color: kBad),
                  StatTile(icon: Icons.percent_rounded, label: S.t('SafeNet fees, SMS and plan'), value: money(t['safenet'] as num, cur), color: kWarn),
                  StatTile(icon: net >= 0 ? Icons.trending_up_rounded : Icons.trending_down_rounded,
                      label: net >= 0 ? S.t('Profit') : S.t('Loss'), value: money(net, cur), color: net >= 0 ? kGood : kBad),
                ],
              ),
              SectionTitle(S.t('Has it paid back?')),
              PaybackCard(p: d['payback'] as Map, currency: cur, shared: d['shared'] as num?),
              if (cats.isNotEmpty) ...[
                SectionTitle(S.t('Where the money went')),
                SnCard(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(children: [
                      for (final c in cats)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                            Row(children: [
                              Expanded(child: Text('${c['name']}', style: const TextStyle(fontSize: 13))),
                              Text(money(c['amount'] as num, cur), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
                            ]),
                            const SizedBox(height: 5),
                            SnProgressBar(value: top > 0 ? (c['amount'] as num) / top : 0, color: kBad, minHeight: 6),
                          ]),
                        ),
                    ]),
                  ),
                ),
              ],
              if ((d['months'] as List).isNotEmpty) ...[
                SectionTitle(S.t('Month by month')),
                SnCard(
                  child: Column(children: [
                    for (final m in (d['months'] as List).reversed)
                      SnTile(
                        dense: true,
                        title: Text('${m['label']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                        subtitle: Text('${S.t('Money in')} ${compactMoney(m['sales'] as num)} · ${S.t('Money out')} ${compactMoney(m['out'] as num)}'),
                        trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                          Text(money(m['net'] as num, cur),
                              style: TextStyle(fontWeight: FontWeight.w700, color: (m['net'] as num) >= 0 ? kGood : kBad)),
                          Text('${S.t('Total so far')}: ${compactMoney(m['running'] as num)}', style: TextStyle(fontSize: 11, color: Sn.muted(context))),
                        ]),
                      ),
                  ]),
                ),
              ],
              SectionTitle('${S.t('Expenses')} (${items.length})'),
              SnCard(
                child: items.isEmpty
                    ? EmptyView(icon: Icons.receipt_long_outlined, text: S.t('No expenses in this period.'))
                    : Column(children: [for (final e in items) ExpenseTile(e: e as Map, currency: cur, onTap: d['can_edit'] == true ? () => open(d, e) : null)]),
              ),
            ]),
          ),
        );
      },
    );
  }
}

class ExpenseTile extends StatelessWidget {
  const ExpenseTile({super.key, required this.e, required this.currency, this.onTap});
  final Map e;
  final String currency;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => SnTile(
        onTap: onTap,
        leading: CircleAvatar(
          backgroundColor: kBad.withValues(alpha: 0.12),
          child: Icon(_icon(e['category'] as String?), color: kBad, size: 20),
        ),
        title: Text('${e['description']}', style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text([
          DateFormat('d MMM yyyy').format(DateTime.parse(e['date'] as String)),
          e['category_name'],
          if (e['site'] != null) e['site'] else S.t('Whole business'),
          if (e['paid_to'] != null) S.t('to {name}', {'name': e['paid_to']}),
        ].join(' · ')),
        trailing: Text(money(e['amount'] as num, currency), style: const TextStyle(fontWeight: FontWeight.w700)),
      );

  static IconData _icon(String? c) => switch (c) {
        'equipment' => Icons.router_rounded,
        'installation' => Icons.construction_rounded,
        'materials' => Icons.cable_rounded,
        'printing' => Icons.print_rounded,
        'internet' => Icons.public_rounded,
        'power' => Icons.bolt_rounded,
        'rent' => Icons.home_work_rounded,
        'transport' => Icons.local_shipping_rounded,
        'repairs' => Icons.build_rounded,
        'salaries' => Icons.badge_rounded,
        'marketing' => Icons.campaign_rounded,
        _ => Icons.receipt_rounded,
      };
}

/// How much of what went in has come back (all time).
class PaybackCard extends StatelessWidget {
  const PaybackCard({super.key, required this.p, required this.currency, this.shared});
  final Map p;
  final String currency;
  final num? shared;

  @override
  Widget build(BuildContext context) {
    final out = (p['out'] as num).toDouble(), inn = (p['in'] as num).toDouble(), net = (p['net'] as num).toDouble();
    final pct = (p['percent'] as num).toInt();
    return SnCard(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (out == 0 && inn == 0)
            Text(S.t('Record what you spent to set up this site (equipment, installation, posters...) and SafeNet shows when the sales have paid it back.'),
                style: TextStyle(color: Sn.muted(context)))
          else ...[
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('$pct%', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w900, color: pct >= 100 ? kGood : Sn.brand(context))),
              const SizedBox(width: 8),
              Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(S.t('paid back (all time)'), style: TextStyle(color: Sn.muted(context)))),
            ]),
            const SizedBox(height: 8),
            SnProgressBar(value: pct / 100, color: pct >= 100 ? kGood : kAccent, minHeight: 10),
            const SizedBox(height: 12),
            _row(context, S.t('Invested (your expenses)'), money(p['invested'] as num, currency)),
            _row(context, S.t('All money out'), money(out, currency)),
            _row(context, S.t('All money in'), money(inn, currency)),
            const Divider(height: 16),
            _row(context, net >= 0 ? S.t('Profit so far') : S.t('Still to earn back'), money(net.abs(), currency), bold: true,
                color: net >= 0 ? kGood : kBad),
            if (net >= 0 && out > 0 && p['month'] != null)
              Padding(padding: const EdgeInsets.only(top: 8), child: Text(S.t('Paid back in {month}.', {'month': p['month']}), style: TextStyle(color: Sn.muted(context), fontSize: 12))),
            if (net < 0 && p['months_left'] != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(S.t("At the last three months' pace, about {n} more months.", {'n': p['months_left']}),
                    style: TextStyle(color: Sn.muted(context), fontSize: 12)),
              ),
          ],
          if (shared != null && shared! > 0)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(S.t('{amount} of costs shared by all sites are not counted here; see All sites.', {'amount': money(shared, currency)}),
                  style: TextStyle(color: Sn.muted(context), fontSize: 12)),
            ),
        ]),
      ),
    );
  }

  Widget _row(BuildContext c, String k, String v, {bool bold = false, Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(child: Text(k, style: TextStyle(fontWeight: bold ? FontWeight.w700 : FontWeight.w400))),
          Text(v, style: TextStyle(fontWeight: bold ? FontWeight.w800 : FontWeight.w600, color: color)),
        ]),
      );
}

class ExpenseForm extends StatefulWidget {
  const ExpenseForm({super.key, required this.data, this.expense});
  final Map<String, dynamic> data;
  final Map? expense;

  @override
  State<ExpenseForm> createState() => _ExpenseFormState();
}

class _ExpenseFormState extends State<ExpenseForm> {
  late final e = widget.expense;
  late final amount = TextEditingController(text: e == null ? '' : NumberFormat('#,###', 'en').format((e!['amount'] as num).round()));
  late final description = TextEditingController(text: e?['description'] as String? ?? '');
  late final paidTo = TextEditingController(text: e?['paid_to'] as String? ?? '');
  late DateTime date = e != null ? DateTime.parse(e!['date'] as String) : DateTime.now();
  late String category = e?['category'] as String? ?? 'equipment';
  late int? siteId = e != null ? e!['site_id'] as int? : _defaultSite();
  bool busy = false;

  int? _defaultSite() {
    final sites = widget.data['sites'] as List;
    final picked = context.read<Session>().api.siteId;
    if (picked != null) return picked;
    return sites.length == 1 ? sites.first['id'] as int : null;
  }

  Future<void> save({bool again = false}) async {
    setState(() => busy = true);
    final api = context.read<Session>().api;
    final body = {
      'amount': amount.text.replaceAll(',', '').trim(), 'date': DateFormat('yyyy-MM-dd').format(date), 'description': description.text,
      'category': category, 'site_id': siteId, 'paid_to': paidTo.text,
    };
    final r = await attempt(context, () => api.post(e == null ? '/api/m/expenses' : '/api/m/expenses/${e!['id']}', body));
    if (!mounted) return;
    setState(() => busy = false);
    if (r == null) return;
    toast(context, S.t('Expense saved: {amount}.', {'amount': money(r['amount'] as num, widget.data['currency'] as String)}));
    if (again) {
      setState(() {
        amount.clear();
        description.clear();
        paidTo.clear();
      });
      return;
    }
    Navigator.pop(context, true);
  }

  Future<void> delete() async {
    if (!await confirm(context, S.t('Delete this expense?'), yes: S.t('Delete'), danger: true) || !mounted) return;
    if (await attempt(context, () => context.read<Session>().api.delete('/api/m/expenses/${e!['id']}')) != null && mounted) {
      Navigator.pop(context, true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.data;
    final cats = d['categories'] as List;
    final sites = d['sites'] as List;
    return Scaffold(
      appBar: SnAppBar(title: Text(e == null ? S.t('Add an expense') : S.t('Change an expense'))),
      bottomNavigationBar: SaveBar(busy: busy, onSave: () => save(), onDelete: e != null ? delete : null),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
        FieldGroup(title: S.t('Expense'), children: [
          SnField(
            controller: amount,
            autofocus: e == null,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(labelText: '${S.t('Amount paid')} (${d['currency']})', prefixIcon: const Icon(Icons.payments_outlined)),
          ),
          SnField(
            controller: description,
            textCapitalization: TextCapitalization.sentences,
            decoration: InputDecoration(labelText: S.t('What was it for?'), hintText: S.t('e.g. 2 access points, 50 posters, installation'),
                prefixIcon: const Icon(Icons.edit_note_rounded)),
          ),
          SnSelect<String>(
            label: S.t('Category'),
            icon: Icons.category_outlined,
            value: category,
            items: {for (final c in cats) c['id'] as String: '${c['name']}'},
            onChanged: (v) => setState(() => category = v),
          ),
          SnTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.event_rounded),
            title: Text(S.t('Date paid')),
            subtitle: Text(DateFormat('d MMMM yyyy').format(date)),
            onTap: () async {
              final now = DateTime.now();
              final v = await showDatePicker(context: context, initialDate: date, firstDate: DateTime(2015), lastDate: now);
              if (v != null) setState(() => date = v);
            },
          ),
        ]),
        FieldGroup(title: S.t('Where and who'), children: [
          PickField(label: S.t('Site'), icon: Icons.place_outlined, items: sites, value: siteId, none: S.t('Whole business (shared by all sites)'),
              onChanged: (v) => setState(() => siteId = v)),
          SnField(
            controller: paidTo,
            textCapitalization: TextCapitalization.words,
            decoration: InputDecoration(labelText: '${S.t('Paid to')} (${S.t('optional')})', hintText: S.t('Shop, technician or printer'),
                prefixIcon: const Icon(Icons.storefront_outlined)),
          ),
        ]),
        if (e == null)
          SnButton.icon(
            variant: SnVariant.secondary,
            onPressed: busy ? null : () => save(again: true),
            icon: const Icon(Icons.add_rounded),
            label: Text(S.t('Save and add another')),
          ),
      ]),
    );
  }
}
