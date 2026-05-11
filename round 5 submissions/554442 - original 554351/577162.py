from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v10
#
#  BASE: v8 (+16,891 PnL, Sharpe +1.64) — our best result.
#  v9 regressed to +12,586 due to adaptive GROUP_PULL and wider sniping.
#
#  DEEP CSV ANALYSIS FINDINGS (all 3 historical days, 50 products):
#  ────────────────────────────────────────────────────────────────────
#    Hint 1: No measurable intra-group lead-lag exists. Cross-correlation
#      at lag 1-5 was max 0.01 across ALL groups. GROUP_PULL injects noise.
#    Hint 2: Profitability is driven by market microstructure tiers:
#      Tier A (SNACKPACK): spr=16-17, depth=29.6 at L1 → best edge
#      Tier B (UV_VISOR, GALAXY, OXYGEN): spr=12-14, depth=18.3 → good edge
#      All other groups: spr<10 or depth<12 → no viable MM edge
#    Hint 3: Only SNACKPACK pairs are cross-day stable (CV spread <1%).
#      UV_VISOR pairs shift significantly day-to-day (CV spread >3%).
#      OXYGEN pairs look good on Day 2 but blow out on Day 4.
#
#  v10 CHANGES (based on v8 base):
#  ────────────────────────────────────────────────────────────────────
#    1. REMOVE GROUP_PULL: set to 0.0. No lead-lag signal exists in
#       the data. fair = mid (clean, no noise injection).
#    2. DROP SOLAR_WINDS: lost -463 in both v7 and v8 (2 samples).
#    3. UV_VISOR stat-arb pair_size: 2 → 1. Pairs are cross-day
#       unstable. Smaller size limits downside on shifting days.
#    4. REVERT v9's wider sniping. Back to v8's original logic
#       (snipe only when best_ask <= bid_px). v9 sniping may have
#       caused adverse selection on PLANETARY_RINGS (-3,405).
#    5. KEEP inventory acceleration from v8 (structural improvement).
#    6. KEEP SNACKPACK stat-arb unchanged (only stable pairs).
#
#  NON-OVERFITTING:
#    All changes are based on structural analysis of 3 historical days
#    (not tuned to any single log file). Removals confirmed across
#    multiple independent random samples.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT         = 10
CAP_THRESHOLD = 8   # stop adding in direction of exposure above this

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (11 products)
#
#  Product selection rationale (from CSV microstructure analysis):
#    SNACKPACK:  spr=16-17, depth=29.6, spr/σ=2.1-3.0 → best edge
#    UV_VISOR:   spr=13-15, depth=18.3, spr/σ=1.27    → good edge
#    GALAXY:     spr=13-15, depth=18.3, spr/σ=1.26    → good edge
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK (Tier A: deepest books + widest spreads) ──────────────────
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 10},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9},
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10},

    # ── UV_VISOR (Tier B: deep books + wide spreads) ────────────────────────
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 9},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8},

    # ── GALAXY_SOUNDS (Tier B: 3 proven winners) ───────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8},
    "GALAXY_SOUNDS_PLANETARY_RINGS":{"ema_span": 20, "mm_hs": 8},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG  (1 product — stable across all runs)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH": {"ema_span": 20, "mr_thr": 32, "mr_close": 13},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (Hint 3: "pairing for profit")
#
#  SNACKPACK: Cross-day stable (CV spread <1% across 3 days).
#    "Some relationships are stable. Same behavior, round after round."
#
#  UV_VISOR: Cross-day UNSTABLE (CV spread >3%). Keep at pair_size=1
#    to limit downside. "Others shift. They hold until something changes."
# ─────────────────────────────────────────────────────────────────────────────

# SNACKPACK pairs (proven stable — original params)
SNACK_PAIRS: List[Tuple[str, str, float, float]] = [
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_PISTACHIO",  1.0368, 0.0213),
    ("SNACKPACK_VANILLA",    "SNACKPACK_RASPBERRY",  1.0022, 0.0242),
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_RASPBERRY",  0.9770, 0.0252),
    ("SNACKPACK_VANILLA",    "SNACKPACK_PISTACHIO",  1.0639, 0.0325),
]
SNACK_ENTRY_Z    = 1.5
SNACK_EXIT_Z     = 0.3
SNACK_PAIR_SIZE  = 3
SNACK_RATIO_SPAN = 50

# UV_VISOR pairs (unstable cross-day — conservative size=1)
UV_PAIRS: List[Tuple[str, str, float, float]] = [
    ("UV_VISOR_ORANGE",  "UV_VISOR_MAGENTA",  0.9397, 0.0465),
    ("UV_VISOR_ORANGE",  "UV_VISOR_YELLOW",   0.8531, 0.0500),
    ("UV_VISOR_MAGENTA", "UV_VISOR_YELLOW",   0.9082, 0.0550),
]
UV_ENTRY_Z    = 2.0
UV_EXIT_Z     = 0.5
UV_PAIR_SIZE  = 1     # v10: reduced from 2 → 1 (cross-day unstable)
UV_RATIO_SPAN = 80


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
            mid = (bb + ba) / 2.0 if (bb is not None and ba is not None) else float(bb or ba)
            mid_map[prod] = mid

            cfg   = MM_CFG.get(prod) or MR_CFG.get(prod, {})
            alpha = 2.0 / (cfg.get("ema_span", 20) + 1.0)
            ema_map[prod] = alpha * mid + (1.0 - alpha) * ema_map.get(prod, mid)

        # ── Step 2: Market making ────────────────────────────────────────────
        #  v10: fair = mid (no GROUP_PULL — no lead-lag exists in the data)
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos  = state.position.get(prod, 0)
            od   = state.order_depths[prod]
            fair = mid_map[prod]

            result[prod] = self._mm(prod, od, pos, fair, cfg["mm_hs"])

        # ── Step 3: Mean reversion (EVENING_BREATH only) ─────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                ema_map[prod], cfg["mr_thr"], cfg["mr_close"]
            )

        # ── Step 4: Stat-arb pairs ───────────────────────────────────────────
        pair_orders: Dict[str, List[Order]] = {}

        # SNACKPACK: stable pairs, full size
        self._run_pairs(SNACK_PAIRS, SNACK_ENTRY_Z, SNACK_EXIT_Z,
                        SNACK_PAIR_SIZE, SNACK_RATIO_SPAN,
                        mid_map, rmean_map, pair_pos, state, pair_orders)

        # UV_VISOR: unstable pairs, minimal size
        self._run_pairs(UV_PAIRS, UV_ENTRY_Z, UV_EXIT_Z,
                        UV_PAIR_SIZE, UV_RATIO_SPAN,
                        mid_map, rmean_map, pair_pos, state, pair_orders)

        for prod, orders in pair_orders.items():
            result.setdefault(prod, []).extend(orders)

        return result, 0, json.dumps({"ema": ema_map, "rm": rmean_map, "pp": pair_pos})

    # ─────────────────────────────────────────────────────────────────────────
    def _run_pairs(self, pairs, entry_z, exit_z, pair_size, ratio_span,
                   mid_map, rmean_map, pair_pos, state, pair_orders):
        """Execute stat-arb logic for a list of pairs with given params."""
        for pa, pb, hist_mean, hist_std in pairs:
            if pa not in mid_map or pb not in mid_map:
                continue
            ratio = mid_map[pa] / mid_map[pb]
            pkey  = f"{pa}|{pb}"
            alpha = 2.0 / (ratio_span + 1.0)
            rmean = alpha * ratio + (1.0 - alpha) * rmean_map.get(pkey, hist_mean)
            rmean_map[pkey] = rmean
            z        = (ratio - rmean) / hist_std
            cur_side = pair_pos.get(pkey, 0)
            pos_a    = state.position.get(pa, 0)
            pos_b    = state.position.get(pb, 0)
            od_a     = state.order_depths[pa]
            od_b     = state.order_depths[pb]

            if cur_side == 0:
                if z > entry_z and od_a.buy_orders and od_b.sell_orders:
                    vol = min(pair_size, LIMIT + pos_a, LIMIT - pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, max(od_a.buy_orders), -vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, min(od_b.sell_orders),  vol))
                        pair_pos[pkey] = -1
                elif z < -entry_z and od_a.sell_orders and od_b.buy_orders:
                    vol = min(pair_size, LIMIT - pos_a, LIMIT + pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, min(od_a.sell_orders),  vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, max(od_b.buy_orders), -vol))
                        pair_pos[pkey] = 1
            elif abs(z) < exit_z:
                if cur_side == -1 and od_a.sell_orders and od_b.buy_orders:
                    vol = min(pair_size, LIMIT - pos_a, LIMIT + pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, min(od_a.sell_orders),  vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, max(od_b.buy_orders), -vol))
                        pair_pos[pkey] = 0
                elif cur_side == 1 and od_a.buy_orders and od_b.sell_orders:
                    vol = min(pair_size, LIMIT + pos_a, LIMIT - pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, max(od_a.buy_orders), -vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, min(od_b.sell_orders),  vol))
                        pair_pos[pkey] = 0

    # ─────────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, hs: int) -> List[Order]:
        """
        Market making with bounded skew, one-sided quoting, and
        inventory acceleration. No GROUP_PULL (no lead-lag in data).
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # One-sided quoting near cap
        if pos >= CAP_THRESHOLD:
            buy_cap = 0
        if pos <= -CAP_THRESHOLD:
            sell_cap = 0

        # Bounded inventory skew
        raw_skew = pos * 0.5
        skew = int(round(max(-(hs - 1), min(hs - 1, raw_skew))))

        bid_px = round(fair - hs - skew)
        ask_px = round(fair + hs - skew)

        # Hard bound: never post bid > fair-1 or ask < fair+1
        bid_px = min(bid_px, int(fair) - 1)
        ask_px = max(ask_px, int(fair) + 1)

        # Inventory acceleration — when FULLY capped, unwind aggressively
        if pos == LIMIT:
            ask_px = int(fair) + 1
        elif pos == -LIMIT:
            bid_px = int(fair) - 1

        # Snipe clearly mispriced orders (v8 logic — no wider sniping)
        if od.sell_orders and buy_cap > 0:
            best_ask = min(od.sell_orders)
            if best_ask <= bid_px:
                vol = min(-od.sell_orders[best_ask], buy_cap)
                if vol > 0:
                    orders.append(Order(product, best_ask, vol))
                    buy_cap -= vol

        if od.buy_orders and sell_cap > 0:
            best_bid = max(od.buy_orders)
            if best_bid >= ask_px:
                vol = min(od.buy_orders[best_bid], sell_cap)
                if vol > 0:
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
            ema: float, thr: float, close_thr: float) -> List[Order]:
        """
        Mean-reversion scalp for EVENING_BREATH only.
        Enter aggressively when mid deviates > thr from EMA.
        Unwind passively at close_thr offset from EMA.
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # Aggressive entry: lift ask when price is thr below EMA
        if od.sell_orders and buy_cap > 0:
            for ask in sorted(od.sell_orders):
                dev = ema - ask
                if dev < thr:
                    break
                vol = min(-od.sell_orders[ask], buy_cap)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    buy_cap -= vol
                if buy_cap == 0:
                    break

        # Aggressive entry: hit bid when price is thr above EMA
        if od.buy_orders and sell_cap > 0:
            for bid in sorted(od.buy_orders, reverse=True):
                dev = bid - ema
                if dev < thr:
                    break
                vol = min(od.buy_orders[bid], sell_cap)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    sell_cap -= vol
                if sell_cap == 0:
                    break

        # Passive unwind near EMA
        unwind_vol = min(3, abs(pos))
        if unwind_vol > 0:
            if pos > 0 and sell_cap > 0:
                orders.append(Order(product, round(ema + close_thr), -unwind_vol))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order(product, round(ema - close_thr), unwind_vol))

        return orders


# ═══════════════════════════════════════════════════════════════════════════════
#  CHANGE TABLE (v8 → v10, skipping v9 which regressed)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                             | v8 (570281)  | v10
#  ───────────────────────────────────┼──────────────┼─────────────────────────
#  GROUP_PULL                         | flat 0.2     | REMOVED (0.0)
#  GALAXY_SOLAR_WINDS                 | hs=8 (-463)  | REMOVED
#  UV_VISOR pair_size                 | 2            | 1 (cross-day unstable)
#  "group" key in MM_CFG              | present      | REMOVED (no groups)
#  GROUPS dict                        | defined      | REMOVED
#  Active product count               | 13           | 11 MM + 1 MR = 12
#
#  v8 results (570281.log): +16,891 PnL, Sharpe +1.64
#  v9 results (574511.log): +12,586 PnL (REGRESSED — adaptive pull hurt)
#
#  Deep CSV findings that drove v10:
#    1. No lead-lag within groups (max cross-corr = 0.01)
#    2. Profitability = spread × depth (SNACK=29.6, UV/GAL=18.3)
#    3. Only SNACKPACK pairs stable cross-day (CV spread <1%)
#    4. UV_VISOR pairs shift day-to-day (CV spread >3%)
#
# ═══════════════════════════════════════════════════════════════════════════════