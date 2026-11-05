import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/session.dart';
import 'screens/business/shell.dart';
import 'screens/guest/guest_home.dart';
import 'screens/login.dart';
import 'ui/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(ChangeNotifierProvider(create: (_) => Session()..load()..watchWifi(), child: const SafeNetApp()));
}

class SafeNetApp extends StatefulWidget {
  const SafeNetApp({super.key});

  @override
  State<SafeNetApp> createState() => _SafeNetAppState();
}

class _SafeNetAppState extends State<SafeNetApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) context.read<Session>().checkHere(force: true);   // maybe on another Wi-Fi now
  }

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
