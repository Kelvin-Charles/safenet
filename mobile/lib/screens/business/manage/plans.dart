import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';

/// Speed plans: download / upload limits (and a data cap) that packages and vouchers use.
class PlansScreen extends StatefulWidget {
  const PlansScreen({super.key});

  @override
  State<PlansScreen> createState() => _PlansScreenState();
}

class _PlansScreenState extends State<PlansScreen> {
  int key = 0;

  Future<void> open([Map? plan]) async {
    final saved = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => _PlanForm(plan: plan)));
    if (saved == true) setState(() => key++);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: AppBar(title: Text(S.t('Speed plans'))),
      floatingActionButton: FloatingActionButton.extended(onPressed: open, icon: const Icon(Icons.add_rounded), label: Text(S.t('New plan'))),
      body: Loader<Map<String, dynamic>>(
        reloadKey: key,
        load: () => s.api.get('/api/m/plans'),
        builder: (context, d, reload) => RefreshIndicator(
          onRefresh: reload,
          child: (d['items'] as List).isEmpty
              ? ListView(children: [EmptyView(icon: Icons.speed_rounded, text: S.t('No speed plans. Without one, guests get the full speed.'))])
              : ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 96), children: [
                  for (final p in d['items'] as List)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Card(
                        child: ListTile(
                          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                          onTap: () => open(p as Map),
                          leading: CircleAvatar(
                            backgroundColor: (p['active'] == true ? Colors.orange : Colors.grey).withValues(alpha: 0.14),
                            child: Icon(Icons.speed_rounded, color: p['active'] == true ? Colors.orange : Colors.grey),
                          ),
                          title: Text('${p['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                          subtitle: Text([
                            '↓ ${p['down'] ?? '∞'}',
                            '↑ ${p['up'] ?? '∞'}',
                            if (p['cap_gb'] != null) '${p['cap_gb']} GB / ${S.t(p['cap_period'] as String? ?? 'monthly')}',
                          ].join('   ')),
                          trailing: const Icon(Icons.chevron_right_rounded),
                        ),
                      ),
                    ),
                ]),
        ),
      ),
    );
  }
}

class _PlanForm extends StatefulWidget {
  const _PlanForm({this.plan});
  final Map? plan;

  @override
  State<_PlanForm> createState() => _PlanFormState();
}

class _PlanFormState extends State<_PlanForm> {
  late final p = widget.plan;
  late final name = TextEditingController(text: p?['name'] as String? ?? '');
  late final down = TextEditingController(text: p?['down'] as String? ?? '');
  late final up = TextEditingController(text: p?['up'] as String? ?? '');
  late final cap = TextEditingController(text: p?['cap_gb']?.toString() ?? '');
  late String period = p?['cap_period'] as String? ?? 'monthly';
  late bool active = (p?['active'] as bool?) ?? true;
  bool busy = false;

  Future<void> save() async {
    setState(() => busy = true);
    final api = context.read<Session>().api;
    final body = {'name': name.text, 'down': down.text, 'up': up.text, 'cap_gb': cap.text, 'cap_period': period, 'active': active};
    final r = await attempt(context, () => api.post(p == null ? '/api/m/plans' : '/api/m/plans/${p!['id']}', body));
    if (!mounted) return;
    setState(() => busy = false);
    if (r != null) Navigator.pop(context, true);
  }

  Future<void> delete() async {
    if (!await confirm(context, S.t('Delete this plan? Packages and vouchers using it get the full speed.'), yes: S.t('Delete'), danger: true) || !mounted) return;
    if (await attempt(context, () => context.read<Session>().api.delete('/api/m/plans/${p!['id']}')) != null && mounted) Navigator.pop(context, true);
  }

  Widget _speeds(TextEditingController c) => Wrap(spacing: 6, children: [
        for (final v in ['1M', '2M', '5M', '10M', '20M'])
          ActionChip(label: Text(v), onPressed: () => setState(() => c.text = v), visualDensity: VisualDensity.compact),
      ]);

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(p == null ? S.t('New plan') : S.t('Edit plan'))),
        bottomNavigationBar: SaveBar(busy: busy, onSave: save, onDelete: p != null ? delete : null),
        body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
          FieldGroup(children: [
            TextField(controller: name, decoration: InputDecoration(labelText: S.t('Name'), hintText: S.t('e.g. Student 2 Mbps'), prefixIcon: const Icon(Icons.label_outline))),
          ]),
          FieldGroup(title: S.t('Speed'), children: [
            TextField(controller: down, decoration: InputDecoration(labelText: S.t('Download'), hintText: '5M', prefixIcon: const Icon(Icons.south_rounded, color: kGood))),
            _speeds(down),
            TextField(controller: up, decoration: InputDecoration(labelText: S.t('Upload'), hintText: '2M', prefixIcon: const Icon(Icons.north_rounded, color: kAccent))),
            _speeds(up),
            Text(S.t('M = megabits a second, k = kilobits. Empty = no limit.'), style: Theme.of(context).textTheme.bodySmall),
          ]),
          FieldGroup(title: S.t('Data cap'), children: [
            TextField(controller: cap, keyboardType: TextInputType.number,
                decoration: InputDecoration(labelText: 'GB (${S.t('optional')})', prefixIcon: const Icon(Icons.data_usage_rounded))),
            SegmentedButton<String>(
              segments: [
                ButtonSegment(value: 'daily', label: Text(S.t('daily'))),
                ButtonSegment(value: 'weekly', label: Text(S.t('weekly'))),
                ButtonSegment(value: 'monthly', label: Text(S.t('monthly'))),
              ],
              selected: {period},
              showSelectedIcon: false,
              onSelectionChanged: (v) => setState(() => period = v.first),
            ),
          ]),
          FieldGroup(children: [SwitchRow(title: S.t('On'), value: active, onChanged: (v) => setState(() => active = v))]),
        ]),
      );
}
