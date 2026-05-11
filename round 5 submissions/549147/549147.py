from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple, Optional
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v2
#  "Cherry Picking Winners"
#
#  STRATEGY OVERVIEW
#  ─────────────────
#  Three independent strategies, each economically motivated:
#
#    1. MARKET MAKING (MM)
#       For random-walk products where spread/noise > 1.0×.
#       Quote bid + ask symmetrically around a group-adjusted fair value.
#       Group fair value incorporates a cross-sectional lead-lag signal
#       (IMC Hint 1: lagging products in a cluster catch up to leaders).
#
#    2. MEAN REVERSION (MR)
#       For the 4 products with statistically significant ACF < −0.08.
#       Aggressively buy/sell when price dislocates from EMA by ≥ p90 deviation.
#       Passively unwind position near EMA as price reverts.
#
#    3. STAT-ARB PAIRS (SNACKPACK only)
#       Long the cheap leg / short the expensive leg when the rolling
#       z-score of the price ratio exceeds ±1.5σ (IMC Hint 3: stable
#       intra-cluster relationships).  Exit at |z| < 0.3.
#
#  ANTI-OVERFITTING RULES
#  ──────────────────────
#  ⚠️  DO NOT tune parameters by submitting to the competition engine,
#      reading the .log, and adjusting numbers. That is overfitting.
#
#  ✅  Each parameter below is justified by historical analysis only:
#       - mm_hs    : derived from observed bid-ask spread in CSV data
#       - mr_thr   : p90 EMA deviation from 00_parameter_report.txt
#       - mr_aggr  : p90 × 1.5 (physically: extreme dislocation)
#       - ENTRY_Z  : 1.5σ standard in stat-arb literature; not tuned
#       - GROUP_PULL: 0.4 — conservative blend; not tuned from logs
#
#  ✅  If you want to change a parameter, document the economic reason
#      in a comment on the same line. "The log said so" is not a reason.
#
#  ✅  Test robustness by splitting historical CSVs in half and checking
#      that PnL is stable across both halves before submitting.
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT = 10   # position limit per product (hard exchange rule)

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG
#  mm_hs : half-spread (ticks each side of fair value to quote)
#          — SNACKPACK: mean spread ≈ 16–18t, σΔ ≈ 5–8t → hs=9 sits well
#            inside observed spread and far above the break-even (σΔ) level.
#            Draft-1 used hs=4 which was below σΔ — adverse selection guaranteed.
#          — Tier-B products (UV_VISOR, GALAXY): spread/noise ≈ 1.26–1.29×,
#            so hs must be ≤ observed half-spread (≈6–8t) to remain profitable.
#  group : cross-sectional lead-lag group name (None = no group signal)
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK  (tier-S · spread/noise 2.1–3.0× · score 0.36–0.60) ──────
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},

    # ── UV_VISOR  (tier-B · spread/noise 1.26–1.29×) ────────────────────────
    "UV_VISOR_RED":                 {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 7,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_AMBER":               {"ema_span": 20, "mm_hs": 6,  "group": "UV_VISOR"},

    # ── GALAXY_SOUNDS  (tier-B · spread/noise 1.26–1.27×) ───────────────────
    # NOTE: SOLAR_FLAMES showed strong upward trend in historical data.
    # If you observe trending behaviour early in the round, remove it.
    "GALAXY_SOUNDS_DARK_MATTER":    {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY"},
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_SOLAR_WINDS":    {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY"},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},

    # ── OXYGEN_SHAKE  (random-walk tier · spread/noise 1.25–1.27×) ──────────
    "OXYGEN_SHAKE_MINT":            {"ema_span": 20, "mm_hs": 7,  "group": "O2_SHAKE"},
    "OXYGEN_SHAKE_MORNING_BREATH":  {"ema_span": 20, "mm_hs": 7,  "group": "O2_SHAKE"},
    "OXYGEN_SHAKE_GARLIC":          {"ema_span": 20, "mm_hs": 8,  "group": "O2_SHAKE"},

    # ── PANEL_1X2  (best-scoring PANEL product · spread/noise 1.27×) ────────
    "PANEL_1X2":                    {"ema_span": 20, "mm_hs": 6,  "group": None},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG
#  mr_thr  : entry threshold = p90 EMA deviation (00_parameter_report.txt)
#            ⚠️  Draft-1 used 12–15 ticks. The p90 values are 31–40 ticks.
#            Too-small thresholds trade on normal noise, not genuine dislocations.
#            This is the most critical bug fixed in v2.
#  mr_aggr : sweep threshold = p90 × 1.5 (only hit at extreme dislocations)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "ROBOT_DISHES":                 {"ema_span": 20, "mr_thr": 40, "mr_aggr": 60},
    "ROBOT_IRONING":                {"ema_span": 20, "mr_thr": 31, "mr_aggr": 48},
    "OXYGEN_SHAKE_EVENING_BREATH":  {"ema_span": 20, "mr_thr": 32, "mr_aggr": 50},
    "OXYGEN_SHAKE_CHOCOLATE":       {"ema_span": 20, "mr_thr": 33, "mr_aggr": 50},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (SNACKPACK only)
#  Only pairs with CV < 4% are included (tight historical cointegration).
#  ratio_mean  : historical mean of price_A / price_B
#  ratio_std   : historical std (FIXED — not rolling — prevents adapting to
#                regime breaks which would disguise the signal as noise)
#  The rolling EMA of the ratio mean does adapt (span=50) so we handle
#  slow level drift, but the volatility anchor stays historical.
# ─────────────────────────────────────────────────────────────────────────────
PAIRS: List[Tuple[str, str, float, float]] = [
    # (product_A,              product_B,              ratio_mean, ratio_std)
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_PISTACHIO",   1.0368,     0.0213),  # CV=2.1%
    ("SNACKPACK_VANILLA",    "SNACKPACK_RASPBERRY",   1.0022,     0.0242),  # CV=2.4%
    ("SNACKPACK_CHOCOLATE",  "SNACKPACK_RASPBERRY",   0.9770,     0.0252),  # CV=2.6%
    ("SNACKPACK_VANILLA",    "SNACKPACK_PISTACHIO",   1.0639,     0.0325),  # CV=3.2%
]

ENTRY_Z    = 1.5   # standard stat-arb entry — not tuned from logs
EXIT_Z     = 0.3   # exit when spread is near zero
PAIR_SIZE  = 3     # units per leg; intentionally small to leave MM headroom
RATIO_SPAN = 50    # EMA span for rolling ratio mean (adapts slowly to drift)

# ─────────────────────────────────────────────────────────────────────────────
#  CROSS-SECTIONAL LEAD-LAG GROUPS  (IMC Hint 1)
#  When one product in a group moves, others tend to follow.
#  We compute a group consensus EMA and blend each product's own EMA
#  toward it. GROUP_PULL=0.4 means fair_value = 60% own EMA + 40% group EMA.
#  This anticipates the lagging product catching up to the leading ones.
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK": ["SNACKPACK_PISTACHIO", "SNACKPACK_VANILLA",
                  "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE", "SNACKPACK_STRAWBERRY"],
    "UV_VISOR":  ["UV_VISOR_RED", "UV_VISOR_MAGENTA", "UV_VISOR_ORANGE",
                  "UV_VISOR_YELLOW", "UV_VISOR_AMBER"],
    "GALAXY":    ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_SOLAR_FLAMES",
                  "GALAXY_SOUNDS_SOLAR_WINDS", "GALAXY_SOUNDS_BLACK_HOLES"],
    "O2_SHAKE":  ["OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_MORNING_BREATH",
                  "OXYGEN_SHAKE_GARLIC"],
}

GROUP_PULL = 0.4   # blend weight toward group consensus EMA — conservative


# ─────────────────────────────────────────────────────────────────────────────
class Trader:

    def run(self, state: TradingState):

        # ── Restore persisted state ──────────────────────────────────────────
        # ema_map  : per-product EMA of mid price
        # rmean_map: per-pair rolling EMA of price ratio (adapts to drift)
        # pair_pos : stat-arb position tracker (+1/-1/0 per pair)
        try:
            sv = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sv = {}
        ema_map:   Dict[str, float] = sv.get("ema",  {})
        rmean_map: Dict[str, float] = sv.get("rm",   {})
        pair_pos:  Dict[str, int]   = sv.get("pp",   {})

        result: Dict[str, List[Order]] = {}

        # ── Step 1: Update EMAs and collect current mid prices ───────────────
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
            mid = (bb + ba) / 2.0 if (bb is not None and ba is not None) \
                  else float(bb if bb is not None else ba)
            mid_map[prod] = mid

            cfg = MM_CFG.get(prod) or MR_CFG.get(prod, {})
            span = cfg.get("ema_span", 20)
            alpha = 2.0 / (span + 1.0)
            ema_map[prod] = alpha * mid + (1.0 - alpha) * ema_map.get(prod, mid)

        # ── Step 2: Compute group consensus EMA (lead-lag signal) ────────────
        # "One product reacts first. Others follow. Use the gap." — Hint 1
        # Group EMA = simple average of individual product EMAs within the group.
        # Products whose EMA lags behind the group are expected to catch up.
        group_ema: Dict[str, float] = {}
        for grp, members in GROUPS.items():
            vals = [ema_map[p] for p in members if p in ema_map]
            if vals:
                group_ema[grp] = sum(vals) / len(vals)

        # ── Step 3: Market making ────────────────────────────────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos  = state.position.get(prod, 0)
            grp  = cfg["group"]

            # Group-adjusted fair value:
            # If this product's EMA is below the group EMA, fair value is
            # pulled UP (anticipating catch-up). If above, pulled DOWN.
            # GROUP_PULL=0 disables entirely; =1 uses pure group signal.
            own_ema = ema_map[prod]
            if grp and grp in group_ema:
                fair = own_ema + GROUP_PULL * (group_ema[grp] - own_ema)
            else:
                fair = own_ema

            result[prod] = self._mm(
                prod, state.order_depths[prod], pos, fair, cfg["mm_hs"]
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

        # ── Step 5: Stat-arb overlay (SNACKPACK pairs) ───────────────────────
        # "Look at what is going on between the products inside them." — Hint 3
        # We track pair positions separately from MM positions.
        # Position limits are checked before placing any order.
        pair_orders: Dict[str, List[Order]] = {}

        for pa, pb, hist_mean, hist_std in PAIRS:
            if pa not in mid_map or pb not in mid_map:
                continue

            ratio = mid_map[pa] / mid_map[pb]
            pkey  = f"{pa}|{pb}"

            # Rolling mean adapts slowly to price level drift (span=50).
            # Std is FIXED from historical data — prevents the signal from
            # widening its own goalposts when the spread blows out.
            ratio_alpha = 2.0 / (RATIO_SPAN + 1.0)
            rmean = ratio_alpha * ratio + (1.0 - ratio_alpha) * \
                    rmean_map.get(pkey, hist_mean)
            rmean_map[pkey] = rmean

            z = (ratio - rmean) / hist_std
            cur_side = pair_pos.get(pkey, 0)   # +1=longA/shortB, -1=shortA/longB

            pos_a = state.position.get(pa, 0)
            pos_b = state.position.get(pb, 0)
            od_a  = state.order_depths[pa]
            od_b  = state.order_depths[pb]

            if cur_side == 0:
                # ── Entry ──────────────────────────────────────────────────
                if z > ENTRY_Z and od_a.buy_orders and od_b.sell_orders:
                    # A is expensive vs B → short A at bid, long B at ask
                    bid_a = max(od_a.buy_orders)
                    ask_b = min(od_b.sell_orders)
                    vol   = min(PAIR_SIZE, LIMIT + pos_a, LIMIT - pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, bid_a, -vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, ask_b,  vol))
                        pair_pos[pkey] = -1

                elif z < -ENTRY_Z and od_a.sell_orders and od_b.buy_orders:
                    # A is cheap vs B → long A at ask, short B at bid
                    ask_a = min(od_a.sell_orders)
                    bid_b = max(od_b.buy_orders)
                    vol   = min(PAIR_SIZE, LIMIT - pos_a, LIMIT + pos_b)
                    if vol > 0:
                        pair_orders.setdefault(pa, []).append(Order(pa, ask_a,  vol))
                        pair_orders.setdefault(pb, []).append(Order(pb, bid_b, -vol))
                        pair_pos[pkey] = 1

            elif abs(z) < EXIT_Z:
                # ── Exit: z-score has reverted to near-zero ────────────────
                if cur_side == -1:
                    # Unwind: buy A back, sell B
                    if od_a.sell_orders and od_b.buy_orders:
                        ask_a = min(od_a.sell_orders)
                        bid_b = max(od_b.buy_orders)
                        vol   = min(PAIR_SIZE, LIMIT - pos_a, LIMIT + pos_b)
                        if vol > 0:
                            pair_orders.setdefault(pa, []).append(Order(pa, ask_a,  vol))
                            pair_orders.setdefault(pb, []).append(Order(pb, bid_b, -vol))
                            pair_pos[pkey] = 0
                else:  # cur_side == 1
                    # Unwind: sell A, buy B back
                    if od_a.buy_orders and od_b.sell_orders:
                        bid_a = max(od_a.buy_orders)
                        ask_b = min(od_b.sell_orders)
                        vol   = min(PAIR_SIZE, LIMIT + pos_a, LIMIT - pos_b)
                        if vol > 0:
                            pair_orders.setdefault(pa, []).append(Order(pa, bid_a, -vol))
                            pair_orders.setdefault(pb, []).append(Order(pb, ask_b,  vol))
                            pair_pos[pkey] = 0

        # Merge stat-arb orders into result
        for prod, orders in pair_orders.items():
            result.setdefault(prod, []).extend(orders)

        # ── Persist state ────────────────────────────────────────────────────
        new_state = json.dumps({"ema": ema_map, "rm": rmean_map, "pp": pair_pos})
        return result, 0, new_state

    # ─────────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, hs: int) -> List[Order]:
        """
        Market making with inventory skew.
        Step 1: Snipe any bot order that crosses our fair-value window.
        Step 2: Post passive resting quotes with remaining capacity.
        Skew = mild push against inventory to mean-revert position risk.
        The skew coefficient 0.3 is conservative — avoids collapsing one
        side of the spread to zero at low inventory.
        """
        orders: List[Order] = []
        skew     = int(round(pos * 0.3))
        bid_px   = round(fair - hs - skew)
        ask_px   = round(fair + hs - skew)
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # Aggressively take mispriced orders
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
        Mean-reversion scalping.
        Enter when ask (or bid) dislocates from EMA by ≥ thr ticks.
        Sweep additional OB levels when dislocation reaches aggr ticks.
        Post a passive unwind quote at thr*0.4 from EMA to drain position
        as price reverts — don't wait for another dislocation to unwind.

        Key fix vs draft-1: thresholds are now p90 EMA deviation values
        (31–40 ticks) not 12–15. The old values were below the typical
        noise level, causing the bot to trade on every random fluctuation.
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # BUY: ask is depressed well below EMA
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

        # SELL: bid is elevated well above EMA
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

        # Passive unwind: rest a small order to drain inventory near EMA
        unwind_vol = min(3, abs(pos))
        if unwind_vol > 0:
            if pos > 0 and sell_cap > 0:
                orders.append(Order(product, round(ema + thr * 0.4), -unwind_vol))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order(product, round(ema - thr * 0.4), unwind_vol))

        return orders


# ═══════════════════════════════════════════════════════════════════════════════
#  TESTING + OPTIMISATION WORKFLOW  (read before touching any numbers)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  HOW TO TEST WITHOUT OVERFITTING
#  ────────────────────────────────
#
#  1. SPLIT YOUR DATA FIRST
#     Divide the historical CSV into two halves:
#       train.csv  → first 50% of ticks  (ticks 0 → 2_000_000)
#       valid.csv  → last 50% of ticks   (ticks 2_000_001 → 4_000_000)
#     Run your backtester on train.csv to understand strategy behaviour.
#     Run it ONCE on valid.csv ONLY after you've finalised parameters.
#     If PnL drops significantly on valid.csv, you have overfit to train.csv.
#
#  2. WHAT YOU CAN LEGITIMATELY DO WITH LOGS
#     ✅  Debug crashes:  "RuntimeError on tick 1234 — why?"
#     ✅  Verify logic:   "Did the stat-arb leg actually fire? How often?"
#     ✅  Catch bugs:     "MM is posting bid > ask — there's a sign error"
#     ❌  Tune numbers:   "Log says PnL is higher with hs=7, so change 9→7"
#     ❌  Add products:   "MICROCHIP_OVAL looks good in this log — add it"
#
#  3. PARAMETER CHANGE PROTOCOL
#     Before changing any number, fill in this template in a team comment:
#       Parameter: mm_hs for SNACKPACK_PISTACHIO
#       Old value: 9
#       New value: 8
#       Economic reason: observed spread in FIRST DAY of live round data
#                        is consistently 14 ticks, not 16–18t from history.
#                        hs=7 keeps us inside the spread with margin.
#     If you cannot fill this in, the change is overfitting. Don't make it.
#
#  4. WHICH PRODUCTS TO REMOVE / ADD DURING THE ROUND
#     Safe to remove if, after 5,000+ ticks of live data:
#       - A product is consistently trending (check live price chart)
#       - Your MM is always getting adversely selected (filled only on one side)
#     Do NOT add new products based on early live PnL — sample size too small.
#
#  5. WHAT WE CHANGED FROM DRAFT-1 AND WHY
#     ┌──────────────────────────────────────┬───────────┬────────────────────┐
#     │ Change                               │ Draft-1   │ v2                 │
#     ├──────────────────────────────────────┼───────────┼────────────────────┤
#     │ SNACKPACK mm_hs                      │ 4–5       │ 9–10               │
#     │   draft used hs < σΔ → adverse sel.  │           │ from spread hist.  │
#     │ MR thresholds (DISHES etc.)          │ 12–15     │ 31–40 (p90 values) │
#     │   draft traded noise, not signal     │           │                    │
#     │ UV_VISOR coverage                    │ 2 products│ all 5              │
#     │ GALAXY coverage                      │ 2 products│ 4 products         │
#     │ OXYGEN_SHAKE_GARLIC added            │ missing   │ ✓ mm_hs=8          │
#     │ Stat-arb pairs (SNACKPACK)           │ missing   │ 4 pairs added      │
#     │ Group lead-lag fair value            │ missing   │ GROUP_PULL=0.4     │
#     └──────────────────────────────────────┴───────────┴────────────────────┘
#
# ═══════════════════════════════════════════════════════════════════════════════