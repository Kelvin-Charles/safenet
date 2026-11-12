import 'dart:async';

import 'package:flutter/material.dart';
import 'account_actions.dart' show openPrivacy;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../core/session.dart';
import '../core/strings.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import '../ui/wifi_hero.dart';
import 'guest/here_banner.dart';
import 'register.dart';
import '../ui/kit.dart';

/// Sign in: a business (username + password, or register) or a Wi-Fi customer (phone number + SMS code, or voucher).
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  bool business = false;
  Map<String, dynamic> config = const {'signup': true, 'sms_login': true};

  @override
  void initState() {
    super.initState();
    context.read<Session>().loadConfig().then((c) {
      if (mounted) setState(() => config = c);
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final t = Theme.of(context);
    final h = MediaQuery.of(context).size.height;
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: kNavyDeep,
        body: Stack(children: [
          // background: deep navy with soft light
          Positioned.fill(
            child: DecoratedBox(
              decoration: const BoxDecoration(
                gradient: LinearGradient(colors: [Color(0xFF0A2A80), kNavy, kNavyDeep], begin: Alignment.topCenter, end: Alignment.bottomCenter),
              ),
            ),
          ),
          Positioned(top: -80, right: -60, child: _Glow(size: 260, color: const Color(0xFF3B82F6).withValues(alpha: 0.35))),
          Positioned(top: h * 0.25, left: -90, child: _Glow(size: 220, color: const Color(0xFF22C55E).withValues(alpha: 0.12))),
          SafeArea(
            bottom: false,
            child: CustomScrollView(slivers: [
              SliverFillRemaining(
                hasScrollBody: false,
                child: Column(children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 8, 8, 0),
                    child: Row(children: [
                      Image.asset('assets/logo.png', height: 30, errorBuilder: (_, _, _) => const Icon(Icons.wifi, color: Colors.white)),
                      const SizedBox(width: 10),
                      Text('SafeNet', style: t.textTheme.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w800, letterSpacing: 0.3)),
                      const Spacer(),
                      SnButton.icon(variant: SnVariant.ghost, size: SnSize.small,
                        onPressed: () => s.setLanguage(S.lang == 'sw' ? 'en' : 'sw'),
                        icon: const Icon(Icons.translate_rounded, size: 18, color: Colors.white70),
                        label: Text(S.lang == 'sw' ? 'English' : 'Kiswahili',),
                      ),
                    ]),
                  ),
                  SizedBox(height: h < 700 ? 4 : 16),
                  WifiHero(size: (h * 0.3).clamp(170.0, 280.0)),
                  const SizedBox(height: 16),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 28),
                    child: AnimatedSwitcher(
                      duration: const Duration(milliseconds: 250),
                      child: Column(key: ValueKey(business), children: [
                        Text(business ? S.t('Run your Wi-Fi business from your phone') : S.t('Your Wi-Fi, in your pocket'),
                            textAlign: TextAlign.center,
                            style: t.textTheme.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w800, height: 1.2)),
                        const SizedBox(height: 8),
                        Text(
                          business ? S.t('Sales, vouchers, customers and who is online, all in one place.') : S.t('Your Wi-Fi: time left, data used and what you spent'),
                          textAlign: TextAlign.center,
                          style: t.textTheme.bodyMedium?.copyWith(color: Colors.white70),
                        ),
                      ]),
                    ),
                  ),
                  const Spacer(),
                  const SizedBox(height: 20),
                  const Padding(padding: EdgeInsets.symmetric(horizontal: 16), child: HereBanner()),
                  // the form card
                  Container(
                    width: double.infinity,
                    decoration: BoxDecoration(
                      color: t.colorScheme.surface,
                      borderRadius: const BorderRadius.vertical(top: Radius.circular(32)),
                    ),
                    padding: EdgeInsets.fromLTRB(22, 22, 22, 4 + MediaQuery.of(context).padding.bottom),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      _Switch(business: business, onChanged: (v) => setState(() => business = v)),
                      const SizedBox(height: 20),
                      AnimatedSize(
                        duration: const Duration(milliseconds: 220),
                        curve: Curves.easeOut,
                        child: business ? _BusinessForm(config: config) : _CustomerForm(config: config),
                      ),
                      const PoweredBy(),
                      Center(child: SnButton(variant: SnVariant.ghost, size: SnSize.small, onPressed: openPrivacy, child: Text(S.t('Privacy policy')))),
                    ]),
                  ),
                ]),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _Glow extends StatelessWidget {
  const _Glow({required this.size, required this.color});
  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) => IgnorePointer(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(shape: BoxShape.circle, gradient: RadialGradient(colors: [color, color.withValues(alpha: 0)])),
        ),
      );
}

/// "Wi-Fi customer | Business" switch.
class _Switch extends StatelessWidget {
  const _Switch({required this.business, required this.onChanged});
  final bool business;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    Widget side(bool value, IconData icon, String label) => Expanded(
          child: GestureDetector(
            onTap: () => onChanged(value),
            behavior: HitTestBehavior.opaque,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(vertical: 12),
              decoration: BoxDecoration(
                color: business == value ? c.primary : Colors.transparent,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Icon(icon, size: 18, color: business == value ? c.onPrimary : c.onSurfaceVariant),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(label,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontWeight: FontWeight.w700, color: business == value ? c.onPrimary : c.onSurfaceVariant)),
                ),
              ]),
            ),
          ),
        );
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: c.surfaceContainerHighest.withValues(alpha: 0.7), borderRadius: BorderRadius.circular(18)),
      child: Row(children: [
        side(false, Icons.smartphone_rounded, S.t('Wi-Fi customer')),
        side(true, Icons.storefront_rounded, S.t('Business')),
      ]),
    );
  }
}

class _ErrorText extends StatelessWidget {
  const _ErrorText(this.text);
  final String? text;

  @override
  Widget build(BuildContext context) => text == null
      ? const SizedBox.shrink()
      : Container(
          margin: const EdgeInsets.only(top: 12),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: kBad.withValues(alpha: 0.08), borderRadius: BorderRadius.circular(12)),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.error_outline_rounded, color: kBad, size: 20),
            const SizedBox(width: 8),
            Expanded(child: Text(text!, style: const TextStyle(color: kBad))),
          ]),
        );
}

Widget _busyButton({required bool busy, required VoidCallback? onPressed, required String label, IconData? icon}) => SnButton(
      onPressed: busy ? null : onPressed,
      child: busy
          ? const SizedBox(width: 22, height: 22, child: SnSpinner(strokeWidth: 2.5))
          : Row(mainAxisSize: MainAxisSize.min, children: [Text(label), if (icon != null) ...[const SizedBox(width: 8), Icon(icon, size: 20)]]),
    );

// ---------------------------------------------------------------- business
class _BusinessForm extends StatefulWidget {
  const _BusinessForm({required this.config});
  final Map<String, dynamic> config;

  @override
  State<_BusinessForm> createState() => _BusinessFormState();
}

class _BusinessFormState extends State<_BusinessForm> {
  final user = TextEditingController();
  final pass = TextEditingController();
  bool hide = true, busy = false;
  String? error;

  Future<void> submit() async {
    if (user.text.trim().isEmpty || pass.text.isEmpty) {
      setState(() => error = S.t('Enter your username and password.'));
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await context.read<Session>().signInBusiness(user.text.trim(), pass.text);
    } on ApiError catch (e) {
      if (!mounted) return;
      setState(() => error = e.message);
      if (e.data['unverified'] == true) _unverified(e.data['email'] as String? ?? '');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void _unverified(String email) {
    showSnDialog(
      context: context,
      builder: (c) => SnDialog(
        icon: const Icon(Icons.mark_email_unread_outlined, size: 40),
        title: Text(S.t('Confirm your email')),
        content: Text(S.t('Open the link we sent to {email}, then sign in.', {'email': email})),
        actions: [
          SnButton(variant: SnVariant.ghost, size: SnSize.small,
            onPressed: () async {
              await context.read<Session>().resendEmail(email).catchError((_) {});
              if (c.mounted) Navigator.pop(c);
              if (mounted) {
                toast(context, S.t('We sent a new link.'));
              }
            },
            child: Text(S.t('Send the link again')),
          ),
          SnButton( onPressed: () => Navigator.pop(c), child: const Text('OK')),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AutofillGroup(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SnField(
            controller: user,
            autofillHints: const [AutofillHints.username, AutofillHints.email],
            keyboardType: TextInputType.emailAddress,
            autocorrect: false,
            textInputAction: TextInputAction.next,
            decoration: InputDecoration(labelText: S.t('Username or email'), prefixIcon: const Icon(Icons.person_outline_rounded)),
          ),
          const SizedBox(height: 12),
          SnField(
            controller: pass,
            autofillHints: const [AutofillHints.password],
            obscureText: hide,
            onSubmitted: (_) => submit(),
            decoration: InputDecoration(
              labelText: S.t('Password'),
              prefixIcon: const Icon(Icons.lock_outline_rounded),
              suffixIcon: SnIconButton(
                  icon: Icon(hide ? Icons.visibility_outlined : Icons.visibility_off_outlined), onPressed: () => setState(() => hide = !hide)),
            ),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: SnButton(variant: SnVariant.ghost, size: SnSize.small,
              onPressed: () => launchUrl(Uri.parse((widget.config['forgot_url'] as String?) ?? '$kServer/forgot'), mode: LaunchMode.externalApplication),
              child: Text(S.t('Forgot password?')),
            ),
          ),
          _ErrorText(error),
          const SizedBox(height: 8),
          _busyButton(busy: busy, onPressed: submit, label: S.t('Sign in'), icon: Icons.arrow_forward_rounded),
          if (widget.config['signup'] != false) ...[
            const SizedBox(height: 14),
            Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(S.t('New to SafeNet?'), style: TextStyle(color: Theme.of(context).colorScheme.outline)),
              SnButton(variant: SnVariant.ghost, size: SnSize.small,
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => RegisterScreen(trialDays: widget.config['trial_days'] as int?))),
                child: Text(S.t('Register your business'),),
              ),
            ]),
          ],
        ]),
      );
}

// ---------------------------------------------------------------- Wi-Fi customer
class _CustomerForm extends StatefulWidget {
  const _CustomerForm({required this.config});
  final Map<String, dynamic> config;

  @override
  State<_CustomerForm> createState() => _CustomerFormState();
}

class _CustomerFormState extends State<_CustomerForm> {
  late bool byPhone = widget.config['sms_login'] != false;
  final phone = TextEditingController();
  final otp = TextEditingController();
  final code = TextEditingController();
  bool sent = false, busy = false, already = false;
  String? error;
  int wait = 0;
  Timer? timer;

  @override
  void didUpdateWidget(covariant _CustomerForm old) {
    super.didUpdateWidget(old);
    if (widget.config['sms_login'] == false && byPhone) byPhone = false;
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> run(Future<void> Function() call) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await call();
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  /// Continue with the phone number: signed in at once if this phone proved the number before; else one SMS code
  /// (asking again while it still works sends no new SMS).
  Future<void> sendCode({bool resend = false}) async {
    if (phone.text.trim().length < 9) {
      setState(() => error = S.t('Enter your phone number, e.g. 0712 345 678.'));
      return;
    }
    await run(() async {
      final s = context.read<Session>();
      if (!resend && await s.signInRemembered(phone.text.trim())) return;
      final r = await s.sendCode(phone.text.trim());
      if (!mounted) return;
      setState(() {
        sent = true;
        already = r['already_sent'] == true;
        wait = (r['seconds_left'] as num?)?.toInt() ?? 600;
      });
      timer?.cancel();
      timer = Timer.periodic(const Duration(seconds: 1), (t) {
        if (!mounted || wait <= 0) return t.cancel();
        setState(() => wait--);
      });
    });
  }

  Future<void> verify() async {
    if (otp.text.trim().length != 6) {
      setState(() => error = S.t('Enter the 6-digit code from the SMS.'));
      return;
    }
    await run(() => context.read<Session>().signInPhone(phone.text.trim(), otp.text.trim()));
  }

  Future<void> voucher() async {
    if (code.text.trim().isEmpty) {
      setState(() => error = S.t('Enter your voucher code.'));
      return;
    }
    await run(() => context.read<Session>().signInVoucher(code.text.trim()));
  }

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (widget.config['sms_login'] != false)
        Row(children: [
          for (final m in [(true, Icons.phone_iphone_rounded, S.t('Phone number')), (false, Icons.confirmation_number_outlined, S.t('Voucher code'))])
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: SnChip(
                avatar: Icon(m.$2, size: 18),
                label: Text(m.$3),
                selected: byPhone == m.$1,
                showCheckmark: false,
                onSelected: (_) => setState(() {
                  byPhone = m.$1;
                  error = null;
                }),
              ),
            ),
        ]),
      const SizedBox(height: 16),
      if (byPhone) ...[
        SnField(
          controller: phone,
          enabled: !sent,
          keyboardType: TextInputType.phone,
          autofillHints: const [AutofillHints.telephoneNumber],
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9+ ]')), LengthLimitingTextInputFormatter(16)],
          onSubmitted: (_) => sendCode(),
          decoration: InputDecoration(
            labelText: S.t('Phone number'),
            hintText: '0712 345 678',
            prefixIcon: const Icon(Icons.phone_outlined),
            suffixIcon: sent
                ? SnButton(variant: SnVariant.ghost, size: SnSize.small,
                    onPressed: () => setState(() {
                      sent = false;
                      otp.clear();
                      error = null;
                    }),
                    child: Text(S.t('Change')))
                : null,
          ),
        ),
        if (sent) ...[
          const SizedBox(height: 12),
          SnField(
            controller: otp,
            autofocus: true,
            keyboardType: TextInputType.number,
            autofillHints: const [AutofillHints.oneTimeCode],
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 24, letterSpacing: 12, fontWeight: FontWeight.w800),
            inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(6)],
            onChanged: (v) {
              if (v.length == 6) verify();
            },
            decoration: InputDecoration(hintText: '••••••', labelText: S.t('Code from the SMS'), floatingLabelAlignment: FloatingLabelAlignment.center),
          ),
          const SizedBox(height: 4),
          Row(children: [
            Expanded(
              child: Text(
                  already
                      ? S.t('We already sent a code to {phone}. Use that one; it works for {m} more minutes.', {'phone': phone.text.trim(), 'm': (wait / 60).ceil()})
                      : S.t('We sent a code to {phone}.', {'phone': phone.text.trim()}),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: c.outline)),
            ),
            SnButton(variant: SnVariant.ghost, size: SnSize.small,
              onPressed: wait > 0 || busy ? null : () => sendCode(resend: true),
              child: Text(wait > 0 ? S.t('New code in {t}', {'t': '${wait ~/ 60}:${(wait % 60).toString().padLeft(2, '0')}'}) : S.t('Send a new code')),
            ),
          ]),
        ] else
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(S.t('The first time on this phone we text you a 6-digit code. After that, just your number.'),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: c.outline)),
          ),
        _ErrorText(error),
        const SizedBox(height: 16),
        _busyButton(
          busy: busy,
          onPressed: sent ? verify : sendCode,
          label: sent ? S.t('Sign in') : S.t('Continue'),
          icon: Icons.arrow_forward_rounded,
        ),
      ] else ...[
        SnField(
          controller: code,
          keyboardType: TextInputType.number,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 22, letterSpacing: 6, fontWeight: FontWeight.w800),
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9A-Za-z ]')), LengthLimitingTextInputFormatter(20)],
          onSubmitted: (_) => voucher(),
          decoration: InputDecoration(labelText: S.t('Voucher code'), hintText: '12345678', floatingLabelAlignment: FloatingLabelAlignment.center),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(S.t('The code on your voucher, or in the SMS you got after paying.'),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: c.outline)),
        ),
        _ErrorText(error),
        const SizedBox(height: 16),
        _busyButton(busy: busy, onPressed: voucher, label: S.t('Sign in'), icon: Icons.arrow_forward_rounded),
      ],
    ]);
  }
}
