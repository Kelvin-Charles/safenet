import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';
import 'sms.dart';
import '../../../ui/kit.dart';

class OffersScreen extends StatefulWidget {
  const OffersScreen({super.key});

  @override
  State<OffersScreen> createState() => _OffersScreenState();
}

class _OffersScreenState extends State<OffersScreen> {
  int key = 0;

  Future<void> open(Map<String, dynamic> d, [Map? offer]) async {
    final saved = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => OfferForm(data: d, offer: offer)));
    if (saved == true) setState(() => key++);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Loader<Map<String, dynamic>>(
      reloadKey: key,
      load: () => s.api.get('/api/m/offers'),
      builder: (context, d, reload) => Scaffold(
        appBar: SnAppBar(title: Text(S.t('Offers'))),
        floatingActionButton: SnFab(onPressed: () => open(d), icon: const Icon(Icons.add_rounded), label: Text(S.t('New offer'))),
        body: RefreshIndicator(
          onRefresh: reload,
          child: (d['items'] as List).isEmpty
              ? ListView(children: [EmptyView(icon: Icons.local_offer_outlined, text: S.t('No offers yet. Give extra time or a discount to sell more.'))])
              : ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 96), children: [
                  for (final o in d['items'] as List)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: SnCard(
                        clipBehavior: Clip.antiAlias,
                        child: InkWell(
                          onTap: () => open(d, o as Map),
                          child: Container(
                            decoration: BoxDecoration(
                              border: Border(left: BorderSide(color: o['live'] == true ? kGold : Colors.grey.shade400, width: 5)),
                            ),
                            padding: const EdgeInsets.fromLTRB(14, 12, 8, 8),
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Row(children: [
                                const Icon(Icons.local_offer_rounded, color: kGold, size: 20),
                                const SizedBox(width: 8),
                                Expanded(child: Text('${o['name']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15))),
                                SnSwitch(
                                  value: o['active'] as bool,
                                  onChanged: (_) async {
                                    if (await attempt(context, () => s.api.post('/api/m/offers/${o['id']}/toggle')) != null) reload();
                                  },
                                ),
                              ]),
                              Wrap(spacing: 6, runSpacing: 6, children: [
                                if ((o['bonus_minutes'] as int) > 0) Pill('+${minutesLabel(o['bonus_minutes'] as int)}', color: kGood),
                                if ((o['discount_percent'] as int) > 0) Pill('-${o['discount_percent']}%', color: kBad),
                                Pill(o['package'] as String? ?? S.t('Every package'), color: kAccent),
                                if (o['site'] != null) Pill(o['site'] as String),
                                if (o['ended'] == true) Pill(S.t('Ended')) else if (o['live'] == true) Pill(S.t('Live now'), color: kGold),
                              ]),
                              const SizedBox(height: 6),
                              Row(children: [
                                Text(S.t('{n} sold', {'n': o['sold']}), style: Theme.of(context).textTheme.bodySmall),
                                if (o['ends'] != null) Text(' · ${S.t('Ends')} ${_fmt(o['ends'] as String)}', style: Theme.of(context).textTheme.bodySmall),
                                const Spacer(),
                                if (o['live'] == true && s.can('sms'))
                                  SnButton.icon(variant: SnVariant.ghost, size: SnSize.small,
                                    onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => SmsScreen(offerId: o['id'] as int))),
                                    icon: const Icon(Icons.sms_outlined, size: 18),
                                    label: Text(S.t('Tell customers')),
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

  static String _fmt(String local) => DateFormat('d MMM, HH:mm').format(DateTime.parse(local));
}

class OfferForm extends StatefulWidget {
  const OfferForm({super.key, required this.data, this.offer});
  final Map<String, dynamic> data;
  final Map? offer;

  @override
  State<OfferForm> createState() => _OfferFormState();
}

class _OfferFormState extends State<OfferForm> {
  late final o = widget.offer;
  late final name = TextEditingController(text: o?['name'] as String? ?? '');
  late int bonus = (o?['bonus_minutes'] as int?) ?? 1440;
  late int discount = (o?['discount_percent'] as int?) ?? 0;
  late int? packageId = o?['package_id'] as int?;
  late int? siteId = o?['site_id'] as int?;
  late DateTime? starts = o?['starts'] != null ? DateTime.parse(o!['starts'] as String) : null;
  late DateTime? ends = o?['ends'] != null ? DateTime.parse(o!['ends'] as String) : null;
  late bool active = (o?['active'] as bool?) ?? true;
  bool busy = false;

  String? _local(DateTime? d) => d == null ? null : DateFormat("yyyy-MM-dd'T'HH:mm").format(d);

  Future<void> save() async {
    setState(() => busy = true);
    final api = context.read<Session>().api;
    final body = {
      'name': name.text, 'bonus_minutes': bonus, 'discount_percent': discount, 'package_id': packageId, 'site_id': siteId,
      'starts': _local(starts), 'ends': _local(ends), 'active': active,
    };
    final r = await attempt(context, () => api.post(o == null ? '/api/m/offers' : '/api/m/offers/${o!['id']}', body));
    if (!mounted) return;
    setState(() => busy = false);
    if (r != null) Navigator.pop(context, true);
  }

  Future<void> delete() async {
    if (!await confirm(context, S.t('Delete this offer?'), yes: S.t('Delete'), danger: true) || !mounted) return;
    if (await attempt(context, () => context.read<Session>().api.delete('/api/m/offers/${o!['id']}')) != null && mounted) Navigator.pop(context, true);
  }

  Future<DateTime?> pick(DateTime? current) async {
    final now = DateTime.now();
    final day = await showDatePicker(context: context, initialDate: current ?? now, firstDate: now.subtract(const Duration(days: 1)), lastDate: now.add(const Duration(days: 365)));
    if (day == null || !mounted) return current;
    final time = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(current ?? now));
    return DateTime(day.year, day.month, day.day, time?.hour ?? 0, time?.minute ?? 0);
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.data;
    final pk = (d['packages'] as List).cast<Map>().where((p) => p['id'] == packageId).firstOrNull;
    final cur = d['currency'] as String;
    return Scaffold(
      appBar: SnAppBar(title: Text(o == null ? S.t('New offer') : S.t('Edit offer'))),
      bottomNavigationBar: SaveBar(busy: busy, onSave: save, onDelete: o != null ? delete : null),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
        // what the guest sees
        Container(
          padding: const EdgeInsets.all(16),
          margin: const EdgeInsets.only(bottom: 16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18),
            gradient: const LinearGradient(colors: [Color(0xFFFFF4D6), Color(0xFFFFE7A3)]),
            border: Border.all(color: kGold),
          ),
          child: Row(children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(color: kGold, borderRadius: BorderRadius.circular(8)),
              child: Text(S.lang == 'sw' ? 'OFA' : 'OFFER', style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 11, color: Colors.black)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(name.text.isEmpty ? S.t('Offer name') : name.text, style: const TextStyle(fontWeight: FontWeight.w800, color: Colors.black87)),
                if (pk != null)
                  Text(
                    '${pk['name']}: ${minutesLabel((pk['minutes'] as int) + bonus)} · '
                    '${money((pk['price'] as num) * (100 - discount) / 100, cur)}'
                    '${discount > 0 ? '  (${money(pk['price'] as num, cur)})' : ''}',
                    style: const TextStyle(color: Colors.black54, fontSize: 12),
                  ),
              ]),
            ),
          ]),
        ),
        FieldGroup(title: S.t('Offer'), children: [
          SnField(
            controller: name,
            onChanged: (_) => setState(() {}),
            textCapitalization: TextCapitalization.sentences,
            decoration: InputDecoration(labelText: S.t('Name guests see'), hintText: S.t('e.g. Buy 3 days, get 1 day free'), prefixIcon: const Icon(Icons.campaign_outlined)),
          ),
          PickField(label: S.t('Package'), icon: Icons.inventory_2_outlined, items: d['packages'] as List, value: packageId, none: S.t('Every package'),
              onChanged: (v) => setState(() => packageId = v)),
          if ((d['sites'] as List).length > 1)
            PickField(label: S.t('Site'), icon: Icons.place_outlined, items: d['sites'] as List, value: siteId, none: S.t('All sites'),
                onChanged: (v) => setState(() => siteId = v)),
        ]),
        FieldGroup(title: S.t('What they get'), children: [
          DurationField(label: S.t('Extra time'), minutes: bonus, allowZero: true, onChanged: (v) => setState(() => bonus = v)),
          Row(children: [
            const Icon(Icons.percent_rounded),
            const SizedBox(width: 12),
            Expanded(child: Text('${S.t('Discount')}: $discount%')),
          ]),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final p in const [0, 5, 10, 15, 20, 25, 30, 40, 50])
              SnChip(label: Text(p == 0 ? S.t('None') : '-$p%'), selected: discount == p, onSelected: (_) => setState(() => discount = p)),
          ]),
        ]),
        FieldGroup(title: S.t('When'), children: [
          SnTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.play_circle_outline),
            title: Text(S.t('Starts')),
            subtitle: Text(starts == null ? S.t('Now') : DateFormat('d MMM yyyy, HH:mm').format(starts!)),
            trailing: starts != null ? SnIconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => starts = null)) : null,
            onTap: () async {
              final v = await pick(starts);
              setState(() => starts = v);
            },
          ),
          SnTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.stop_circle_outlined),
            title: Text(S.t('Ends')),
            subtitle: Text(ends == null ? S.t('Until I switch it off') : DateFormat('d MMM yyyy, HH:mm').format(ends!)),
            trailing: ends != null ? SnIconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => ends = null)) : null,
            onTap: () async {
              final v = await pick(ends);
              setState(() => ends = v);
            },
          ),
          SwitchRow(title: S.t('On'), value: active, onChanged: (v) => setState(() => active = v)),
        ]),
      ]),
    );
  }
}
