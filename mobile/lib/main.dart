import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/session.dart';
import 'screens/business/shell.dart';
import 'screens/guest/guest_home.dart';
import 'screens/login.dart';
import 'ui/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(ChangeNotifierProvider(create: (_) => Session()..load(), child: const SafeNetApp()));
}

class SafeNetApp extends StatelessWidget {
  const SafeNetApp({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    return MaterialApp(
      title: 'SafeNet',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      home: !s.ready
          ? const _Splash()
          : switch (s.kind) {
              Kind.business => const BusinessShell(),
              Kind.guest => const GuestHome(),
              Kind.none => const LoginScreen(),
            },
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: kNavy,
        body: Center(child: Image.asset('assets/logo.png', width: 120, errorBuilder: (_, _, _) => const Icon(Icons.wifi, size: 72, color: Colors.white))),
      );
}
