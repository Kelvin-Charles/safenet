import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/theme.dart';
import '../../ui/widgets.dart';
import '../../ui/kit.dart';

/// Buy a package inside the app: choose it, pay with mobile money (the PIN prompt comes to the phone), get the code.
class BuyScreen extends StatefulWidget {
  const BuyScreen({super.key, required this.businessId, required this.name, this.siteId});
  final int businessId;
  final String name;
  final int? siteId;

  @override
  State<BuyScreen> createState() => _BuyScreenState();
}

class _BuyScreenState extends State<BuyScreen> {
  late int? siteId = widget.siteId;
  int key = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Scaffold(
      appBar: SnAppBar(title: Text(widget.name)),
      body: Loader<Map<String, dynamic>>(
        reloadKey: '$siteId-$key',
        load: () => s.api.get('/api/m/guest/shop/${widget.businessId}', {'site_id': siteId}),
        builder: (context, d, reload) {
          final packages = d['packages'] as List;
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
              Text(S.t('Choose a package'), style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              Text(S.t('Pay with mobile money. The code is yours straight away.'), style: TextStyle(color: Theme.of(context).colorScheme.outline)),
              if ((d['sites'] as List).length > 1) ...[
                const SizedBox(height: 14),
                SizedBox(
                  height: 40,
                  child: ListView(scrollDirection: Axis.horizontal, children: [
                    for (final x in d['sites'] as List)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: SnChip(
                          avatar: const Icon(Icons.place_outlined, size: 16),
                          label: Text('${x['name']}'),
                          selected: d['site_id'] == x['id'],
                          onSelected: (_) => setState(() => siteId = x['id'] as int),
                        ),
                      ),
                  ]),
                ),
              ],
              const SizedBox(height: 16),
              if (d['can_buy'] != true)
                SnCard(child: EmptyView(icon: Icons.storefront_outlined, text: S.t("Buying isn't available here right now. Ask {name}.", {'name': widget.name})))
              else
                for (final p in packages)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: _PackageCard(
                      p: p as Map,
                      onTap: () async {
                        final bought = await showSnSheet<bool>(
                          context: context,
                          isScrollControlled: true,
                          isDismissible: false,
                          enableDrag: false,
                          builder: (_) => _Checkout(shop: d, package: p),
                        );
                        if (bought == true && context.mounted) Navigator.pop(context, true);
                      },
                    ),
                  ),
              const PoweredBy(),
            ]),
          );
        },
      ),
    );
  }
}

class _PackageCard extends StatelessWidget {
  const _PackageCard({required this.p, required this.onTap});
  final Map p;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final offer = (p['offer'] as String? ?? '').isNotEmpty;
    final mins = p['validity_minutes'] as int;
    return SnCard(
      borderColor: offer ? kGold : null,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(children: [
            Container(
              width: 62,
              height: 62,
              decoration: BoxDecoration(
                gradient: const LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)], begin: Alignment.topLeft, end: Alignment.bottomRight),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Center(
                child: Text(minutesLabel(mins).replaceFirst(' ', '\n'),
                    textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 12, height: 1.15)),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (offer)
                  Container(
                    margin: const EdgeInsets.only(bottom: 4),
                    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                    decoration: BoxDecoration(color: kGold, borderRadius: BorderRadius.circular(6)),
                    child: Text(S.lang == 'sw' ? 'OFA' : 'OFFER', style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w900, color: Colors.black)),
                  ),
                Text('${p['name']}', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                if (offer) Text('${p['offer']}', style: const TextStyle(color: Color(0xFFB7791F), fontWeight: FontWeight.w600, fontSize: 12)),
                if (!offer && (p['description'] as String? ?? '').isNotEmpty)
                  Text('${p['description']}', style: Theme.of(context).textTheme.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
              ]),
            ),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(money(num.parse('${p['price']}'), '${p['currency']}'), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
              if ((p['old_price'] as String? ?? '').isNotEmpty)
                Text(money(num.parse('${p['old_price']}'), '${p['currency']}'),
                    style: TextStyle(decoration: TextDecoration.lineThrough, color: Theme.of(context).colorScheme.outline, fontSize: 12)),
              const SizedBox(height: 6),
              const Icon(Icons.arrow_forward_rounded, size: 20),
            ]),
          ]),
        ),
      ),
    );
  }
}

/// Phone, network, for a friend, pay; then wait for the PIN; then the code.
class _Checkout extends StatefulWidget {
  const _Checkout({required this.shop, required this.package});
  final Map<String, dynamic> shop;
  final Map package;

  @override
  State<_Checkout> createState() => _CheckoutState();
}

enum _Step { form, waiting, paid, failed }

class _CheckoutState extends State<_Checkout> {
  late final phone = TextEditingController(text: localPhone(widget.shop['phone'] as String?));
  final friend = TextEditingController();
  String? network;
  bool gift = false, busy = false;
  String? error;
  _Step step = _Step.form;
  Map<String, dynamic>? result;
  String? reference;
  Timer? poll;
  int polls = 0;

  List get networks => widget.shop['networks'] as List;

  @override
  void initState() {
    super.initState();
    _guessNetwork();
  }

  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  /// The network from the number (0745… is M-Pesa), when it is one that can pay.
  void _guessNetwork() {
    final digits = phone.text.replaceAll(RegExp(r'\D'), '');
    final local = digits.startsWith('255') ? digits.substring(3) : digits.replaceFirst(RegExp(r'^0'), '');
    if (local.length < 2) return;
    for (final n in networks) {
      if ((n['prefixes'] as List).contains(local.substring(0, 2))) {
        setState(() => network = n['id'] as String);
        return;
      }
    }
  }

  Future<void> pay() async {
    if (networks.isNotEmpty && network == null) {
      setState(() => error = S.t('Choose your mobile-money network.'));
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    final s = context.read<Session>();
    try {
      final r = await s.api.post('/api/m/guest/buy', {
        'business_id': widget.shop['business']['id'],
        'site_id': widget.shop['site_id'],
        'package_id': widget.package['id'],
        'phone': phone.text.trim(),
        'network': network,
        'gift': gift,
        if (gift) 'gift_phone': friend.text.trim(),
      });
      reference = r['reference'] as String;
      setState(() => step = _Step.waiting);
      polls = 0;
      poll = Timer.periodic(const Duration(seconds: 3), (_) => _check());
    } on ApiError catch (e) {
      setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _check() async {
    polls++;
    final s = context.read<Session>();
    try {
      final r = await s.api.get('/api/m/guest/pay/$reference');
      if (!mounted) return;
      if (r['status'] == 'paid') {
        poll?.cancel();
        if (r['token'] != null) {
          // bought on a SafeNet Wi-Fi without signing in: now signed in with the new code
          s.kind == Kind.guest ? await s.replaceToken(r['token'] as String) : await s.adoptGuestToken(r['token'] as String);
        }
        HapticFeedback.mediumImpact();
        setState(() {
          result = r;
          step = _Step.paid;
        });
      } else if (r['status'] == 'failed' || r['status'] == 'review') {
        poll?.cancel();
        setState(() {
          result = r;
          step = _Step.failed;
        });
      } else if (polls > 100) {          // about 5 minutes
        poll?.cancel();
        setState(() {
          result = {'message': S.t("We didn't hear back about your payment. If money left your account, the code comes by SMS.")};
          step = _Step.failed;
        });
      }
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.package;
    final t = Theme.of(context);
    final price = money(num.parse('${p['price']}'), '${p['currency']}');
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SafeArea(
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 250),
          child: switch (step) {
            _Step.form => SingleChildScrollView(
                key: const ValueKey('form'),
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${p['name']}', style: t.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
                        Text(minutesLabel(p['validity_minutes'] as int), style: TextStyle(color: t.colorScheme.outline)),
                      ]),
                    ),
                    Text(price, style: t.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900)),
                    SnIconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.pop(context)),
                  ]),
                  const SizedBox(height: 18),
                  SnField(
                    controller: phone,
                    keyboardType: TextInputType.phone,
                    onChanged: (_) => _guessNetwork(),
                    decoration: InputDecoration(labelText: S.t('Number that pays'), hintText: '07XX XXX XXX', prefixIcon: const Icon(Icons.phone_iphone_rounded)),
                  ),
                  if (networks.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    Text(S.t('Pay with'), style: t.textTheme.labelLarge),
                    const SizedBox(height: 8),
                    Wrap(spacing: 8, runSpacing: 8, children: [
                      for (final n in networks)
                        SnChip(
                          showCheckmark: false,
                          avatar: ClipRRect(
                            borderRadius: BorderRadius.circular(4),
                            child: Image.network('${n['logo']}', width: 22, height: 22, fit: BoxFit.contain,
                                errorBuilder: (_, _, _) => const Icon(Icons.account_balance_wallet_outlined, size: 18)),
                          ),
                          label: Text('${n['name']}'),
                          selected: network == n['id'],
                          onSelected: (_) => setState(() => network = n['id'] as String),
                        ),
                    ]),
                  ],
                  if (widget.shop['can_gift'] == true) ...[
                    const SizedBox(height: 8),
                    SnSwitchTile(
                      contentPadding: EdgeInsets.zero,
                      secondary: const Icon(Icons.card_giftcard_rounded, color: Colors.pink),
                      title: Text(S.t('For a friend')),
                      subtitle: Text(S.t('They get the code by SMS.')),
                      value: gift,
                      onChanged: (v) => setState(() => gift = v),
                    ),
                    if (gift)
                      SnField(
                        controller: friend,
                        keyboardType: TextInputType.phone,
                        decoration: InputDecoration(labelText: S.t("Friend's number"), prefixIcon: const Icon(Icons.person_outline_rounded)),
                      ),
                  ],
                  if (error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: const TextStyle(color: kBad))),
                  const SizedBox(height: 18),
                  SnButton.icon(
                    onPressed: busy ? null : pay,
                    icon: busy ? const SizedBox(width: 20, height: 20, child: SnSpinner(strokeWidth: 2.5)) : const Icon(Icons.lock_rounded, size: 18),
                    label: Text('${S.t('Pay')} $price'),
                  ),
                  const SizedBox(height: 8),
                  Text(S.t('A prompt comes to your phone: enter your mobile-money PIN to pay.'),
                      textAlign: TextAlign.center, style: t.textTheme.bodySmall?.copyWith(color: t.colorScheme.outline)),
                ]),
              ),
            _Step.waiting => Padding(
                key: const ValueKey('wait'),
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 28),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const _Pulse(),
                  const SizedBox(height: 20),
                  Text(S.t('Enter your PIN on your phone'), textAlign: TextAlign.center, style: t.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 8),
                  Text(S.t('A payment prompt for {amount} was sent to {phone}. Keep this screen open.', {'amount': price, 'phone': phone.text.trim()}),
                      textAlign: TextAlign.center, style: TextStyle(color: t.colorScheme.outline)),
                  const SizedBox(height: 20),
                  const SnProgressBar(minHeight: 4,),
                  const SizedBox(height: 12),
                  SnButton(variant: SnVariant.ghost, size: SnSize.small, onPressed: () => Navigator.pop(context, false), child: Text(S.t('Close (the code also comes by SMS)'))),
                ]),
              ),
            _Step.paid => Padding(
                key: const ValueKey('paid'),
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const Center(child: CircleAvatar(radius: 38, backgroundColor: kGood, child: Icon(Icons.check_rounded, color: Colors.white, size: 48))),
                  const SizedBox(height: 16),
                  Text(S.t('Paid! Thank you'), textAlign: TextAlign.center, style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900)),
                  const SizedBox(height: 6),
                  if (result?['code'] != null) ...[
                    Text(S.t('Your Wi-Fi code'), textAlign: TextAlign.center, style: TextStyle(color: t.colorScheme.outline)),
                    const SizedBox(height: 10),
                    InkWell(
                      borderRadius: BorderRadius.circular(16),
                      onTap: () {
                        Clipboard.setData(ClipboardData(text: '${result!['code']}'));
                        toast(context, S.t('Copied'));
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        decoration: BoxDecoration(
                          color: Sn.brand(context).withValues(alpha: 0.06),
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(color: Sn.brand(context).withValues(alpha: 0.25), width: 1.5),
                        ),
                        child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                          Text('${result!['code']}', style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900, letterSpacing: 5, fontFamily: 'monospace')),
                          const SizedBox(width: 10),
                          const Icon(Icons.copy_rounded, size: 20),
                        ]),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      result?['reyee'] == true
                          ? (result?['ready'] == true
                              ? S.t('Connect to the Wi-Fi and type this code on the login page.')
                              : S.t('Getting your code ready on the Wi-Fi. In a minute, connect and type it on the login page.'))
                          : S.t('Connect to the Wi-Fi: this phone goes online by itself, or type the code on the login page.'),
                      textAlign: TextAlign.center,
                    ),
                  ] else
                    Text(S.t('Your friend gets the code by SMS on {phone}.', {'phone': friend.text.trim()}), textAlign: TextAlign.center),
                  const SizedBox(height: 20),
                  SnButton(onPressed: () => Navigator.pop(context, true), child: Text(S.t('Done'))),
                ]),
              ),
            _Step.failed => Padding(
                key: const ValueKey('failed'),
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const Center(child: CircleAvatar(radius: 34, backgroundColor: kBad, child: Icon(Icons.close_rounded, color: Colors.white, size: 40))),
                  const SizedBox(height: 14),
                  Text(S.t('Payment not completed'), textAlign: TextAlign.center, style: t.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 8),
                  Text('${result?['message'] ?? ''}', textAlign: TextAlign.center, style: TextStyle(color: t.colorScheme.outline)),
                  const SizedBox(height: 20),
                  SnButton(onPressed: () => setState(() => step = _Step.form), child: Text(S.t('Try again'))),
                  SnButton(variant: SnVariant.ghost, size: SnSize.small, onPressed: () => Navigator.pop(context, false), child: Text(S.t('Cancel'))),
                ]),
              ),
          },
        ),
      ),
    );
  }
}

/// A phone with rings going out: waiting for the PIN.
class _Pulse extends StatefulWidget {
  const _Pulse();

  @override
  State<_Pulse> createState() => _PulseState();
}

class _PulseState extends State<_Pulse> with SingleTickerProviderStateMixin {
  late final AnimationController c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1600))..repeat();

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 140,
        height: 140,
        child: AnimatedBuilder(
          animation: c,
          builder: (_, _) => Stack(alignment: Alignment.center, children: [
            for (var i = 0; i < 2; i++)
              Builder(builder: (_) {
                final p = (c.value + i / 2) % 1;
                return Container(
                  width: 70 + p * 70,
                  height: 70 + p * 70,
                  decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: kAccent.withValues(alpha: 1 - p), width: 2)),
                );
              }),
            Container(
              width: 70,
              height: 70,
              decoration: const BoxDecoration(shape: BoxShape.circle, gradient: LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)])),
              child: const Icon(Icons.phonelink_ring_rounded, color: Colors.white, size: 34),
            ),
          ]),
        ),
      );
}
