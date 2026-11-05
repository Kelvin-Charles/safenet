/// SafeNet UI kit: the app's own buttons, fields, chips, switches, cards, rows, bars, sheets, dialogs and toasts.
/// Screens use these instead of the stock Material widgets, so the app has one look of its own.
library;

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'theme.dart';

// ---------------------------------------------------------------- tokens
class Sn {
  static const r1 = 10.0, r2 = 14.0, r3 = 18.0, r4 = 24.0;
  static const ease = Curves.easeOutCubic;
  static const fast = Duration(milliseconds: 160);
  static const gradient = LinearGradient(colors: [kNavy, Color(0xFF0A3AA8)], begin: Alignment.topLeft, end: Alignment.bottomRight);

  static bool dark(BuildContext c) => Theme.of(c).brightness == Brightness.dark;
  static Color surface(BuildContext c) => dark(c) ? const Color(0xFF161E33) : Colors.white;
  static Color sunken(BuildContext c) => dark(c) ? const Color(0xFF0F1628) : const Color(0xFFF0F3F9);
  static Color line(BuildContext c) => dark(c) ? const Color(0xFF26324D) : const Color(0xFFE3E8F1);
  static Color ink(BuildContext c) => dark(c) ? const Color(0xFFE8EDF7) : const Color(0xFF0F172A);
  static Color muted(BuildContext c) => dark(c) ? const Color(0xFF8D9AB5) : const Color(0xFF64748B);
  static Color brand(BuildContext c) => dark(c) ? const Color(0xFF8FB0FF) : kNavy;
  static List<BoxShadow> shadow(BuildContext c) =>
      dark(c) ? const [] : [BoxShadow(color: const Color(0xFF0F172A).withValues(alpha: 0.05), blurRadius: 14, offset: const Offset(0, 4))];
}

/// Shrinks a little while pressed (every tappable thing in the kit).
class SnPressable extends StatefulWidget {
  const SnPressable({super.key, required this.child, this.onTap, this.onLongPress, this.scale = 0.97, this.haptic = false, this.borderRadius});
  final Widget child;
  final VoidCallback? onTap, onLongPress;
  final double scale;
  final bool haptic;
  final BorderRadius? borderRadius;

  @override
  State<SnPressable> createState() => _SnPressableState();
}

class _SnPressableState extends State<SnPressable> {
  bool down = false;

  void _set(bool v) {
    if (widget.onTap != null && down != v) setState(() => down = v);
  }

  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => _set(true),
        onTapUp: (_) => _set(false),
        onTapCancel: () => _set(false),
        onLongPress: widget.onLongPress,
        onTap: widget.onTap == null
            ? null
            : () {
                if (widget.haptic) HapticFeedback.selectionClick();
                widget.onTap!();
              },
        child: AnimatedScale(
          scale: down ? widget.scale : 1,
          duration: const Duration(milliseconds: 110),
          curve: Sn.ease,
          child: AnimatedOpacity(opacity: down ? 0.88 : 1, duration: const Duration(milliseconds: 110), child: widget.child),
        ),
      );
}

// ---------------------------------------------------------------- buttons
enum SnVariant { primary, secondary, ghost, danger, success, light }

enum SnSize { large, medium, small }

class SnButton extends StatelessWidget {
  const SnButton({super.key, required this.onPressed, required this.child, this.variant = SnVariant.primary, this.size = SnSize.large,
      this.loading = false, this.icon, this.expand = false})
      : label = null;

  const SnButton.icon({super.key, required this.onPressed, required this.icon, required Widget this.label, this.variant = SnVariant.primary,
      this.size = SnSize.large, this.loading = false, this.expand = false})
      : child = null;

  final VoidCallback? onPressed;
  final Widget? child, label, icon;
  final SnVariant variant;
  final SnSize size;
  final bool loading, expand;

  @override
  Widget build(BuildContext context) {
    final on = onPressed != null && !loading;
    final h = switch (size) { SnSize.large => 54.0, SnSize.medium => 44.0, SnSize.small => 36.0 };
    final pad = switch (size) { SnSize.large => 22.0, SnSize.medium => 16.0, SnSize.small => 12.0 };
    final fs = switch (size) { SnSize.large => 16.0, SnSize.medium => 15.0, SnSize.small => 13.5 };
    Color fg;
    Decoration deco;
    final r = BorderRadius.circular(size == SnSize.small ? Sn.r1 : Sn.r2);
    switch (variant) {
      case SnVariant.primary:
        fg = Colors.white;
        deco = BoxDecoration(
          borderRadius: r,
          gradient: on ? Sn.gradient : null,
          color: on ? null : Sn.line(context),
          boxShadow: on && size == SnSize.large ? [BoxShadow(color: kNavy.withValues(alpha: 0.28), blurRadius: 16, offset: const Offset(0, 6))] : null,
        );
      case SnVariant.danger:
        fg = Colors.white;
        deco = BoxDecoration(borderRadius: r, color: on ? kBad : Sn.line(context));
      case SnVariant.success:
        fg = Colors.white;
        deco = BoxDecoration(borderRadius: r, color: on ? kGood : Sn.line(context));
      case SnVariant.light:
        fg = kNavy;
        deco = BoxDecoration(borderRadius: r, color: Colors.white.withValues(alpha: on ? 1 : 0.6));
      case SnVariant.secondary:
        fg = Sn.brand(context);
        deco = BoxDecoration(borderRadius: r, color: Sn.brand(context).withValues(alpha: 0.07), border: Border.all(color: Sn.brand(context).withValues(alpha: 0.22)));
      case SnVariant.ghost:
        fg = Sn.brand(context);
        deco = BoxDecoration(borderRadius: r);
    }
    if (!on && variant != SnVariant.ghost && variant != SnVariant.secondary) fg = Sn.muted(context);
    if (!on && (variant == SnVariant.ghost || variant == SnVariant.secondary)) fg = Sn.muted(context);
    final text = DefaultTextStyle.merge(
      style: TextStyle(color: fg, fontWeight: FontWeight.w700, fontSize: fs, letterSpacing: 0.1),
      child: IconTheme.merge(
        data: IconThemeData(color: fg, size: fs + 3),
        child: loading
            ? SnSpinner(size: fs + 4, color: fg, strokeWidth: 2.4)
            : child ??
                Row(mainAxisSize: MainAxisSize.min, children: [
                  if (icon != null) ...[icon!, SizedBox(width: size == SnSize.small ? 6 : 8)],
                  Flexible(child: label!),
                ]),
      ),
    );
    return Semantics(
      button: true,
      enabled: on,
      child: SnPressable(
        onTap: on ? onPressed : null,
        haptic: variant == SnVariant.primary,
        child: AnimatedContainer(
          duration: Sn.fast,
          constraints: BoxConstraints(minHeight: h, minWidth: expand ? double.infinity : 0),
          padding: EdgeInsets.symmetric(horizontal: pad),
          decoration: deco,
          alignment: Alignment.center,
          child: text,
        ),
      ),
    );
  }
}

/// A round icon button.
class SnIconButton extends StatelessWidget {
  const SnIconButton({super.key, required this.icon, required this.onPressed, this.tooltip, this.color, this.tinted = false, this.size = 40});
  final Widget icon;
  final VoidCallback? onPressed;
  final String? tooltip;
  final Color? color;
  final bool tinted;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Sn.ink(context);
    final b = SnPressable(
      onTap: onPressed,
      scale: 0.9,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: tinted ? c.withValues(alpha: 0.1) : Colors.transparent,
        ),
        alignment: Alignment.center,
        child: IconTheme.merge(data: IconThemeData(color: onPressed == null ? Sn.muted(context) : c, size: size * 0.55), child: icon),
      ),
    );
    return tooltip == null ? b : Tooltip(message: tooltip!, child: b);
  }
}

/// The floating "add" button.
class SnFab extends StatelessWidget {
  const SnFab({super.key, required this.onPressed, required this.icon, required this.label});
  final VoidCallback onPressed;
  final Widget icon, label;

  @override
  Widget build(BuildContext context) => SnPressable(
        onTap: onPressed,
        haptic: true,
        child: Container(
          height: 56,
          padding: const EdgeInsets.symmetric(horizontal: 20),
          decoration: BoxDecoration(
            gradient: Sn.gradient,
            borderRadius: BorderRadius.circular(Sn.r3),
            boxShadow: [BoxShadow(color: kNavy.withValues(alpha: 0.35), blurRadius: 20, offset: const Offset(0, 8))],
          ),
          child: IconTheme.merge(
            data: const IconThemeData(color: Colors.white, size: 22),
            child: DefaultTextStyle.merge(
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15),
              child: Row(mainAxisSize: MainAxisSize.min, children: [icon, const SizedBox(width: 10), label]),
            ),
          ),
        ),
      );
}

// ---------------------------------------------------------------- surfaces
class SnCard extends StatelessWidget {
  const SnCard({super.key, required this.child, this.color, this.margin, this.onTap, this.borderColor, this.padding, this.gradient,
      this.clipBehavior = Clip.antiAlias, this.radius = Sn.r3});
  final Widget child;
  final Color? color, borderColor;
  final EdgeInsetsGeometry? margin, padding;
  final VoidCallback? onTap;
  final Gradient? gradient;
  final Clip clipBehavior;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final box = Container(
      margin: margin,
      padding: padding,
      clipBehavior: clipBehavior,
      decoration: BoxDecoration(
        color: gradient == null ? (color ?? Sn.surface(context)) : null,
        gradient: gradient,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: borderColor ?? Sn.line(context).withValues(alpha: Sn.dark(context) ? 1 : 0.7), width: borderColor != null ? 1.6 : 1),
        boxShadow: Sn.shadow(context),
      ),
      child: Material(type: MaterialType.transparency, child: child),
    );
    return onTap == null ? box : SnPressable(onTap: onTap, scale: 0.985, child: box);
  }
}

/// A row in a list: leading, title, subtitle, trailing.
class SnTile extends StatelessWidget {
  const SnTile({super.key, this.leading, this.title, this.subtitle, this.trailing, this.onTap, this.dense = false, this.contentPadding,
      this.isThreeLine = false});
  final Widget? leading, title, subtitle, trailing;
  final VoidCallback? onTap;
  final bool dense, isThreeLine;
  final EdgeInsetsGeometry? contentPadding;

  @override
  Widget build(BuildContext context) {
    final row = Padding(
      padding: contentPadding ?? EdgeInsets.symmetric(horizontal: 16, vertical: dense ? 8 : 12),
      child: Row(crossAxisAlignment: isThreeLine ? CrossAxisAlignment.start : CrossAxisAlignment.center, children: [
        if (leading != null) ...[
          IconTheme.merge(data: IconThemeData(color: Sn.muted(context), size: 22), child: leading!),
          const SizedBox(width: 14),
        ],
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            if (title != null)
              DefaultTextStyle.merge(style: TextStyle(color: Sn.ink(context), fontSize: dense ? 14 : 15, fontWeight: FontWeight.w600), child: title!),
            if (subtitle != null) ...[
              const SizedBox(height: 2),
              DefaultTextStyle.merge(style: TextStyle(color: Sn.muted(context), fontSize: 12.5, height: 1.35), child: subtitle!),
            ],
          ]),
        ),
        if (trailing != null) ...[
          const SizedBox(width: 10),
          IconTheme.merge(data: IconThemeData(color: Sn.muted(context)), child: DefaultTextStyle.merge(style: TextStyle(color: Sn.ink(context)), child: trailing!)),
        ],
      ]),
    );
    return onTap == null ? row : SnPressable(onTap: onTap, scale: 0.99, child: row);
  }
}

// ---------------------------------------------------------------- inputs
/// A text field: label above, a soft box that lights up when focused, help or error below.
/// Takes an InputDecoration for its words and icons (labelText, hintText, helperText, errorText, prefixIcon, suffixIcon).
class SnField extends StatefulWidget {
  const SnField({super.key, this.controller, this.decoration = const InputDecoration(), this.keyboardType, this.obscureText = false, this.onChanged,
      this.onSubmitted, this.maxLines = 1, this.minLines, this.maxLength, this.inputFormatters, this.textAlign = TextAlign.start, this.style,
      this.autofocus = false, this.autofillHints, this.textInputAction, this.textCapitalization = TextCapitalization.none, this.enabled,
      this.autocorrect = true});
  final TextEditingController? controller;
  final InputDecoration decoration;
  final TextInputType? keyboardType;
  final bool obscureText, autofocus, autocorrect;
  final bool? enabled;
  final ValueChanged<String>? onChanged, onSubmitted;
  final int? maxLines, minLines, maxLength;
  final List<TextInputFormatter>? inputFormatters;
  final TextAlign textAlign;
  final TextStyle? style;
  final Iterable<String>? autofillHints;
  final TextInputAction? textInputAction;
  final TextCapitalization textCapitalization;

  @override
  State<SnField> createState() => _SnFieldState();
}

class _SnFieldState extends State<SnField> {
  final focus = FocusNode();

  @override
  void initState() {
    super.initState();
    focus.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.decoration;
    final error = d.errorText;
    final on = focus.hasFocus;
    final ring = error != null ? kBad : (on ? kAccent : Sn.line(context));
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      if (d.labelText != null)
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 6),
          child: Text(d.labelText!,
              textAlign: widget.textAlign == TextAlign.center ? TextAlign.center : TextAlign.start,
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: error != null ? kBad : (on ? kAccent : Sn.muted(context)))),
        ),
      AnimatedContainer(
        duration: Sn.fast,
        decoration: BoxDecoration(
          color: widget.enabled == false ? Sn.sunken(context) : Sn.surface(context),
          borderRadius: BorderRadius.circular(Sn.r2),
          border: Border.all(color: ring, width: on || error != null ? 1.6 : 1),
          boxShadow: on ? [BoxShadow(color: kAccent.withValues(alpha: 0.12), blurRadius: 0, spreadRadius: 4)] : null,
        ),
        child: Row(crossAxisAlignment: widget.maxLines == 1 || widget.obscureText ? CrossAxisAlignment.center : CrossAxisAlignment.start, children: [
          if (d.prefixIcon != null)
            Padding(
              padding: const EdgeInsets.only(left: 14),
              child: IconTheme.merge(data: IconThemeData(color: on ? kAccent : Sn.muted(context), size: 20), child: d.prefixIcon!),
            ),
          Expanded(
            child: TextField(
              controller: widget.controller,
              focusNode: focus,
              keyboardType: widget.keyboardType,
              obscureText: widget.obscureText,
              onChanged: widget.onChanged,
              onSubmitted: widget.onSubmitted,
              maxLines: widget.obscureText ? 1 : widget.maxLines,
              minLines: widget.minLines,
              maxLength: widget.maxLength,
              inputFormatters: widget.inputFormatters,
              textAlign: widget.textAlign,
              style: TextStyle(fontSize: 16, color: Sn.ink(context), fontWeight: FontWeight.w500).merge(widget.style),
              autofocus: widget.autofocus,
              autofillHints: widget.autofillHints,
              textInputAction: widget.textInputAction,
              textCapitalization: widget.textCapitalization,
              enabled: widget.enabled,
              autocorrect: widget.autocorrect,
              cursorColor: kAccent,
              decoration: InputDecoration(
                hintText: d.hintText,
                hintStyle: TextStyle(color: Sn.muted(context).withValues(alpha: 0.7), fontWeight: FontWeight.w400),
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                disabledBorder: InputBorder.none,
                filled: false,
                counterText: '',
                isDense: true,
                contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: widget.style?.fontSize != null && widget.style!.fontSize! > 18 ? 16 : 15),
              ),
            ),
          ),
          if (d.suffixIcon != null) Padding(padding: const EdgeInsets.only(right: 4), child: d.suffixIcon!),
        ]),
      ),
      if (error != null || d.helperText != null)
        Padding(
          padding: const EdgeInsets.only(left: 4, top: 6),
          child: Text(error ?? d.helperText!, style: TextStyle(fontSize: 12, color: error != null ? kBad : Sn.muted(context))),
        ),
    ]);
  }
}

/// A pill to pick (selected) or tap (onPressed).
class SnChip extends StatelessWidget {
  const SnChip({super.key, required this.label, this.selected = false, this.onSelected, this.onPressed, this.avatar, this.showCheckmark = false});
  final Widget label;
  final bool selected, showCheckmark;
  final ValueChanged<bool>? onSelected;
  final VoidCallback? onPressed;
  final Widget? avatar;

  @override
  Widget build(BuildContext context) {
    final fg = selected ? Colors.white : Sn.ink(context);
    return SnPressable(
      onTap: onSelected != null ? () => onSelected!(!selected) : onPressed,
      scale: 0.95,
      haptic: true,
      child: AnimatedContainer(
        duration: Sn.fast,
        curve: Sn.ease,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          gradient: selected ? Sn.gradient : null,
          color: selected ? null : Sn.surface(context),
          borderRadius: BorderRadius.circular(40),
          border: Border.all(color: selected ? Colors.transparent : Sn.line(context)),
        ),
        child: IconTheme.merge(
          data: IconThemeData(color: selected ? Colors.white : Sn.muted(context), size: 16),
          child: DefaultTextStyle.merge(
            style: TextStyle(color: fg, fontWeight: FontWeight.w600, fontSize: 13.5),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (avatar != null) ...[avatar!, const SizedBox(width: 6)],
              label,
            ]),
          ),
        ),
      ),
    );
  }
}

/// A small static label (no tap).
class SnTag extends StatelessWidget {
  const SnTag({super.key, required this.label, this.avatar, this.color});
  final Widget label;
  final Widget? avatar;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Sn.brand(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.08), borderRadius: BorderRadius.circular(Sn.r1), border: Border.all(color: c.withValues(alpha: 0.18))),
      child: DefaultTextStyle.merge(
        style: TextStyle(color: c, fontWeight: FontWeight.w700),
        child: Row(mainAxisSize: MainAxisSize.min, children: [if (avatar != null) ...[avatar!, const SizedBox(width: 6)], label]),
      ),
    );
  }
}

/// The app's own on/off switch.
class SnSwitch extends StatelessWidget {
  const SnSwitch({super.key, required this.value, required this.onChanged});
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) => Semantics(
        toggled: value,
        child: SnPressable(
          onTap: onChanged == null ? null : () => onChanged!(!value),
          scale: 0.94,
          haptic: true,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            curve: Sn.ease,
            width: 50,
            height: 30,
            padding: const EdgeInsets.all(3),
            decoration: BoxDecoration(
              gradient: value ? const LinearGradient(colors: [Color(0xFF0F9D58), Color(0xFF12B76A)]) : null,
              color: value ? null : Sn.line(context),
              borderRadius: BorderRadius.circular(30),
            ),
            child: AnimatedAlign(
              duration: const Duration(milliseconds: 200),
              curve: Sn.ease,
              alignment: value ? Alignment.centerRight : Alignment.centerLeft,
              child: Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                  boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.18), blurRadius: 4, offset: const Offset(0, 1))],
                ),
                child: value ? const Icon(Icons.check_rounded, size: 15, color: Color(0xFF0F9D58)) : null,
              ),
            ),
          ),
        ),
      );
}

class SnSwitchTile extends StatelessWidget {
  const SnSwitchTile({super.key, required this.title, this.subtitle, required this.value, required this.onChanged, this.secondary, this.contentPadding,
      this.dense = false});
  final Widget title;
  final Widget? subtitle, secondary;
  final bool value, dense;
  final ValueChanged<bool>? onChanged;
  final EdgeInsetsGeometry? contentPadding;

  @override
  Widget build(BuildContext context) => SnTile(
        contentPadding: contentPadding ?? const EdgeInsets.symmetric(vertical: 8),
        leading: secondary,
        title: title,
        subtitle: subtitle,
        dense: dense,
        trailing: SnSwitch(value: value, onChanged: onChanged),
        onTap: onChanged == null ? null : () => onChanged!(!value),
      );
}

/// A tick box row.
class SnCheckTile extends StatelessWidget {
  const SnCheckTile({super.key, required this.value, required this.onChanged, required this.title, this.subtitle, this.contentPadding});
  final bool value;
  final ValueChanged<bool?>? onChanged;
  final Widget title;
  final Widget? subtitle;
  final EdgeInsetsGeometry? contentPadding;

  @override
  Widget build(BuildContext context) => SnTile(
        contentPadding: contentPadding ?? const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        onTap: onChanged == null ? null : () => onChanged!(!value),
        leading: AnimatedContainer(
          duration: Sn.fast,
          width: 24,
          height: 24,
          decoration: BoxDecoration(
            gradient: value ? Sn.gradient : null,
            borderRadius: BorderRadius.circular(7),
            border: Border.all(color: value ? Colors.transparent : Sn.line(context), width: 2),
          ),
          child: value ? const Icon(Icons.check_rounded, size: 17, color: Colors.white) : null,
        ),
        title: title,
        subtitle: subtitle,
      );
}

/// Choose one of a few: a sliding pill on a soft track. Takes ButtonSegments for its choices.
class SnSegmented<T> extends StatelessWidget {
  const SnSegmented({super.key, required this.segments, required this.selected, required this.onSelectionChanged, this.showSelectedIcon = false});
  final List<ButtonSegment<T>> segments;
  final Set<T> selected;
  final ValueChanged<Set<T>> onSelectionChanged;
  final bool showSelectedIcon;

  @override
  Widget build(BuildContext context) {
    final i = segments.indexWhere((s) => selected.contains(s.value));
    return Container(
      height: 44,
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: Sn.sunken(context), borderRadius: BorderRadius.circular(Sn.r2)),
      child: LayoutBuilder(builder: (context, box) {
        final w = box.maxWidth / segments.length;
        return Stack(children: [
          AnimatedPositioned(
            duration: const Duration(milliseconds: 220),
            curve: Sn.ease,
            left: w * math.max(i, 0),
            top: 0,
            bottom: 0,
            width: w,
            child: Container(
              decoration: BoxDecoration(
                color: Sn.surface(context),
                borderRadius: BorderRadius.circular(Sn.r1),
                boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.08), blurRadius: 6, offset: const Offset(0, 2))],
              ),
            ),
          ),
          Row(children: [
            for (var k = 0; k < segments.length; k++)
              Expanded(
                child: SnPressable(
                  onTap: () => onSelectionChanged({segments[k].value}),
                  scale: 0.96,
                  haptic: true,
                  child: Center(
                    child: IconTheme.merge(
                      data: IconThemeData(size: 16, color: k == i ? Sn.brand(context) : Sn.muted(context)),
                      child: DefaultTextStyle.merge(
                        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5, color: k == i ? Sn.brand(context) : Sn.muted(context)),
                        child: Row(mainAxisSize: MainAxisSize.min, children: [
                          if (segments[k].icon != null) ...[segments[k].icon!, const SizedBox(width: 6)],
                          if (segments[k].label != null) Flexible(child: segments[k].label!),
                        ]),
                      ),
                    ),
                  ),
                ),
              ),
          ]),
        ]);
      }),
    );
  }
}

// ---------------------------------------------------------------- progress
class SnSpinner extends StatefulWidget {
  const SnSpinner({super.key, this.size = 28, this.color, this.strokeWidth = 3, this.value});
  final double size, strokeWidth;
  final Color? color;
  final double? value;

  @override
  State<SnSpinner> createState() => _SnSpinnerState();
}

class _SnSpinnerState extends State<SnSpinner> with SingleTickerProviderStateMixin {
  late final AnimationController c = AnimationController(vsync: this, duration: const Duration(milliseconds: 900))..repeat();

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox(
        width: widget.size,
        height: widget.size,
        child: AnimatedBuilder(
          animation: c,
          builder: (_, _) => CustomPaint(painter: _Arc(c.value, widget.color ?? kAccent, widget.strokeWidth)),
        ),
      );
}

class _Arc extends CustomPainter {
  _Arc(this.t, this.color, this.w);
  final double t, w;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(rect.deflate(w / 2), 0, math.pi * 2, false, p..color = color.withValues(alpha: 0.15));
    canvas.drawArc(rect.deflate(w / 2), t * math.pi * 2, math.pi * 0.75, false, p..color = color);
  }

  @override
  bool shouldRepaint(covariant _Arc old) => old.t != t;
}

class SnProgressBar extends StatelessWidget {
  const SnProgressBar({super.key, this.value, this.minHeight = 4});
  final double? value;
  final double minHeight;

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(minHeight),
        child: SizedBox(
          height: minHeight,
          child: value == null ? const _Indeterminate() : LayoutBuilder(
            builder: (_, box) => Stack(children: [
              Container(color: Sn.line(context)),
              AnimatedContainer(duration: Sn.fast, width: box.maxWidth * value!.clamp(0, 1), decoration: const BoxDecoration(gradient: Sn.gradient)),
            ]),
          ),
        ),
      );
}

class _Indeterminate extends StatefulWidget {
  const _Indeterminate();

  @override
  State<_Indeterminate> createState() => _IndeterminateState();
}

class _IndeterminateState extends State<_Indeterminate> with SingleTickerProviderStateMixin {
  late final AnimationController c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1300))..repeat();

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (_, box) => AnimatedBuilder(
          animation: c,
          builder: (_, _) => Stack(children: [
            Container(color: Sn.line(context)),
            Positioned(
              left: (c.value * 1.6 - 0.4) * box.maxWidth,
              width: box.maxWidth * 0.4,
              top: 0,
              bottom: 0,
              child: Container(decoration: BoxDecoration(gradient: Sn.gradient, borderRadius: BorderRadius.circular(4))),
            ),
          ]),
        ),
      );
}

// ---------------------------------------------------------------- bars
class SnAppBar extends StatelessWidget implements PreferredSizeWidget {
  const SnAppBar({super.key, this.title, this.actions, this.leading, this.bottom});
  final Widget? title, leading;
  final List<Widget>? actions;
  final PreferredSizeWidget? bottom;

  @override
  Size get preferredSize => Size.fromHeight(60 + (bottom?.preferredSize.height ?? 0));

  @override
  Widget build(BuildContext context) {
    final canPop = Navigator.of(context).canPop();
    final lead = leading ??
        (canPop
            ? SnIconButton(icon: const Icon(Icons.arrow_back_ios_new_rounded), tinted: true, size: 40, onPressed: () => Navigator.maybePop(context))
            : null);
    return AnnotatedRegion(
      value: Sn.dark(context) ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark,
      child: Material(
        color: Theme.of(context).scaffoldBackgroundColor,
        child: SafeArea(
          bottom: false,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            SizedBox(
              height: 60,
              child: Row(children: [
                SizedBox(width: lead != null ? 10 : 20),
                if (lead != null) ...[lead, const SizedBox(width: 8)],
                Expanded(
                  child: DefaultTextStyle.merge(
                    style: TextStyle(fontSize: 21, fontWeight: FontWeight.w800, color: Sn.ink(context), letterSpacing: -0.3),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    child: title ?? const SizedBox.shrink(),
                  ),
                ),
                ...?actions,
                const SizedBox(width: 8),
              ]),
            ),
            if (bottom != null) bottom!,
          ]),
        ),
      ),
    );
  }
}

/// The bottom bar: a floating rounded bar with a sliding highlight. Takes NavigationDestinations for its tabs.
class SnBottomNav extends StatelessWidget {
  const SnBottomNav({super.key, required this.selectedIndex, required this.onDestinationSelected, required this.destinations});
  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final List<NavigationDestination> destinations;

  @override
  Widget build(BuildContext context) => SafeArea(
        top: false,
        child: Container(
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 10),
          height: 68,
          decoration: BoxDecoration(
            color: Sn.surface(context),
            borderRadius: BorderRadius.circular(Sn.r4),
            border: Border.all(color: Sn.line(context)),
            boxShadow: [BoxShadow(color: const Color(0xFF0F172A).withValues(alpha: 0.1), blurRadius: 24, offset: const Offset(0, 8))],
          ),
          child: Row(children: [
            for (var i = 0; i < destinations.length; i++)
              Expanded(
                child: SnPressable(
                  onTap: () => onDestinationSelected(i),
                  scale: 0.92,
                  haptic: true,
                  child: _NavItem(d: destinations[i], on: i == selectedIndex),
                ),
              ),
          ]),
        ),
      );
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.d, required this.on});
  final NavigationDestination d;
  final bool on;

  @override
  Widget build(BuildContext context) => Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          curve: Sn.ease,
          padding: EdgeInsets.symmetric(horizontal: on ? 16 : 10, vertical: 5),
          decoration: BoxDecoration(gradient: on ? Sn.gradient : null, borderRadius: BorderRadius.circular(20)),
          child: IconTheme.merge(
            data: IconThemeData(color: on ? Colors.white : Sn.muted(context), size: 22),
            child: on ? (d.selectedIcon ?? d.icon) : d.icon,
          ),
        ),
        const SizedBox(height: 4),
        Text(d.label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 11, fontWeight: on ? FontWeight.w800 : FontWeight.w600, color: on ? Sn.brand(context) : Sn.muted(context))),
      ]);
}

// ---------------------------------------------------------------- sheets, dialogs, toasts, menus
/// Bottom sheet in the kit's look (rounded, handle, the kit's surface).
Future<T?> showSnSheet<T>({required BuildContext context, required WidgetBuilder builder, bool isScrollControlled = false,
    bool isDismissible = true, bool enableDrag = true}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: isScrollControlled,
    isDismissible: isDismissible,
    enableDrag: enableDrag,
    backgroundColor: Colors.transparent,
    elevation: 0,
    showDragHandle: false,
    barrierColor: const Color(0xFF0B1220).withValues(alpha: 0.55),
    builder: (c) => Container(
      decoration: BoxDecoration(color: Theme.of(c).scaffoldBackgroundColor, borderRadius: const BorderRadius.vertical(top: Radius.circular(28))),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Container(
          margin: const EdgeInsets.only(top: 10, bottom: 14),
          width: 44,
          height: 5,
          decoration: BoxDecoration(color: Sn.line(c), borderRadius: BorderRadius.circular(4)),
        ),
        Flexible(child: builder(c)),
      ]),
    ),
  );
}

/// A dialog card: icon, title, words, buttons (SnButtons, or any widgets).
class SnDialog extends StatelessWidget {
  const SnDialog({super.key, this.icon, this.title, this.content, this.actions = const []});
  final Widget? icon, title, content;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Material(
            color: Sn.surface(context),
            borderRadius: BorderRadius.circular(Sn.r4),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(22, 24, 22, 18),
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                if (icon != null) ...[Center(child: IconTheme.merge(data: const IconThemeData(size: 44, color: kAccent), child: icon!)), const SizedBox(height: 12)],
                if (title != null)
                  DefaultTextStyle.merge(
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Sn.ink(context)),
                    child: title!,
                  ),
                if (content != null) ...[
                  const SizedBox(height: 8),
                  DefaultTextStyle.merge(textAlign: TextAlign.center, style: TextStyle(fontSize: 15, height: 1.4, color: Sn.muted(context)), child: content!),
                ],
                const SizedBox(height: 20),
                Row(children: [
                  for (var i = 0; i < actions.length; i++) ...[if (i > 0) const SizedBox(width: 10), Expanded(child: actions[i])],
                ]),
              ]),
            ),
          ),
        ),
      );
}

Future<T?> showSnDialog<T>({required BuildContext context, required WidgetBuilder builder}) => showGeneralDialog<T>(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'close',
      barrierColor: const Color(0xFF0B1220).withValues(alpha: 0.55),
      transitionDuration: const Duration(milliseconds: 220),
      pageBuilder: (c, _, _) => builder(c),
      transitionBuilder: (c, a, _, child) => FadeTransition(
        opacity: a,
        child: ScaleTransition(scale: Tween(begin: 0.92, end: 1.0).animate(CurvedAnimation(parent: a, curve: Sn.ease)), child: child),
      ),
    );

/// A message that floats in at the top and goes by itself.
void snToast(BuildContext context, String text, {bool error = false}) {
  final overlay = Overlay.maybeOf(context, rootOverlay: true);
  if (overlay == null) return;
  late OverlayEntry entry;
  entry = OverlayEntry(builder: (c) => _Toast(text: text, error: error, onDone: () => entry.remove()));
  overlay.insert(entry);
}

class _Toast extends StatefulWidget {
  const _Toast({required this.text, required this.error, required this.onDone});
  final String text;
  final bool error;
  final VoidCallback onDone;

  @override
  State<_Toast> createState() => _ToastState();
}

class _ToastState extends State<_Toast> with SingleTickerProviderStateMixin {
  late final AnimationController c = AnimationController(vsync: this, duration: const Duration(milliseconds: 260))..forward();
  Timer? t;

  @override
  void initState() {
    super.initState();
    t = Timer(Duration(milliseconds: widget.error ? 4200 : 2600), () async {
      if (!mounted) return;
      await c.reverse();
      widget.onDone();
    });
  }

  @override
  void dispose() {
    t?.cancel();
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Positioned(
        top: MediaQuery.of(context).padding.top + 10,
        left: 16,
        right: 16,
        child: SlideTransition(
          position: Tween(begin: const Offset(0, -1.4), end: Offset.zero).animate(CurvedAnimation(parent: c, curve: Sn.ease)),
          child: FadeTransition(
            opacity: c,
            child: Material(
              color: Colors.transparent,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                decoration: BoxDecoration(
                  color: widget.error ? kBad : const Color(0xFF0F172A),
                  borderRadius: BorderRadius.circular(Sn.r3),
                  boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.25), blurRadius: 20, offset: const Offset(0, 8))],
                ),
                child: Row(children: [
                  Icon(widget.error ? Icons.error_outline_rounded : Icons.check_circle_rounded, color: widget.error ? Colors.white : const Color(0xFF6EE7A8)),
                  const SizedBox(width: 12),
                  Expanded(child: Text(widget.text, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
                ]),
              ),
            ),
          ),
        ),
      );
}

/// A "⋯" menu that opens as a sheet of choices. Takes PopupMenuItems (their value and child).
class SnMenuButton<T> extends StatelessWidget {
  const SnMenuButton({super.key, required this.itemBuilder, required this.onSelected, this.child, this.icon});
  final List<PopupMenuEntry<T>> Function(BuildContext) itemBuilder;
  final ValueChanged<T> onSelected;
  final Widget? child, icon;

  @override
  Widget build(BuildContext context) {
    Future<void> open() async {
      final items = itemBuilder(context).whereType<PopupMenuItem<T>>().toList();
      final v = await showSnSheet<T>(
        context: context,
        builder: (c) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              for (final it in items)
                SnCard(
                  margin: const EdgeInsets.only(bottom: 8),
                  onTap: () => Navigator.pop(c, it.value),
                  child: Padding(padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16), child: Align(alignment: Alignment.centerLeft, child: it.child)),
                ),
            ]),
          ),
        ),
      );
      if (v != null) onSelected(v);
    }

    return child != null
        ? SnPressable(onTap: open, child: child!)
        : SnIconButton(icon: icon ?? const Icon(Icons.more_horiz_rounded), onPressed: open);
  }
}

// ---------------------------------------------------------------- ring, select
/// A ring that fills to `value` (0..1): time left on a code.
class SnRing extends StatelessWidget {
  const SnRing({super.key, required this.value, this.strokeWidth = 8, this.color = kAccent, this.track});
  final double value, strokeWidth;
  final Color color;
  final Color? track;

  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: value.clamp(0, 1)),
        duration: const Duration(milliseconds: 900),
        curve: Sn.ease,
        builder: (_, v, _) => CustomPaint(painter: _RingPainter(v, strokeWidth, color, track ?? Sn.line(context))),
      );
}

class _RingPainter extends CustomPainter {
  _RingPainter(this.v, this.w, this.color, this.track);
  final double v, w;
  final Color color, track;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = (Offset.zero & size).deflate(w / 2);
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(rect, 0, math.pi * 2, false, p..color = track);
    if (v > 0) canvas.drawArc(rect, -math.pi / 2, math.pi * 2 * v, false, p..color = color);
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) => old.v != v || old.color != color;
}

/// Pick one of a few: looks like a field, opens a sheet of choices.
class SnSelect<T> extends StatelessWidget {
  const SnSelect({super.key, required this.label, required this.value, required this.items, required this.onChanged, this.icon});
  final String label;
  final T value;
  final Map<T, String> items;
  final ValueChanged<T> onChanged;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final current = items[value] ?? (items.isNotEmpty ? items.values.first : '');
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      if (label.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 6),
          child: Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Sn.muted(context))),
        ),
      SnPressable(
        scale: 0.985,
        onTap: () async {
          final picked = await showSnSheet<_Pick<T>>(
            context: context,
            isScrollControlled: true,
            builder: (c) => SafeArea(
              child: ConstrainedBox(
                constraints: BoxConstraints(maxHeight: MediaQuery.of(c).size.height * 0.7),
                child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(16, 0, 16, 12), children: [
                  if (label.isNotEmpty)
                    Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 12), child: Text(label, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: Sn.ink(c)))),
                  for (final e in items.entries)
                    SnCard(
                      margin: const EdgeInsets.only(bottom: 8),
                      borderColor: e.key == value ? kAccent : null,
                      onTap: () => Navigator.pop(c, _Pick(e.key)),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
                        child: Row(children: [
                          Expanded(child: Text(e.value, style: TextStyle(fontWeight: FontWeight.w600, color: Sn.ink(c)))),
                          if (e.key == value) const Icon(Icons.check_circle_rounded, color: kAccent),
                        ]),
                      ),
                    ),
                ]),
              ),
            ),
          );
          if (picked != null) onChanged(picked.value);
        },
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 15),
          decoration: BoxDecoration(
            color: Sn.surface(context),
            borderRadius: BorderRadius.circular(Sn.r2),
            border: Border.all(color: Sn.line(context)),
          ),
          child: Row(children: [
            if (icon != null) ...[Icon(icon, size: 20, color: Sn.muted(context)), const SizedBox(width: 12)],
            Expanded(child: Text(current, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: Sn.ink(context)))),
            Icon(Icons.unfold_more_rounded, color: Sn.muted(context)),
          ]),
        ),
      ),
    ]);
  }
}

class _Pick<T> {
  const _Pick(this.value);
  final T value;
}
