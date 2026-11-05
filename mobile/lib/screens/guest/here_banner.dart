import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/strings.dart';
import 'buy.dart';
import '../../ui/kit.dart';

/// "You're on <site> Wi-Fi": shown when the phone is on any SafeNet business's Wi-Fi, with Buy right there.
class HereBanner extends StatelessWidget {
  const HereBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final h = s.here;
    return AnimatedSize(
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOut,
      child: h == null
          ? const SizedBox(width: double.infinity)
          : Container(
              margin: const EdgeInsets.only(bottom: 14),
              padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(20),
                gradient: const LinearGradient(colors: [Color(0xFF0F9D58), Color(0xFF12B76A)], begin: Alignment.topLeft, end: Alignment.bottomRight),
                boxShadow: [BoxShadow(color: const Color(0xFF12B76A).withValues(alpha: 0.35), blurRadius: 18, offset: const Offset(0, 6))],
              ),
              child: Row(children: [
                Container(
                  padding: const EdgeInsets.all(9),
                  decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.2), shape: BoxShape.circle),
                  child: const Icon(Icons.wifi_rounded, color: Colors.white, size: 22),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(S.t("You're on {site} Wi-Fi", {'site': h['site']['name']}),
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15), maxLines: 1, overflow: TextOverflow.ellipsis),
                    Text(
                      [
                        '${h['business']['name']}',
                        if (h['cheapest'] != null) S.t('from {price}', {'price': money(h['cheapest'] as num, h['currency'] as String? ?? 'TZS')}),
                      ].join(' · '),
                      style: const TextStyle(color: Colors.white70, fontSize: 12),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ]),
                ),
                if (h['can_buy'] == true)
                  SnButton(
                    variant: SnVariant.light,
                    size: SnSize.small,
                    onPressed: () => Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => BuyScreen(
                          businessId: h['business']['id'] as int,
                          name: '${h['business']['name']}',
                          siteId: h['site']['id'] as int?,
                        ),
                      ),
                    ),
                    child: Text(S.t('Buy'),),
                  ),
              ]),
            ),
    );
  }
}
