import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../../core/api.dart';
import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/kit.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';

/// The balance for SMS and the SafeNet plan, and adding to it by mobile money.
class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key, this.amount});
  final int? amount;

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  late final amount = TextEditingController(text: widget.amount == null ? '' : '${widget.amount}');
  final phone = TextEditingController();
  bool filled = false, busy = false;
  String? error;

  @override
  void dispose() {
    amount.dispose();
    phone.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> load() async {
    final d = await context.read<Session>().api.get('/api/m/wallet');
    if (!filled && mounted) {
      filled = true;
      phone.text = '${d['phone'] ?? ''}';
      final least = (d['least'] as num).toInt();
      if (widget.amount != null && widget.amount! < least) amount.text = '$least';
    }
    return d;
  }

  Future<void> wait(Map deposit, Future<void> Function() reload) async {
    await showSnSheet<void>(context: context, isScrollControlled: true, builder: (_) => _DepositWait(deposit: deposit));
    if (mounted) await reload();
  }

  Future<void> deposit(Future<void> Function() reload) async {
    final api = context.read<Session>().api;
    setState(() {
      busy = true;
      error = null;
    });
    Map<String, dynamic>? r;
    try {
      r = await api.post('/api/m/wallet/deposit', {'amount': amount.text.trim(), 'phone': phone.text.trim()});
    } on ApiError catch (e) {
      // no answer: the prompt may have gone out, so don't invite a second payment
      error = e.status == 0 ? S.t('No answer from SafeNet. Check your deposits below before trying again.') : e.message;
    }
    if (!mounted) return;
    setState(() => busy = false);
    r != null ? await wait(r, reload) : await reload();
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Scaffold(
      appBar: SnAppBar(title: Text(S.t('Wallet'))),
      body: Loader<Map<String, dynamic>>(
        load: load,
        builder: (context, d, reload) {
          final cur = '${d['currency']}';
          final balance = d['balance'] as num, price = d['sms_price'] as num, rate = d['fee_percent'] as num;
          final deposits = (d['deposits'] as List).cast<Map>();
          if (d['platform'] != true) {
            return EmptyView(icon: Icons.account_balance_wallet_outlined, text: S.t('SMS is added to your SafeNet bill, so you do not need to deposit.'));
          }
          final a = int.tryParse(amount.text.replaceAll(',', '').trim()) ?? 0;
          final pays = (double.parse((a * 100 / (100 - rate)).toStringAsFixed(6))).ceil();
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(borderRadius: BorderRadius.circular(24), gradient: const LinearGradient(colors: [Color(0xFF0B7A3B), kGood])),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(S.t('SafeNet Pay balance'), style: const TextStyle(color: Colors.white70)),
                  const SizedBox(height: 6),
                  Text(money(balance, cur), style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.w800)),
                  if (price > 0)
                    Text(S.t('About {n} SMS at {price} each', {'n': balance > 0 ? balance ~/ price : 0, 'price': money(price, cur)}), style: const TextStyle(color: Colors.white70)),
                  if ((d['unspent'] as num) > 0)
                    Text(S.t('Deposited and not used yet: {amount}', {'amount': money(d['unspent'] as num, cur)}), style: const TextStyle(color: Colors.white70)),
                ]),
              ),
              const SizedBox(height: 16),
              if (d['ready'] != true)
                SnCard(child: EmptyView(icon: Icons.phonelink_erase_rounded, text: S.t('Online payment is not available right now. Please contact SafeNet.')))
              else
                FieldGroup(title: S.t('Deposit money'), children: [
                  SnField(
                    controller: amount,
                    keyboardType: TextInputType.number,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    onChanged: (_) => setState(() {}),
                    decoration: InputDecoration(
                      labelText: S.t('Amount ({cur})', {'cur': cur}),
                      helperText: S.t('From {least} to {most}', {'least': money(d['least'] as num, cur), 'most': money(d['most'] as num, cur)}),
                      prefixIcon: const Icon(Icons.payments_outlined),
                    ),
                  ),
                  SnField(
                    controller: phone,
                    keyboardType: TextInputType.phone,
                    decoration: InputDecoration(labelText: S.t('Number that pays'), hintText: '07XX XXX XXX', prefixIcon: const Icon(Icons.phone_iphone_rounded)),
                  ),
                  if (rate > 0 && a > 0)
                    Text(S.t('Mobile-money fee: {fee} · You pay: {pays}', {'fee': money(pays - a, cur), 'pays': money(pays, cur)}),
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (error != null) Text(error!, style: const TextStyle(color: kBad)),
                  SnButton.icon(
                    onPressed: busy || a <= 0 ? null : () => deposit(reload),
                    loading: busy,
                    icon: const Icon(Icons.add_rounded),
                    label: Text(S.t('Deposit')),
                  ),
                  Text(S.t('Deposits pay for SMS and your SafeNet plan. They cannot be withdrawn; your sales can.'), style: t.textTheme.bodySmall),
                ]),
              SectionTitle(S.t('Deposits')),
              SnCard(
                child: deposits.isEmpty
                    ? EmptyView(icon: Icons.account_balance_wallet_outlined, text: S.t('None yet.'))
                    : Column(children: [
                        for (final x in deposits)
                          SnTile(
                            title: Text(money(x['amount'] as num, cur), style: const TextStyle(fontWeight: FontWeight.w700)),
                            subtitle: Text([
                              when(x['created'] as String?),
                              localPhone(x['phone'] as String?),
                              '${x['reference']}',
                              if (x['status'] == 'failed' && x['message'] != null) '${x['message']}',
                            ].join(' · ')),
                            trailing: Pill(
                              switch (x['status']) { 'paid' => S.t('paid'), 'pending' => S.t('pending'), 'review' => S.t('Being checked'), _ => S.t('failed') },
                              color: switch (x['status']) { 'paid' => kGood, 'failed' => kBad, _ => kWarn },
                            ),
                            onTap: x['status'] == 'pending' ? () => wait(x, reload) : null,
                          ),
                      ]),
              ),
            ]),
          );
        },
      ),
    );
  }
}

/// Waiting for the PIN, then how the deposit ended.
class _DepositWait extends StatefulWidget {
  const _DepositWait({required this.deposit});
  final Map deposit;

  @override
  State<_DepositWait> createState() => _DepositWaitState();
}

class _DepositWaitState extends State<_DepositWait> {
  late Map d = widget.deposit;
  Timer? poll;
  bool asking = false;

  @override
  void initState() {
    super.initState();
    final end = DateTime.now().add(const Duration(minutes: 5));
    poll = Timer.periodic(const Duration(seconds: 3), (t) async {
      if (DateTime.now().isAfter(end)) {
        t.cancel();
        if (mounted) setState(() {});
        return;
      }
      if (asking) return;
      asking = true;
      try {
        final r = await context.read<Session>().api.get('/api/m/wallet/deposit/${widget.deposit['reference']}');
        if (!mounted) return;
        if (r['status'] != 'pending') {
          t.cancel();
          if (r['status'] == 'paid') HapticFeedback.mediumImpact();
        }
        setState(() => d = r);
      } catch (_) {
      } finally {
        asking = false;
      }
    });
  }

  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final status = d['status'];
    final waiting = status == 'pending';
    final cur = context.read<Session>().me?['tenant']?['currency'] as String? ?? 'TZS';
    final (title, text) = switch (status) {
      'paid' => (S.t('Deposit received'), S.t('Your balance is now {amount}.', {'amount': money(d['balance'] as num?, cur)})),
      'pending' when poll?.isActive != true => (S.t('Still waiting'), S.t("If you've paid, your balance will update by itself.")),
      'pending' => (
          S.t('Enter your PIN on your phone'),
          S.t('A payment prompt for {amount} was sent to {phone}. Keep this screen open.', {'amount': money(d['pays'] as num, cur), 'phone': localPhone(d['phone'] as String?)})
        ),
      'review' => (S.t('Payment needs checking'), S.t('SafeNet is checking this payment.')),
      _ => (S.t('Payment not completed'), '${d['message'] ?? S.t('Try again')}'),
    };
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Icon(
            switch (status) { 'paid' => Icons.check_circle_rounded, 'pending' => Icons.phonelink_ring_rounded, 'review' => Icons.hourglass_top_rounded, _ => Icons.cancel_rounded },
            size: 72,
            color: switch (status) { 'paid' => kGood, 'pending' => kAccent, 'review' => kWarn, _ => kBad },
          ),
          const SizedBox(height: 14),
          Text(title, textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(text, textAlign: TextAlign.center),
          const SizedBox(height: 18),
          if (waiting && poll?.isActive == true) const SnProgressBar(),
          const SizedBox(height: 12),
          SnButton(variant: waiting ? SnVariant.ghost : SnVariant.primary, onPressed: () => Navigator.pop(context), child: Text(waiting ? S.t('Close') : S.t('Done'))),
        ]),
      ),
    );
  }
}
