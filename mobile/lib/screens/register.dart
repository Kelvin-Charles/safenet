import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api.dart';
import '../core/session.dart';
import '../core/strings.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import '../ui/kit.dart';

/// Register a business, as on the web: a free trial business and its owner. Then confirm the email and sign in.
class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key, this.trialDays});
  final int? trialDays;

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final business = TextEditingController();
  final username = TextEditingController();
  final email = TextEditingController();
  final phone = TextEditingController();
  final password = TextEditingController();
  bool hide = true, accept = false, busy = false;
  Map<String, String> fields = {};
  String? error, doneEmail;

  Future<void> submit() async {
    setState(() {
      busy = true;
      error = null;
      fields = {};
    });
    try {
      final r = await context.read<Session>().register({
        'business_name': business.text.trim(),
        'username': username.text.trim(),
        'email': email.text.trim(),
        'phone': phone.text.trim(),
        'password': password.text,
        'accept': accept,
      });
      if (mounted) setState(() => doneEmail = r['email'] as String?);
    } on ApiError catch (e) {
      if (mounted) setState(() {
        fields = e.fields;
        error = fields.isEmpty ? e.message : null;
      });
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  int get strength {
    final p = password.text;
    var n = 0;
    if (p.length >= 8) n++;
    if (p.length >= 12) n++;
    if (RegExp(r'[A-Z]').hasMatch(p) && RegExp(r'[a-z]').hasMatch(p)) n++;
    if (RegExp(r'[0-9]').hasMatch(p) && RegExp(r'[^A-Za-z0-9]').hasMatch(p)) n++;
    return n;
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    if (doneEmail != null) return _Done(email: doneEmail!);
    InputDecoration deco(String label, IconData icon, String key, {String? helper}) =>
        InputDecoration(labelText: label, prefixIcon: Icon(icon), errorText: fields[key], helperText: helper);
    final colors = [kBad, kBad, kWarn, kGood, kGood];
    return Scaffold(
      appBar: SnAppBar(title: Text(S.t('Register your business'))),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.fromLTRB(20, 4, 20, 24), children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(18),
              gradient: const LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)]),
            ),
            child: Row(children: [
              const Icon(Icons.rocket_launch_rounded, color: Colors.white, size: 32),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(
                    widget.trialDays != null && widget.trialDays! > 0
                        ? S.t('Free for {n} days', {'n': widget.trialDays})
                        : S.t('Start selling Wi-Fi today'),
                    style: t.textTheme.titleMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 2),
                  Text(S.t('Vouchers, mobile-money payments and your customers, from one place.'),
                      style: t.textTheme.bodySmall?.copyWith(color: Colors.white70)),
                ]),
              ),
            ]),
          ),
          const SizedBox(height: 20),
          AutofillGroup(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              SnField(
                controller: business,
                textCapitalization: TextCapitalization.words,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.organizationName],
                decoration: deco(S.t('Business name'), Icons.storefront_outlined, 'business_name', helper: S.t('Guests see it on the login page.')),
              ),
              const SizedBox(height: 14),
              SnField(
                controller: username,
                autocorrect: false,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.newUsername],
                decoration: deco(S.t('Username'), Icons.alternate_email_rounded, 'username'),
              ),
              const SizedBox(height: 14),
              SnField(
                controller: email,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.email],
                decoration: deco(S.t('Email'), Icons.mail_outline_rounded, 'email', helper: S.t('We send a link to confirm it.')),
              ),
              const SizedBox(height: 14),
              SnField(
                controller: phone,
                keyboardType: TextInputType.phone,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.telephoneNumber],
                decoration: deco('${S.t('Phone number')} (${S.t('optional')})', Icons.phone_outlined, 'phone'),
              ),
              const SizedBox(height: 14),
              SnField(
                controller: password,
                obscureText: hide,
                autofillHints: const [AutofillHints.newPassword],
                onChanged: (_) => setState(() {}),
                decoration: deco(S.t('Password'), Icons.lock_outline_rounded, 'password', helper: S.t('At least 8 characters.')).copyWith(
                  suffixIcon: SnIconButton(
                      icon: Icon(hide ? Icons.visibility_outlined : Icons.visibility_off_outlined), onPressed: () => setState(() => hide = !hide)),
                ),
              ),
              if (password.text.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Row(children: [
                    for (var i = 0; i < 4; i++)
                      Expanded(
                        child: Container(
                          height: 4,
                          margin: const EdgeInsets.only(right: 4),
                          decoration: BoxDecoration(
                            color: i < strength ? colors[strength] : t.colorScheme.outlineVariant.withValues(alpha: 0.5),
                            borderRadius: BorderRadius.circular(4),
                          ),
                        ),
                      ),
                  ]),
                ),
            ]),
          ),
          const SizedBox(height: 10),
          SnCheckTile(
            contentPadding: EdgeInsets.zero,
            value: accept,
            onChanged: (v) => setState(() => accept = v == true),
            title: Text(S.t('I accept the terms of service')),
            subtitle: fields['accept'] != null ? Text(fields['accept']!, style: const TextStyle(color: kBad)) : null,
          ),
          if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: const TextStyle(color: kBad))),
          const SizedBox(height: 8),
          SnButton(
            onPressed: busy ? null : submit,
            child: busy ? const SizedBox(width: 22, height: 22, child: SnSpinner(strokeWidth: 2.5)) : Text(S.t('Create account')),
          ),
          const SizedBox(height: 12),
          SnButton(variant: SnVariant.ghost, size: SnSize.small, onPressed: () => Navigator.pop(context), child: Text(S.t('I already have an account'))),
          const PoweredBy(),
        ]),
      ),
    );
  }
}

class _Done extends StatelessWidget {
  const _Done({required this.email});
  final String email;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Center(
              child: Container(
                padding: const EdgeInsets.all(22),
                decoration: BoxDecoration(color: kGood.withValues(alpha: 0.12), shape: BoxShape.circle),
                child: const Icon(Icons.mark_email_read_rounded, color: kGood, size: 56),
              ),
            ),
            const SizedBox(height: 24),
            Text(S.t('Check your email'), textAlign: TextAlign.center, style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            Text(S.t('We sent a link to {email}. Open it to confirm your account, then sign in.', {'email': email}),
                textAlign: TextAlign.center, style: t.textTheme.bodyLarge?.copyWith(color: t.colorScheme.outline)),
            const SizedBox(height: 32),
            SnButton(onPressed: () => Navigator.pop(context), child: Text(S.t('Back to sign in'))),
            const SizedBox(height: 8),
            SnButton(variant: SnVariant.ghost, size: SnSize.small,
              onPressed: () async {
                await context.read<Session>().resendEmail(email).catchError((_) {});
                if (context.mounted) {
                  toast(context, S.t('We sent a new link.'));
                }
              },
              child: Text(S.t('Send the link again')),
            ),
          ]),
        ),
      ),
    );
  }
}
