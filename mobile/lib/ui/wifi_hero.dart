import 'dart:math' as math;

import 'package:flutter/material.dart';

/// The sign-in illustration: a hotspot sending Wi-Fi out in rings, phones and laptops around it connected by lines,
/// with data flowing to them. Drawn in code (sharp at any size, works offline, no image to download).
class WifiHero extends StatefulWidget {
  const WifiHero({super.key, this.size = 260});
  final double size;

  @override
  State<WifiHero> createState() => _WifiHeroState();
}

class _WifiHeroState extends State<WifiHero> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 12))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  static const _devices = <(IconData, double, double)>[
    // icon, angle (radians), distance (fraction of radius)
    (Icons.smartphone_rounded, -0.35, 0.86),
    (Icons.laptop_mac_rounded, 0.95, 0.9),
    (Icons.tablet_android_rounded, 2.2, 0.84),
    (Icons.smartphone_rounded, 3.4, 0.9),
    (Icons.tv_rounded, 4.55, 0.86),
  ];

  @override
  Widget build(BuildContext context) {
    final s = widget.size;
    return SizedBox(
      width: s,
      height: s,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final t = _c.value;
          final r = s / 2;
          final spin = t * 2 * math.pi * 0.25; // the ring of devices turns slowly
          return Stack(clipBehavior: Clip.none, children: [
            Positioned.fill(child: CustomPaint(painter: _HeroPainter(t: t, spin: spin, devices: _devices))),
            for (var i = 0; i < _devices.length; i++)
              _device(r, _devices[i], spin, i, t),
            Center(child: _hub(s)),
          ]);
        },
      ),
    );
  }

  Widget _device(double r, (IconData, double, double) d, double spin, int i, double t) {
    final a = d.$2 + spin;
    final dist = r * d.$3;
    final bob = math.sin((t * 6 + i) * 2 * math.pi / 3) * 3; // a gentle float
    final box = r * 0.3;
    final online = ((t * 5 + i * 0.37) % 1) < 0.85;
    return Positioned(
      left: r + math.cos(a) * dist - box / 2,
      top: r + math.sin(a) * dist - box / 2 + bob,
      child: Container(
        width: box,
        height: box,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(box * 0.3),
          boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.25), blurRadius: 12, offset: const Offset(0, 4))],
        ),
        child: Stack(children: [
          Center(child: Icon(d.$1, size: box * 0.52, color: const Color(0xFF0A3AA8))),
          Positioned(
            right: box * 0.12,
            top: box * 0.12,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 300),
              width: box * 0.16,
              height: box * 0.16,
              decoration: BoxDecoration(color: online ? const Color(0xFF22C55E) : const Color(0xFFF5B301), shape: BoxShape.circle),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _hub(double s) {
    final box = s * 0.28;
    return Container(
      width: box,
      height: box,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: const LinearGradient(colors: [Color(0xFF3B82F6), Color(0xFF1D4ED8)], begin: Alignment.topLeft, end: Alignment.bottomRight),
        border: Border.all(color: Colors.white.withValues(alpha: 0.9), width: 3),
        boxShadow: [BoxShadow(color: const Color(0xFF3B82F6).withValues(alpha: 0.6), blurRadius: 30, spreadRadius: 4)],
      ),
      child: Icon(Icons.wifi_rounded, color: Colors.white, size: box * 0.55),
    );
  }
}

class _HeroPainter extends CustomPainter {
  _HeroPainter({required this.t, required this.spin, required this.devices});
  final double t, spin;
  final List<(IconData, double, double)> devices;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = size.width / 2;

    // Wi-Fi rings going out from the hub
    for (var i = 0; i < 3; i++) {
      final p = (t * 4 + i / 3) % 1;
      final ring = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = Colors.white.withValues(alpha: (1 - p) * 0.35);
      canvas.drawCircle(c, r * 0.16 + p * r * 0.85, ring);
    }
    // a faint orbit
    canvas.drawCircle(
        c,
        r * 0.87,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1
          ..color = Colors.white.withValues(alpha: 0.12));

    // links to each device, with data packets travelling out
    for (var i = 0; i < devices.length; i++) {
      final a = devices[i].$2 + spin;
      final end = c + Offset(math.cos(a), math.sin(a)) * r * devices[i].$3;
      final start = c + Offset(math.cos(a), math.sin(a)) * r * 0.16;
      _dashed(canvas, start, end, Paint()
        ..color = Colors.white.withValues(alpha: 0.28)
        ..strokeWidth = 1.5);
      for (var k = 0; k < 2; k++) {
        final p = (t * 7 + i * 0.21 + k * 0.5) % 1;
        final pos = Offset.lerp(start, end, p)!;
        canvas.drawCircle(pos, 3.2, Paint()..color = const Color(0xFF6EE7A8).withValues(alpha: math.sin(p * math.pi)));
      }
    }
  }

  void _dashed(Canvas canvas, Offset a, Offset b, Paint paint) {
    final len = (b - a).distance;
    final dir = (b - a) / len;
    for (double d = 0; d < len; d += 9) {
      canvas.drawLine(a + dir * d, a + dir * math.min(d + 4, len), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _HeroPainter old) => old.t != t;
}
