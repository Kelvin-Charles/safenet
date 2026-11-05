import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';

/// SMS to customers: pick who (site, recent buyers, tag, time left, quiet ones, or customers ticked on Customers),
/// write or pick an offer message, see the exact SMS and the cost, untick anyone, send.
class SmsScreen extends StatefulWidget {
  const SmsScreen({super.key, this.offerId, this.ids, this.siteId, this.state, this.tag});
  final int? offerId;
  final List<int>? ids;
  final int? siteId;
  final String? state;
  final String? tag;

  @override
  State<SmsScreen> createState() => _SmsScreenState();
}

class _SmsScreenState extends State<SmsScreen> {
  final text = TextEditingController();
  Map<String, dynamic>? d;
  late int? siteId = widget.siteId;
  int? days, quiet;
  late String? state = widget.state, tag = widget.tag;
  late int? offerId = widget.offerId;
  Set<String>? ticked;
  bool busy = false, sending = false;
  Timer? debounce;

  @override
  void initState() {
    super.initState();
    refresh(first: true);
  }

  Map<String, dynamic> get body => {
        'text': text.text,
        'site_id': siteId,
        'days': days,
        'quiet': quiet,
        'state': state,
        'tag': tag,
        'offer_id': offerId,
        if (widget.ids != null) 'ids': widget.ids,
        if (ticked != null) 'phones': ticked!.toList(),
      };

  Future<void> refresh({bool first = false, bool keepTicks = false}) async {
    if (!keepTicks) ticked = null;
    setState(() => busy = true);
    try {
      final r = await context.read<Session>().api.post('/api/m/sms', body);
      if (!mounted) return;
      if (first && offerId != null && text.text.isEmpty) {
        final o = (r['offers'] as List).cast<Map>().where((x) => x['id'] == offerId).firstOrNull;
        if (o != null) text.text = o['text'] as String;
        setState(() => d = r);
        return refresh();
      }
      setState(() => d = r);
    } catch (e) {
      if (mounted) toast(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void typed() {
    debounce?.cancel();
    debounce = Timer(const Duration(milliseconds: 500), () => refresh(keepTicks: true));
    setState(() {});
  }

  Future<void> send() async {
    final x = d!;
    final cost = money(x['cost'] as num, x['currency'] as String);
    final from = x['balance'] != null ? S.t('taken from your SafeNet Pay balance') : S.t('added to your next SafeNet bill');
    if (!await confirm(context, S.t('Send to {n} customers? Up to {cost} is {from}.', {'n': x['count'], 'cost': cost, 'from': from}), yes: S.t('Send'))) return;
    if (!mounted) return;
    setState(() => sending = true);
    final r = await attempt(context, () => context.read<Session>().api.post('/api/m/sms', {...body, 'action': 'send'}));
    if (!mounted) return;
    setState(() => sending = false);
    if (r != null) {
      await showDialog(
        context: context,
        builder: (c) => AlertDialog(
          icon: const Icon(Icons.send_rounded, color: kGood, size: 40),
          title: Text(S.t('Sending to {n} customers', {'n': r['sent']})),
          content: Text(S.t('It takes a few minutes. Only SMS that go out are charged.')),
          actions: [FilledButton(style: FilledButton.styleFrom(minimumSize: const Size(88, 44)), onPressed: () => Navigator.pop(c), child: const Text('OK'))],
        ),
      );
      if (mounted) Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final x = d;
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(S.t('SMS to customers')), actions: [
        IconButton(
          icon: const Icon(Icons.history_rounded),
          tooltip: S.t('History'),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const _History())),
        ),
      ]),
      bottomNavigationBar: x == null
          ? null
          : SafeArea(
              top: false,
              child: Container(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                decoration: BoxDecoration(color: t.colorScheme.surface, border: Border(top: BorderSide(color: t.colorScheme.outlineVariant.withValues(alpha: 0.4)))),
                child: Row(children: [
                  Expanded(
                    child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(money(x['cost'] as num, x['currency'] as String), style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                      Text('${x['count']} × ${x['parts']} SMS × ${x['price']}', style: t.textTheme.bodySmall),
                      if (x['balance'] != null)
                        Text('${S.t('Balance')}: ${money(x['balance'] as num, x['currency'] as String)}',
                            style: t.textTheme.labelSmall?.copyWith(color: (x['cost'] as num) > (x['balance'] as num) ? kBad : kGood)),
                    ]),
                  ),
                  FilledButton.icon(
                    style: FilledButton.styleFrom(minimumSize: const Size(130, 52)),
                    onPressed: sending || busy || (x['count'] as int) == 0 || text.text.trim().isEmpty || x['ready'] != true ? null : send,
                    icon: sending ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.send_rounded),
                    label: Text(S.t('Send')),
                  ),
                ]),
              ),
            ),
      body: x == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
              if (x['ready'] != true)
                Card(color: kWarn.withValues(alpha: 0.12), child: ListTile(leading: const Icon(Icons.warning_amber_rounded, color: kWarn), title: Text(S.t('SMS is not available right now. Contact SafeNet.')))),
              // who
              SectionTitle(S.t('Who gets it'), trailing: busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : null),
              if (widget.ids != null)
                Card(child: ListTile(leading: const Icon(Icons.checklist_rounded), title: Text(S.t('The {n} customers you picked', {'n': widget.ids!.length}))))
              else
                Wrap(spacing: 8, runSpacing: 8, children: [
                  if ((x['sites'] as List).length > 1)
                    _Menu<int?>(
                      icon: Icons.place_outlined,
                      label: siteId == null ? S.t('All sites') : (x['sites'] as List).firstWhere((s) => s['id'] == siteId)['name'] as String,
                      active: siteId != null,
                      items: {null: S.t('All sites'), for (final s in x['sites'] as List) s['id'] as int: s['name'] as String},
                      onPick: (v) => setState(() => siteId = v),
                      after: refresh,
                    ),
                  _Menu<int?>(
                    icon: Icons.event_outlined,
                    label: days == null ? S.t('Bought any time') : S.t('Bought in {n} days', {'n': days}),
                    active: days != null,
                    items: {null: S.t('Bought any time'), for (final n in x['choices']['days'] as List) n as int: S.t('Bought in {n} days', {'n': n})},
                    onPick: (v) => setState(() => days = v),
                    after: refresh,
                  ),
                  _Menu<String?>(
                    icon: Icons.timelapse_rounded,
                    label: state == 'active' ? S.t('Has time left') : state == 'idle' ? S.t('No time left') : S.t('Package now: anyone'),
                    active: state != null,
                    items: {null: S.t('Package now: anyone'), 'active': S.t('Has time left'), 'idle': S.t('No time left')},
                    onPick: (v) => setState(() => state = v),
                    after: refresh,
                  ),
                  _Menu<int?>(
                    icon: Icons.bedtime_outlined,
                    label: quiet == null ? S.t("Hasn't bought for…") : S.t("Hasn't bought for {n} days", {'n': quiet}),
                    active: quiet != null,
                    items: {null: S.t('Anyone'), for (final n in x['choices']['quiet'] as List) n as int: S.t("Hasn't bought for {n} days", {'n': n})},
                    onPick: (v) => setState(() => quiet = v),
                    after: refresh,
                  ),
                  if ((x['tags'] as List).isNotEmpty)
                    _Menu<String?>(
                      icon: Icons.sell_outlined,
                      label: tag == null ? S.t('Any tag') : '#$tag',
                      active: tag != null,
                      items: {null: S.t('Any tag'), for (final g in x['tags'] as List) g as String: '#$g'},
                      onPick: (v) => setState(() => tag = v),
                      after: refresh,
                    ),
                ]),
              const SizedBox(height: 10),
              Card(
                child: ListTile(
                  leading: CircleAvatar(backgroundColor: kAccent.withValues(alpha: 0.12), child: const Icon(Icons.people_alt_rounded, color: kAccent)),
                  title: Text(S.t('{n} customers', {'n': x['count']}), style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text([
                    if ((x['recent'] as int) > 0) S.t('{n} left out: got a message in the last 24 hours', {'n': x['recent']}),
                    if ((x['stopped'] as int) > 0) S.t('{n} asked to stop', {'n': x['stopped']}),
                  ].join(' · ').ifEmpty(S.t('Tap to see them and untick anyone.'))),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: (x['people'] as List).isEmpty ? null : _people,
                ),
              ),
              // what
              SectionTitle(S.t('Message')),
              if ((x['offers'] as List).isNotEmpty)
                SizedBox(
                  height: 40,
                  child: ListView(scrollDirection: Axis.horizontal, children: [
                    for (final o in x['offers'] as List)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ActionChip(
                          avatar: const Icon(Icons.local_offer_rounded, size: 16, color: kGold),
                          label: Text('${o['name']}'),
                          onPressed: () {
                            text.text = o['text'] as String;
                            offerId = o['id'] as int;
                            typed();
                          },
                        ),
                      ),
                  ]),
                ),
              const SizedBox(height: 8),
              TextField(
                controller: text,
                maxLines: 5,
                minLines: 3,
                maxLength: x['max_text'] as int,
                onChanged: (_) => typed(),
                decoration: InputDecoration(hintText: S.t('Write your message…'), alignLabelWithHint: true),
              ),
              // preview: a phone message bubble
              SectionTitle(S.t('What they get')),
              Align(
                alignment: Alignment.centerLeft,
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 320),
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: t.brightness == Brightness.dark ? const Color(0xFF263042) : const Color(0xFFE9EDF5),
                    borderRadius: const BorderRadius.only(
                        topLeft: Radius.circular(18), topRight: Radius.circular(18), bottomRight: Radius.circular(18), bottomLeft: Radius.circular(4)),
                  ),
                  child: Text('${x['sample']}', style: const TextStyle(height: 1.35)),
                ),
              ),
              const SizedBox(height: 6),
              Text('${'${x['sample']}'.length} ${S.lang == 'sw' ? 'herufi' : 'characters'} · ${x['parts']} SMS', style: t.textTheme.labelSmall),
            ]),
    );
  }

  Future<void> _people() async {
    final x = d!;
    final all = (x['people'] as List).cast<Map>();
    final picked = Set<String>.from(ticked ?? all.map((p) => p['phone'] as String));
    final r = await showModalBottomSheet<Set<String>>(
      context: context,
      isScrollControlled: true,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => DraggableScrollableSheet(
          expand: false,
          initialChildSize: 0.7,
          builder: (c, scroll) => Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 12, 8),
              child: Row(children: [
                Expanded(child: Text(S.t('{n} of {total} ticked', {'n': picked.length, 'total': all.length}), style: Theme.of(c).textTheme.titleMedium)),
                TextButton(
                    onPressed: () => set(() => picked.length == all.length ? picked.clear() : picked.addAll(all.map((p) => p['phone'] as String))),
                    child: Text(picked.length == all.length ? S.t('None') : S.t('All'))),
                FilledButton(style: FilledButton.styleFrom(minimumSize: const Size(80, 40)), onPressed: () => Navigator.pop(c, picked), child: Text(S.t('Done'))),
              ]),
            ),
            Expanded(
              child: ListView.builder(
                controller: scroll,
                itemCount: all.length,
                itemBuilder: (c, i) {
                  final p = all[i];
                  return CheckboxListTile(
                    value: picked.contains(p['phone']),
                    onChanged: (v) => set(() => v == true ? picked.add(p['phone'] as String) : picked.remove(p['phone'])),
                    title: Text((p['name'] as String?) ?? localPhone(p['phone'] as String)),
                    subtitle: p['name'] != null ? Text(localPhone(p['phone'] as String)) : null,
                  );
                },
              ),
            ),
          ]),
        ),
      ),
    );
    if (r != null) {
      ticked = r;
      refresh(keepTicks: true);
    }
  }
}

extension on String {
  String ifEmpty(String other) => isEmpty ? other : this;
}

class _Menu<T> extends StatelessWidget {
  const _Menu({required this.icon, required this.label, required this.active, required this.items, required this.onPick, required this.after});
  final IconData icon;
  final String label;
  final bool active;
  final Map<T, String> items;
  final ValueChanged<T> onPick;
  final VoidCallback after;

  @override
  Widget build(BuildContext context) => PopupMenuButton<T>(
        onSelected: (v) {
          onPick(v);
          after();
        },
        itemBuilder: (_) => [for (final e in items.entries) PopupMenuItem<T>(value: e.key, child: Text(e.value))],
        child: Chip(
          avatar: Icon(icon, size: 16, color: active ? Theme.of(context).colorScheme.onPrimary : null),
          label: Text(label),
          backgroundColor: active ? Theme.of(context).colorScheme.primary : null,
          labelStyle: TextStyle(color: active ? Theme.of(context).colorScheme.onPrimary : null, fontWeight: FontWeight.w600),
          deleteIcon: const Icon(Icons.expand_more_rounded, size: 18),
          onDeleted: () {},
          deleteIconColor: active ? Theme.of(context).colorScheme.onPrimary : null,
        ),
      );
}

class _History extends StatelessWidget {
  const _History();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: AppBar(title: Text(S.t('Messages sent'))),
      body: Loader<Map<String, dynamic>>(
        load: () => s.api.get('/api/m/sms/history'),
        builder: (context, d, reload) => RefreshIndicator(
          onRefresh: reload,
          child: (d['items'] as List).isEmpty
              ? ListView(children: [EmptyView(icon: Icons.sms_outlined, text: S.t('None yet.'))])
              : ListView(padding: const EdgeInsets.all(16), children: [
                  for (final c in d['items'] as List)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Card(
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Row(children: [
                              Pill(c['kind'] == 'offer' ? S.t('Offer') : c['kind'] == 'outage' ? S.t('Outage') : S.t('Message'),
                                  color: c['kind'] == 'offer' ? kGold : c['kind'] == 'outage' ? kWarn : kAccent),
                              const SizedBox(width: 8),
                              Text(when(c['at'] as String?), style: Theme.of(context).textTheme.bodySmall),
                              const Spacer(),
                              if (c['status'] == 'sending') const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                            ]),
                            const SizedBox(height: 8),
                            Text('${c['text']}', maxLines: 3, overflow: TextOverflow.ellipsis),
                            const SizedBox(height: 8),
                            Text('${c['sent']}/${c['recipients']} · ${money(c['amount'] as num, d['currency'] as String)}${c['site'] != null ? ' · ${c['site']}' : ''}',
                                style: Theme.of(context).textTheme.labelMedium),
                          ]),
                        ),
                      ),
                    ),
                ]),
        ),
      ),
    );
  }
}
