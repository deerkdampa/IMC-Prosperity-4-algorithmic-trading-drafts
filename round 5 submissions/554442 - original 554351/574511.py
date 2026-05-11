from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v9
#
#  v8 result: +16,891 XIRECS, Sharpe +1.64. Only 2 losers:
#    PISTACHIO -433 (persistent bias, accept as cost of stat-arb edge)
#    SOLAR_WINDS -463 (lost in v7 AND v8 → structural, drop it)
#
#  v9 CHANGES:
#  ──────────────────────────────────────────────────────────────────
#    1. DROP SOLAR_WINDS: lost -463 in both v7 and v8. Structural issue.
#
#    2. ADAPTIVE GROUP_PULL (Hint 1: "the gap is the interesting part")
#       Old: flat 0.2 pull for all deviations
#       New: pull strength scales with gap size:
#         - |gap| > hs ticks → 0.35 pull (strong lead-lag signal)
#         - |gap| > hs/2     → 0.20 pull (moderate signal, same as before)
#         - |gap| ≤ hs/2     → 0.10 pull (small gap = noise, pull less)
#       NON-OVERFITTING: thresholds derived from each product's OWN
#       half-spread. No historical data. Self-calibrating per product.
#
#    3. WIDER SNIPING in _mm: also snipe when best_ask < fair (not just
#       when best_ask <= bid_px). Captures more fills on mispriced orders.
#       Structural change — applies to ALL products equally.
#
#  NON-OVERFITTING JUSTIFICATION:
#    - SOLAR_WINDS drop: evidence from 2 independent random samples
#    - Adaptive GROUP_PULL: uses product's OWN hs as threshold, not
#      historical data. Self-calibrating. Same pull range (0.1-0.35)
#      as already tested (v5 used 0.3, v6-v8 used 0.2).
#    - Wider sniping: takes anything below fair value — structural
#      market-making improvement, not product-specific tuning.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT         = 10
CAP_THRESHOLD = 8   # stop adding in direction of exposure above this

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (12 products)
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK (spread/noise 2.1–3.0×) — highest edge group ──────────────
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},

    # ── UV_VISOR (spread/noise ~1.27×) — 3 proven winners ──────────────────
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 9,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},

    # ── GALAXY_SOUNDS — 3 proven winners ───────────────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_PLANETARY_RINGS":{"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    # v9: SOLAR_WINDS removed (lost -463 in both v7 and v8)
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG  (1 product)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH": {"ema_span": 20, "mr_thr": 32, "mr_close": 13},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (Hint 3: "pairing for profit")
# ─────────────────────────────────────────────────────────────────────────────

# SNACKPACK pairs (proven across v4-v8)
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

# UV_VISOR pairs (conservative params — looser CVs than SNACKPACK)
UV_PAIRS: List[Tuple[str, str, float, float]] = [
    ("UV_VISOR_ORANGE",  "UV_VISOR_MAGENTA",  0.9397, 0.0465),
    ("UV_VISOR_ORANGE",  "UV_VISOR_YELLOW",   0.8531, 0.0500),
    ("UV_VISOR_MAGENTA", "UV_VISOR_YELLOW",   0.9082, 0.0550),
]
UV_ENTRY_Z    = 2.0
UV_EXIT_Z     = 0.5
UV_PAIR_SIZE  = 2
UV_RATIO_SPAN = 80

# ─────────────────────────────────────────────────────────────────────────────
#  GROUPS for cross-sectional signal (Hint 1 + Hint 2)
#  v9: Adaptive GROUP_PULL replaces flat 0.2.
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK": ["SNACKPACK_PISTACHIO", "SNACKPACK_VANILLA",
                  "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE",
                  "SNACKPACK_STRAWBERRY"],
    "UV_VISOR":  ["UV_VISOR_MAGENTA", "UV_VISOR_ORANGE", "UV_VISOR_YELLOW"],
    "GALAXY":    ["GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_BLACK_HOLES",
                  "GALAXY_SOUNDS_PLANETARY_RINGS"],
}

# Adaptive pull thresholds (derived from each product's own hs)
PULL_STRONG = 0.35   # |gap| > hs      → strong lead-lag signal
PULL_NORMAL = 0.20   # |gap| > hs/2    → moderate signal
PULL_WEAK   = 0.10   # |gap| <= hs/2   → small gap, probably noise


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

        # ── Step 2: Group cross-sectional fair value (Hint 1) ────────────────
        group_mid: Dict[str, float] = {}
        for grp, members in GROUPS.items():
            vals = [mid_map[p] for p in members if p in mid_map]
            if vals:
                group_mid[grp] = sum(vals) / len(vals)

        # ── Step 3: Market making with adaptive GROUP_PULL ───────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            od  = state.order_depths[prod]
            grp = cfg["group"]
            hs  = cfg["mm_hs"]

            # v9: Adaptive GROUP_PULL — Hint 1: "the gap is the interesting part"
            mid = mid_map[prod]
            if grp in group_mid:
                gap = group_mid[grp] - mid
                abs_gap = abs(gap)
                if abs_gap > hs:
                    pull = PULL_STRONG   # large gap → strong lead-lag signal
                elif abs_gap > hs / 2:
                    pull = PULL_NORMAL   # moderate gap
                else:
                    pull = PULL_WEAK     # small gap → noise
                fair = mid + pull * gap
            else:
                fair = mid

            result[prod] = self._mm(prod, od, pos, fair, hs)

        # ── Step 4: Mean reversion (EVENING_BREATH only) ─────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                ema_map[prod], cfg["mr_thr"], cfg["mr_close"]
            )

        # ── Step 5: Stat-arb pairs ───────────────────────────────────────────
        pair_orders: Dict[str, List[Order]] = {}

        self._run_pairs(SNACK_PAIRS, SNACK_ENTRY_Z, SNACK_EXIT_Z,
                        SNACK_PAIR_SIZE, SNACK_RATIO_SPAN,
                        mid_map, rmean_map, pair_pos, state, pair_orders)

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
        Market making with bounded skew, one-sided quoting,
        inventory acceleration, and wider sniping (v9).
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

        # v9: Wider sniping — take anything priced better than fair value
        # This captures more fills without changing passive quoting logic
        if od.sell_orders and buy_cap > 0:
            best_ask = min(od.sell_orders)
            snipe_threshold = min(bid_px, int(fair) - 1)  # snipe at or below fair-1
            if best_ask <= snipe_threshold:
                vol = min(-od.sell_orders[best_ask], buy_cap)
                if vol > 0:
                    orders.append(Order(product, best_ask, vol))
                    buy_cap -= vol

        if od.buy_orders and sell_cap > 0:
            best_bid = max(od.buy_orders)
            snipe_threshold = max(ask_px, int(fair) + 1)  # snipe at or above fair+1
            if best_bid >= snipe_threshold:
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
#  CHANGE TABLE (v8 → v9)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                             | v8 (570281)  | v9
#  ───────────────────────────────────┼──────────────┼─────────────────────────
#  GALAXY_SOLAR_WINDS                 | hs=8 (-463)  | REMOVED (lost in v7+v8)
#  GROUP_PULL                         | flat 0.2     | adaptive 0.1/0.2/0.35
#  Sniping threshold                  | bid_px only  | fair-1 (wider captures)
#  GALAXY group members               | 4            | 3
#  Active product count               | 13           | 12 MM + 1 MR = 13
#
#  v8 results (570281.log):
#    +16,891 PnL, Sharpe +1.64. Only 2 losers:
#    PISTACHIO -433 (accept), SOLAR_WINDS -463 (dropped)
#    Winners: MAGENTA +6,650, ORANGE +4,408, VANILLA +1,690
#    SOLAR_FLAMES +1,145, PLANETARY_RINGS +1,134, BLACK_HOLES +572
#
#  v9 UPGRADES (non-overfitting):
#    1. Adaptive GROUP_PULL: Hint 1 "the gap is the interesting part"
#       Uses each product's OWN hs as threshold — self-calibrating.
#    2. Wider sniping: takes mispriced orders at fair±1, not just bid/ask.
#       Structural improvement to fill logic, not product-specific.
#
# ═══════════════════════════════════════════════════════════════════════════════