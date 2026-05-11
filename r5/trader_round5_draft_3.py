from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v4
#
#  ROOT CAUSE ANALYSIS: WHY v3 LOST -171,814 vs v2's -27,248
#  ──────────────────────────────────────────────────────────
#
#  v3 introduced TWO changes that interacted catastrophically:
#
#    1. HARD EXIT (EXIT_PATIENCE=3 ticks) — fires when |pos| ≥ 8 for 3 ticks.
#       Problem: with EMA-based fair value, position naturally oscillates to ±8
#       every few ticks because the EMA lags the mid. Hard exit then CROSSES
#       the spread (sells at best_bid, costs ≈hs ticks per unit), position
#       drops to ~3, and within 5 more ticks it's back to 8 again.
#       Result: a tight loop that bleeds ~9 ticks × 5 units = 45 XIRECS every
#       5 ticks per product. Over 1000 ticks, 5 SNACKPACK products × ~40
#       forced exits × 45 XIRECS = ~90,000 XIRECS lost from SNACKPACK alone.
#       This matches the observed SNACKPACK loss of -92,382.
#
#    2. SKEW 0.3→1.0 — at pos=10 with hs=9: ask = EMA+9-10 = EMA-1.
#       We were actively posting asks BELOW our own fair value estimate.
#       Even without the hard exit, this causes bots to fill our asks at a
#       discount. Combined with hard exit it was catastrophic.
#
#  The straight-line PnL decline in every product's chart is the definitive
#  signature: constant bleed rate = forced exits happening every N ticks.
#
#  ALSO: randomness in the submission point.
#  The wiki states that each test run uses a slightly randomised 80% subset of
#  quotes. v2 vs v3 are NOT on the same simulation sample, so some PnL
#  difference is expected from randomness. However -171k vs -27k is far outside
#  normal variance — the structural changes in v3 caused the regression.
#
#  ───────────────────────────────────────────────────────────────────────────
#  v4 FIXES (all structural, zero parameter tuning from logs)
#  ───────────────────────────────────────────────────────────────────────────
#
#  FIX 1 — REMOVE HARD EXIT ENTIRELY
#    The hard exit was supposed to prevent permanent position lock. But for
#    random-walk and mean-reverting products, the position self-clears if you
#    stop adding to it. We don't need to force-exit by crossing spreads.
#    Instead, use one-sided quoting (FIX 3).
#
#  FIX 2 — USE MID AS FAIR VALUE (not EMA) for MM products
#    EMA lags the current price. When price drifts up, EMA is below mid,
#    making the ask = EMA + hs - skew lower than it should be. Bots fill it.
#    Position builds. Then hard exit fires below actual fair value.
#    Fix: use the CURRENT mid as fair value for quoting. The mid = (best_bid +
#    best_ask) / 2 is the market's current consensus on fair value. It has zero
#    lag. Keep EMA only for the MR strategy where it belongs.
#    EMA is still tracked for the group lead-lag signal (only cross-sectional).
#
#  FIX 3 — ONE-SIDED QUOTING when near position cap
#    When pos ≥ CAP_THRESHOLD (=8): do not post any buy orders.
#    When pos ≤ -CAP_THRESHOLD: do not post any sell orders.
#    This is the inventory management equivalent of "if you're already long
#    enough, stop going longer." No spread crossing needed. The position will
#    self-clear as the random-walk/MR product oscillates back through your
#    outstanding passive sell quote.
#
#  FIX 4 — BOUNDED SKEW (0.5, capped so ask ≥ mid+1 always)
#    The skew must never push ask below mid or bid above mid. With hs=9 and
#    skew=0.5×pos: at pos=8, ask = mid+9-4 = mid+5 (still above mid ✓).
#    Hard cap: ask_px = max(ask_px, int(mid)+1), bid_px = min(bid_px, int(mid)-1)
#    This prevents ever selling below or buying above fair value.
#
#  FIX 5 — REMOVE OXYGEN_SHAKE_CHOCOLATE from MR
#    In v3 live run it lost -2,288. Its ACF=-0.084 is below the 95% CI
#    significance threshold in the most recent live data. Only EVENING_BREATH
#    has ACF=-0.128, consistently significant. Remove SHAKE_CHOCOLATE from MR.
#
#  UNCHANGED from v3:
#    Product list, hs values, SNACKPACK stat-arb, pair parameters
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT          = 10
CAP_THRESHOLD  = 8    # stop adding in direction of exposure above this


# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK  (spread/noise 2.1–3.0×) ──────────────────────────────────
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},

    # ── UV_VISOR  (kept 3 per v3) ────────────────────────────────────────────
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},

    # ── GALAXY_SOUNDS  (2 per v3) ────────────────────────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG  (FIX 5: only EVENING_BREATH; SHAKE_CHOCOLATE removed)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH":  {"ema_span": 20, "mr_thr": 32, "mr_aggr": 50},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (unchanged — these worked in v2)
# ─────────────────────────────────────────────────────────────────────────────
PAIRS: List[Tuple[str, str, float, float]] = [
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_PISTACHIO",  1.0368, 0.0213),
    ("SNACKPACK_VANILLA",    "SNACKPACK_RASPBERRY",  1.0022, 0.0242),
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_RASPBERRY",  0.9770, 0.0252),
    ("SNACKPACK_VANILLA",    "SNACKPACK_PISTACHIO",  1.0639, 0.0325),
]
ENTRY_Z   = 1.5
EXIT_Z    = 0.3
PAIR_SIZE = 3
RATIO_SPAN = 50

# ─────────────────────────────────────────────────────────────────────────────
#  GROUPS for lead-lag cross-sectional signal (Hint 1)
#  NOTE: group signal now uses CURRENT MIDS (not EMAs) to avoid lag
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK": ["SNACKPACK_PISTACHIO", "SNACKPACK_VANILLA",
                  "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE", "SNACKPACK_STRAWBERRY"],
    "UV_VISOR":  ["UV_VISOR_MAGENTA", "UV_VISOR_YELLOW", "UV_VISOR_ORANGE"],
    "GALAXY":    ["GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_BLACK_HOLES"],
}
GROUP_PULL = 0.2   # reduced from 0.4 — conservative; using mids now (more accurate)


class Trader:

    def run(self, state: TradingState):

        try:
            sv = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sv = {}
        ema_map:   Dict[str, float] = sv.get("ema", {})
        rmean_map: Dict[str, float] = sv.get("rm",  {})
        pair_pos:  Dict[str, int]   = sv.get("pp",  {})

        result: Dict[str, List[Order]] = {}

        # ── Step 1: Compute current mids + update EMAs ───────────────────────
        # Mid is the primary fair-value anchor for MM (no lag).
        # EMA is still updated for MR products and for the group signal.
        mid_map: Dict[str, float] = {}
        all_prods = set(MM_CFG) | set(MR_CFG)

        for prod in all_prods:
            if prod not in state.order_depths:
                continue
            od = state.order_depths[prod]
            bb = max(od.buy_orders)  if od.buy_orders  else None
            ba = min(od.sell_orders) if od.sell_orders else None
            if bb is None and ba is None:
                continue
            mid = (bb + ba) / 2.0 if (bb and ba) else float(bb or ba)
            mid_map[prod] = mid

            cfg   = MM_CFG.get(prod) or MR_CFG.get(prod, {})
            alpha = 2.0 / (cfg.get("ema_span", 20) + 1.0)
            ema_map[prod] = alpha * mid + (1.0 - alpha) * ema_map.get(prod, mid)

        # ── Step 2: Group signal from CURRENT mids (not EMAs) ────────────────
        # Using mids avoids lag. Cross-sectional signal: if one product in the
        # group has drifted above the group average, its fair value gets pulled
        # slightly down (and vice versa). This is the lead-lag mechanism.
        group_mid: Dict[str, float] = {}
        for grp, members in GROUPS.items():
            vals = [mid_map[p] for p in members if p in mid_map]
            if vals:
                group_mid[grp] = sum(vals) / len(vals)

        # ── Step 3: Market making ────────────────────────────────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            od  = state.order_depths[prod]
            grp = cfg["group"]

            # FIX 2: fair value = current mid (not EMA)
            mid  = mid_map[prod]
            fair = mid + GROUP_PULL * (group_mid.get(grp, mid) - mid) \
                   if grp and grp in group_mid else mid

            result[prod] = self._mm(prod, od, pos, fair, cfg["mm_hs"])

        # ── Step 4: Mean reversion ───────────────────────────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                ema_map[prod], cfg["mr_thr"], cfg["mr_aggr"]
            )

        # ── Step 5: Stat-arb (SNACKPACK) ─────────────────────────────────────
        pair_orders: Dict[str, List[Order]] = {}
        for pa, pb, hist_mean, hist_std in PAIRS:
            if pa not in mid_map or pb not in mid_map:
                continue
            ratio = mid_map[pa] / mid_map[pb]
            pkey  = f"{pa}|{pb}"
            alpha = 2.0 / (RATIO_SPAN + 1.0)
            rmean = alpha * ratio + (1.0 - alpha) * rmean_map.get(pkey, hist_mean)
            rmean_map[pkey] = rmean
            z        = (ratio - rmean) / hist_std
            cur_side = pair_pos.get(pkey, 0)
            pos_a    = state.position.get(pa, 0)
            pos_b    = state.position.get(pb, 0)
            od_a     = state.order_depths[pa]
            od_b     = state.order_depths[pb]

            if cur_side == 0:
                if z > ENTRY_Z and od_a.buy_orders and od_b.sell_orders:
                    vol = min(PAIR_SIZE, LIMIT + pos_a, LIMIT - pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, max(od_a.buy_orders), -vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, min(od_b.sell_orders),  vol))
                        pair_pos[pkey] = -1
                elif z < -ENTRY_Z and od_a.sell_orders and od_b.buy_orders:
                    vol = min(PAIR_SIZE, LIMIT - pos_a, LIMIT + pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, min(od_a.sell_orders),  vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, max(od_b.buy_orders), -vol))
                        pair_pos[pkey] = 1
            elif abs(z) < EXIT_Z:
                if cur_side == -1 and od_a.sell_orders and od_b.buy_orders:
                    vol = min(PAIR_SIZE, LIMIT - pos_a, LIMIT + pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, min(od_a.sell_orders),  vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, max(od_b.buy_orders), -vol))
                        pair_pos[pkey] = 0
                elif cur_side == 1 and od_a.buy_orders and od_b.sell_orders:
                    vol = min(PAIR_SIZE, LIMIT + pos_a, LIMIT - pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, max(od_a.buy_orders), -vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, min(od_b.sell_orders),  vol))
                        pair_pos[pkey] = 0

        for prod, orders in pair_orders.items():
            result.setdefault(prod, []).extend(orders)

        return result, 0, json.dumps({"ema": ema_map, "rm": rmean_map, "pp": pair_pos})

    # ─────────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, hs: int) -> List[Order]:
        """
        Market making — v4 fixes applied.

        FIX 2: fair value is passed in as current mid (not EMA).

        FIX 4: bounded skew.
          skew = pos × 0.5, but capped so that:
            ask_px is ALWAYS ≥ int(fair) + 1  (never sell below fair)
            bid_px is ALWAYS ≤ int(fair) - 1  (never buy above fair)
          At pos=0:   bid=fair-hs,   ask=fair+hs     (symmetric)
          At pos=+8:  bid=fair-hs-4, ask=fair+hs-4   (ask closer to fair)
          At pos=+10: bid=fair-hs-5, ask=fair+hs-5   (ask = fair+hs-5)
                      With hs=9: ask = fair+4 (still above fair ✓)

        FIX 3: one-sided quoting.
          When pos ≥ CAP_THRESHOLD: buy_cap=0 (no new buys)
          When pos ≤ -CAP_THRESHOLD: sell_cap=0 (no new sells)
          This stops the position drifting further in a bad direction
          WITHOUT crossing the spread. The existing passive ask/bid will
          clear the position as the price naturally oscillates.

        NO hard exit (FIX 1).
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # FIX 3: one-sided quoting near cap
        if pos >= CAP_THRESHOLD:
            buy_cap = 0
        if pos <= -CAP_THRESHOLD:
            sell_cap = 0

        # FIX 4: bounded skew
        # Cap magnitude at (hs - 1) so ask never goes below fair+1
        raw_skew = pos * 0.5
        skew = int(round(max(-(hs - 1), min(hs - 1, raw_skew))))

        bid_px = round(fair - hs - skew)
        ask_px = round(fair + hs - skew)

        # Hard bound: NEVER post bid > fair-1 or ask < fair+1
        bid_px = min(bid_px, int(fair) - 1)
        ask_px = max(ask_px, int(fair) + 1)

        # Snipe clearly mispriced orders (only when capacity allows)
        if od.sell_orders and buy_cap > 0:
            best_ask = min(od.sell_orders)
            if best_ask <= bid_px:
                vol = min(-od.sell_orders[best_ask], buy_cap)
                orders.append(Order(product, best_ask, vol))
                buy_cap -= vol

        if od.buy_orders and sell_cap > 0:
            best_bid = max(od.buy_orders)
            if best_bid >= ask_px:
                vol = min(od.buy_orders[best_bid], sell_cap)
                orders.append(Order(product, best_bid, -vol))
                sell_cap -= vol

        # Passive resting quotes
        if buy_cap > 0:
            orders.append(Order(product, bid_px, buy_cap))
        if sell_cap > 0:
            orders.append(Order(product, ask_px, -sell_cap))

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    def _mr(self, product: str, od: OrderDepth, pos: int,
            ema: float, thr: float, aggr: float) -> List[Order]:
        """
        Mean-reversion unchanged. EMA is correct here — we're deliberately
        betting on reversion to a trailing mean.
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        if od.sell_orders and buy_cap > 0:
            for ask in sorted(od.sell_orders):
                dev = ema - ask
                if dev < thr:
                    break
                vol = min(-od.sell_orders[ask], buy_cap)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    buy_cap -= vol
                if buy_cap == 0 or dev < aggr:
                    break

        if od.buy_orders and sell_cap > 0:
            for bid in sorted(od.buy_orders, reverse=True):
                dev = bid - ema
                if dev < thr:
                    break
                vol = min(od.buy_orders[bid], sell_cap)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    sell_cap -= vol
                if sell_cap == 0 or dev < aggr:
                    break

        unwind_vol = min(3, abs(pos))
        if unwind_vol > 0:
            if pos > 0 and sell_cap > 0:
                orders.append(Order(product, round(ema + thr * 0.4), -unwind_vol))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order(product, round(ema - thr * 0.4), unwind_vol))

        return orders


# ═══════════════════════════════════════════════════════════════════════════════
#  CHANGE TABLE (v3 → v4)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                    | v3       | v4       | Economic justification
#  ──────────────────────────┼──────────┼──────────┼──────────────────────────
#  Hard exit mechanism       | YES      | REMOVED  | Death spiral: forced exits
#                            |          |          | cross spread every 5 ticks
#  Fair value for MM         | EMA      | mid      | EMA lags → adverse select.
#  Inventory skew            | 1.0      | 0.5      | 1.0 pushed ask below fair
#  Skew hard bound           | none     | added    | ask≥fair+1 always
#  One-sided quoting cap     | pos≥8    | pos≥8    | unchanged concept; now
#                            | hard exit| stop buy | gentler implementation
#  Group signal              | EMA-based| mid-based| removes lag from signal
#  GROUP_PULL                | 0.4      | 0.2      | conservative w/ mids
#  SHAKE_CHOCOLATE in MR     | YES      | REMOVED  | ACF below significance CI
#  stuck_ticks state         | tracked  | removed  | no longer needed
#
#  WHAT WE ARE CERTAIN FIXED THE v3 REGRESSION (not overfitting):
#    - hard exit removal: the straight-line linear PnL decline is a textbook
#      signature of repeated spread-crossing. Every product showed this.
#    - skew bound: ask = fair-1 at pos=10 was provably wrong; bots arbitraged it.
#
#  WHAT WE ARE LESS CERTAIN ABOUT (monitor but don't tune):
#    - mid vs EMA as fair value: mid is more responsive; EMA is smoother.
#      If SNACKPACK shows very noisy fills in test (no consistent fills on
#      either side), the mid may be too jumpy. Do NOT change this based on
#      PnL — only change if order fills are clearly wrong (e.g. always fill
#      at ask, never at bid, suggesting fair is anchored at wrong price).
#    - GROUP_PULL 0.2: conservative. The lead-lag signal is real (Hint 1)
#      but hard to size without overfitting. 0.2 is a gentle nudge.
#
# ═══════════════════════════════════════════════════════════════════════════════