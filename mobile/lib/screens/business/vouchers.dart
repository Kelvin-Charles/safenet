import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import 'shell.dart';

class VouchersScreen extends StatefulWidget {
  const VouchersScreen({super.key});

  @override
  State<VouchersScreen> createState() => _VouchersScreenState();
}

class _VouchersScreenState extends State<VouchersScreen> {
  String state = '';
  String search = '';
  final items = <Map<String, dynamic>>[];
  Map<String, dynamic>? stats;
  int page = 1, pages = 1;
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
    try {
      final d = await context.read<Session>().api.get('/api/m/vouchers', {'state': state, 'search': search, 'page': page + 1});
      if (!mounted) return;
      setState(() {
        if (reset) items.clear();
        items.addAll((d['items'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        page = d['page'] as int;
        pages = d['pages'] as int;
        stats = Map<String, dynamic>.from(d['stats'] as Map);
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> make() async {
    final made = await showModalBottomSheet<List>(context: context, isScrollControlled: true, builder: (_) => const _MakeSheet());
    if (made != null && mounted) {
      load(reset: true);
      _showMade(context, made);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final filters = [('', S.t('All')), ('unused', S.t('Unused')), ('active', S.t('Active')), ('expired', S.t('Expired')), ('disabled', S.t('Disabled'))];
    return Scaffold(
      appBar: AppBar(title: Text(S.t('Vouchers')), actions: const [SiteButton()]),
      floatingActionButton: s.can('change')
          ? FloatingActionButton.extended(onPressed: make, icon: const Icon(Icons.add_rounded), label: Text(S.t('Make vouchers')))
          : null,
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: TextField(
            keyboardType: TextInputType.number,
            decoration: InputDecoration(hintText: S.t('Search code'), prefixIcon: const Icon(Icons.search_rounded), isDense: true),
            onChanged: (v) {
              debounce?.cancel();
              debounce = Timer(const Duration(milliseconds: 400), () {
                search = v.trim();
                load(reset: true);
              });
            },
          ),
        ),
        SizedBox(
          height: 44,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
            for (final f in filters)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: ChoiceChip(
                  label: Text(stats != null && stats![f.$1] != null ? '${f.$2} · ${stats![f.$1]}' : f.$2),
                  selected: state == f.$1,
                  onSelected: (_) {
                    state = f.$1;
                    load(reset: true);
                  },
                ),
              ),
          ]),
        ),
        Expanded(
          child: error != null && items.isEmpty
              ? ErrorView(message: error!, onRetry: () => load(reset: true))
              : RefreshIndicator(
                  onRefresh: () => load(reset: true),
                  child: items.isEmpty && !loading
                      ? ListView(children: [EmptyView(icon: Icons.confirmation_number_outlined, text: S.t('No vouchers.'))])
                      : ListView.builder(
                          controller: scroll,
                          padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                          itemCount: items.length + (loading ? 1 : 0),
                          itemBuilder: (c, i) => i >= items.length
                              ? const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()))
                              : _VoucherTile(
                                  v: items[i],
                                  currency: s.currency,
                                  onTap: () => _details(items[i]),
                                ),
                        ),
                ),
        ),
      ]),
    );
  }

  Future<void> _details(Map<String, dynamic> v) async {
    final s = context.read<Session>();
    final changed = await showModalBottomSheet<String>(
      context: context,
      builder: (c) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Text((v['code'] as String?) ?? '•••• ••••', style: Theme.of(c).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, letterSpacing: 2)),
              const Spacer(),
              Pill(stateLabel(v['state'] as String?), color: stateColor(v['state'] as String?)),
            ]),
            const SizedBox(height: 12),
            _row(c, S.t('Lasts'), minutesLabel(v['minutes'] as int)),
            if (v['price'] != null) _row(c, S.t('Price'), money(v['price'] as num, s.currency)),
            if (v['free'] == true) _row(c, S.t('Price'), S.t('Free')),
            _row(c, S.t('Devices'), '${v['devices']}'),
            if (v['plan'] != null) _row(c, 'Plan', '${v['plan']}'),
            if (v['phone'] != null) _row(c, S.t('Bought by'), localPhone(v['phone'] as String)),
            if (v['started'] != null) _row(c, S.t('Started'), when(v['started'] as String?)),
            if (v['expires'] != null) _row(c, S.t('Ends'), when(v['expires'] as String?)),
            if ((v['sites'] as List).isNotEmpty) _row(c, S.t('Works at'), (v['sites'] as List).join(', ')),
            _row(c, 'Batch', '${v['batch']}'),
            if (v['code'] == null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(S.t('Being made on Reyee. The code shows here once Ruijie Cloud has it (usually within a minute).'),
                    style: const TextStyle(color: kWarn)),
              ),
            if (v['reyee_why'] != null)
              Padding(padding: const EdgeInsets.only(top: 8), child: Text('${v['reyee_why']}', style: const TextStyle(color: kBad))),
            const SizedBox(height: 16),
            if (v['code'] != null) Row(children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: v['code'] as String));
                    toast(c, S.t('Copied'));
                  },
                  icon: const Icon(Icons.copy_rounded),
                  label: Text(S.t('Copy')),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => SharePlus.instance.share(ShareParams(text: _shareText([v]))),
                  icon: const Icon(Icons.share_rounded),
                  label: Text(S.t('Share')),
                ),
              ),
            ]),
            if (s.can('change')) ...[
              const SizedBox(height: 8),
              Row(children: [
                Expanded(
                  child: TextButton.icon(
                    onPressed: () => Navigator.pop(c, 'toggle'),
                    icon: Icon(v['state'] == 'disabled' ? Icons.play_circle_outline : Icons.block_rounded),
                    label: Text(v['state'] == 'disabled' ? S.t('Enable') : S.t('Disable')),
                  ),
                ),
                Expanded(
                  child: TextButton.icon(
                    style: TextButton.styleFrom(foregroundColor: kBad),
                    onPressed: () => Navigator.pop(c, 'delete'),
                    icon: const Icon(Icons.delete_outline_rounded),
                    label: Text(S.t('Delete')),
                  ),
                ),
              ]),
            ],
          ]),
        ),
      ),
    );
    if (!mounted || changed == null) return;
    if (changed == 'toggle') {
      final r = await attempt(context, () => s.api.post('/api/m/vouchers/${v['id']}/toggle'));
      if (r != null) setState(() => v.addAll(r));
    } else if (changed == 'delete') {
      if (!await confirm(context, S.t('Delete code {code}?', {'code': v['code']}), yes: S.t('Delete'), danger: true) || !mounted) return;
      final r = await attempt(context, () => s.api.delete('/api/m/vouchers/${v['id']}'));
      if (r != null) setState(() => items.remove(v));
    }
  }

  Widget _row(BuildContext c, String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          SizedBox(width: 110, child: Text(k, style: TextStyle(color: Theme.of(c).colorScheme.outline))),
          Expanded(child: Text(v, style: const TextStyle(fontWeight: FontWeight.w600))),
        ]),
      );
}

String _shareText(List vs) {
  final lines = vs.where((v) => v['code'] != null).map((v) => '${v['code']} — ${minutesLabel(v['minutes'] as int)}').join('\n');
  return S.lang == 'sw' ? 'Vocha za Wi-Fi:\n$lines' : 'Wi-Fi vouchers:\n$lines';
}

void _showMade(BuildContext context, List made) {
  showModalBottomSheet(
    context: context,
    builder: (c) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Icon(Icons.check_circle_rounded, color: kGood, size: 48),
          const SizedBox(height: 8),
          Text(S.t('{n} vouchers made', {'n': made.length}), textAlign: TextAlign.center, style: Theme.of(c).textTheme.titleLarge),
          const SizedBox(height: 12),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 220),
            child: SingleChildScrollView(
              child: Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.center, children: [
                for (final v in made.where((v) => v['code'] != null))
                  Chip(label: Text(v['code'] as String, style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.w700, letterSpacing: 1))),
              ]),
            ),
          ),
          if (made.any((v) => v['code'] == null))
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(S.t('{n} are still being made on Reyee: they appear in the list in a minute.', {'n': made.where((v) => v['code'] == null).length}),
                  textAlign: TextAlign.center, style: const TextStyle(color: kWarn)),
            ),
          const SizedBox(height: 16),
          if (made.any((v) => v['code'] != null)) FilledButton.icon(
            onPressed: () => SharePlus.instance.share(ShareParams(text: _shareText(made))),
            icon: const Icon(Icons.share_rounded),
            label: Text(S.t('Share codes')),
          ),
        ]),
      ),
    ),
  );
}

class _VoucherTile extends StatelessWidget {
  const _VoucherTile({required this.v, required this.currency, required this.onTap});
  final Map<String, dynamic> v;
  final String currency;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final st = v['state'] as String?;
    final expires = parseIso(v['expires'] as String?);
    final left = st == 'active' && expires != null ? expires.difference(DateTime.now()) : null;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(children: [
              Container(width: 4, height: 40, decoration: BoxDecoration(color: stateColor(st), borderRadius: BorderRadius.circular(4))),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text((v['code'] as String?) ?? '•••• ••••', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16, letterSpacing: 1.2, fontFamily: 'monospace')),
                  const SizedBox(height: 2),
                  Text(
                    [
                      minutesLabel(v['minutes'] as int),
                      if (v['price'] != null) money(v['price'] as num, currency) else if (v['free'] == true) S.t('Free'),
                      if (v['phone'] != null) localPhone(v['phone'] as String),
                      if (left != null && !left.isNegative) '${S.t('Time left')} ${secondsLeft(left.inSeconds)}',
                    ].join(' · '),
                    style: Theme.of(context).textTheme.bodySmall,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ]),
              ),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Pill(stateLabel(st), color: stateColor(st)),
                if (v['reyee'] == 'pending' || v['reyee'] == 'sending' || v['reyee'] == 'catchup')
                  Padding(padding: const EdgeInsets.only(top: 4), child: Pill(S.t('Being sent to Reyee'), color: kWarn))
                else if (v['reyee'] == 'ok')
                  Padding(padding: const EdgeInsets.only(top: 4), child: Pill(S.t('On Reyee'), color: kAccent))
                else if (v['reyee'] == 'failed')
                  Padding(padding: const EdgeInsets.only(top: 4), child: Pill(S.t('Not on Reyee'), color: kBad)),
              ]),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Make vouchers: from a package or custom length/price, how many, which sites.
class _MakeSheet extends StatefulWidget {
  const _MakeSheet();

  @override
  State<_MakeSheet> createState() => _MakeSheetState();
}

class _MakeSheetState extends State<_MakeSheet> {
  Map<String, dynamic>? opts;
  int? packageId;
  int count = 10;
  int lasts = 1;
  String unit = 'days';
  bool free = false;
  int devices = 1;
  final price = TextEditingController();
  final batch = TextEditingController();
  final sites = <int>{};
  bool busy = false;

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/m/vouchers/options').then((d) {
      if (!mounted) return;
      setState(() {
        opts = d;
        final pk = d['packages'] as List;
        if (pk.isNotEmpty) packageId = pk.first['id'] as int;
      });
    });
  }

  Future<void> submit() async {
    setState(() => busy = true);
    final body = <String, dynamic>{
      'count': count,
      'free': free,
      'batch': batch.text.trim(),
      'site_ids': sites.toList(),
      if (packageId != null) 'package_id': packageId,
      if (packageId == null) 'minutes': lasts * (unit == 'days' ? 1440 : 60),
      if (packageId == null) 'devices': devices,
      if (!free && price.text.trim().isNotEmpty) 'price': price.text.trim(),
    };
    final r = await attempt(context, () => context.read<Session>().api.post('/api/m/vouchers', body));
    if (!mounted) return;
    setState(() => busy = false);
    if (r != null) Navigator.pop(context, r['items'] as List);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    final o = opts;
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SafeArea(
        child: o == null
            ? const SizedBox(height: 240, child: Center(child: CircularProgressIndicator()))
            : SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Text(S.t('Make vouchers'), style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 16),
                  Text(S.t('Package'), style: Theme.of(context).textTheme.labelLarge),
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    for (final p in o['packages'] as List)
                      ChoiceChip(
                        label: Text('${p['name']} · ${compactMoney(p['price'] as num)}'),
                        selected: packageId == p['id'],
                        onSelected: (_) => setState(() => packageId = p['id'] as int),
                      ),
                    ChoiceChip(label: Text(S.t('Custom')), selected: packageId == null, onSelected: (_) => setState(() => packageId = null)),
                  ]),
                  if (packageId == null) ...[
                    const SizedBox(height: 16),
                    Row(children: [
                      Expanded(child: _Stepper(label: S.t('Lasts'), value: lasts, min: 1, max: 365, onChanged: (v) => setState(() => lasts = v))),
                      const SizedBox(width: 8),
                      SegmentedButton<String>(
                        segments: [ButtonSegment(value: 'hours', label: Text(S.t('hours'))), ButtonSegment(value: 'days', label: Text(S.t('days')))],
                        selected: {unit},
                        showSelectedIcon: false,
                        onSelectionChanged: (v) => setState(() => unit = v.first),
                      ),
                    ]),
                    const SizedBox(height: 12),
                    _Stepper(label: S.t('Devices'), value: devices, min: 1, max: 20, onChanged: (v) => setState(() => devices = v)),
                  ],
                  const SizedBox(height: 16),
                  _Stepper(label: S.t('How many'), value: count, min: 1, max: 500, step: count >= 20 ? 10 : 1, onChanged: (v) => setState(() => count = v)),
                  const SizedBox(height: 12),
                  SwitchListTile(contentPadding: EdgeInsets.zero, title: Text(S.t('Free (no price)')), value: free, onChanged: (v) => setState(() => free = v)),
                  if (!free)
                    TextField(
                      controller: price,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(labelText: '${S.t('Price')} (${s.currency})', hintText: packageId != null ? S.t('Package') : null),
                    ),
                  const SizedBox(height: 12),
                  TextField(controller: batch, decoration: InputDecoration(labelText: S.t('Batch name (optional)'))),
                  if ((o['sites'] as List).length > 1) ...[
                    const SizedBox(height: 16),
                    Text(S.t('Works at'), style: Theme.of(context).textTheme.labelLarge),
                    const SizedBox(height: 8),
                    Wrap(spacing: 8, runSpacing: 8, children: [
                      FilterChip(label: Text(S.t('All sites')), selected: sites.isEmpty, onSelected: (_) => setState(sites.clear)),
                      for (final site in o['sites'] as List)
                        FilterChip(
                          label: Text(site['name'] as String),
                          selected: sites.contains(site['id']),
                          onSelected: (on) => setState(() => on ? sites.add(site['id'] as int) : sites.remove(site['id'])),
                        ),
                    ]),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: busy ? null : submit,
                    child: busy ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)) : Text('${S.t('Make')} $count'),
                  ),
                ]),
              ),
      ),
    );
  }
}

class _Stepper extends StatelessWidget {
  const _Stepper({required this.label, required this.value, required this.min, required this.max, required this.onChanged, this.step = 1});
  final String label;
  final int value, min, max, step;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        decoration: BoxDecoration(
          color: Theme.of(context).inputDecorationTheme.fillColor,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: 0.6)),
        ),
        child: Row(children: [
          Expanded(child: Text(label)),
          IconButton(onPressed: value > min ? () => onChanged((value - step).clamp(min, max)) : null, icon: const Icon(Icons.remove_circle_outline)),
          SizedBox(width: 40, child: Text('$value', textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
          IconButton(onPressed: value < max ? () => onChanged((value + step).clamp(min, max)) : null, icon: const Icon(Icons.add_circle_outline)),
        ]),
      );
}
