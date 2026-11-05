import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';

class PackagesScreen extends StatefulWidget {
  const PackagesScreen({super.key});

  @override
  State<PackagesScreen> createState() => _PackagesScreenState();
}

class _PackagesScreenState extends State<PackagesScreen> {
  int key = 0;

  Future<void> open([int? id]) async {
    final saved = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => PackageForm(id: id)));
    if (saved == true) setState(() => key++);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: AppBar(title: Text(S.t('Packages'))),
      floatingActionButton: FloatingActionButton.extended(onPressed: open, icon: const Icon(Icons.add_rounded), label: Text(S.t('New package'))),
      body: Loader<Map<String, dynamic>>(
        reloadKey: key,
        load: () => s.api.get('/api/m/packages'),
        builder: (context, d, reload) => RefreshIndicator(
          onRefresh: reload,
          child: (d['items'] as List).isEmpty
              ? ListView(children: [EmptyView(icon: Icons.inventory_2_outlined, text: S.t('No packages yet. Add the first one guests can buy.'))])
              : ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 96), children: [
                  for (final p in d['items'] as List)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Card(
                        clipBehavior: Clip.antiAlias,
                        child: InkWell(
                          onTap: () => open(p['id'] as int),
                          child: Padding(
                            padding: const EdgeInsets.fromLTRB(16, 14, 8, 6),
                            child: Column(children: [
                              Row(children: [
                                Container(
                                  width: 48,
                                  height: 48,
                                  decoration: BoxDecoration(
                                    gradient: LinearGradient(colors: p['active'] == true ? [kNavy, const Color(0xFF0A3AA8)] : [Colors.grey, Colors.blueGrey]),
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                  child: Center(
                                    child: Text(minutesLabel(p['minutes'] as int).split(' ').take(2).join('\n'),
                                        textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w800, height: 1.1)),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                    Text('${p['name']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                                    Text([minutesLabel(p['minutes'] as int), '${p['devices']} ${S.t('devices')}', p['site'] ?? S.t('All sites')].join(' · '),
                                        style: Theme.of(context).textTheme.bodySmall),
                                  ]),
                                ),
                                Text(money(p['price'] as num, d['currency'] as String), style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
                                const Icon(Icons.chevron_right_rounded),
                              ]),
                              Row(children: [
                                Expanded(
                                  child: _MiniSwitch(
                                    label: S.t('On sale'),
                                    value: p['active'] as bool,
                                    onChanged: (v) async {
                                      if (await attempt(context, () => s.api.post('/api/m/packages/${p['id']}', {'active': v})) != null) reload();
                                    },
                                  ),
                                ),
                                Expanded(
                                  child: _MiniSwitch(
                                    label: S.t('On login page'),
                                    value: p['on_portal'] as bool,
                                    onChanged: (v) async {
                                      if (await attempt(context, () => s.api.post('/api/m/packages/${p['id']}', {'on_portal': v})) != null) reload();
                                    },
                                  ),
                                ),
                              ]),
                            ]),
                          ),
                        ),
                      ),
                    ),
                ]),
        ),
      ),
    );
  }
}

class _MiniSwitch extends StatelessWidget {
  const _MiniSwitch({required this.label, required this.value, required this.onChanged});
  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => Row(children: [
        Transform.scale(scale: 0.8, child: Switch(value: value, onChanged: onChanged)),
        Flexible(child: Text(label, style: Theme.of(context).textTheme.bodySmall, overflow: TextOverflow.ellipsis)),
      ]);
}

class PackageForm extends StatefulWidget {
  const PackageForm({super.key, this.id});
  final int? id;

  @override
  State<PackageForm> createState() => _PackageFormState();
}

class _PackageFormState extends State<PackageForm> {
  Map<String, dynamic>? form;
  final name = TextEditingController();
  final description = TextEditingController();
  final price = TextEditingController();
  int minutes = 1440, devices = 1;
  int? planId, siteId;
  bool active = true, onPortal = true, busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<Session>().api;
    final f = await api.get('/api/m/packages/form');
    if (widget.id != null) {
      final p = await api.get('/api/m/packages/${widget.id}/full');
      name.text = p['name'] as String;
      description.text = (p['description'] as String?) ?? '';
      price.text = (p['price'] as num).round().toString();
      minutes = p['minutes'] as int;
      devices = p['devices'] as int;
      planId = p['plan_id'] as int?;
      siteId = p['site_id'] as int?;
      active = p['active'] as bool;
      onPortal = p['on_portal'] as bool;
    }
    if (mounted) setState(() => form = f);
  }

  Future<void> save() async {
    setState(() => busy = true);
    final body = {
      'name': name.text, 'description': description.text, 'price': price.text.trim(), 'minutes': minutes, 'devices': devices,
      'plan_id': planId, 'site_id': siteId, 'active': active, 'on_portal': onPortal,
    };
    final api = context.read<Session>().api;
    final r = await attempt(context, () => widget.id == null ? api.post('/api/m/packages/new', body) : api.post('/api/m/packages/${widget.id}/save', body));
    if (!mounted) return;
    setState(() => busy = false);
    if (r != null) Navigator.pop(context, true);
  }

  Future<void> delete() async {
    if (!await confirm(context, S.t('Delete this package? Past payments keep their records.'), yes: S.t('Delete'), danger: true) || !mounted) return;
    final r = await attempt(context, () => context.read<Session>().api.delete('/api/m/packages/${widget.id}'));
    if (r != null && mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    final f = form;
    return Scaffold(
      appBar: AppBar(title: Text(widget.id == null ? S.t('New package') : S.t('Edit package'))),
      bottomNavigationBar: f == null ? null : SaveBar(busy: busy, onSave: save, onDelete: widget.id != null ? delete : null),
      body: f == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
              FieldGroup(title: S.t('What guests buy'), children: [
                TextField(controller: name, textCapitalization: TextCapitalization.sentences,
                    decoration: InputDecoration(labelText: S.t('Name'), hintText: S.t('e.g. 1 Day'), prefixIcon: const Icon(Icons.label_outline))),
                TextField(controller: price, keyboardType: TextInputType.number,
                    decoration: InputDecoration(labelText: '${S.t('Price')} (${f['currency']})', prefixIcon: const Icon(Icons.payments_outlined))),
                DurationField(label: S.t('Lasts'), minutes: minutes, onChanged: (v) => minutes = v),
                TextField(controller: description, decoration: InputDecoration(labelText: '${S.t('Description')} (${S.t('optional')})')),
              ]),
              FieldGroup(title: S.t('Limits'), children: [
                Row(children: [
                  const Icon(Icons.devices_other_rounded),
                  const SizedBox(width: 12),
                  Expanded(child: Text(S.t('Devices at once'))),
                  IconButton(onPressed: devices > 1 ? () => setState(() => devices--) : null, icon: const Icon(Icons.remove_circle_outline)),
                  Text('$devices', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                  IconButton(onPressed: devices < 20 ? () => setState(() => devices++) : null, icon: const Icon(Icons.add_circle_outline)),
                ]),
                PickField(label: S.t('Speed'), icon: Icons.speed_rounded, items: f['plans'] as List, value: planId, none: S.t('No speed limit'),
                    onChanged: (v) => setState(() => planId = v)),
                if ((f['sites'] as List).length > 1)
                  PickField(label: S.t('Sold at'), icon: Icons.place_outlined, items: f['sites'] as List, value: siteId, none: S.t('All sites'),
                      onChanged: (v) => setState(() => siteId = v)),
              ]),
              FieldGroup(children: [
                SwitchRow(title: S.t('On sale'), value: active, onChanged: (v) => setState(() => active = v)),
                SwitchRow(title: S.t('Shown on the login page'), subtitle: S.t('Guests can buy it with mobile money.'), value: onPortal,
                    onChanged: (v) => setState(() => onPortal = v)),
              ]),
            ]),
    );
  }
}
