from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v7
#
#  WHY v6 (+10,941) < v4 (+17,556)
#  ─────────────────────────────────────────────────────────────────────────────
#  The v6 log reveals three structural problems:
#
#  PROBLEM 1 — POSITION STUCK AT CAP (97-99% utilisation, both winners & losers)
#    Directional bias chart shows EVERY active product capped at ±10 for
#    nearly the entire run. CAP_THRESHOLD=8 stops new orders but the existing
#    passive quote at fair±hs is never hit when the market trends away.
#    Result: a capped-long position during a falling market = continuous bleed.
#    UV_VISOR_MAGENTA: capped LONG 99%, price fell → -3,767 (was +7k in v4).
#    TRANSLATOR_ECLIPSE_CHARCOAL: capped SHORT 97% → -3,763 (was +3.7k in v5).
#    This isn't randomness — it's the inventory management not working.
#
#  FIX 1 — GRADUATED UNWIND QUOTES (not hard exit, not wider spread)
#    When |pos| >= CAP_THRESHOLD, post the unwind-side quote INSIDE the spread:
#      Normal: ask = fair + hs (passive, wide)
#      Capped long: ask = fair + UNWIND_HS (tighter — attracts fills faster)
#    UNWIND_HS = max(2, hs // 2). Still profitable (above fair), but close enough
#    to mid that it fills during normal volatility, not only during price spikes.
#    This avoids crossing the spread (no hard exit cost) while clearing position.
#
#  PROBLEM 2 — ROBOT_IRONING MR FIRES IN WRONG DIRECTION
#    Execution chart: ROBOT_IRONING has massive long buy-side fills.
#    MR logic buys when ask < EMA - mr_thr. If price falls steadily, EMA lags
#    above current price, so we keep buying into a falling trend.
#    Result: -920 PnL, WR=12.8% (should be ~30% for MR).
#    FIX: Add an EMA momentum filter — only take MR positions if the EMA itself
#    has not moved more than MOMENTUM_GUARD ticks in the last update direction.
#    Simpler fix: raise mr_thr for ROBOT_IRONING to match its actual spread
#    (spread≈5.9 ticks, mr_thr was 30 which is 5× spread — too sensitive).
#    Raise to mr_thr=40 so we only fire on genuine outliers, not normal moves.
#
#  PROBLEM 3 — OXYGEN_SHAKE_CHOCOLATE MR WRONG (WR=17%, -2,288)
#    Historical ACF=-0.089 was marginal. Live data shows it acts as RANDOM_WALK
#    in both v5 and v6. The MR threshold fires on noise, not true reversions.
#    FIX: Remove OXYGEN_SHAKE_CHOCOLATE from MR. Add back to MM_CFG with
#    WIDER hs=7 (spread≈12 ticks → hs=6 was inside the noise band).
#    Actually the v5 MM result was only -202. v6 MR was -2,288. MM is better.
#    Keep in MM_CFG with hs=6 (unchanged from v5 original).
#
#  PROBLEM 4 — GALAXY_SOUNDS_PLANETARY_RINGS: BALANCED CAPPED (-2,709)
#    Position flips between +10 and -10, bleeding spread both ways.
#    Diagnostic: "spread too tight relative to noise — fill both sides at
#    unfavourable prices." mm_hs=7, but the product needs hs=8 minimum.
#    FIX: Raise mm_hs 7→8 for PLANETARY_RINGS. Still within the spread (≈14).
#
#  UNCHANGED from v6:
#    All v4 structural fixes, SNACK_PAIRS, GROUP_PULL=0.2, product universe.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT          = 10
CAP_THRESHOLD  = 8    # stop adding in direction of exposure above this
UNWIND_HS_FRAC = 0.5  # FIX 1: unwind quote = hs * UNWIND_HS_FRAC when capped
                       # e.g. hs=8 → unwind ask at fair+4 instead of fair+8


# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (21 products)
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK ────────────────────────────────────────────────────────────
    "SNACKPACK_VANILLA":              {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":           {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_PISTACHIO":            {"ema_span": 20, "mm_hs": 8,  "group": "SNACKPACK"},

    # ── UV_VISOR ─────────────────────────────────────────────────────────────
    "UV_VISOR_MAGENTA":               {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":                {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},

    # ── GALAXY_SOUNDS ────────────────────────────────────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES":     {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},
    "GALAXY_SOUNDS_BLACK_HOLES":      {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY_SOUNDS"},
    "GALAXY_SOUNDS_PLANETARY_RINGS":  {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY_SOUNDS"},  # FIX 4: 7→8

    # ── ROBOT ────────────────────────────────────────────────────────────────
    "ROBOT_VACUUMING":                {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},
    "ROBOT_MOPPING":                  {"ema_span": 20, "mm_hs": 4,  "group": "ROBOT"},

    # ── TRANSLATOR ───────────────────────────────────────────────────────────
    "TRANSLATOR_ECLIPSE_CHARCOAL":    {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},
    "TRANSLATOR_ASTRO_BLACK":         {"ema_span": 20, "mm_hs": 5,  "group": "TRANSLATOR"},

    # ── PANEL ────────────────────────────────────────────────────────────────
    "PANEL_2X4":                      {"ema_span": 20, "mm_hs": 5,  "group": "PANEL"},

    # ── SLEEP_POD ────────────────────────────────────────────────────────────
    "SLEEP_POD_NYLON":                {"ema_span": 20, "mm_hs": 5,  "group": "SLEEP_POD"},

    # ── MICROCHIP ────────────────────────────────────────────────────────────
    "MICROCHIP_SQUARE":               {"ema_span": 20, "mm_hs": 7,  "group": "MICROCHIP"},
    "MICROCHIP_TRIANGLE":             {"ema_span": 20, "mm_hs": 5,  "group": "MICROCHIP"},

    # ── PEBBLES ──────────────────────────────────────────────────────────────
    "PEBBLES_M":                      {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},
    "PEBBLES_L":                      {"ema_span": 20, "mm_hs": 6,  "group": "PEBBLES"},

    # ── OXYGEN_SHAKE (MM, not MR) ────────────────────────────────────────────
    "OXYGEN_SHAKE_CHOCOLATE":         {"ema_span": 20, "mm_hs": 6,  "group": "OXYGEN_SHAKE"},  # FIX 3: back to MM
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG
#  EVENING_BREATH: ACF=-0.128, live +516 consistent across v5/v6
#  ROBOT_IRONING:  ACF=-0.128, mr_thr raised 30→40 (FIX 2: fewer false fires)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH": {"ema_span": 20, "mr_thr": 32, "mr_aggr": 50},
    "ROBOT_IRONING":               {"ema_span": 20, "mr_thr": 40, "mr_aggr": 55},  # FIX 2: thr 30→40
    # OXYGEN_SHAKE_CHOCOLATE: REMOVED from MR (WR=17% in v6) → back to MM
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB — SNACKPACK only (unchanged from v6)
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
#  GROUPS (updated to match active universe)
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
GROUP_PULL = 0.2


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

        # ── Step 1: Mids + EMAs ───────────────────────────────────────────
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

        # ── Step 2: Group signal ──────────────────────────────────────────
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
            mid = mid_map[prod]
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
        Market making — v4 fixes + FIX 1 (graduated unwind quotes).

        When |pos| >= CAP_THRESHOLD, the unwind-side quote is posted TIGHTER
        (at fair + UNWIND_HS instead of fair + hs) so it fills during normal
        volatility rather than waiting for a price spike.

        UNWIND_HS = max(2, round(hs * UNWIND_HS_FRAC))
          hs=9 → unwind at fair+5  (still +5 above fair, profitable)
          hs=8 → unwind at fair+4
          hs=7 → unwind at fair+4
          hs=5 → unwind at fair+3
          hs=4 → unwind at fair+2

        Hard bounds still enforced: unwind ask >= fair+1, unwind bid <= fair-1.
        No spread crossing — this is tighter passive quoting, not market orders.
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # Compute unwind half-spread (tighter than normal hs)
        unwind_hs = max(2, round(hs * UNWIND_HS_FRAC))

        # Standard bounded skew for normal quoting
        raw_skew = pos * 0.5
        skew = int(round(max(-(hs - 1), min(hs - 1, raw_skew))))

        capped_long  = pos >= CAP_THRESHOLD
        capped_short = pos <= -CAP_THRESHOLD

        if capped_long:
            buy_cap = 0
            # FIX 1: tighter ask to unwind long faster
            ask_px = max(round(fair + unwind_hs), int(fair) + 1)
            bid_px = None  # no bids when capped long
        elif capped_short:
            sell_cap = 0
            # FIX 1: tighter bid to unwind short faster
            bid_px = min(round(fair - unwind_hs), int(fair) - 1)
            ask_px = None  # no asks when capped short
        else:
            bid_px = round(fair - hs - skew)
            ask_px = round(fair + hs - skew)
            # Hard bounds: never post bid > fair-1 or ask < fair+1
            bid_px = min(bid_px, int(fair) - 1)
            ask_px = max(ask_px, int(fair) + 1)

        # Snipe clearly mispriced orders
        if od.sell_orders and buy_cap > 0:
            best_ask = min(od.sell_orders)
            snipe_ref = ask_px if ask_px is not None else round(fair + hs)
            if best_ask <= snipe_ref:
                vol = min(-od.sell_orders[best_ask], buy_cap)
                orders.append(Order(product, best_ask, vol))
                buy_cap -= vol

        if od.buy_orders and sell_cap > 0:
            best_bid = max(od.buy_orders)
            snipe_ref = bid_px if bid_px is not None else round(fair - hs)
            if best_bid >= snipe_ref:
                vol = min(od.buy_orders[best_bid], sell_cap)
                orders.append(Order(product, best_bid, -vol))
                sell_cap -= vol

        # Passive resting quotes
        if buy_cap > 0 and bid_px is not None:
            orders.append(Order(product, bid_px, buy_cap))
        if sell_cap > 0 and ask_px is not None:
            orders.append(Order(product, ask_px, -sell_cap))

        return orders

    # ─────────────────────────────────────────────────────────────────────
    def _mr(self, product: str, od: OrderDepth, pos: int,
            ema: float, thr: float, aggr: float) -> List[Order]:
        """
        Mean reversion — unchanged logic, thr raised for ROBOT_IRONING (FIX 2).
        Higher mr_thr means we only enter on genuine outliers, not normal dips.
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
#  CHANGE TABLE (v6 → v7)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                          | v6       | v7       | Justification
#  ────────────────────────────────┼──────────┼──────────┼───────────────────
#  Unwind quotes when capped       | passive  | TIGHTER  | 97-99% utilisation
#    (UNWIND_HS = hs*0.5)          | at ±hs   | at ±hs/2 | on ALL products
#  ROBOT_IRONING mr_thr            | 30       | 40       | WR=12.8%, buys trend
#  OXYGEN_SHAKE_CHOCOLATE          | MR(-2288)| MM hs=6  | WR=17% in MR, bad
#  GALAXY_SOUNDS_PLANETARY_RINGS   | hs=7     | hs=8     | balanced-capped bleed
#  MM_CFG products                 | 20       | 21       | +SHAKE_CHOCOLATE
#  MR_CFG products                 | 3        | 2        | -SHAKE_CHOCOLATE
#
# ═══════════════════════════════════════════════════════════════════════════════
