import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/strings.dart';
import 'theme.dart';

/// Loads data once (and on pull-to-refresh), with loading and error states.
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.builder, this.reloadKey});
  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;
  final Object? reloadKey;

  @override
  State<Loader<T>> createState() => _LoaderState<T>();
}

class _LoaderState<T> extends State<Loader<T>> {
  T? data;
  Object? error;

  @override
  void initState() {
    super.initState();
    reload();
  }

  @override
  void didUpdateWidget(covariant Loader<T> old) {
    super.didUpdateWidget(old);
    if (old.reloadKey != widget.reloadKey) {
      data = null;
      reload();
    }
  }

  Future<void> reload() async {
    try {
      final d = await widget.load();
      if (mounted) setState(() {
        data = d;
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (data != null) return widget.builder(context, data as T, reload);
    if (error != null) return ErrorView(message: '$error', onRetry: () {
      setState(() => error = null);
      reload();
    });
    return const Center(child: CircularProgressIndicator());
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.cloud_off_rounded, size: 48, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: Text(S.t('Try again'))),
          ]),
        ),
      );
}

class EmptyView extends StatelessWidget {
  const EmptyView({super.key, required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 32),
        child: Column(children: [
          Icon(icon, size: 52, color: Theme.of(context).colorScheme.outlineVariant),
          const SizedBox(height: 12),
          Text(text, textAlign: TextAlign.center, style: TextStyle(color: Theme.of(context).colorScheme.outline)),
        ]),
      );
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 20, 4, 10),
        child: Row(children: [
          Expanded(child: Text(text, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
          if (trailing != null) trailing!,
        ]),
      );
}

/// A small number tile: icon, label, value.
class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.icon, required this.label, required this.value, this.color, this.sub, this.onTap});
  final IconData icon;
  final String label;
  final String value;
  final String? sub;
  final Color? color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.primary;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(color: c.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
              child: Icon(icon, color: c, size: 20),
            ),
            const SizedBox(height: 12),
            Text(value, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800), maxLines: 1,
                overflow: TextOverflow.ellipsis),
            const SizedBox(height: 2),
            Text(label, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Theme.of(context).colorScheme.outline)),
            if (sub != null) Text(sub!, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: c)),
          ]),
        ),
      ),
    );
  }
}

class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.color});
  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.outline;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(20)),
      child: Text(text, style: TextStyle(color: c, fontSize: 11.5, fontWeight: FontWeight.w700)),
    );
  }
}

Color stateColor(String? state) => switch (state) {
      'active' => kGood,
      'unused' => kAccent,
      'expired' => Colors.grey,
      'disabled' => kBad,
      'paid' => kGood,
      'pending' => kWarn,
      'failed' || 'review' => kBad,
      _ => Colors.grey,
    };

String stateLabel(String? state) => switch (state) {
      'active' => S.t('Active'),
      'unused' => S.t('Unused'),
      'expired' => S.t('Expired'),
      'disabled' => S.t('Disabled'),
      _ => S.t(state ?? ''),
    };

void toast(BuildContext context, String text, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(text),
      behavior: SnackBarBehavior.floating,
      backgroundColor: error ? kBad : null,
    ));
}

Future<bool> confirm(BuildContext context, String question, {String? yes, bool danger = false}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      content: Text(question),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: Text(S.t('Cancel'))),
        FilledButton(
          style: danger ? FilledButton.styleFrom(backgroundColor: kBad, minimumSize: const Size(88, 44)) : FilledButton.styleFrom(minimumSize: const Size(88, 44)),
          onPressed: () => Navigator.pop(c, true),
          child: Text(yes ?? 'OK'),
        ),
      ],
    ),
  );
  return r == true;
}

/// Runs an API call, showing its error as a message. Returns null on failure.
Future<T?> attempt<T>(BuildContext context, Future<T> Function() call) async {
  try {
    return await call();
  } on ApiError catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  }
  return null;
}


/// "Powered by Safezone Tech" at the bottom of screens.
class PoweredBy extends StatelessWidget {
  const PoweredBy({super.key, this.light = false});
  final bool light;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 14),
        child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(Icons.bolt_rounded, size: 14, color: light ? Colors.white54 : Theme.of(context).colorScheme.outline),
          const SizedBox(width: 4),
          Text.rich(
            TextSpan(children: [
              TextSpan(text: S.lang == 'sw' ? 'Inaendeshwa na ' : 'Powered by '),
              const TextSpan(text: 'Safezone Tech', style: TextStyle(fontWeight: FontWeight.w800)),
            ]),
            style: TextStyle(fontSize: 12, letterSpacing: 0.2, color: light ? Colors.white54 : Theme.of(context).colorScheme.outline),
          ),
        ]),
      );
}
