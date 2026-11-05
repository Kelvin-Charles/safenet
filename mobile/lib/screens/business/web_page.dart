import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import '../../ui/widgets.dart';
import '../../ui/kit.dart';

/// Opens a dashboard page inside the app, already signed in (a one-time link from the server).
Future<void> openWeb(BuildContext context, String title, String path) async {
  final s = context.read<Session>();
  final r = await attempt(context, () => s.api.post('/api/m/web-link', {'path': path}));
  if (r == null || !context.mounted) return;
  await Navigator.push(context, MaterialPageRoute(builder: (_) => WebPage(title: title, url: r['url'] as String)));
}

class WebPage extends StatefulWidget {
  const WebPage({super.key, required this.title, required this.url});
  final String title;
  final String url;

  @override
  State<WebPage> createState() => _WebPageState();
}

class _WebPageState extends State<WebPage> {
  late final WebViewController web;
  int progress = 0;

  @override
  void initState() {
    super.initState();
    web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onProgress: (p) => setState(() => progress = p),
        onNavigationRequest: (req) {
          final u = Uri.parse(req.url);
          // stay on SafeNet; signing out of the web page doesn't sign out of the app
          if (u.host != Uri.parse(kServer).host) return NavigationDecision.prevent;
          if (u.path == '/logout') {
            Navigator.maybePop(context);
            return NavigationDecision.prevent;
          }
          return NavigationDecision.navigate;
        },
      ))
      ..loadRequest(Uri.parse(widget.url));
  }

  @override
  Widget build(BuildContext context) => PopScope(
        canPop: false,
        onPopInvokedWithResult: (didPop, _) async {
          if (didPop) return;
          if (await web.canGoBack()) {
            web.goBack();
          } else if (context.mounted) {
            Navigator.pop(context);
          }
        },
        child: Scaffold(
          appBar: SnAppBar(
            title: Text(widget.title),
            leading: SnIconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.pop(context)),
            actions: [SnIconButton(icon: const Icon(Icons.refresh_rounded), onPressed: web.reload, tooltip: S.t('Try again'))],
            bottom: progress < 100
                ? PreferredSize(preferredSize: const Size.fromHeight(3), child: SnProgressBar(value: progress / 100, minHeight: 3))
                : null,
          ),
          body: WebViewWidget(controller: web),
        ),
      );
}
