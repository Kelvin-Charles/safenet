import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/kit.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';
import '../web_page.dart';

/// One change on a site's Ruijie Cloud; true when done (the server's message is shown either way).
Future<bool> reyeeDo(BuildContext context, int site, Map<String, dynamic> body) async {
  final api = context.read<Session>().api;
  final r = await attempt(context, () => api.post('/api/m/sites/$site/reyee', body));
  if (r != null && context.mounted) toast(context, '${r['message']}');
  return r != null;
}

Future<bool> reyeeBlock(BuildContext context, int site, String mac) async {
  if (!await confirm(context, S.t('Block this phone? It cannot join this Wi-Fi until you unblock it.'), yes: S.t('Block'), danger: true)) return false;
  return context.mounted && await reyeeDo(context, site, {'action': 'block', 'mac': mac});
}

/// Run a site's Reyee access points: restart, Wi-Fi, who is logged in, blocked phones.
class ReyeeScreen extends StatefulWidget {
  const ReyeeScreen({super.key, required this.siteId, required this.siteName});
  final int siteId;
  final String siteName;

  @override
  State<ReyeeScreen> createState() => _ReyeeScreenState();
}

class _ReyeeScreenState extends State<ReyeeScreen> {
  final mac = TextEditingController(), note = TextEditingController();
  bool busy = false;

  @override
  void dispose() {
    mac.dispose();
    note.dispose();
    super.dispose();
  }

  Future<bool> act(Map<String, dynamic> body, Future<void> Function() reload, {String? ask, String? yes}) async {
    if (busy) return false;
    if (ask != null && !await confirm(context, ask, yes: yes, danger: true)) return false;
    if (!mounted) return false;
    setState(() => busy = true);
    final ok = await reyeeDo(context, widget.siteId, body);
    if (ok) await reload();
    if (mounted) setState(() => busy = false);
    return ok;
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final small = Theme.of(context).textTheme.bodySmall;
    return Scaffold(
      appBar: SnAppBar(title: Text(widget.siteName)),
      body: Loader<Map<String, dynamic>>(
        load: () => s.api.get('/api/m/sites/${widget.siteId}/reyee'),
        builder: (context, d, reload) {
          if (d['error'] != null) {
            return ErrorView(message: S.t('Ruijie Cloud did not answer: {error}', {'error': d['error']}), onRetry: reload);
          }
          final aps = (d['aps'] as List).cast<Map>(), wifi = (d['wifi'] as List).cast<Map>(), portals = (d['portals'] as List).cast<Map>();
          final blocked = (d['blocked'] as List).cast<Map>(), guests = (d['guests'] as List).cast<Map>();
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
              if (busy) const Padding(padding: EdgeInsets.only(bottom: 8), child: SnProgressBar()),
              SectionTitle(S.t('Access points')),
              if (aps.isEmpty) SnCard(child: EmptyView(icon: Icons.router_outlined, text: S.t('None yet.'))),
              for (final a in aps)
                SnCard(
                  margin: const EdgeInsets.only(bottom: 10),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    SnTile(
                      leading: Icon(Icons.router_rounded, size: 30, color: a['online'] == true ? kGood : kBad),
                      title: Text('${a['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                      subtitle: Text([
                        a['model'],
                        a['sn'],
                        if (a['online'] != true && a['last_online'] != null) S.t('last seen {time}', {'time': when(a['last_online'] as String?)}),
                      ].join(' · ')),
                      trailing: Pill(a['online'] == true ? S.t('Online') : S.t('Offline'), color: a['online'] == true ? kGood : kBad),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
                      child: a['online'] == true
                          ? Align(
                              alignment: Alignment.centerRight,
                              child: SnButton.icon(
                                variant: SnVariant.ghost,
                                size: SnSize.small,
                                icon: const Icon(Icons.restart_alt_rounded, size: 18),
                                label: Text(S.t('Restart')),
                                onPressed: busy
                                    ? null
                                    : () => act({'action': 'reboot', 'sn': a['sn']}, reload,
                                        ask: S.t('Restart {name}? Guests drop off for about 2 minutes.', {'name': a['name']}), yes: S.t('Restart')),
                              ),
                            )
                          : Text(S.t('Check that it has power and its cable goes to a router with internet.'), style: small?.copyWith(color: kBad)),
                    ),
                  ]),
                ),
              SectionTitle(S.t('Wi-Fi')),
              if (wifi.isEmpty) SnCard(child: EmptyView(icon: Icons.wifi_off_rounded, text: S.t('None yet.'))),
              for (final w in wifi)
                SnCard(
                  margin: const EdgeInsets.only(bottom: 10),
                  child: SnTile(
                    leading: Icon(w['enable'] == true ? Icons.wifi_rounded : Icons.wifi_off_rounded, color: w['enable'] == true ? kAccent : Colors.grey),
                    title: Text('${w['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                    subtitle: Text([
                      w['enable'] == true ? S.t('On') : S.t('Off'),
                      w['secure'] == true ? S.t('With a password') : S.t('Open'),
                      if (w['hidden'] == true) S.t('Hidden name'),
                    ].join(' · ')),
                    trailing: const Icon(Icons.edit_outlined, size: 20),
                    onTap: busy
                        ? null
                        : () async {
                            final saved = await showSnSheet<bool>(
                              context: context,
                              isScrollControlled: true,
                              builder: (_) => _WifiSheet(siteId: widget.siteId, net: w),
                            );
                            if (saved == true && mounted) await reload();
                          },
                  ),
                ),
              SectionTitle(S.t('Login page')),
              SnCard(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    if (portals.isEmpty) Text(S.t('No login page on Ruijie Cloud yet.')),
                    for (final p in portals) ...[
                      Text([p['name'], ...(p['wifi'] as List)].join(' · '), style: const TextStyle(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 6),
                      Wrap(spacing: 6, runSpacing: 6, children: [for (final a in p['auth'] as List) Pill('$a')]),
                      if (p['one_click'] == true && d['trial_minutes'] == null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(S.t('Free trial is off, so phones that log in free (One-Click) are logged out automatically within a few minutes.'), style: small),
                        ),
                      const SizedBox(height: 8),
                    ],
                    Text(S.t('Free trial: {state}', {'state': d['trial_minutes'] == null ? S.t('Off') : minutesLabel((d['trial_minutes'] as num).toInt())}), style: small),
                    Align(
                      alignment: Alignment.centerRight,
                      child: SnButton(
                        variant: SnVariant.ghost,
                        size: SnSize.small,
                        onPressed: () async {
                          await openWeb(context, S.t('Login page design'), '/portal');
                          if (mounted) await reload();
                        },
                        child: Text(S.t('Change')),
                      ),
                    ),
                  ]),
                ),
              ),
              SectionTitle('${S.t('Logged in now')} (${guests.length})'),
              if (guests.any((g) => g['free'] == true))
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: SnButton.icon(
                    variant: SnVariant.danger,
                    size: SnSize.medium,
                    icon: const Icon(Icons.person_remove_rounded, size: 18),
                    label: Text(S.t('Disconnect free logins')),
                    onPressed: busy
                        ? null
                        : () => act({'action': 'free'}, reload, ask: S.t('Log out every phone that came in free (not with a code)?'), yes: S.t('Disconnect')),
                  ),
                ),
              if (guests.isEmpty) SnCard(child: EmptyView(icon: Icons.people_outline_rounded, text: S.t('Nobody is logged in right now.'))),
              for (final g in guests)
                SnCard(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: SnTile(
                    title: Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                      if ('${g['code'] ?? ''}'.isNotEmpty) Text('${g['code']}', style: const TextStyle(fontWeight: FontWeight.w700, fontFamily: 'monospace')),
                      if (g['free'] == true) Pill(S.t('Free (One-Click)'), color: kWarn),
                      if (g['state'] == 'expired' || g['state'] == 'disabled') Pill(stateLabel(g['state'] as String?), color: kBad),
                    ]),
                    subtitle: Text([
                      '${g['mac'] ?? ''}'.toUpperCase(),
                      if (g['signal'] != null) '${g['signal']} dBm',
                      if (g['since'] != null) when(g['since'] as String?),
                    ].join(' · ')),
                    trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                      SnIconButton(
                        icon: const Icon(Icons.logout_rounded, size: 20),
                        tooltip: S.t('Log out'),
                        onPressed: busy ? null : () => act({'action': 'kick', 'mac': g['mac']}, reload, ask: S.t('Log this phone out?'), yes: S.t('Log out')),
                      ),
                      SnIconButton(
                        icon: const Icon(Icons.block_rounded, size: 20, color: kBad),
                        tooltip: S.t('Block'),
                        onPressed: busy
                            ? null
                            : () => act({'action': 'block', 'mac': g['mac']}, reload,
                                ask: S.t('Block this phone? It cannot join this Wi-Fi until you unblock it.'), yes: S.t('Block')),
                      ),
                    ]),
                  ),
                ),
              SectionTitle(S.t('Blocked phones')),
              if (blocked.isNotEmpty)
                SnCard(
                  margin: const EdgeInsets.only(bottom: 10),
                  child: Column(children: [
                    for (final b in blocked)
                      SnTile(
                        title: Text('${b['mac']}'.toUpperCase(), style: const TextStyle(fontFamily: 'monospace')),
                        subtitle: '${b['name'] ?? ''}'.isEmpty ? null : Text('${b['name']}'),
                        trailing: SnButton(
                          variant: SnVariant.ghost,
                          size: SnSize.small,
                          onPressed: busy ? null : () => act({'action': 'unblock', 'mac': b['mac']}, reload),
                          child: Text(S.t('Unblock')),
                        ),
                      ),
                  ]),
                ),
              FieldGroup(children: [
                SnField(controller: mac, autocorrect: false, decoration: InputDecoration(labelText: S.t('Phone MAC address'), hintText: '8e:4a:3b:ef:71:6c')),
                SnField(controller: note, decoration: InputDecoration(labelText: S.t('Note (optional)'))),
                SnButton(
                  variant: SnVariant.danger,
                  size: SnSize.medium,
                  onPressed: busy
                      ? null
                      : () async {
                          if (await act({'action': 'block', 'mac': mac.text.trim(), 'name': note.text.trim()}, reload)) {
                            mac.clear();
                            note.clear();
                          }
                        },
                  child: Text(S.t('Block')),
                ),
              ]),
            ]),
          );
        },
      ),
    );
  }
}

class _WifiSheet extends StatefulWidget {
  const _WifiSheet({required this.siteId, required this.net});
  final int siteId;
  final Map net;

  @override
  State<_WifiSheet> createState() => _WifiSheetState();
}

class _WifiSheetState extends State<_WifiSheet> {
  late final name = TextEditingController(text: '${widget.net['name']}');
  final password = TextEditingController();
  late bool secure = widget.net['secure'] == true, enable = widget.net['enable'] == true, hidden = widget.net['hidden'] == true;
  bool busy = false;
  String? error;

  @override
  void dispose() {
    name.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> save() async {
    final api = context.read<Session>().api;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final r = await api.post('/api/m/sites/${widget.siteId}/reyee', {
        'action': 'wifi', 'ssid_id': widget.net['id'], 'name': name.text.trim(), 'security': secure ? 'wpa2-psk' : 'open',
        'password': secure ? password.text : '', 'enable': enable, 'hidden': hidden,
      });
      if (!mounted) return;
      toast(context, '${r['message']}');
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          busy = false;
          error = '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              SnField(controller: name, maxLength: 32, decoration: InputDecoration(labelText: S.t('Wi-Fi name'), prefixIcon: const Icon(Icons.wifi_rounded))),
              const SizedBox(height: 12),
              SnSelect<bool>(
                label: S.t('Security'),
                value: secure,
                items: {false: S.t('Open (guests log in on the login page)'), true: S.t('Password (WPA2)')},
                onChanged: (v) => setState(() => secure = v),
              ),
              if (secure) ...[
                const SizedBox(height: 12),
                SnField(
                  controller: password,
                  obscureText: true,
                  decoration: InputDecoration(
                    labelText: S.t('New password'),
                    helperText: widget.net['secure'] == true ? S.t('Leave empty to keep the password.') : S.t('At least 8 characters'),
                  ),
                ),
                const SizedBox(height: 8),
                Text(S.t('With a password, guests need it before they see the login page.'), style: Theme.of(context).textTheme.bodySmall),
              ],
              SwitchRow(title: S.t('On'), value: enable, onChanged: (v) => setState(() => enable = v)),
              SwitchRow(title: S.t('Hidden name'), value: hidden, onChanged: (v) => setState(() => hidden = v)),
              if (error != null) Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(error!, style: const TextStyle(color: kBad))),
              SnButton(onPressed: busy ? null : save, loading: busy, child: Text(S.t('Save Wi-Fi'))),
            ]),
          ),
        ),
      );
}
