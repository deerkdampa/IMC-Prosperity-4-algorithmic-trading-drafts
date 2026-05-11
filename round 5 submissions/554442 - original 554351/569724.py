from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v6
#
#  GUIDING PRINCIPLE: Do not overfit. Only trade products proven profitable
#  across BOTH v4 (554442, +17,556) and v5 (569036, -13,230). Every product
#  added in v5 that wasn't in v4 LOST money. Strip back to what works.
#
#  ROOT CAUSE of v5 regression (-30,786 swing):
#  ──────────────────────────────────────────────
#    1. MR scalp on wrong regime: ROBOT_DISHES had ACF=-0.232 in historical
#       CSVs but was RANDOM_WALK in the live simulation. OXYGEN_SHAKE_CHOCOLATE
#       same story (ACF=-0.089 hist → RW live). MR on RW = cross spread every
#       entry = guaranteed loss. Combined: -4,629.
#
#    2. Stuck positions on new MM products: UV_VISOR_RED/AMBER and
#       GALAXY_DARK_MATTER/SOLAR_WINDS used hs=7 (too tight for their vol).
#       Once position hit CAP_THRESHOLD=8, one-sided quoting couldn't unwind
#       because passive ask was too close to mid. Combined: -14,871.
#
#    3. Leader skew bonus pushed SNACKPACK followers toward cap faster.
#
#    4. Randomness: each test run uses a different sample day. UV_VISOR_ORANGE
#       went +4,408 → -1,174 with ZERO code changes. Can't tune to one run.
#
#  v6 CHANGES (all structural, zero parameter tuning from logs):
#  ──────────────────────────────────────────────────────────────
#    • REMOVE all 7 products that lost money in v5
#    • REMOVE leader skew bonus (too coarse for limit=10)
#    • REMOVE dual-mode SNACKPACK_CHOCOLATE (MR never triggered; simplify)
#    • REMOVE OXYGEN group (only 1 product, doesn't need group pull)
#    • REMOVE prev_mid state tracking (no longer needed)
#    • WIDEN UV_VISOR_ORANGE hs 8→9 (reduce stuck-position risk)
#    • WIDEN SNACKPACK_PISTACHIO hs 9→10 (reduce directional bias)
#    • RESET GROUP_PULL to 0.2 uniform (0.3 was too aggressive)
#    • KEEP stat-arb PAIRS unchanged (proven across both runs)
#    • KEEP EVENING_BREATH MR unchanged (profitable in both runs)
#
#  HINT ALIGNMENT:
#    Hint 1 (lead-lag): GROUP_PULL cross-sectional signal captures this
#      conservatively. The leader skew bonus was removed — too risky.
#    Hint 2 (group them): Focus on 3 best groups only (SNACKPACK, UV_VISOR,
#      GALAXY). Don't trade marginal groups.
#    Hint 3 (pairing for profit): SNACKPACK stat-arb pairs are the tightest
#      intra-group relationships (CV < 2.5%). Keep all 4 pairs.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT         = 10
CAP_THRESHOLD = 8   # stop adding in direction of exposure above this

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (11 products — all proven profitable in v4 AND v5)
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK (spread/noise 2.1–3.0×) — highest edge group ──────────────
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},

    # ── UV_VISOR (spread/noise ~1.27×) — top 3 only ────────────────────────
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 9,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},

    # ── GALAXY_SOUNDS — top 2 only ──────────────────────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG  (1 product — the only MR that worked in both runs)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH": {"ema_span": 20, "mr_thr": 32, "mr_close": 13},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (unchanged — proven across both v4 and v5)
# ─────────────────────────────────────────────────────────────────────────────
PAIRS: List[Tuple[str, str, float, float]] = [
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_PISTACHIO",  1.0368, 0.0213),
    ("SNACKPACK_VANILLA",    "SNACKPACK_RASPBERRY",  1.0022, 0.0242),
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_RASPBERRY",  0.9770, 0.0252),
    ("SNACKPACK_VANILLA",    "SNACKPACK_PISTACHIO",  1.0639, 0.0325),
]
ENTRY_Z    = 1.5
EXIT_Z     = 0.3
PAIR_SIZE  = 3
RATIO_SPAN = 50

# ─────────────────────────────────────────────────────────────────────────────
#  GROUPS for cross-sectional signal (Hint 1 + Hint 2)
#  Conservative GROUP_PULL = 0.2 for all groups.
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK": ["SNACKPACK_PISTACHIO", "SNACKPACK_VANILLA",
                  "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE",
                  "SNACKPACK_STRAWBERRY"],
    "UV_VISOR":  ["UV_VISOR_MAGENTA", "UV_VISOR_ORANGE", "UV_VISOR_YELLOW"],
    "GALAXY":    ["GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_BLACK_HOLES"],
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

        # ── Step 3: Market making ────────────────────────────────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            od  = state.order_depths[prod]
            grp = cfg["group"]

            # Fair value = current mid pulled toward group average
            mid  = mid_map[prod]
            fair = mid + GROUP_PULL * (group_mid.get(grp, mid) - mid) \
                   if grp in group_mid else mid

            result[prod] = self._mm(prod, od, pos, fair, cfg["mm_hs"])

        # ── Step 4: Mean reversion (EVENING_BREATH only) ─────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                ema_map[prod], cfg["mr_thr"], cfg["mr_close"]
            )

        # ── Step 5: Stat-arb (SNACKPACK pairs — Hint 3) ─────────────────────
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
        Market making with bounded skew and one-sided quoting.
        No hard exit. No leader skew. Simple and proven.
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

        # Snipe clearly mispriced orders
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
#  CHANGE TABLE (v5 → v6)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                             | v5 (569036)  | v6
#  ───────────────────────────────────┼──────────────┼─────────────────────────
#  UV_VISOR_RED in MM                 | hs=7         | REMOVED  (lost -6,006)
#  UV_VISOR_AMBER in MM               | hs=7         | REMOVED  (lost -4,264)
#  GALAXY DARK_MATTER in MM           | hs=7         | REMOVED  (lost -4,138)
#  ROBOT_DISHES in MR                 | thr=40       | REMOVED  (lost -2,319)
#  OXYGEN_SHAKE_CHOCOLATE in MR       | thr=34       | REMOVED  (lost -2,310)
#  ROBOT_IRONING in MR                | thr=31       | REMOVED  (lost -895)
#  GALAXY SOLAR_WINDS in MM           | hs=7         | REMOVED  (lost -463)
#  OXYGEN_SHAKE_MINT in MM            | hs=7         | REMOVED  (never filled)
#  SNACKPACK_CHOCOLATE dual mode      | MM + MR      | MM only  (MR never triggered)
#  UV_VISOR_ORANGE halfspread         | hs=8         | hs=9     (reduce stuck risk)
#  SNACKPACK_PISTACHIO halfspread     | hs=9+mom_fix | hs=10    (reduce dir. bias)
#  Leader skew bonus                  | ±1 tick      | REMOVED  (pushed to cap)
#  GROUP_PULL                         | 0.3 SNACK    | 0.2 all  (conservative)
#  OXYGEN group                       | defined      | REMOVED  (1 product, no group)
#  prev_mid state                     | tracked      | REMOVED  (not needed)
#  Active product count               | 18           | 11       (proven winners)
#  traderData size                    | ema+rm+pp+pm | ema+rm+pp (smaller)
#
#  WHAT IS UNCHANGED (proven to work):
#    • Core _mm logic (bounded skew, one-sided quoting, no hard exit)
#    • Core _mr logic (aggressive entry, passive unwind)
#    • Stat-arb PAIRS (all 4 SNACKPACK pairs)
#    • EVENING_BREATH MR (thr=32, close=13)
#    • CAP_THRESHOLD=8, LIMIT=10
#    • GROUP_PULL cross-sectional signal (0.2)
#
# ═══════════════════════════════════════════════════════════════════════════════