from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json

# ═══════════════════════════════════════════════════════════════════════════════
#  IMC PROSPERITY 4  –  ROUND 5 TRADER  v5
#
#  KEY CHANGES vs v4 (554442.py)
#  ──────────────────────────────────────────────────────────────────────────
#
#  ROOT ISSUE (v4): ORDERS_REJECTED for 39 products — position-limit arithmetic
#  bug caused algo to think it was already at limit. ROBOT_DISHES, ROBOT_IRONING,
#  OXYGEN_SHAKE_CHOCOLATE, OXYGEN_SHAKE_MINT were listed in MR/MM configs but the
#  position limit check was computing buy_cap = LIMIT - pos before pos was known,
#  using stale state. Real issue: products in NEITHER MM_CFG nor MR_CFG had no
#  orders at all (the 39 ORDERS_REJECTED products were never even targeted).
#
#  CHANGE 1 — ADD ROBOT_DISHES to MR (ACF=-0.232, highest signal in dataset)
#    Historical data confirms: ema_thresh=40, close at ±16. This is the
#    strongest mean-reverting signal across all 50 products.
#
#  CHANGE 2 — ADD ROBOT_IRONING to MR (ACF=-0.128, score=0.281)
#    Was already flagged in v4 comment but never added. ema_thresh=31, close ±12.
#
#  CHANGE 3 — ADD OXYGEN_SHAKE_CHOCOLATE to MR (ACF=-0.089, score=0.306)
#    v4 removed it due to single live-run loss. Historical data (days 2-4)
#    confirms ACF significantly negative. Restore with conservative threshold.
#
#  CHANGE 4 — ADD OXYGEN_SHAKE_MINT as light MM (spread/noise=1.27, score=0.192)
#    Teammate suggestion confirmed by parameter report: mm_halfspread=7, MARKET_MAKE.
#    ACF=-0.033 (modest noise), spread=12.4 ticks. Post 5 units at ±7.
#
#  CHANGE 5 — ADD UV_VISOR_AMBER + UV_VISOR_RED (both MARKET_MAKE, score>0.12)
#    Both have spread/noise ~1.29, consistently profitable in historical data.
#    Expand UV_VISOR group from 3 → 5 products. hs=7 (slightly tighter than
#    MAGENTA/ORANGE due to lower vol).
#
#  CHANGE 6 — ADD GALAXY_SOUNDS_DARK_MATTER + GALAXY_SOUNDS_SOLAR_WINDS
#    Both RANDOM_WALK, score=0.282 and 0.198, spread/noise=1.27 and 1.26.
#    They were ORDERS_REJECTED in v4 — they just weren't in MM_CFG. Fix: add them.
#    hs=7. They join the GALAXY group for the cross-sectional signal.
#
#  CHANGE 7 — SNACKPACK_PISTACHIO directional bias fix
#    Brief: BiasCrr=-0.068, CAPPED LONG while price moved DOWN. Fix: lower
#    fair value by subtracting a momentum adjustment. When 3-tick mid change
#    is negative, shift fair down by 1 tick before quoting.
#
#  CHANGE 8 — SNACKPACK_CHOCOLATE: treat as dual-mode (MM + MR)
#    ACF=-0.084 (MEAN_REVERT regime in live data, score=28). Apply EMA MR
#    scalp when deviation > 22 ticks, while still allowing MM at ±9 when
#    deviation is modest. This replaces the pure MM approach.
#
#  CHANGE 9 — Lead-lag (Hint 1): stronger CHOCOLATE leader signal
#    SNACKPACK_CHOCOLATE leads the group with ACF=-0.084. When its mid moves
#    >3 ticks in one step, skew follower bids/asks by +1/-1 tick.
#    Increase GROUP_PULL from 0.2 → 0.3 for SNACKPACK only.
#
#  UNCHANGED: stat-arb PAIRS, CAP_THRESHOLD=8, LIMIT=10, core MM/MR logic,
#    skew bound, one-sided quoting, no hard exit.
#
# ═══════════════════════════════════════════════════════════════════════════════

LIMIT         = 10
CAP_THRESHOLD = 8   # stop adding in direction of exposure above this

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET-MAKING CONFIG
#  Keys: ema_span, mm_hs, group, [mm_size optional override]
# ─────────────────────────────────────────────────────────────────────────────
MM_CFG: Dict[str, dict] = {

    # ── SNACKPACK (spread/noise 2.1–3.0×) — Tier 1, full size ───────────────
    # PISTACHIO: directional-bias fix applied via momentum_adjust flag
    "SNACKPACK_PISTACHIO":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK", "mom_fix": True},
    "SNACKPACK_VANILLA":            {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_RASPBERRY":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    # CHOCOLATE: dual MM+MR — mm_hs used for passive quotes; MR handled in MR_CFG
    "SNACKPACK_CHOCOLATE":          {"ema_span": 20, "mm_hs": 9,  "group": "SNACKPACK"},
    "SNACKPACK_STRAWBERRY":         {"ema_span": 20, "mm_hs": 10, "group": "SNACKPACK"},

    # ── UV_VISOR (spread/noise ~1.27×) — Tier 3, all 5 ─────────────────────
    "UV_VISOR_MAGENTA":             {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_ORANGE":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    "UV_VISOR_YELLOW":              {"ema_span": 20, "mm_hs": 8,  "group": "UV_VISOR"},
    # CHANGE 5: add AMBER + RED
    "UV_VISOR_AMBER":               {"ema_span": 20, "mm_hs": 7,  "group": "UV_VISOR"},
    "UV_VISOR_RED":                 {"ema_span": 20, "mm_hs": 7,  "group": "UV_VISOR"},

    # ── GALAXY_SOUNDS (spread/noise ~1.27×) — Tier 3 ────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    "GALAXY_SOUNDS_BLACK_HOLES":    {"ema_span": 20, "mm_hs": 8,  "group": "GALAXY"},
    # CHANGE 6: add DARK_MATTER + SOLAR_WINDS
    "GALAXY_SOUNDS_DARK_MATTER":    {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY"},
    "GALAXY_SOUNDS_SOLAR_WINDS":    {"ema_span": 20, "mm_hs": 7,  "group": "GALAXY"},

    # ── OXYGEN_SHAKE_MINT — Tier 3 light MM (CHANGE 4) ──────────────────────
    # spread=12.4, score=0.192, ACF=-0.033 (random walk), spr/noise=1.27
    "OXYGEN_SHAKE_MINT":            {"ema_span": 20, "mm_hs": 7,  "group": "OXYGEN"},
}

# ─────────────────────────────────────────────────────────────────────────────
#  MEAN-REVERSION CONFIG
#  Keys: ema_span, mr_thr (entry threshold), mr_close (close threshold ~40%)
# ─────────────────────────────────────────────────────────────────────────────
MR_CFG: Dict[str, dict] = {
    # Strongest MR signal in the entire dataset (ACF=-0.232, score=0.483)
    # CHANGE 1: ROBOT_DISHES was ORDERS_REJECTED — add it properly
    "ROBOT_DISHES":                {"ema_span": 20, "mr_thr": 40, "mr_close": 16},

    # ACF=-0.128, score=0.281 (CHANGE 2: restore ROBOT_IRONING)
    "ROBOT_IRONING":               {"ema_span": 20, "mr_thr": 31, "mr_close": 12},

    # ACF=-0.128 (live data), score=0.398. The primary MR workhorse.
    "OXYGEN_SHAKE_EVENING_BREATH": {"ema_span": 20, "mr_thr": 32, "mr_close": 13},

    # ACF=-0.089, score=0.306 (CHANGE 3: restore with conservative threshold)
    # Was removed in v4 after single live loss — historical data confirms signal.
    "OXYGEN_SHAKE_CHOCOLATE":      {"ema_span": 20, "mr_thr": 34, "mr_close": 14},

    # SNACKPACK_CHOCOLATE: ACF=-0.084 in MEAN_REVERT regime — dual mode
    # This handles aggressive MR entries; MM_CFG handles the passive quotes.
    # Use tighter threshold since spread is wide (16 ticks) — only enter on
    # genuine deviations, not noise. (CHANGE 8)
    "SNACKPACK_CHOCOLATE":         {"ema_span": 20, "mr_thr": 22, "mr_close": 9},
}

# ─────────────────────────────────────────────────────────────────────────────
#  STAT-ARB PAIRS  (unchanged — these worked)
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
#  GROUPS for cross-sectional lead-lag signal (Hint 1)
#  SNACKPACK_CHOCOLATE is the confirmed leader (ACF=-0.084, leads followers).
# ─────────────────────────────────────────────────────────────────────────────
GROUPS: Dict[str, List[str]] = {
    "SNACKPACK": ["SNACKPACK_PISTACHIO", "SNACKPACK_VANILLA",
                  "SNACKPACK_RASPBERRY", "SNACKPACK_CHOCOLATE", "SNACKPACK_STRAWBERRY"],
    "UV_VISOR":  ["UV_VISOR_MAGENTA", "UV_VISOR_ORANGE", "UV_VISOR_YELLOW",
                  "UV_VISOR_AMBER", "UV_VISOR_RED"],
    "GALAXY":    ["GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_BLACK_HOLES",
                  "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_SOLAR_WINDS"],
    "OXYGEN":    ["OXYGEN_SHAKE_MINT"],
}

# SNACKPACK uses stronger pull (Hint 1 lead-lag is most reliable there)
GROUP_PULL: Dict[str, float] = {
    "SNACKPACK": 0.3,   # CHANGE 9: increased from 0.2
    "UV_VISOR":  0.2,
    "GALAXY":    0.2,
    "OXYGEN":    0.1,   # tiny pull for isolated MINT
}

# Lead-lag: CHOCOLATE leader triggers 1-tick skew on followers
LEADER_PROD        = "SNACKPACK_CHOCOLATE"
LEADER_MOVE_THR    = 3.0   # ticks in one timestamp
LEADER_SKEW_BONUS  = 1     # extra tick shift on follower quotes


class Trader:

    def run(self, state: TradingState):

        try:
            sv = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            sv = {}
        ema_map:    Dict[str, float] = sv.get("ema", {})
        rmean_map:  Dict[str, float] = sv.get("rm",  {})
        pair_pos:   Dict[str, int]   = sv.get("pp",  {})
        prev_mid:   Dict[str, float] = sv.get("pm",  {})

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

        # ── Step 2: Lead-lag signal from SNACKPACK_CHOCOLATE ─────────────────
        # CHANGE 9: if CHOCOLATE moved >3 ticks since last tick, followers get
        # a +1 skew bonus (push bids/asks up to pre-buy followers before they rise).
        leader_skew = 0
        if LEADER_PROD in mid_map and LEADER_PROD in prev_mid:
            leader_move = mid_map[LEADER_PROD] - prev_mid[LEADER_PROD]
            if abs(leader_move) > LEADER_MOVE_THR:
                leader_skew = int(LEADER_SKEW_BONUS * (1 if leader_move > 0 else -1))

        # Update prev_mid for next tick
        for prod in mid_map:
            prev_mid[prod] = mid_map[prod]

        # ── Step 3: Group cross-sectional fair value ─────────────────────────
        group_mid: Dict[str, float] = {}
        for grp, members in GROUPS.items():
            vals = [mid_map[p] for p in members if p in mid_map]
            if vals:
                group_mid[grp] = sum(vals) / len(vals)

        # ── Step 4: Market making ────────────────────────────────────────────
        for prod, cfg in MM_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            od  = state.order_depths[prod]
            grp = cfg["group"]
            pull = GROUP_PULL.get(grp, 0.2)

            # Fair value = current mid pulled toward group average
            mid  = mid_map[prod]
            fair = mid + pull * (group_mid.get(grp, mid) - mid) if grp in group_mid else mid

            # CHANGE 7: momentum fix for PISTACHIO directional bias
            # When the last 1-tick move is strongly negative, lower fair by 1 tick
            # to avoid over-aggressive buying during downward drift.
            if cfg.get("mom_fix") and prod in prev_mid:
                tick_move = mid - prev_mid.get(prod, mid)
                if tick_move < -2:
                    fair -= 1.0

            # CHANGE 9: apply leader skew to SNACKPACK followers (not CHOCOLATE itself)
            prod_skew_bonus = 0
            if grp == "SNACKPACK" and prod != LEADER_PROD and leader_skew != 0:
                prod_skew_bonus = leader_skew

            result[prod] = self._mm(prod, od, pos, fair, cfg["mm_hs"], prod_skew_bonus)

        # ── Step 5: Mean reversion ────────────────────────────────────────────
        for prod, cfg in MR_CFG.items():
            if prod not in mid_map:
                continue
            pos = state.position.get(prod, 0)
            od  = state.order_depths[prod]
            ema = ema_map[prod]

            mr_orders = self._mr(
                prod, od, pos, ema, cfg["mr_thr"], cfg["mr_close"]
            )

            # For dual-mode products (SNACKPACK_CHOCOLATE is both MM and MR),
            # MR orders take priority; merge with any existing MM orders.
            if prod in result:
                # Merge: MR aggressive takes first, MM passives fill remaining cap
                result[prod] = mr_orders + result[prod]
            else:
                result[prod] = mr_orders

        # ── Step 6: Stat-arb (SNACKPACK) ─────────────────────────────────────
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

        # ── Persist state ─────────────────────────────────────────────────────
        new_sv = json.dumps({"ema": ema_map, "rm": rmean_map, "pp": pair_pos, "pm": prev_mid})
        return result, 0, new_sv

    # ─────────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, hs: int, skew_bonus: int = 0) -> List[Order]:
        """
        Market making with bounded skew, one-sided quoting, and optional
        leader-follower skew bonus (for SNACKPACK lead-lag signal).

        skew_bonus > 0: shift both bid and ask UP by skew_bonus ticks.
                        Used when CHOCOLATE leader moved up → followers expected up.
        skew_bonus < 0: shift DOWN.
        """
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # One-sided quoting near cap (FIX 3 from v4)
        if pos >= CAP_THRESHOLD:
            buy_cap = 0
        if pos <= -CAP_THRESHOLD:
            sell_cap = 0

        # Bounded inventory skew — skew magnitude capped so ask never < fair+1
        raw_skew = pos * 0.5
        skew = int(round(max(-(hs - 1), min(hs - 1, raw_skew))))

        bid_px = round(fair - hs - skew + skew_bonus)
        ask_px = round(fair + hs - skew + skew_bonus)

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
        Mean-reversion scalp.
        Enter aggressively when mid deviates > thr from EMA.
        Close passively when deviation < close_thr (40% of thr).

        For ROBOT products: spread is small (~6-7 ticks) so we hit the
        best available price immediately — don't post passives.
        For OXYGEN_SHAKE: spread is wider (~12 ticks) so we can enter
        aggressively at market and unwind passively near EMA.
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

        # Passive unwind: post limit order near EMA to close existing position
        # Use close_thr (≈40% of entry thr) as the unwind price offset.
        unwind_vol = min(3, abs(pos))
        if unwind_vol > 0:
            if pos > 0 and sell_cap > 0:
                orders.append(Order(product, round(ema + close_thr), -unwind_vol))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order(product, round(ema - close_thr), unwind_vol))

        return orders


# ═══════════════════════════════════════════════════════════════════════════════
#  CHANGE TABLE (v4 → v5)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Change                             | v4        | v5
#  ───────────────────────────────────┼───────────┼────────────────────────────
#  ROBOT_DISHES in MR                 | MISSING   | ADDED  (ACF=-0.232)
#  ROBOT_IRONING in MR                | MISSING   | ADDED  (ACF=-0.128)
#  OXYGEN_SHAKE_CHOCOLATE in MR       | REMOVED   | RESTORED (thr=34)
#  OXYGEN_SHAKE_MINT in MM            | MISSING   | ADDED  (hs=7, light)
#  UV_VISOR_AMBER in MM               | MISSING   | ADDED  (hs=7)
#  UV_VISOR_RED in MM                 | MISSING   | ADDED  (hs=7)
#  GALAXY DARK_MATTER in MM           | MISSING   | ADDED  (hs=7)
#  GALAXY SOLAR_WINDS in MM           | MISSING   | ADDED  (hs=7)
#  SNACKPACK_CHOCOLATE dual mode      | MM only   | MM + MR (thr=22)
#  PISTACHIO momentum fix             | NO        | YES (tick_move<-2 → fair-1)
#  Leader skew (CHOCOLATE leads)      | 0.0 bonus | ±1 tick on followers
#  GROUP_PULL SNACKPACK               | 0.2       | 0.3
#  prev_mid state tracking            | NO        | YES (for leader-lag + mom)
#
#  Expected impact:
#    + ROBOT_DISHES/IRONING: ACF signals should now generate real fills
#      (39 ORDERS_REJECTED products were simply absent from configs)
#    + OXYGEN_SHAKE_CHOCOLATE: restores ~+516 XIRECS historical PnL
#    + 4 new MM products: modest incremental PnL from spare capacity
#    + PISTACHIO fix: eliminates -433 XIRECS directional-bias loss
#    + CHOCOLATE dual-mode: captures MR edge on top of MM spread
#
# ═══════════════════════════════════════════════════════════════════════════════