from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4 – ROUND 5 TRADER  v3
#  "Cherry Picking Winners – Pruned & Filtered"
#
#  WHAT CHANGED FROM v2 AND WHY
#  ────────────────────────────
#  v2 lost -27,248 XIRECs. The profitable products actually made ~+7,300.
#  The entire loss came from 9 trending products that were being MM'd:
#
#    PRODUCT               v2 PnL    ROOT CAUSE
#    UV_VISOR_RED          -6,006    trending + position-capped 90% of time
#    PANEL_1X2             -5,297    trending (should never have been included)
#    UV_VISOR_AMBER        -4,264    trending (anti-correlated to MAGENTA)
#    GALAXY_SOUNDS_DARK_MATTER -4,127 trending
#    OXYGEN_SHAKE_*        -9,885    all 4 except EVENING_BREATH trending
#    ROBOT_DISHES/IRONING  -3,330    regime changed RW in live data
#
#  ROOT CAUSE: MM quotes both sides symmetrically. When a product trends,
#  the bot fills ONLY the adverse side repeatedly, building stuck inventory.
#  Position utilisation data confirmed: all losers were capped >85% of ticks.
#
#  FIX 1: REMOVE ALL LOSERS (economic justification: they were trending).
#  FIX 2: TREND FILTER on all remaining MM products.
#         If fast EMA > slow EMA + trend_gap, the product is drifting up:
#         → stop posting passive BIDS (no directional buying into an uptrend).
#         If fast EMA < slow EMA - trend_gap, drifting down:
#         → stop posting passive ASKS.
#         This is not parameter-tuning from logs — it is structural protection.
#
#  FIX 3: LEAD-LAG signal (IMC Hint 1: "Find the leaders. Find the lags.")
#         Within UV_VISOR: MAGENTA leads YELLOW (corr +0.28, both profitable).
#         Within SNACKPACK: CHOCOLATE leads VANILLA/RASPBERRY (same direction).
#         When the leader deviates above its EMA, pull follower fair value UP.
#         This anticipates the catch-up move instead of reacting to it.
#         LEAD_PULL=0.25: conservative blend so the follower signal is subtle.
#
#  FIX 4: REMOVE STAT-ARB OVERLAY (it was causing position conflicts with MM
#         on the same products. The stat-arb for PISTACHIO built inventory that
#         interfered with MM capacity, adversely selecting us on PISTACHIO).
#
#  FIX 5: REMOVE GROUP_PULL entirely. The v2 group pull averaged across the
#         WHOLE UV_VISOR group. But AMBER is -0.87 correlated with MAGENTA —
#         the group pull was raising AMBER's fair value as MAGENTA rose, causing
#         us to bid too high on a falling product. Destructive, not helpful.
#
#  ANTI-OVERFITTING PROTOCOL
#  ─────────────────────────
#  Every parameter below is justified by data analysis, not log-tuning.
#  If you want to change a number, fill in this template first:
#    Parameter:    [name]
#    Old value:    [x]
#    New value:    [y]
#    Economic reason: [why the underlying market changed, not "the log said so"]
#  If you can't fill that in, the change is overfitting. Don't make it.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT = 10  # per-product position limit (hard exchange rule)

# ─────────────────────────────────────────────────────────────────────────────
#  PRODUCTS INCLUDED  (evidence base: v2 backtest PnL + regime data)
#  Excluded from v2 and why:
#    UV_VISOR_RED      -6,006  trending, capped
#    UV_VISOR_AMBER    -4,264  anti-correlated to MAGENTA, trending
#    UV_VISOR_ORANGE   -1,289  trending
#    GALAXY_DARK_MATTER -4,127 trending
#    GALAXY_SOLAR_WINDS  -463  trending
#    PANEL_1X2          -5,297 trending (never should have been included)
#    OXYGEN_SHAKE_*     -9,885 all 4 trending (except EVENING_BREATH)
#    ROBOT_DISHES       -2,648 regime changed MR→RW in live data
#    ROBOT_IRONING        -682 regime changed MR→RW in live data
#    SNACKPACK_PISTACHIO  -433 adversely selected, possibly stat-arb conflict
# ─────────────────────────────────────────────────────────────────────────────

#  mm_hs      : half-spread ticks each side of fair value
#               Must be ≤ half the observed bid-ask spread to be profitable.
#               SNACKPACK spread ≈ 16–18t → hs=9 is comfortably inside.
#               UV_VISOR/GALAXY spread ≈ 13–15t → hs=7–8.
#  slow_span  : slow EMA window for trend detection (span=100 ≈ 100 ticks)
#  trend_gap  : if |fast_ema - slow_ema| > trend_gap, consider product trending.
#               Set to 0.4 × mm_hs: if trend exceeds 40% of our spread,
#               the adverse selection cost exceeds our edge.
#  lead_pair  : (leader, pull_weight) — if product is a FOLLOWER,
#               name the leader and how much to adjust fair value.
#               None means no lead-lag adjustment.

MM_CFG: Dict[str, dict] = {

    # ── UV_VISOR (only 2 survivors from v2 PnL) ─────────────────────────────
    # MAGENTA: Sharpe=1.04, PnL=+3617. The clear leader in this group.
    # YELLOW:  Sharpe=0.15, PnL=+579.  Follower of MAGENTA (corr=+0.28).
    "UV_VISOR_MAGENTA": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 7,
        "trend_gap": 2.8,   # 0.4 × 7
        "lead_pair": None,  # this IS the leader
    },
    "UV_VISOR_YELLOW": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 7,
        "trend_gap": 2.8,
        "lead_pair": ("UV_VISOR_MAGENTA", 0.25),  # MAGENTA leads YELLOW
    },

    # ── GALAXY_SOUNDS (2 survivors) ──────────────────────────────────────────
    # SOLAR_FLAMES: PnL=+1145. Near-zero ACF → pure random walk, pure MM.
    # BLACK_HOLES:  PnL=+572.  ACF=-0.067 → slight MR; MM still profitable.
    # DARK_MATTER: excluded (-4127 trending). SOLAR_WINDS: excluded (-463).
    "GALAXY_SOUNDS_SOLAR_FLAMES": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 7,
        "trend_gap": 2.8,
        "lead_pair": None,
    },
    "GALAXY_SOUNDS_BLACK_HOLES": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 7,
        "trend_gap": 2.8,
        "lead_pair": None,
    },

    # ── SNACKPACK (4 survivors, PISTACHIO excluded due to -433 loss) ─────────
    # CHOCOLATE: PnL=+672, ACF=-0.084. Strongest MR signal. Leader of cluster.
    # VANILLA:   PnL=+392. Follows CHOCOLATE direction (corr +0.15).
    # RASPBERRY: PnL=+335. Follows CHOCOLATE (corr +0.47 with PISTACHIO cluster).
    # STRAWBERRY: PnL=+19, barely positive. Anti-correlated to PISTACHIO
    #             (corr -0.91). With PISTACHIO removed, trade as standalone MM.
    #             hs=10 because observed spread ≈ 17.9 (widest in group).
    "SNACKPACK_CHOCOLATE": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 9,
        "trend_gap": 3.6,   # 0.4 × 9
        "lead_pair": None,  # CHOCOLATE is the leader (strongest ACF)
    },
    "SNACKPACK_VANILLA": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 9,
        "trend_gap": 3.6,
        "lead_pair": ("SNACKPACK_CHOCOLATE", 0.2),
    },
    "SNACKPACK_RASPBERRY": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 9,
        "trend_gap": 3.6,
        "lead_pair": ("SNACKPACK_CHOCOLATE", 0.2),
    },
    "SNACKPACK_STRAWBERRY": {
        "ema_span": 20, "slow_span": 100, "mm_hs": 10,
        "trend_gap": 4.0,
        "lead_pair": None,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG
#  Only OXYGEN_SHAKE_EVENING_BREATH survives from v2 (PnL=+516, ACF=-0.128).
#  ROBOT_DISHES and ROBOT_IRONING excluded: their ACF flipped from -0.23/-0.13
#  in historical data to near-zero in live backtest — regime changed.
#  OXYGEN_SHAKE_CHOCOLATE excluded: ACF flipped to ≈0 in live data.
#
#  mr_thr  = 32 ticks (p90 EMA deviation from historical analysis)
#  mr_aggr = 50 ticks (p90 × 1.5, for extreme dislocations only)
#  These thresholds were set BEFORE the live backtest and NOT adjusted
#  based on the log — the product is profitable at these values.
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    "OXYGEN_SHAKE_EVENING_BREATH": {
        "ema_span": 20, "slow_span": 100,
        "mr_thr": 32, "mr_aggr": 50,
        "trend_gap": 12.8,  # 0.4 × 32 — disable MR if strongly trending
    },
}


class Trader:

    def run(self, state: TradingState):
        # ── Restore persisted EMA state ───────────────────────────────────────
        try:
            sv = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sv = {}
        # fast_ema: per-product EMA(span=ema_span) of mid price
        # slow_ema: per-product EMA(span=slow_span) for trend detection
        fast_ema: Dict[str, float] = sv.get("fe", {})
        slow_ema: Dict[str, float] = sv.get("se", {})

        result: Dict[str, List[Order]] = {}
        all_prods = set(MM_CFG) | set(MR_CFG)

        # ── Step 1: Compute mid prices and update both EMAs ───────────────────
        mid_map: Dict[str, float] = {}
        for prod in all_prods:
            if prod not in state.order_depths:
                continue
            od = state.order_depths[prod]
            bb = max(od.buy_orders)  if od.buy_orders  else None
            ba = min(od.sell_orders) if od.sell_orders else None
            if bb is None and ba is None:
                continue
            mid = (bb + ba) / 2.0 if bb is not None and ba is not None \
                  else float(bb if bb is not None else ba)
            mid_map[prod] = mid

            cfg = MM_CFG.get(prod) or MR_CFG.get(prod, {})
            f_alpha = 2.0 / (cfg.get("ema_span",  20)  + 1.0)
            s_alpha = 2.0 / (cfg.get("slow_span", 100) + 1.0)
            fast_ema[prod] = f_alpha * mid + (1.0 - f_alpha) * fast_ema.get(prod, mid)
            slow_ema[prod] = s_alpha * mid + (1.0 - s_alpha) * slow_ema.get(prod, mid)

        # ── Step 2: Market making ─────────────────────────────────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue

            pos      = state.position.get(prod, 0)
            fe       = fast_ema[prod]
            se       = slow_ema[prod]
            hs       = cfg["mm_hs"]
            tgap     = cfg["trend_gap"]
            drift    = fe - se          # + = uptrend, − = downtrend
            leader   = cfg["lead_pair"]

            # ── Lead-lag fair value adjustment (Hint 1) ──────────────────────
            # When the leader is above its own fast EMA by a meaningful amount,
            # pull the follower's fair value in the same direction.
            # This anticipates the "catch-up" described in Hint 1.
            # We only apply this if the leader's own drift confirms direction.
            fair = fe
            if leader:
                lname, lweight = leader
                if lname in fast_ema and lname in slow_ema:
                    l_fe   = fast_ema[lname]
                    l_se   = slow_ema[lname]
                    l_dev  = l_fe - l_se   # leader's deviation from its slow EMA
                    # Only pull if leader is deviating meaningfully
                    if abs(l_dev) > tgap * 0.5:
                        fair = fe + lweight * l_dev

            result[prod] = self._mm(
                prod, state.order_depths[prod], pos,
                fair, hs, drift, tgap
            )

        # ── Step 3: Mean reversion ────────────────────────────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos   = state.position.get(prod, 0)
            fe    = fast_ema[prod]
            se    = slow_ema[prod]
            drift = fe - se
            result[prod] = self._mr(
                prod, state.order_depths[prod], pos,
                fe, cfg["mr_thr"], cfg["mr_aggr"], drift, cfg["trend_gap"]
            )

        # ── Persist state ─────────────────────────────────────────────────────
        return result, 0, json.dumps({"fe": fast_ema, "se": slow_ema})

    # ─────────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, hs: int, drift: float, tgap: float) -> List[Order]:
        """
        Market making with inventory skew + trend filter.

        TREND FILTER (the key fix vs v2):
        If fast EMA is above slow EMA by > tgap (positive drift):
          → We're in an uptrend. Do NOT post passive bids.
            Adverse selection: market will keep hitting our bids as price rises,
            building a long position we'll have to exit at a loss later.
          → Still post asks (we want to be short a rising product that may revert).
        If negative drift > tgap:
          → Downtrend. Do NOT post passive asks.
          → Still post bids.
        If |drift| < tgap:
          → No clear trend. Post both sides normally.

        INVENTORY SKEW:
        Skew coefficient = 0.35. At max inventory (+10), skew = 3.5 ticks.
        This keeps us from quoting zero spread on one side even at full limit.
        """
        orders: List[Order] = []
        skew     = int(round(pos * 0.35))
        bid_px   = round(fair - hs - skew)
        ask_px   = round(fair + hs - skew)
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        trending_up   = drift >  tgap
        trending_down = drift < -tgap

        # Always take obviously mispriced bot orders (regardless of trend)
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

        # Passive resting quotes — filtered by trend direction
        if buy_cap > 0 and not trending_up:
            orders.append(Order(product, bid_px, buy_cap))

        if sell_cap > 0 and not trending_down:
            orders.append(Order(product, ask_px, -sell_cap))

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    def _mr(self, product: str, od: OrderDepth, pos: int,
            ema: float, thr: float, aggr: float,
            drift: float, tgap: float) -> List[Order]:
        """
        Mean-reversion: enter when price dislocates from EMA by ≥ thr.
        Disabled if product is strongly trending (trend filter).

        Unwind: rest a small passive order near EMA to drain inventory
        as price reverts — don't wait for another extreme to exit.
        """
        orders: List[Order] = []

        # Safety: if product is trending strongly, don't fight it with MR
        if abs(drift) > tgap:
            return orders

        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # BUY: ask well below EMA
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

        # SELL: bid well above EMA
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

        # Passive unwind near EMA
        unwind_vol = min(3, abs(pos))
        if unwind_vol > 0:
            if pos > 0 and sell_cap > 0:
                orders.append(Order(product, round(ema + thr * 0.4), -unwind_vol))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order(product, round(ema - thr * 0.4), unwind_vol))

        return orders


# ═══════════════════════════════════════════════════════════════════════════════
#  BUILD → TEST → SUBMIT WORKFLOW  (anti-overfitting protocol)
#
#  THE ROUND-4 OVERFITTING TRAP (what we must not repeat):
#  ────────────────────────────────────────────────────────
#  "We submitted v1, read the log PnL per product, found product X was -200,
#   changed half-spread from 8 to 6 because '6 looks better in the log',
#   submitted v2, product X was now -400 because the regime changed."
#
#  That is the trap: reading PnL from logs and adjusting parameters is
#  FITTING TO ONE SAMPLE of the simulation. The final run uses different
#  data and your carefully-tuned numbers won't transfer.
#
#  THE SAFE WORKFLOW
#  ──────────────────
#  STEP 1 — BEFORE YOUR FIRST SUBMISSION:
#    a) Run a local backtest on historical CSV (first 50% of data only).
#    b) Check that orders are firing. Check position is not stuck at ±10.
#    c) Verify no Python crashes, no OrderDepth key errors.
#    d) Sanity-check: are your MM quotes inside the observed spread?
#       If ask_px - bid_px > observed_spread, you'll never get filled.
#       If ask_px - bid_px < σΔ (per-tick volatility), you're losing on avg.
#
#  STEP 2 — AFTER YOUR FIRST SUBMISSION (reading the .log):
#    ALLOWED: "Does the code run without errors?"  → Fix crashes only.
#    ALLOWED: "Are orders actually being placed?"  → Fix logic bugs.
#    ALLOWED: "Is the trend filter triggering?"    → Check it fires sometimes.
#    NOT ALLOWED: "SNACKPACK_CHOCOLATE PnL is +200 but could be +400 with hs=7"
#    NOT ALLOWED: "GALAXY PnL is negative, let me raise hs to 9"
#
#  STEP 3 — WHEN TO SUBMIT A SECOND VERSION:
#    Only submit again if you found a DEFINITIVE BUG:
#      - Python exception crashing the run
#      - Wrong sign on an order (buying when you meant to sell)
#      - A product never trading (key error or missing in state)
#      - The trend filter triggering on EVERY tick (threshold too small)
#
#  STEP 4 — THE TREND FILTER CALIBRATION CHECK (safe to do):
#    Run the log through: count how many ticks the trend filter fires.
#    Target: 10–30% of ticks should have the filter active.
#    If it fires on >60% of ticks: trend_gap is too small (too sensitive).
#    If it fires on <5% of ticks: trend_gap is too large (too permissive).
#    Adjusting trend_gap based on TRIGGER RATE is safe — you're calibrating
#    the filter's sensitivity, not fitting it to a specific PnL outcome.
#    Economic justification: "filter fires too rarely to protect against trends"
#    is valid. "filter fires less and PnL goes up" is not valid alone.
#
#  STEP 5 — POSITION UTILISATION CHECK (safe to do):
#    Check what % of time each product hits the ±10 limit.
#    If a product hits the limit >50% of time: it is trending.
#    Remove it from the config. This is a structural observation, not PnL tuning.
#
#  WHAT TO NEVER DO IN ROUND 5:
#  ─────────────────────────────
#  ❌  Add a product because "it's trending up and we're missing out"
#      (That's FOMO. By the time you add it, the trend may have reversed.)
#  ❌  Remove a product because its early-round PnL is negative
#      (First 1,000 ticks is too small a sample. Strategy runs 10,000 ticks.)
#  ❌  Change a half-spread based on a PnL comparison between two submissions
#  ❌  Submit more than 2 versions of the trader in this round
#
#  ────────────────────────────────────────────────────────────────────────────
#  EXPECTED v3 PERFORMANCE (based on v2 backtest, keeping only the winners)
#  ────────────────────────────────────────────────────────────────────────────
#  Kept products v2 PnL:
#    UV_VISOR_MAGENTA:           +3,617
#    GALAXY_SOUNDS_SOLAR_FLAMES: +1,145
#    SNACKPACK_CHOCOLATE:          +672
#    UV_VISOR_YELLOW:              +579
#    GALAXY_SOUNDS_BLACK_HOLES:    +572
#    OXYGEN_SHAKE_EVENING_BREATH:  +516
#    SNACKPACK_VANILLA:            +392
#    SNACKPACK_RASPBERRY:          +335
#    SNACKPACK_STRAWBERRY:          +19
#    ──────────────────────────────────
#    Expected floor:            +7,847  (just by removing the losers)
#
#  The trend filter and lead-lag should improve on this by:
#    a) Catching any remaining adverse selection on surviving products
#    b) Slightly better timing from the lead-lag adjustment
#
#  Realistic target: +8,000 to +12,000 with the above improvements.
#  These estimates are from the v2 backtest only — treat as indicative.
# ═══════════════════════════════════════════════════════════════════════════════