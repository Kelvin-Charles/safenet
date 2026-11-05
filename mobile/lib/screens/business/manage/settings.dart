import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/widgets.dart';
import '../web_page.dart';

/// Business settings: names, support phone, guest terms, hotspot sharing, and the owner's alerts.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  Map<String, dynamic>? d;
  final name = TextEditingController();
  final hotspot = TextEditingController();
  final support = TextEditingController();
  final terms = TextEditingController();
  final alertPhone = TextEditingController();
  bool tether = false, saleSms = false, dailySms = false, dailyEmail = false, busy = false;

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/m/settings').then(_fill).catchError((e) {
      if (mounted) toast(context, '$e', error: true);
    });
  }

  void _fill(Map<String, dynamic> x) {
    if (!mounted) return;
    setState(() {
      d = x;
      name.text = x['name'] as String? ?? '';
      hotspot.text = x['hotspot_name'] as String? ?? '';
      support.text = x['support_phone'] as String? ?? '';
      terms.text = x['terms'] as String? ?? '';
      alertPhone.text = x['notify_phone'] as String? ?? '';
      tether = x['block_tethering'] as bool;
      saleSms = x['sale_sms'] as bool;
      dailySms = x['daily_sms'] as bool;
      dailyEmail = x['daily_email'] as bool;
    });
  }

  Future<void> save() async {
    setState(() => busy = true);
    final s = context.read<Session>();
    final r = await attempt(context, () => s.api.post('/api/m/settings', {
          'name': name.text, 'hotspot_name': hotspot.text, 'support_phone': support.text, 'terms': terms.text, 'block_tethering': tether,
          if (d?['owner'] == true) ...{'notify_phone': alertPhone.text, 'sale_sms': saleSms, 'daily_sms': dailySms, 'daily_email': dailyEmail},
        }));
    if (!mounted) return;
    setState(() => busy = false);
    if (r != null) {
      _fill(r);
      toast(context, S.t('Saved'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final x = d;
    return Scaffold(
      appBar: AppBar(title: Text(S.t('Settings'))),
      bottomNavigationBar: x == null ? null : SaveBar(busy: busy, onSave: save),
      body: x == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
              FieldGroup(title: S.t('Business'), children: [
                TextField(controller: name, decoration: InputDecoration(labelText: S.t('Business name'), prefixIcon: const Icon(Icons.storefront_outlined))),
                TextField(controller: hotspot, decoration: InputDecoration(labelText: S.t('Wi-Fi name shown to guests'), helperText: S.t('Empty: the business name.'), prefixIcon: const Icon(Icons.wifi_rounded))),
                TextField(controller: support, keyboardType: TextInputType.phone, decoration: InputDecoration(labelText: S.t('Support phone / WhatsApp'), prefixIcon: const Icon(Icons.support_agent_rounded))),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.phone_outlined),
                  title: Text(S.t('Business phone')),
                  subtitle: Text([x['phone'] ?? '—', if (x['phone_pending'] != null) S.t('change to {p} waiting for SafeNet', {'p': x['phone_pending']})].join(' · ')),
                  trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                  onTap: () => openWeb(context, S.t('Settings'), '/settings'),
                ),
              ]),
              FieldGroup(title: S.t('Guests'), children: [
                SwitchRow(title: S.t('Block hotspot sharing'), subtitle: S.t("Guests can't share their internet through their own phone's hotspot."),
                    value: tether, onChanged: (v) => setState(() => tether = v)),
                TextField(controller: terms, maxLines: 4, minLines: 2, decoration: InputDecoration(labelText: S.t('Terms of use for guests'), alignLabelWithHint: true)),
              ]),
              if (x['owner'] == true)
                FieldGroup(title: S.t('Alerts to you'), children: [
                  TextField(controller: alertPhone, keyboardType: TextInputType.phone,
                      decoration: InputDecoration(labelText: S.t('Phone for alerts'), helperText: S.t('Empty: the business phone.'), prefixIcon: const Icon(Icons.notifications_active_outlined))),
                  SwitchRow(title: S.t('SMS for every sale'), subtitle: S.t('TZS {p} per SMS, from your balance.', {'p': x['sms_price']}), value: saleSms, onChanged: (v) => setState(() => saleSms = v)),
                  SwitchRow(title: S.t('Daily summary by SMS'), value: dailySms, onChanged: (v) => setState(() => dailySms = v)),
                  SwitchRow(title: S.t('Daily summary by email'), value: dailyEmail, onChanged: (v) => setState(() => dailyEmail = v)),
                ]),
              FieldGroup(title: S.t('More settings'), children: [
                for (final e in [
                  (Icons.account_balance_outlined, S.t('Payments & SMS to guests'), '/settings/payments'),
                  (Icons.card_giftcard_rounded, S.t('Free trial for guests'), '/settings/free-trial'),
                  (Icons.palette_outlined, S.t('Login page design'), '/portal'),
                ])
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(e.$1),
                    title: Text(e.$2),
                    trailing: const Icon(Icons.chevron_right_rounded),
                    onTap: () => openWeb(context, e.$2, e.$3),
                  ),
              ]),
            ]),
    );
  }
}
