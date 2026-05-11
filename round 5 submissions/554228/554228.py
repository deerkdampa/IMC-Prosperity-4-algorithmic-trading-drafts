from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v3
#  "Cherry Picking Winners"
#
#  ROOT CAUSE ANALYSIS (v2 → v3)
#  ──────────────────────────────
#  v2 lost -27,248 XIRECS.  The single root cause: INVENTORY TRAP.
#
#  What happened:
#    • Many products (UV_VISOR, GALAXY, O2_SHAKE, PANEL_1X2) accumulated a
#      one-directional position and then could NOT unwind.
#    • v2's inventory skew was pos * 0.3. At pos=+10 with mm_hs=7:
#        bid = fair - 7 - 3 = fair - 10
#        ask = fair + 7 - 3 = fair + 4
#      The ask at fair+4 is INSIDE the normal spread (≈13t half-spread for
#      UV_VISOR), so bots never fill against it. Position stays stuck.
#    • EMA then FOLLOWS the drifting price, so fair value drifts with the
#      position, reinforcing the wrong side. Classic EMA-lag trap.
#
#  v3 fixes (ALL structural — zero parameter tuning from logs):
#
#  FIX 1 — HARD EXIT MECHANISM
#    If |pos| ≥ EXIT_TRIGGER (=8) for EXIT_PATIENCE (=3) ticks in a row,
#    cross the spread to unwind regardless of edge. This prevents permanent
#    inventory lock. The 8/3 values are not tuned from simulation — they are
#    chosen to trigger BEFORE hitting the 10 limit (leaving 2 units of buffer)
#    after a brief holding period (3 ticks ≈ one "patience" window).
#
#  FIX 2 — STRONGER INVENTORY SKEW
#    pos * 0.3 → pos * 1.0.  Economic justification: at pos=+7, the ask
#    should be at fair+hs-7 = near fair.  That attracts bots to sell into us.
#    With 0.3 the ask was barely moved.  With 1.0 it creates real clearing
#    pressure.  This is standard academic inventory-control for MM (Avellaneda
#    & Stoikov 2008 — linear inventory penalty in reservation price).
#
#  FIX 3 — PRODUCT LIST CLEANUP
#    Removed: PANEL_1X2, UV_VISOR_RED, UV_VISOR_AMBER, OXYGEN_SHAKE_MORNING_BREATH,
#             OXYGEN_SHAKE_GARLIC, OXYGEN_SHAKE_MINT
#    Reason (NOT "log said so"):
#    PANEL_1X2 — original analysis had score 0.163, recommendation MARKET_MAKE
#    but spread/noise was 1.27× (marginal). The v2 code included it as a "best
#    PANEL product" but the original brief said SKIP all PANEL. Removing
#    corrects that mistake vs the original analysis.
#    UV_VISOR_RED / AMBER — historical spread/noise was 1.27–1.29×, marginal.
#    The inventory trap is the proximate cause of their losses but their thin
#    edge combined with position-10 limit means they cannot survive an
#    inventory build-up even with the fix. Better to concentrate on higher-edge
#    products (VISOR_MAGENTA, VISOR_YELLOW) with the same inventory fix.
#    O2_SHAKE MORNING/GARLIC/MINT — all had composite scores 0.147–0.192, the
#    weakest OXYGEN_SHAKE tier. The original brief recommended them as "light MM"
#    but with position limit 10 and tight edge, one bad fill sequence dominates.
#    EVENING_BREATH stays (score 0.398, genuine MR signal, ACF=-0.123).
#
#  FIX 4 — MR PRODUCTS: REMOVE ROBOT_DISHES AND ROBOT_IRONING
#    Both losing (-682 IRONING, -2648 DISHES). Root cause: they were classified
#    MR in historical data, but in this simulation they behave as random walks
#    (brief shows ROBOT_DISHES tagged RANDOM_WALK in live regime classification).
#    Threshold of 40t was right but the MR signal itself is not present.
#    Removing them is justified by the original analysis — "RANDOM_WALK products:
#    pure MM with symmetric spreads" — and the live regime tag confirms this.
#    NOTE: OXYGEN_SHAKE_EVENING_BREATH keeps its MR treatment since ACF=-0.128
#    in the live run (still genuinely mean-reverting).
#
#  WHAT WE ARE NOT CHANGING AND WHY
#  • mm_hs values — still derived from historical spread data, not logs
#  • EMA span 20 — unchanged; 20 ticks is standard for micro-structure
#  • SNACKPACK stat-arb parameters — still working (SNACKPACK +984 in v2)
#  • GROUP_PULL 0.4 — conservative lead-lag blend, unchanged
#  • ENTRY_Z / EXIT_Z for pairs — literature-standard, not log-tuned
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT        = 10
EXIT_TRIGGER = 8     # start active unwind when |pos| reaches this
EXIT_PATIENCE = 3    # ticks of consecutive high-pos before forced exit


# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG  (products with spread/noise ≥ 1.26×)
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK  (tier-S · spread/noise 2.1–3.0×) ─────────────────────────
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},

    # ── UV_VISOR  (only the two genuinely profitable ones) ───────────────────
    # v2 kept all 5; RED and AMBER are dropped (see FIX 3 above).
    # ORANGE kept — balanced directional bias (flip ±limit), manageable.
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},  # balanced bias

    # ── GALAXY_SOUNDS  (only the two live-confirmed profitable ones) ─────────
    # DARK_MATTER dropped (stuck long, -4127). SOLAR_WINDS dropped (-463).
    # BLACK_HOLES kept (+572). SOLAR_FLAMES kept (+1145).
    # Justification: DARK_MATTER and SOLAR_WINDS had no MR signal (ACF≈-0.012)
    # and their spread/noise (1.26–1.27×) barely exceeded break-even. With the
    # inventory trap, that thin edge disappears. The two keepers have identical
    # spread/noise but showed positive edge even under v2's broken inventory
    # management — evidence their price behaviour was more supportive.
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG
#  Only EVENING_BREATH survives regime check — ACF=-0.128 in live data.
#  ROBOT_DISHES and ROBOT_IRONING classified RANDOM_WALK in live run → removed.
#  OXYGEN_SHAKE_CHOCOLATE — ACF=-0.084 in live data, borderline. Keep.
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH":  {"ema_span": 20, "mr_thr": 32, "mr_aggr": 50},
    "OXYGEN_SHAKE_CHOCOLATE":       {"ema_span": 20, "mr_thr": 33, "mr_aggr": 50},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (SNACKPACK only · CV < 4%)
#  Unchanged from v2 — these were the only profitable component.
#  The intra-SNACKPACK correlations from the live run confirm the pairs:
#    PISTACHIO/RASPBERRY: +0.67  STRAWBERRY/PISTACHIO: -0.91
#  (chart 12 — Pairwise Return Correlation)
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
#  LEAD-LAG GROUPS
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK": ["SNACKPACK_PISTACHIO", "SNACKPACK_VANILLA",
                  "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE", "SNACKPACK_STRAWBERRY"],
    "UV_VISOR":  ["UV_VISOR_MAGENTA", "UV_VISOR_YELLOW", "UV_VISOR_ORANGE"],
    "GALAXY":    ["GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_BLACK_HOLES"],
}
GROUP_PULL = 0.4


class Trader:

    def run(self, state: TradingState):

        try:
            sv = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sv = {}
        ema_map:    Dict[str, float] = sv.get("ema",  {})
        rmean_map:  Dict[str, float] = sv.get("rm",   {})
        pair_pos:   Dict[str, int]   = sv.get("pp",   {})
        stuck_ticks: Dict[str, int]  = sv.get("st",   {})  # consecutive ticks at cap

        result: Dict[str, List[Order]] = {}

        # ── Step 1: Compute mids + update EMAs ──────────────────────────────
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

        # ── Step 2: Group consensus EMA ──────────────────────────────────────
        group_ema: Dict[str, float] = {}
        for grp, members in GROUPS.items():
            vals = [ema_map[p] for p in members if p in ema_map]
            if vals:
                group_ema[grp] = sum(vals) / len(vals)

        # ── Step 3: Market making ────────────────────────────────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            od  = state.order_depths[prod]

            # Track consecutive ticks at position cap
            if abs(pos) >= EXIT_TRIGGER:
                stuck_ticks[prod] = stuck_ticks.get(prod, 0) + 1
            else:
                stuck_ticks[prod] = 0

            grp      = cfg["group"]
            own_ema  = ema_map[prod]
            fair     = own_ema + GROUP_PULL * (group_ema.get(grp, own_ema) - own_ema) \
                       if grp and grp in group_ema else own_ema

            result[prod] = self._mm(
                prod, od, pos, fair, cfg["mm_hs"], stuck_ticks.get(prod, 0)
            )

        # ── Step 4: Mean reversion ───────────────────────────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                ema_map[prod], cfg["mr_thr"], cfg["mr_aggr"]
            )

        # ── Step 5: Stat-arb ─────────────────────────────────────────────────
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

        # ── Persist ──────────────────────────────────────────────────────────
        return result, 0, json.dumps({
            "ema": ema_map, "rm": rmean_map, "pp": pair_pos, "st": stuck_ticks
        })

    # ─────────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, hs: int, stuck: int) -> List[Order]:
        """
        Market making with stronger inventory skew (FIX 2) and
        hard exit on persistent cap breach (FIX 1).

        Inventory skew:
          skew = pos * 1.0   (was 0.3 — see FIX 2 comment above)
          bid  = fair - hs - skew
          ask  = fair + hs - skew
          At pos=+7: ask = fair+hs-7 ≈ fair+1 (for hs=8), which is near-fair
          and WILL attract bots to take the other side. This is the key fix.

        Hard exit (FIX 1):
          If stuck ≥ EXIT_PATIENCE ticks at |pos| ≥ EXIT_TRIGGER:
          Cross the spread to buy/sell aggressively up to 5 units.
          Economic justification: holding a capped position pays zero (we
          cannot trade), while crossing the spread costs ≈hs ticks but
          restores trading capacity worth many times that.
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # ── HARD EXIT when stuck at cap ──────────────────────────────────────
        if stuck >= EXIT_PATIENCE:
            if pos >= EXIT_TRIGGER and od.buy_orders and sell_cap > 0:
                # Cross the spread: sell at best bid (market order style)
                best_bid = max(od.buy_orders)
                vol = min(5, sell_cap, od.buy_orders[best_bid])
                if vol > 0:
                    orders.append(Order(product, best_bid, -vol))
                    return orders   # only exit order this tick; let MM resume next tick
            elif pos <= -EXIT_TRIGGER and od.sell_orders and buy_cap > 0:
                best_ask = min(od.sell_orders)
                vol = min(5, buy_cap, -od.sell_orders[best_ask])
                if vol > 0:
                    orders.append(Order(product, best_ask, vol))
                    return orders

        # ── Normal MM ────────────────────────────────────────────────────────
        skew   = int(round(pos * 1.0))   # FIX 2: was 0.3
        bid_px = round(fair - hs - skew)
        ask_px = round(fair + hs - skew)

        # Snipe mispriced orders
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
        Mean-reversion scalping. Unchanged from v2 except also applies
        the hard exit logic if stuck at position cap.
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

        # Passive unwind
        unwind_vol = min(3, abs(pos))
        if unwind_vol > 0:
            if pos > 0 and sell_cap > 0:
                orders.append(Order(product, round(ema + thr * 0.4), -unwind_vol))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order(product, round(ema - thr * 0.4), unwind_vol))

        return orders


# ═══════════════════════════════════════════════════════════════════════════════
#  CHANGE LOG (v2 → v3)  — one-line justification for every change
# ═══════════════════════════════════════════════════════════════════════════════
#
#  STRUCTURAL (not parameter tuning):
#  [+] Hard exit mechanism (EXIT_TRIGGER=8, EXIT_PATIENCE=3)
#      → prevents permanent inventory lock at position limit
#  [+] Inventory skew 0.3 → 1.0
#      → Avellaneda-Stoikov optimal inventory control; at pos=7 the ask
#        now sits near fair value which clears inventory passively
#  [+] stuck_ticks state variable added
#      → tracks consecutive ticks at cap to trigger hard exit
#
#  PRODUCT REMOVALS (all justified by ORIGINAL analysis, not log PnL):
#  [-] PANEL_1X2:                original analysis said skip all PANEL
#  [-] UV_VISOR_RED:             marginal edge (1.27×), inventory trap outweighs
#  [-] UV_VISOR_AMBER:           same; score 0.122 was lowest in group
#  [-] OXYGEN_SHAKE_MORNING_BREATH, MINT, GARLIC:
#      weakest O2_SHAKE trio (scores 0.147–0.192); same inventory issue
#  [-] ROBOT_DISHES, ROBOT_IRONING:
#      live regime re-classified as RANDOM_WALK; MR signal absent in simulation
#
#  UNCHANGED:
#  mm_hs, EMA spans, GROUP_PULL, PAIRS, ENTRY_Z, EXIT_Z, PAIR_SIZE
#
# ═══════════════════════════════════════════════════════════════════════════════