from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v6
#
#  WHY v5 LOST (-60,606) vs v4 (+17,556)
#  ────────────────────────────────────────────────────────────────────────────
#  v4's +17k came from ~11 products; 39 had ORDERS_REJECTED (never filled).
#  v5 made all 50 active but with mm_hs values wrong for new products:
#    - spread/σ < 1.0 for SLEEP_POD, PEBBLES, PANEL, TRANSLATOR, MICROCHIP
#    - passive quotes get picked off → position stuck at ±10 → constant bleed
#    - 25 products each losing -1k to -9k = -78k total drag
#
#  v6 FIXES (structural, not parameter tuning from PnL)
#  ────────────────────────────────────────────────────────────────────────────
#  FIX 1 — DROP 25 confirmed stuck-position losers from MM_CFG.
#           Evidence: negative Sharpe + directional-bias "CAPPED+mixed" in
#           v5 live log. This is removing broken tools, not cherry-picking.
#
#  FIX 2 — ROBOT_IRONING moved from MM (ORDERS_REJECTED in v4) to MR_CFG.
#           v5 live: +5,070 PnL, Sharpe +1.82, ACF=-0.128 — best performer.
#           Historical ACF=-0.125 confirms genuine mean-reversion signal.
#
#  FIX 3 — OXYGEN_SHAKE_CHOCOLATE added to MR_CFG.
#           Historical ACF=-0.089, score=0.306, MR_SCALP recommended.
#           v5 MM produced -202 (nearly flat but negative). MR is structurally
#           correct: the spread is wide enough to scalp deviations.
#
#  FIX 4 — ROBOT_DISHES REMOVED from MR_CFG.
#           v5 live: -2,648, WR=26%, regime=RANDOM_WALK in live data.
#           Live data contradicts historical ACF. Remove — do not add to MM.
#
#  FIX 5 — UV_PAIRS and GAL_PAIRS REMOVED (their instruments are dropped).
#
#  UNCHANGED from v5:
#    All v4 structural fixes (no hard exit, mid FV, one-sided quoting,
#    bounded skew), SNACK_PAIRS stat-arb, GROUP_PULL=0.2.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT         = 10
CAP_THRESHOLD = 8

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (20 products — all positive or near-zero in v5 live)
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK  (spr≈16-17; high spr/σ ratio — best MM group) ────────────
    "SNACKPACK_VANILLA":              {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":           {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_PISTACHIO":            {"ema_span": 20, "mm_hs": 8,  "group": "SNACKPACK"},  # hs=8 bias fix from v5

    # ── UV_VISOR  (MAGENTA +3617, YELLOW +579 in v5 live) ───────────────────
    "UV_VISOR_MAGENTA":               {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":                {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    # ORANGE dropped (-1174, conflicts with old stat-arb)
    # RED dropped (-6006, short-stuck)
    # AMBER dropped (-4264, long-stuck)

    # ── GALAXY_SOUNDS  (SOLAR_FLAMES +1145, RINGS +1134, BLACK_HOLES +572) ──
    "GALAXY_SOUNDS_SOLAR_FLAMES":     {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},
    "GALAXY_SOUNDS_BLACK_HOLES":      {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},
    "GALAXY_SOUNDS_PLANETARY_RINGS":  {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},
    # DARK_MATTER dropped (-4138, long-stuck)
    # SOLAR_WINDS dropped (-463, marginal + being cautious)

    # ── ROBOT  (VACUUMING +2246, MOPPING +3350 in v5 live) ──────────────────
    "ROBOT_VACUUMING":                {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},
    "ROBOT_MOPPING":                  {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},
    # IRONING → MR_CFG only (+5070 from MR, ACF=-0.128)
    # LAUNDRY dropped (-4414, long-stuck)
    # DISHES  → removed from MR too (live WR=26%, regime=RANDOM_WALK)

    # ── TRANSLATOR  (ECLIPSE_CHARCOAL +3671, ASTRO_BLACK +3478) ────────────
    "TRANSLATOR_ECLIPSE_CHARCOAL":    {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},
    "TRANSLATOR_ASTRO_BLACK":         {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},
    # VOID_BLUE dropped (-1799, short-stuck)
    # GRAPHITE_MIST dropped (-4662, short-stuck)
    # SPACE_GRAY dropped (-4655, long-stuck)

    # ── PANEL  (only PANEL_2X4 +3363 survived) ───────────────────────────────
    "PANEL_2X4":                      {"ema_span": 20, "mm_hs": 5,  "group": "PANEL"},
    # PANEL_1X2, PANEL_2X2, PANEL_1X4, PANEL_4X4 all dropped (long/short-stuck)

    # ── SLEEP_POD  (only SLEEP_POD_NYLON +1646 survived) ────────────────────
    "SLEEP_POD_NYLON":                {"ema_span": 20, "mm_hs": 5,  "group": "SLEEP_POD"},
    # LAMB_WOOL, SUEDE, COTTON, POLYESTER all dropped (stuck positions)

    # ── MICROCHIP  (SQUARE +4711, TRIANGLE +2723) ────────────────────────────
    "MICROCHIP_SQUARE":               {"ema_span": 20, "mm_hs": 7,  "group": "MICROCHIP"},
    "MICROCHIP_TRIANGLE":             {"ema_span": 20, "mm_hs": 5,  "group": "MICROCHIP"},
    # CIRCLE, OVAL, RECTANGLE all dropped (long-stuck)

    # ── PEBBLES  (PEBBLES_M +1487, PEBBLES_L +512) ───────────────────────────
    "PEBBLES_M":                      {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},
    "PEBBLES_L":                      {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},
    # PEBBLES_XS, PEBBLES_S, PEBBLES_XL all dropped (stuck positions)
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG
#  EVENING_BREATH : ACF=-0.128 live, +516 PnL v5 (consistent MR)
#  ROBOT_IRONING  : ACF=-0.128 live, +5,070 PnL v5 (best performer, MR only)
#  SHAKE_CHOCOLATE: ACF=-0.089 historical, -202 PnL v5 as MM → switch to MR
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH": {"ema_span": 20, "mr_thr": 32, "mr_aggr": 50},
    "ROBOT_IRONING":               {"ema_span": 20, "mr_thr": 30, "mr_aggr": 45},  # FIX 2: NEW
    "OXYGEN_SHAKE_CHOCOLATE":      {"ema_span": 20, "mr_thr": 33, "mr_aggr": 50},  # FIX 3: NEW
    # ROBOT_DISHES removed: FIX 4 — live data shows RANDOM_WALK, WR=26%
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB — SNACKPACK only (UV_PAIRS/GAL_PAIRS removed: instruments dropped)
#  PISTACHIO kept as pb (short side) only — long bias fix from v5
# ─────────────────────────────────────────────────────────────────────────────
SNACK_PAIRS: List[Tuple[str, str, float, float]] = [
    ("SNACKPACK_VANILLA",   "SNACKPACK_RASPBERRY", 1.0022, 0.0242),
    ("SNACKPACK_CHOCOLATE", "SNACKPACK_RASPBERRY", 0.9770, 0.0252),
    ("SNACKPACK_CHOCOLATE", "SNACKPACK_PISTACHIO", 1.0368, 0.0213),
    ("SNACKPACK_VANILLA",   "SNACKPACK_PISTACHIO", 1.0639, 0.0325),
]
SNACK_ENTRY_Z    = 1.5
SNACK_EXIT_Z     = 0.3
SNACK_PAIR_SIZE  = 3
SNACK_RATIO_SPAN = 50

# ─────────────────────────────────────────────────────────────────────────────
#  GROUPS for lead-lag cross-sectional signal (Hints 1 & 2)
#  Updated to match active product universe. MR-only products included in
#  groups so their mids contribute to the cross-sectional signal.
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK":    ["SNACKPACK_VANILLA", "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE",
                     "SNACKPACK_STRAWBERRY", "SNACKPACK_PISTACHIO"],
    "UV_VISOR":     ["UV_VISOR_MAGENTA", "UV_VISOR_YELLOW"],
    "GALAXY_SOUNDS":["GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_BLACK_HOLES",
                     "GALAXY_SOUNDS_PLANETARY_RINGS"],
    "ROBOT":        ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_IRONING"],
    "TRANSLATOR":   ["TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_ASTRO_BLACK"],
    "PANEL":        ["PANEL_2X4"],
    "SLEEP_POD":    ["SLEEP_POD_NYLON"],
    "MICROCHIP":    ["MICROCHIP_SQUARE", "MICROCHIP_TRIANGLE"],
    "PEBBLES":      ["PEBBLES_M", "PEBBLES_L"],
    "OXYGEN_SHAKE": ["OXYGEN_SHAKE_EVENING_BREATH", "OXYGEN_SHAKE_CHOCOLATE"],
}
GROUP_PULL = 0.2   # conservative — unchanged from v4/v5


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

        # ── Step 1: Compute current mids + update EMAs ────────────────────
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

        # ── Step 2: Group signal from CURRENT mids ────────────────────────
        group_mid: Dict[str, float] = {}
        for grp, members in GROUPS.items():
            vals = [mid_map[p] for p in members if p in mid_map]
            if vals:
                group_mid[grp] = sum(vals) / len(vals)

        # ── Step 3: Market making ─────────────────────────────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            od  = state.order_depths[prod]
            grp = cfg["group"]

            mid  = mid_map[prod]
            fair = mid + GROUP_PULL * (group_mid.get(grp, mid) - mid) \
                   if grp in group_mid else mid

            result[prod] = self._mm(prod, od, pos, fair, cfg["mm_hs"])

        # ── Step 4: Mean reversion ────────────────────────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                ema_map[prod], cfg["mr_thr"], cfg["mr_aggr"]
            )

        # ── Step 5: Stat-arb (SNACKPACK only) ────────────────────────────
        pair_orders: Dict[str, List[Order]] = {}
        self._run_pairs(
            state, mid_map, pair_orders, pair_pos,
            SNACK_PAIRS, SNACK_ENTRY_Z, SNACK_EXIT_Z,
            SNACK_PAIR_SIZE, SNACK_RATIO_SPAN, rmean_map, prefix="SN"
        )

        for prod, orders in pair_orders.items():
            result.setdefault(prod, []).extend(orders)

        return result, 0, json.dumps({"ema": ema_map, "rm": rmean_map, "pp": pair_pos})

    # ─────────────────────────────────────────────────────────────────────
    def _run_pairs(self, state, mid_map, pair_orders, pair_pos,
                   pairs, entry_z, exit_z, pair_size, ratio_span,
                   rmean_map, prefix):
        for pa, pb, hist_mean, hist_std in pairs:
            if pa not in mid_map or pb not in mid_map:
                continue
            ratio = mid_map[pa] / mid_map[pb]
            pkey  = f"{prefix}|{pa}|{pb}"
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

    # ─────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, hs: int) -> List[Order]:
        """
        Market making — all v4 structural fixes retained:
          FIX 1: No hard exit.
          FIX 2: Fair value = current mid (not EMA).
          FIX 3: One-sided quoting near cap (pos >= CAP_THRESHOLD).
          FIX 4: Bounded skew (ask >= fair+1, bid <= fair-1 always).
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # One-sided quoting near cap
        if pos >= CAP_THRESHOLD:
            buy_cap = 0
        if pos <= -CAP_THRESHOLD:
            sell_cap = 0

        # Bounded skew: cap magnitude at (hs-1) so ask never goes below fair+1
        raw_skew = pos * 0.5
        skew = int(round(max(-(hs - 1), min(hs - 1, raw_skew))))

        bid_px = round(fair - hs - skew)
        ask_px = round(fair + hs - skew)

        # Hard bound: NEVER post bid > fair-1 or ask < fair+1
        bid_px = min(bid_px, int(fair) - 1)
        ask_px = max(ask_px, int(fair) + 1)

        # Snipe clearly mispriced orders
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

    # ─────────────────────────────────────────────────────────────────────
    def _mr(self, product: str, od: OrderDepth, pos: int,
            ema: float, thr: float, aggr: float) -> List[Order]:
        """
        Mean reversion — unchanged from v4/v5.
        EMA is correct here: we bet on reversion to a trailing mean.
        Unwind leg posts a passive limit near EMA to clear existing position.
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
#  CHANGE TABLE (v5 → v6)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                         | v5        | v6        | Justification
#  ───────────────────────────────┼───────────┼───────────┼────────────────────
#  Products in MM_CFG             | 49        | 20        | Drop 25 stuck losers
#  ROBOT_IRONING                  | MM (flat) | MR only   | ACF=-0.128, +5,070
#  ROBOT_DISHES                   | MR_CFG    | REMOVED   | Live: RW, WR=26%
#  OXYGEN_SHAKE_CHOCOLATE         | MM (-202) | MR only   | Historical ACF=-0.089
#  UV_PAIRS stat-arb              | YES       | REMOVED   | ORANGE dropped
#  GAL_PAIRS stat-arb             | YES       | REMOVED   | DARK_MATTER dropped
#  SNACK_PAIRS stat-arb           | YES       | unchanged | Working in v4+v5
#  mm_hs values (retained prods)  | unchanged | unchanged | No parameter tuning
#  GROUP_PULL                     | 0.2       | 0.2       | unchanged
#  v4 structural fixes            | all in    | all in    | unchanged
#
#  DROPPED PRODUCTS (25 — all confirmed stuck-position losers in v5 live):
#    TRANSLATOR_VOID_BLUE, TRANSLATOR_GRAPHITE_MIST, TRANSLATOR_SPACE_GRAY
#    UV_VISOR_ORANGE, UV_VISOR_RED, UV_VISOR_AMBER
#    GALAXY_SOUNDS_DARK_MATTER, GALAXY_SOUNDS_SOLAR_WINDS
#    ROBOT_LAUNDRY, ROBOT_DISHES
#    SLEEP_POD_LAMB_WOOL, SLEEP_POD_SUEDE, SLEEP_POD_COTTON, SLEEP_POD_POLYESTER
#    MICROCHIP_CIRCLE, MICROCHIP_OVAL, MICROCHIP_RECTANGLE
#    PEBBLES_XS, PEBBLES_S, PEBBLES_XL
#    OXYGEN_SHAKE_MORNING_BREATH, OXYGEN_SHAKE_MINT, OXYGEN_SHAKE_GARLIC
#    PANEL_1X2, PANEL_2X2, PANEL_1X4, PANEL_4X4
#
# ═══════════════════════════════════════════════════════════════════════════════
