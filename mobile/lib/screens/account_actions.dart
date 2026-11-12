import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../core/session.dart';
import '../core/strings.dart';
import '../ui/kit.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

/// SafeNet's privacy policy, in the browser.
Future<void> openPrivacy() => launchUrl(Uri.parse('$kServer/privacy${S.lang == 'sw' ? '#sw' : ''}'), mode: LaunchMode.externalApplication);

/// Ask for the signed-in account and its data to be deleted (the platform team does it within 30 days), then sign out.
Future<void> askToDeleteAccount(BuildContext context, {required bool guest}) async {
  final ok = await confirm(
    context,
    S.t(guest
        ? 'Delete your account? Your phone number, codes and Wi-Fi history are deleted within 30 days. Payment records are kept as the law requires.'
        : 'Delete your account? Your login and the business data are deleted within 30 days (we may call to check it is you). Payment records are kept as the law requires.'),
    yes: S.t('Delete my account'),
    danger: true,
  );
  if (!ok || !context.mounted) return;
  final s = context.read<Session>();
  final r = await attempt(context, () => s.api.post(guest ? '/api/m/guest/account/delete' : '/api/m/account/delete'));
  if (r == null || !context.mounted) return;
  toast(context, '${r['message'] ?? S.t('Request received.')}');
  await s.signOut();
}

/// Privacy policy and Delete my account, at the bottom of the More screen.
class AccountActions extends StatelessWidget {
  const AccountActions({super.key, this.guest = false});
  final bool guest;

  @override
  Widget build(BuildContext context) => SnCard(
        child: Column(children: [
          SnTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: Text(S.t('Privacy policy')),
            trailing: const Icon(Icons.open_in_new_rounded, size: 18),
            onTap: openPrivacy,
          ),
          SnTile(
            leading: const Icon(Icons.person_remove_outlined, color: kBad),
            title: Text(S.t('Delete my account'), style: const TextStyle(color: kBad)),
            onTap: () => askToDeleteAccount(context, guest: guest),
          ),
        ]),
      );
}
