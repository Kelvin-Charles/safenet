import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import 'shell.dart';
import 'manage/sms.dart';
import '../../ui/kit.dart';

class CustomersScreen extends StatefulWidget {
  const CustomersScreen({super.key});

  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  String q = '';
  String state = '';
  String tag = '';
  final items = <Map<String, dynamic>>[];
  List tags = [];
  int page = 0, pages = 1, total = 0;
  bool loading = false;
  String? error;
  Timer? debounce;
  final scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    load(reset: true);
    scroll.addListener(() {
      if (scroll.position.pixels > scroll.position.maxScrollExtent - 300 && !loading && page < pages) load();
    });
  }

  @override
  void dispose() {
    debounce?.cancel();
    scroll.dispose();
    super.dispose();
  }

  Future<void> load({bool reset = false}) async {
    if (reset) {
      page = 0;
      pages = 1;
    }
    setState(() => loading = true);
    final s = context.read<Session>();
    try {
      final d = await s.api.get('/api/m/customers', {'q': q, 'state': state, 'tag': tag, 'site_id': s.api.siteId, 'page': page + 1});
      if (!mounted) return;
      setState(() {
        if (reset) items.clear();
        items.addAll((d['items'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        page = d['page'] as int;
        pages = d['pages'] as int;
        total = d['total'] as int;
        tags = d['tags'] as List;
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: SnAppBar(title: Text('${S.t('Customers')}${total > 0 ? ' · $total' : ''}'), actions: [
        if (s.can('sms'))
          SnIconButton(
            tooltip: S.t('Send SMS'),
            icon: const Icon(Icons.sms_outlined),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => SmsScreen(
                siteId: s.api.siteId, state: state.isEmpty ? null : state, tag: tag.isEmpty ? null : tag))),
          ),
        const SiteButton(),
      ]),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: SnField(
            decoration: InputDecoration(hintText: S.t('Phone, name or tag'), prefixIcon: const Icon(Icons.search_rounded), isDense: true),
            onChanged: (v) {
              debounce?.cancel();
              debounce = Timer(const Duration(milliseconds: 400), () {
                q = v.trim();
                load(reset: true);
              });
            },
          ),
        ),
        SizedBox(
          height: 44,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
            for (final f in [('', S.t('All')), ('active', S.t('Has time left')), ('idle', S.t('No time left'))])
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: SnChip(label: Text(f.$2), selected: state == f.$1, onSelected: (_) {
                  state = f.$1;
                  load(reset: true);
                }),
              ),
            for (final t in tags)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: SnChip(label: Text('#$t'), selected: tag == t, onSelected: (on) {
                  tag = on ? t as String : '';
                  load(reset: true);
                }),
              ),
          ]),
        ),
        Expanded(
          child: error != null && items.isEmpty
              ? ErrorView(message: error!, onRetry: () => load(reset: true))
              : RefreshIndicator(
                  onRefresh: () => load(reset: true),
                  child: items.isEmpty && !loading
                      ? ListView(children: [EmptyView(icon: Icons.people_outline, text: S.t('No customers yet. They are added when they pay for Wi-Fi.'))])
                      : ListView.builder(
                          controller: scroll,
                          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                          itemCount: items.length + (loading ? 1 : 0),
                          itemBuilder: (c, i) {
                            if (i >= items.length) return const Padding(padding: EdgeInsets.all(16), child: Center(child: SnSpinner()));
                            final x = items[i];
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: SnCard(
                                child: SnTile(
                                  contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
                                  leading: CircleAvatar(
                                    backgroundColor: (x['active'] == true ? kGood : Colors.grey).withValues(alpha: 0.14),
                                    child: Text(_initials(x), style: TextStyle(color: x['active'] == true ? kGood : Colors.grey, fontWeight: FontWeight.w700)),
                                  ),
                                  title: Text((x['name'] as String?) ?? localPhone(x['phone'] as String), style: const TextStyle(fontWeight: FontWeight.w700)),
                                  subtitle: Text(
                                    [
                                      if (x['name'] != null) localPhone(x['phone'] as String),
                                      S.t('bought {n}×', {'n': x['purchases']}),
                                      if (x['last_paid'] != null) ago(x['last_paid'] as String?),
                                    ].join(' · '),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  trailing: Text(compactMoney(x['spent'] as num), style: const TextStyle(fontWeight: FontWeight.w800)),
                                  onTap: () async {
                                    await Navigator.push(context, MaterialPageRoute(builder: (_) => CustomerScreen(id: x['id'] as int)));
                                    if (mounted) load(reset: true);
                                  },
                                ),
                              ),
                            );
                          },
                        ),
                ),
        ),
      ]),
    );
  }

  static String _initials(Map x) {
    final n = (x['name'] as String?)?.trim();
    if (n != null && n.isNotEmpty) {
      final p = n.split(RegExp(r'\s+'));
      return (p.first[0] + (p.length > 1 ? p.last[0] : '')).toUpperCase();
    }
    final ph = x['phone'] as String? ?? '';
    return ph.length >= 2 ? ph.substring(ph.length - 2) : '#';
  }
}

class CustomerScreen extends StatelessWidget {
  const CustomerScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Loader<Map<String, dynamic>>(
      load: () => s.api.get('/api/m/customers/$id'),
      builder: (context, d, reload) {
        final c = d['customer'] as Map;
        return Scaffold(
          appBar: SnAppBar(title: Text((c['name'] as String?) ?? localPhone(c['phone'] as String)), actions: [
            SnIconButton(icon: const Icon(Icons.call_outlined), tooltip: S.t('Call'), onPressed: () => launchUrl(Uri.parse('tel:+${c['phone']}'))),
            SnIconButton(
              icon: const Icon(Icons.edit_outlined),
              onPressed: () async {
                final saved = await showSnSheet<bool>(context: context, isScrollControlled: true, builder: (_) => _EditSheet(c: c));
                if (saved == true) reload();
              },
            ),
          ]),
          body: RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
              Row(children: [
                Expanded(child: StatTile(icon: Icons.payments_outlined, label: S.t('Spent'), value: money(c['spent'] as num, s.currency), color: kGood)),
                const SizedBox(width: 12),
                Expanded(child: StatTile(icon: Icons.shopping_bag_outlined, label: S.t('Purchases'), value: '${c['purchases']}', color: kAccent)),
              ]),
              const SizedBox(height: 12),
              SnCard(
                child: Column(children: [
                  SnTile(leading: const Icon(Icons.phone_outlined), title: Text(localPhone(c['phone'] as String))),
                  if (c['last_paid'] != null)
                    SnTile(
                      leading: const Icon(Icons.history_rounded),
                      title: Text(S.t('Last purchase')),
                      subtitle: Text([when(c['last_paid'] as String?), c['last_package'], c['last_site']].whereType<String>().join(' · ')),
                    ),
                  if ((c['tags'] as List).isNotEmpty)
                    SnTile(
                      leading: const Icon(Icons.sell_outlined),
                      title: Wrap(spacing: 6, runSpacing: 6, children: [for (final t in c['tags'] as List) Pill('#$t', color: kAccent)]),
                    ),
                  if (c['note'] != null) SnTile(leading: const Icon(Icons.sticky_note_2_outlined), title: Text(c['note'] as String)),
                  if (c['stopped'] == true) SnTile(leading: const Icon(Icons.notifications_off_outlined, color: kBad), title: Text(S.t('Asked to stop offers'))),
                ]),
              ),
              SectionTitle(S.t('Codes')),
              for (final v in d['codes'] as List)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: SnCard(
                    child: SnTile(
                      title: Text('${v['code']} · ${v['package']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                      subtitle: Text([
                        if (v['state'] == 'active') '${S.t('Time left')} ${secondsLeft(v['seconds_left'] as int)}',
                        bytes((v['down'] as num) + (v['up'] as num)),
                        if (v['site'] != null) v['site'],
                        if (v['bought'] != null) when(v['bought'] as String?),
                      ].join(' · ')),
                      trailing: Pill(stateLabel(v['state'] as String?), color: stateColor(v['state'] as String?)),
                    ),
                  ),
                ),
            ]),
          ),
        );
      },
    );
  }
}

class _EditSheet extends StatefulWidget {
  const _EditSheet({required this.c});
  final Map c;

  @override
  State<_EditSheet> createState() => _EditSheetState();
}

class _EditSheetState extends State<_EditSheet> {
  late final name = TextEditingController(text: widget.c['name'] as String? ?? '');
  late final tags = TextEditingController(text: (widget.c['tags'] as List).join(', '));
  late final note = TextEditingController(text: widget.c['note'] as String? ?? '');

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.of(context).viewInsets.bottom),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SnField(controller: name, decoration: InputDecoration(labelText: S.t('Name')), textCapitalization: TextCapitalization.words),
          const SizedBox(height: 12),
          SnField(controller: tags, decoration: InputDecoration(labelText: S.t('Tags, separated by commas'))),
          const SizedBox(height: 12),
          SnField(controller: note, decoration: InputDecoration(labelText: S.t('Note')), maxLines: 2),
          const SizedBox(height: 16),
          SnButton(
            onPressed: () async {
              final r = await attempt(context,
                  () => context.read<Session>().api.post('/api/m/customers/${widget.c['id']}', {'name': name.text, 'tags': tags.text, 'note': note.text}));
              if (r != null && context.mounted) {
                toast(context, S.t('Saved'));
                Navigator.pop(context, true);
              }
            },
            child: Text(S.t('Save')),
          ),
        ]),
      );
}
