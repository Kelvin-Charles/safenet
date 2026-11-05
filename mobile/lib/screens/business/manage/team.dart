import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/format.dart';
import '../../../core/session.dart';
import '../../../core/strings.dart';
import '../../../ui/form_bits.dart';
import '../../../ui/theme.dart';
import '../../../ui/widgets.dart';
import '../../../ui/kit.dart';

class TeamScreen extends StatefulWidget {
  const TeamScreen({super.key});

  @override
  State<TeamScreen> createState() => _TeamScreenState();
}

class _TeamScreenState extends State<TeamScreen> {
  int key = 0;

  static Color roleColor(String r) => switch (r) { 'owner' => kNavy, 'admin' => kAccent, 'staff' => kGood, _ => kGold };

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return Loader<Map<String, dynamic>>(
      reloadKey: key,
      load: () => s.api.get('/api/m/team'),
      builder: (context, d, reload) => Scaffold(
        appBar: SnAppBar(title: Text(S.t('Team'))),
        floatingActionButton: SnFab(
          onPressed: () async {
            final added = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => _AddMember(data: d)));
            if (added == true) setState(() => key++);
          },
          icon: const Icon(Icons.person_add_alt_1_rounded),
          label: Text(S.t('Add someone')),
        ),
        body: RefreshIndicator(
          onRefresh: reload,
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 96), children: [
            for (final m in d['items'] as List)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: SnCard(
                  child: SnTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                    leading: CircleAvatar(
                      backgroundColor: roleColor(m['role'] as String).withValues(alpha: 0.14),
                      child: Text((m['username'] as String).substring(0, 1).toUpperCase(),
                          style: TextStyle(color: roleColor(m['role'] as String), fontWeight: FontWeight.w800)),
                    ),
                    title: Row(children: [
                      Flexible(child: Text('${m['username']}', style: const TextStyle(fontWeight: FontWeight.w700), overflow: TextOverflow.ellipsis)),
                      if (m['me'] == true) Padding(padding: const EdgeInsets.only(left: 6), child: Pill(S.t('You'))),
                      if (m['active'] != true) Padding(padding: const EdgeInsets.only(left: 6), child: Pill(S.t('Disabled'), color: kBad)),
                    ]),
                    subtitle: Text([m['role_label'], if (m['site'] != null) m['site'], if (m['last_login'] != null) ago(m['last_login'] as String?)].join(' · ')),
                    trailing: m['manageable'] == true
                        ? SnMenuButton<String>(
                            onSelected: (v) async {
                              if (v == 'toggle') {
                                if (await attempt(context, () => s.api.post('/api/m/team/${m['id']}/toggle')) != null) reload();
                              } else if (await confirm(context, S.t('Remove {name} from the team?', {'name': m['username']}), yes: S.t('Remove'), danger: true)) {
                                if (!context.mounted) return;
                                if (await attempt(context, () => s.api.delete('/api/m/team/${m['id']}')) != null) reload();
                              }
                            },
                            itemBuilder: (_) => [
                              PopupMenuItem(value: 'toggle', child: Text(m['active'] == true ? S.t('Disable') : S.t('Enable'))),
                              PopupMenuItem(value: 'delete', child: Text(S.t('Remove'), style: const TextStyle(color: kBad))),
                            ],
                          )
                        : null,
                  ),
                ),
              ),
          ]),
        ),
      ),
    );
  }
}

class _AddMember extends StatefulWidget {
  const _AddMember({required this.data});
  final Map<String, dynamic> data;

  @override
  State<_AddMember> createState() => _AddMemberState();
}

class _AddMemberState extends State<_AddMember> {
  final username = TextEditingController();
  final email = TextEditingController();
  final password = TextEditingController();
  late String role = (widget.data['roles'] as List).first as String;
  int? siteId;
  bool busy = false;

  static const _about = {
    'staff': 'Customer accounts, vouchers and who is online.',
    'admin': 'Everything except the owner.',
    'viewer': 'Sees sales and usage, changes nothing. For partners and shareholders.',
  };
  static const _names = {'staff': 'Staff', 'admin': 'Admin', 'viewer': 'Partner (view only)'};

  Future<void> save() async {
    setState(() => busy = true);
    final r = await attempt(context, () => context.read<Session>().api.post('/api/m/team', {
          'username': username.text.trim(), 'email': email.text.trim(), 'password': password.text, 'role': role, 'site_id': siteId,
        }));
    if (!mounted) return;
    setState(() => busy = false);
    if (r != null) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: SnAppBar(title: Text(S.t('Add someone'))),
        bottomNavigationBar: SaveBar(busy: busy, onSave: save, label: S.t('Add')),
        body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
          FieldGroup(title: S.t('Role'), children: [
            for (final r in widget.data['roles'] as List)
              InkWell(
                borderRadius: BorderRadius.circular(14),
                onTap: () => setState(() => role = r as String),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: role == r ? Theme.of(context).colorScheme.primary : Theme.of(context).colorScheme.outlineVariant, width: role == r ? 2 : 1),
                  ),
                  child: Row(children: [
                    Icon(role == r ? Icons.radio_button_checked : Icons.radio_button_off, color: role == r ? Theme.of(context).colorScheme.primary : null),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(S.t(_names[r]!), style: const TextStyle(fontWeight: FontWeight.w700)),
                        Text(S.t(_about[r]!), style: Theme.of(context).textTheme.bodySmall),
                      ]),
                    ),
                  ]),
                ),
              ),
            if (role == 'viewer' && (widget.data['sites'] as List).length > 1)
              PickField(label: S.t('Can see'), icon: Icons.place_outlined, items: widget.data['sites'] as List, value: siteId,
                  none: S.t('The whole business'), onChanged: (v) => setState(() => siteId = v)),
          ]),
          FieldGroup(title: S.t('Account'), children: [
            SnField(controller: username, autocorrect: false, decoration: InputDecoration(labelText: S.t('Username'), prefixIcon: const Icon(Icons.alternate_email_rounded))),
            SnField(controller: email, keyboardType: TextInputType.emailAddress, decoration: InputDecoration(labelText: S.t('Email'), prefixIcon: const Icon(Icons.mail_outline_rounded))),
            SnField(controller: password, decoration: InputDecoration(labelText: S.t('Temporary password'), helperText: S.t('Give it to them; they can change it later.'), prefixIcon: const Icon(Icons.key_outlined))),
          ]),
        ]),
      );
}
