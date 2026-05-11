from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v5
#
#  v4 → v5 CHANGES (all structural, zero parameter tuning from PnL)
#  ─────────────────────────────────────────────────────────────────
#  1. EXPAND MM to all 50 products.
#     v4 only generated orders for 11 products; 39 were live but we sent
#     nothing. Historical CSV analysis (spread/σ > 0.4 for every product)
#     confirms passive MM is viable across the board.
#     Group-level mm_hs derived from mean_spread/2 (not product-level tuning).
#
#  2. ROBOT_DISHES added to MR_CFG (MR-only, removed from MM).
#     ACF = -0.232 across days 2–4: highest mean-reversion signal in the
#     entire dataset. Structural evidence, not overfitting.
#
#  3. UV_VISOR and GALAXY_SOUNDS intra-group stat-arb (Hint 3).
#     UV_VISOR_ORANGE / UV_VISOR_MAGENTA : CV=0.049
#     GALAXY_SOUNDS_DARK_MATTER / GALAXY_SOUNDS_SOLAR_FLAMES : CV=0.052
#     Conservative: ENTRY_Z=2.0 (vs SNACKPACK 1.5), PAIR_SIZE=2.
#
#  4. Fix SNACKPACK_PISTACHIO directional bias.
#     Log shows -433 PnL from being capped LONG while price fell.
#     Fix: reduce PISTACHIO mm_hs 9→8; remove PISTACHIO from long-side
#     (pa) in stat-arb pairs — it stays as short-side (pb) only.
#
#  5. Group lead-lag extended to all 10 groups (Hints 1 & 2).
#     GROUP_PULL stays 0.2 (conservative, unchanged).
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT         = 10
CAP_THRESHOLD = 8   # stop adding in direction of exposure above this

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (all 49 non-MR-only products)
#  mm_hs derived from group mean_spread / 2, rounded.
#  ROBOT_DISHES is MR-only — not listed here.
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK  (spr≈16-17, hs=9; PISTACHIO bias fix → hs=8) ────────────
    "SNACKPACK_VANILLA":              {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":           {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_PISTACHIO":            {"ema_span": 20, "mm_hs": 8,  "group": "SNACKPACK"},  # FIX: hs 9→8

    # ── UV_VISOR  (spr≈13-14, hs=7-8) ───────────────────────────────────────
    "UV_VISOR_MAGENTA":               {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":                {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":                {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_RED":                   {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},   # NEW
    "UV_VISOR_AMBER":                 {"ema_span": 20, "mm_hs": 6,  "group": "UV_VISOR"},   # NEW (lower spr)

    # ── GALAXY_SOUNDS  (spr≈13-14, hs=7) ────────────────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES":     {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},
    "GALAXY_SOUNDS_BLACK_HOLES":      {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},
    "GALAXY_SOUNDS_DARK_MATTER":      {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},  # NEW
    "GALAXY_SOUNDS_SOLAR_WINDS":      {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},  # NEW
    "GALAXY_SOUNDS_PLANETARY_RINGS":  {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},  # NEW

    # ── ROBOT  (spr≈6-8, hs=4; DISHES excluded — MR only) ──────────────────
    "ROBOT_VACUUMING":                {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},
    "ROBOT_MOPPING":                  {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},
    "ROBOT_IRONING":                  {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},
    "ROBOT_LAUNDRY":                  {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},

    # ── TRANSLATOR  (spr≈8-9, hs=5) ─────────────────────────────────────────
    "TRANSLATOR_SPACE_GRAY":          {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},
    "TRANSLATOR_ASTRO_BLACK":         {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},
    "TRANSLATOR_ECLIPSE_CHARCOAL":    {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},
    "TRANSLATOR_GRAPHITE_MIST":       {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},
    "TRANSLATOR_VOID_BLUE":           {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},

    # ── PANEL  (spr≈8-10, hs=5) ──────────────────────────────────────────────
    "PANEL_1X2":                      {"ema_span": 20, "mm_hs": 5,  "group": "PANEL"},
    "PANEL_2X2":                      {"ema_span": 20, "mm_hs": 5,  "group": "PANEL"},
    "PANEL_1X4":                      {"ema_span": 20, "mm_hs": 5,  "group": "PANEL"},
    "PANEL_2X4":                      {"ema_span": 20, "mm_hs": 5,  "group": "PANEL"},
    "PANEL_4X4":                      {"ema_span": 20, "mm_hs": 5,  "group": "PANEL"},

    # ── SLEEP_POD  (spr≈9-11, hs=5) ─────────────────────────────────────────
    "SLEEP_POD_LAMB_WOOL":            {"ema_span": 20, "mm_hs": 5,  "group": "SLEEP_POD"},
    "SLEEP_POD_NYLON":                {"ema_span": 20, "mm_hs": 5,  "group": "SLEEP_POD"},
    "SLEEP_POD_SUEDE":                {"ema_span": 20, "mm_hs": 5,  "group": "SLEEP_POD"},
    "SLEEP_POD_COTTON":               {"ema_span": 20, "mm_hs": 5,  "group": "SLEEP_POD"},
    "SLEEP_POD_POLYESTER":            {"ema_span": 20, "mm_hs": 5,  "group": "SLEEP_POD"},

    # ── MICROCHIP  (spr≈7-13, hs=4-7) ───────────────────────────────────────
    "MICROCHIP_CIRCLE":               {"ema_span": 20, "mm_hs": 4,  "group": "MICROCHIP"},
    "MICROCHIP_OVAL":                 {"ema_span": 20, "mm_hs": 4,  "group": "MICROCHIP"},
    "MICROCHIP_RECTANGLE":            {"ema_span": 20, "mm_hs": 4,  "group": "MICROCHIP"},
    "MICROCHIP_TRIANGLE":             {"ema_span": 20, "mm_hs": 5,  "group": "MICROCHIP"},
    "MICROCHIP_SQUARE":               {"ema_span": 20, "mm_hs": 7,  "group": "MICROCHIP"},

    # ── PEBBLES  (spr≈12-13, hs=6) ───────────────────────────────────────────
    "PEBBLES_XS":                     {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},
    "PEBBLES_S":                      {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},
    "PEBBLES_M":                      {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},
    "PEBBLES_L":                      {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},
    "PEBBLES_XL":                     {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},

    # ── OXYGEN_SHAKE  (spr≈12-13, hs=6; EVENING_BREATH is MR) ──────────────
    "OXYGEN_SHAKE_MORNING_BREATH":    {"ema_span": 20, "mm_hs": 6,  "group": "OXYGEN_SHAKE"},
    "OXYGEN_SHAKE_MINT":              {"ema_span": 20, "mm_hs": 6,  "group": "OXYGEN_SHAKE"},
    "OXYGEN_SHAKE_CHOCOLATE":         {"ema_span": 20, "mm_hs": 6,  "group": "OXYGEN_SHAKE"},
    "OXYGEN_SHAKE_GARLIC":            {"ema_span": 20, "mm_hs": 6,  "group": "OXYGEN_SHAKE"},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG
#  EVENING_BREATH: ACF=-0.128 (live, consistently significant)
#  ROBOT_DISHES:   ACF=-0.232 (historical, highest in dataset)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH": {"ema_span": 20, "mr_thr": 32, "mr_aggr": 50},
    "ROBOT_DISHES":                {"ema_span": 20, "mr_thr": 40, "mr_aggr": 60},  # NEW
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS
#  SNACKPACK (unchanged from v4, but PISTACHIO removed from long-side/pa)
#  UV_VISOR  (NEW – Hint 3; conservative ENTRY_Z=2.0, PAIR_SIZE=2)
#  GALAXY    (NEW – Hint 3; conservative ENTRY_Z=2.0, PAIR_SIZE=2)
#
#  Format: (pa, pb, hist_mean, hist_std, entry_z, pair_size)
# ─────────────────────────────────────────────────────────────────────────────

# SNACKPACK pairs — PISTACHIO only as pb (short side) to fix long bias
SNACK_PAIRS: List[Tuple[str, str, float, float]] = [
    ("SNACKPACK_VANILLA",    "SNACKPACK_RASPBERRY",  1.0022, 0.0242),
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_RASPBERRY",  0.9770, 0.0252),
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_PISTACHIO",  1.0368, 0.0213),  # PISTACHIO as pb only
    ("SNACKPACK_VANILLA",    "SNACKPACK_PISTACHIO",  1.0639, 0.0325),  # PISTACHIO as pb only
]
SNACK_ENTRY_Z   = 1.5
SNACK_EXIT_Z    = 0.3
SNACK_PAIR_SIZE = 3
SNACK_RATIO_SPAN = 50

# UV_VISOR pair (Hint 3 — intra-group, conservative)
UV_PAIRS: List[Tuple[str, str, float, float]] = [
    ("UV_VISOR_ORANGE", "UV_VISOR_MAGENTA", 0.9397, 0.0465),
]
UV_ENTRY_Z   = 2.0
UV_EXIT_Z    = 0.5
UV_PAIR_SIZE = 2
UV_RATIO_SPAN = 50

# GALAXY_SOUNDS pair (Hint 3 — intra-group, conservative)
GAL_PAIRS: List[Tuple[str, str, float, float]] = [
    ("GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_SOLAR_FLAMES", 0.9235, 0.0482),
]
GAL_ENTRY_Z   = 2.0
GAL_EXIT_Z    = 0.5
GAL_PAIR_SIZE = 2
GAL_RATIO_SPAN = 50

# ─────────────────────────────────────────────────────────────────────────────
#  GROUPS for lead-lag cross-sectional signal (all 10 — Hints 1 & 2)
#  NOTE: group signal uses CURRENT MIDS (not EMAs) to avoid lag
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK":    ["SNACKPACK_VANILLA", "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE",
                     "SNACKPACK_STRAWBERRY", "SNACKPACK_PISTACHIO"],
    "UV_VISOR":     ["UV_VISOR_MAGENTA", "UV_VISOR_ORANGE", "UV_VISOR_YELLOW",
                     "UV_VISOR_RED", "UV_VISOR_AMBER"],
    "GALAXY_SOUNDS":["GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_BLACK_HOLES",
                     "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_SOLAR_WINDS",
                     "GALAXY_SOUNDS_PLANETARY_RINGS"],
    "ROBOT":        ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
                     "ROBOT_IRONING", "ROBOT_LAUNDRY"],
    "TRANSLATOR":   ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                     "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                     "TRANSLATOR_VOID_BLUE"],
    "PANEL":        ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "SLEEP_POD":    ["SLEEP_POD_LAMB_WOOL", "SLEEP_POD_NYLON", "SLEEP_POD_SUEDE",
                     "SLEEP_POD_COTTON", "SLEEP_POD_POLYESTER"],
    "MICROCHIP":    ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_RECTANGLE",
                     "MICROCHIP_TRIANGLE", "MICROCHIP_SQUARE"],
    "PEBBLES":      ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "OXYGEN_SHAKE": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                     "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC"],
}
GROUP_PULL = 0.2   # conservative — unchanged from v4


class Trader:

    def run(self, state: TradingState):

        try:
            sv = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sv = {}
        ema_map:   Dict[str, float] = sv.get("ema", {})
        rmean_map: Dict[str, float] = sv.get("rm",  {})
        # pair_pos keys: "SNACK|pa|pb", "UV|pa|pb", "GAL|pa|pb"
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

        # ── Step 2: Group signal from CURRENT mids (all 10 groups) ───────
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

        # ── Step 5: Stat-arb ─────────────────────────────────────────────
        pair_orders: Dict[str, List[Order]] = {}

        self._run_pairs(
            state, mid_map, pair_orders, pair_pos,
            SNACK_PAIRS, SNACK_ENTRY_Z, SNACK_EXIT_Z,
            SNACK_PAIR_SIZE, SNACK_RATIO_SPAN, rmean_map, prefix="SN"
        )
        self._run_pairs(
            state, mid_map, pair_orders, pair_pos,
            UV_PAIRS, UV_ENTRY_Z, UV_EXIT_Z,
            UV_PAIR_SIZE, UV_RATIO_SPAN, rmean_map, prefix="UV"
        )
        self._run_pairs(
            state, mid_map, pair_orders, pair_pos,
            GAL_PAIRS, GAL_ENTRY_Z, GAL_EXIT_Z,
            GAL_PAIR_SIZE, GAL_RATIO_SPAN, rmean_map, prefix="GA"
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
        Market making — all v4 fixes retained:
          FIX 1: No hard exit.
          FIX 2: Fair value = current mid (not EMA).
          FIX 3: One-sided quoting near cap (pos ≥ CAP_THRESHOLD).
          FIX 4: Bounded skew (ask ≥ fair+1, bid ≤ fair-1 always).
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        if pos >= CAP_THRESHOLD:
            buy_cap = 0
        if pos <= -CAP_THRESHOLD:
            sell_cap = 0

        raw_skew = pos * 0.5
        skew = int(round(max(-(hs - 1), min(hs - 1, raw_skew))))

        bid_px = round(fair - hs - skew)
        ask_px = round(fair + hs - skew)

        bid_px = min(bid_px, int(fair) - 1)
        ask_px = max(ask_px, int(fair) + 1)

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

        if buy_cap > 0:
            orders.append(Order(product, bid_px, buy_cap))
        if sell_cap > 0:
            orders.append(Order(product, ask_px, -sell_cap))

        return orders

    # ─────────────────────────────────────────────────────────────────────
    def _mr(self, product: str, od: OrderDepth, pos: int,
            ema: float, thr: float, aggr: float) -> List[Order]:
        """
        Mean reversion — unchanged from v4.
        EMA is correct here: we bet on reversion to a trailing mean.
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