import 'package:flutter/material.dart';

import '../core/strings.dart';
import 'theme.dart';

/// A labelled group of fields in a rounded card.
class FieldGroup extends StatelessWidget {
  const FieldGroup({super.key, this.title, required this.children});
  final String? title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (title != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
              child: Text(title!.toUpperCase(),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(letterSpacing: 1, fontWeight: FontWeight.w700, color: Theme.of(context).colorScheme.outline)),
            ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _spaced(children)),
            ),
          ),
        ]),
      );

  static List<Widget> _spaced(List<Widget> xs) => [
        for (var i = 0; i < xs.length; i++) ...[if (i > 0) const SizedBox(height: 12), xs[i]],
      ];
}

/// A switch row with title and explanation.
class SwitchRow extends StatelessWidget {
  const SwitchRow({super.key, required this.title, this.subtitle, required this.value, required this.onChanged});
  final String title;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) => SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: subtitle != null ? Text(subtitle!, style: Theme.of(context).textTheme.bodySmall) : null,
        value: value,
        onChanged: onChanged,
      );
}

/// A dropdown of {id, name} maps with an "any/none" first choice.
class PickField extends StatelessWidget {
  const PickField({super.key, required this.label, required this.items, required this.value, required this.onChanged, this.none, this.icon});
  final String label;
  final List items;
  final int? value;
  final ValueChanged<int?> onChanged;
  final String? none;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => DropdownButtonFormField<int?>(
        initialValue: items.any((x) => x['id'] == value) ? value : null,
        isExpanded: true,
        decoration: InputDecoration(labelText: label, prefixIcon: icon != null ? Icon(icon) : null),
        borderRadius: BorderRadius.circular(14),
        items: [
          if (none != null) DropdownMenuItem<int?>(value: null, child: Text(none!)),
          for (final x in items) DropdownMenuItem<int?>(value: x['id'] as int, child: Text('${x['name']}', overflow: TextOverflow.ellipsis)),
        ],
        onChanged: onChanged,
      );
}

/// Minutes typed as a number + unit (minutes, hours, days).
class DurationField extends StatefulWidget {
  const DurationField({super.key, required this.label, required this.minutes, required this.onChanged, this.allowZero = false});
  final String label;
  final int minutes;
  final ValueChanged<int> onChanged;
  final bool allowZero;

  @override
  State<DurationField> createState() => _DurationFieldState();
}

class _DurationFieldState extends State<DurationField> {
  late String unit;
  late final TextEditingController value;

  @override
  void initState() {
    super.initState();
    final m = widget.minutes;
    unit = m > 0 && m % 1440 == 0 ? 'days' : (m > 0 && m % 60 == 0 ? 'hours' : (m == 0 ? 'hours' : 'minutes'));
    final size = {'days': 1440, 'hours': 60, 'minutes': 1}[unit]!;
    value = TextEditingController(text: m == 0 ? '' : '${m ~/ size}');
  }

  void _emit() {
    final n = int.tryParse(value.text.trim()) ?? 0;
    widget.onChanged(n * {'days': 1440, 'hours': 60, 'minutes': 1}[unit]!);
  }

  @override
  Widget build(BuildContext context) => Row(children: [
        Expanded(
          child: TextField(
            controller: value,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: widget.label, prefixIcon: const Icon(Icons.timer_outlined)),
            onChanged: (_) => _emit(),
          ),
        ),
        const SizedBox(width: 8),
        DropdownButton<String>(
          value: unit,
          borderRadius: BorderRadius.circular(14),
          underline: const SizedBox.shrink(),
          items: [
            DropdownMenuItem(value: 'minutes', child: Text(S.lang == 'sw' ? 'dakika' : 'minutes')),
            DropdownMenuItem(value: 'hours', child: Text(S.t('hours'))),
            DropdownMenuItem(value: 'days', child: Text(S.t('days'))),
          ],
          onChanged: (v) {
            setState(() => unit = v!);
            _emit();
          },
        ),
      ]);
}

/// The save button at the bottom of a form page.
class SaveBar extends StatelessWidget {
  const SaveBar({super.key, required this.busy, required this.onSave, this.label, this.onDelete});
  final bool busy;
  final VoidCallback onSave;
  final VoidCallback? onDelete;
  final String? label;

  @override
  Widget build(BuildContext context) => SafeArea(
        top: false,
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surface,
            border: Border(top: BorderSide(color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: 0.4))),
          ),
          child: Row(children: [
            if (onDelete != null) ...[
              IconButton.outlined(
                onPressed: busy ? null : onDelete,
                icon: const Icon(Icons.delete_outline_rounded, color: kBad),
                style: IconButton.styleFrom(minimumSize: const Size(52, 52), side: BorderSide(color: kBad.withValues(alpha: 0.4))),
              ),
              const SizedBox(width: 10),
            ],
            Expanded(
              child: FilledButton(
                onPressed: busy ? null : onSave,
                child: busy ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)) : Text(label ?? S.t('Save')),
              ),
            ),
          ]),
        ),
      );
}
