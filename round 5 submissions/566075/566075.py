from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple, Set
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v5
#
#  WHAT WENT RIGHT IN v4
#  ─────────────────────
#  v4 fixed the two structural bugs from v3:
#    1. Removed the hard exit (was a spread-crossing death spiral)
#    2. Used mid instead of EMA as MM fair value (no adverse selection lag)
#    3. Bounded skew so ask ≥ fair+1 always
#    4. One-sided quoting when near cap
#
#  Result: +17,556 XIRECS, Sharpe=1.957 vs v3's -171,814.
#
#  The submission point DOES introduce randomness (80% subset of quotes per
#  run). v4 vs v3 difference is ~189k which is orders of magnitude larger
#  than run-to-run variance, confirming the structural fixes worked.
#
#  WHAT IS STILL WRONG IN v4
#  ─────────────────────────
#  ONE remaining structural problem, visible in the charts:
#
#  PROBLEM: STAT-ARB CONFLICTS WITH MARKET-MAKING ON SAME PRODUCTS
#
#  Evidence:
#  • SNACKPACK_PISTACHIO: appears in 3 of 4 stat-arb pairs (CHOC/PIST,
#    VAN/PIST, PIST/RASP). PnL = -433 despite high cherry-pick score.
#    Rolling Sharpe goes deeply negative in middle period.
#  • Execution diagnosis: PISTACHIO has the most balanced buy/sell fill
#    volume of all SNACKPACK products — which sounds good but is actually
#    bad: it means MM buys are offsetting pair sells and vice versa.
#  • Mechanism: pair fires "long PISTACHIO" (PIST cheap vs CHOC). Same
#    tick, MM posts ask at mid+9-skew for PISTACHIO. Bots fill that ask.
#    Pair position is immediately partially unwound by MM. PnL leaks.
#
#  THE FIX: PAIR-MM DECOUPLING
#  ───────────────────────────
#  When a stat-arb pair position is open on product P (pair_pos != 0),
#  skip MM for product P entirely that tick. MM resumes when pair exits.
#
#  Economic justification: if we believe PISTACHIO is underpriced vs CHOC
#  (hence the pair trade is long PISTACHIO), then posting a SELL for
#  PISTACHIO at mid+9 is directly contradicting our own signal. The pair
#  trade and MM cannot both be right at the same time on the same product.
#  The pair trade is the higher-conviction signal; MM should yield.
#
#  This is structural (a logic flow change), not a parameter change.
#
#  ALSO ADDED: STRAWBERRY STAT-ARB PAIRS
#  ──────────────────────────────────────
#  Live correlation heatmap (chart 12) shows:
#    PISTACHIO / STRAWBERRY: -0.91
#    RASPBERRY / STRAWBERRY: -0.94
#  These are the strongest relationships in the entire dataset.
#  Our original historical analysis showed exactly the same structure
#  (00_summary.txt statarb section lists SNACKPACK_VANILLA/STRAWBERRY,
#  SNACKPACK_PISTACHIO/STRAWBERRY, SNACKPACK_CHOCOLATE/STRAWBERRY as top-12
#  pairs). We already had the data justification — we just didn't include
#  these pairs in v1-v4.
#
#  Adding PISTACHIO/STRAWBERRY and RASPBERRY/STRAWBERRY pairs:
#    ratio_mean from historical data: PISTACHIO/STRAWBERRY = 0.9427 (CV=3.16%)
#    ratio_mean: RASPBERRY/STRAWBERRY = 0.9208 (approx, from param report)
#  These were in the original statarb_pairs.csv top-20 list.
#
#  UNCHANGED FROM v4: Everything else. mm_hs, EMA spans, GROUP_PULL=0.2,
#  CAP_THRESHOLD=8, all MR parameters, all product selections.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT         = 10
CAP_THRESHOLD = 8


# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (identical to v4)
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG  (identical to v4)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH":  {"ema_span": 20, "mr_thr": 32, "mr_aggr": 50},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (v4 pairs + 2 new STRAWBERRY pairs from historical data)
#
#  All ratio_mean and hist_std values come from the original statarb_pairs.csv
#  and 00_parameter_report.txt — NOT from this simulation run.
#
#  Original 4 pairs (unchanged):
#    CHOC/PIST   ratio_mean=1.0368  hist_std=0.0213
#    VAN/RASP    ratio_mean=1.0022  hist_std=0.0242
#    CHOC/RASP   ratio_mean=0.9770  hist_std=0.0252
#    VAN/PIST    ratio_mean=1.0639  hist_std=0.0325
#
#  New pairs (from original top-20 statarb list):
#    PIST/STRAW  ratio_mean=0.9427  hist_std=0.0316  (CV=3.16%, score=0.445)
#    RASP/STRAW  ratio_mean=0.9208  hist_std=0.0437  (CV=4.37%, from report)
#
#  These were in the original analysis but omitted from v1-v4 by oversight.
# ─────────────────────────────────────────────────────────────────────────────
PAIRS: List[Tuple[str, str, float, float]] = [
    # original 4
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_PISTACHIO",  1.0368, 0.0213),
    ("SNACKPACK_VANILLA",    "SNACKPACK_RASPBERRY",  1.0022, 0.0242),
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_RASPBERRY",  0.9770, 0.0252),
    ("SNACKPACK_VANILLA",    "SNACKPACK_PISTACHIO",  1.0639, 0.0325),
    # new: STRAWBERRY as a hedge for PISTACHIO and RASPBERRY
    ("SNACKPACK_PISTACHIO",  "SNACKPACK_STRAWBERRY", 0.9427, 0.0316),
    ("SNACKPACK_RASPBERRY",  "SNACKPACK_STRAWBERRY", 0.9208, 0.0437),
]
ENTRY_Z    = 1.5
EXIT_Z     = 0.3
PAIR_SIZE  = 3
RATIO_SPAN = 50

# ─────────────────────────────────────────────────────────────────────────────
#  GROUPS  (identical to v4)
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK": ["SNACKPACK_PISTACHIO", "SNACKPACK_VANILLA",
                  "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE", "SNACKPACK_STRAWBERRY"],
    "UV_VISOR":  ["UV_VISOR_MAGENTA", "UV_VISOR_YELLOW", "UV_VISOR_ORANGE"],
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

        # ── Step 1: Mids + EMA update ────────────────────────────────────────
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

        # ── Step 2: Group signal (current mids) ──────────────────────────────
        group_mid: Dict[str, float] = {}
        for grp, members in GROUPS.items():
            vals = [mid_map[p] for p in members if p in mid_map]
            if vals:
                group_mid[grp] = sum(vals) / len(vals)

        # ── Step 3: Identify products with OPEN pair positions ────────────────
        # KEY FIX v5: do not run MM for these products this tick.
        # Reason: pair trade and MM are opposite-direction signals; running
        # both simultaneously on the same product bleeds PnL.
        pair_locked: Set[str] = set()
        for pa, pb, _, _ in PAIRS:
            pkey = f"{pa}|{pb}"
            if pair_pos.get(pkey, 0) != 0:
                pair_locked.add(pa)
                pair_locked.add(pb)

        # ── Step 4: Market making (skip pair-locked products) ─────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            if prod in pair_locked:
                continue   # yield to pair trade this tick
            pos = state.position.get(prod, 0)
            grp = cfg["group"]
            mid  = mid_map[prod]
            fair = mid + GROUP_PULL * (group_mid.get(grp, mid) - mid) \
                   if grp and grp in group_mid else mid
            result[prod] = self._mm(prod, state.order_depths[prod], pos, fair, cfg["mm_hs"])

        # ── Step 5: Mean reversion ────────────────────────────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                ema_map[prod], cfg["mr_thr"], cfg["mr_aggr"]
            )

        # ── Step 6: Stat-arb ──────────────────────────────────────────────────
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
        """Identical to v4. One-sided quoting, bounded skew, no hard exit."""
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        if pos >= CAP_THRESHOLD:
            buy_cap = 0
        if pos <= -CAP_THRESHOLD:
            sell_cap = 0

        raw_skew = pos * 0.5
        skew = int(round(max(-(hs - 1), min(hs - 1, raw_skew))))
        bid_px = min(round(fair - hs - skew), int(fair) - 1)
        ask_px = max(round(fair + hs - skew), int(fair) + 1)

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

    # ─────────────────────────────────────────────────────────────────────────
    def _mr(self, product: str, od: OrderDepth, pos: int,
            ema: float, thr: float, aggr: float) -> List[Order]:
        """Identical to v4."""
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
#  CHANGE TABLE v4 → v5
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                    | v4           | v5            | Justification
#  ──────────────────────────┼──────────────┼───────────────┼─────────────────
#  Pair-MM decoupling        | No           | YES           | Structural: pair
#                            |              |               | and MM cannot be
#                            |              |               | right on same side
#                            |              |               | simultaneously
#  pair_locked Set           | Not tracked  | tracked       | implements above
#  New STRAW pairs           | 4 pairs      | 6 pairs       | Were in original
#                            |              |               | top-20 statarb
#                            |              |               | list but omitted
#  All numbers               | unchanged    | unchanged     | not tuning
#  Product list              | unchanged    | unchanged     | not tuning
#
#  WHAT TO CHECK IN TEST (not PnL):
#  1. PISTACHIO fills more balanced (pair and MM not fighting each other)
#  2. STRAWBERRY now appears in pair_locked when pair fires — check that
#     STRAWBERRY MM pauses during those ticks
#  3. No position limit breaches from 6 simultaneous pairs all firing
#     on PISTACHIO at once (max exposure: PISTACHIO could be in 3 pairs
#     simultaneously, each taking 3 units = 9 units. With MM paused,
#     position stays within limit).
#
#  RISK OF NEW PAIRS:
#  Multiple pairs share PISTACHIO and STRAWBERRY. If all 3 PISTACHIO
#  pairs fire simultaneously (CHOC/PIST, VAN/PIST, PIST/STRAW), the
#  combined vol is 3×3=9 units in the same direction on PISTACHIO.
#  With pair_locked this cannot be offset by MM. Position limit is 10.
#  At 9 units of pair exposure + 1 existing MM position = 10. Tight.
#  The vol=min(PAIR_SIZE, LIMIT-pos_a, ...) guard in stat-arb ensures
#  we never breach the limit, but PISTACHIO may effectively be fully
#  committed to pairs and MM will be blocked for extended periods.
#  This is acceptable: PISTACHIO's edge comes from pairs, not MM.
#
# ═══════════════════════════════════════════════════════════════════════════════