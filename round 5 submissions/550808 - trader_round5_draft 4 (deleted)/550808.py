"""
IMC Prosperity 4 – Round 5 Trader
Strategy: Cherry-picking winners based on statistical analysis of historical data.

Tier 1 – SNACKPACK (all 5):  Market-making, spread/noise ratio 2-3x.
Tier 2 – MR SCALP:           ROBOT_DISHES, ROBOT_IRONING, OXYGEN_SHAKE_EVENING_BREATH, OXYGEN_SHAKE_CHOCOLATE.
Tier 3 – MARKET MAKE:        GALAXY_SOUNDS top 3, UV_VISOR top 3, OXYGEN_SHAKE_MINT.

SKIP: SLEEP_POD, MICROCHIP, PEBBLES (spread/noise < 1, low composite score).

LEAD-LAG (Round 5 hint): Within SNACKPACK, monitor which product moves first and
skew MM on correlated products accordingly.

Parameters are FIXED from historical analysis. Do NOT tune based on single-run logs.
This avoids the overfitting problem from Round 4.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json, math


# ── FIXED PARAMETERS (do not tune based on log runs) ──────────────────────────
# Source: 00_parameter_report.txt + 00_summary.txt
# halfspread = mm_halfspread, take_edge = aggressive take threshold

PRODUCTS = {
    # TIER 1: SNACKPACK – pure MM, best spread/noise ratio (2-3x)
    "SNACKPACK_PISTACHIO":             {"tier": 1, "hs": 9,  "ema_thresh": 18, "take_edge": 7,  "ema_span": 20},
    "SNACKPACK_VANILLA":               {"tier": 1, "hs": 9,  "ema_thresh": 22, "take_edge": 9,  "ema_span": 20},
    "SNACKPACK_RASPBERRY":             {"tier": 1, "hs": 9,  "ema_thresh": 28, "take_edge": 11, "ema_span": 20},
    "SNACKPACK_CHOCOLATE":             {"tier": 1, "hs": 9,  "ema_thresh": 22, "take_edge": 9,  "ema_span": 20},
    "SNACKPACK_STRAWBERRY":            {"tier": 1, "hs": 10, "ema_thresh": 28, "take_edge": 11, "ema_span": 20},

    # TIER 2: MR SCALP – strong negative ACF, enter on EMA deviation
    "ROBOT_DISHES":                    {"tier": 2, "hs": 4,  "ema_thresh": 40, "take_edge": 16, "ema_span": 20},
    "ROBOT_IRONING":                   {"tier": 2, "hs": 4,  "ema_thresh": 31, "take_edge": 12, "ema_span": 20},
    "OXYGEN_SHAKE_EVENING_BREATH":     {"tier": 2, "hs": 7,  "ema_thresh": 33, "take_edge": 13, "ema_span": 20},
    "OXYGEN_SHAKE_CHOCOLATE":          {"tier": 2, "hs": 7,  "ema_thresh": 34, "take_edge": 13, "ema_span": 20},

    # TIER 3: MARKET MAKE – decent spread/noise (1.26-1.27x), stable regime
    "GALAXY_SOUNDS_DARK_MATTER":       {"tier": 3, "hs": 7,  "ema_thresh": 35, "take_edge": 14, "ema_span": 20},
    "GALAXY_SOUNDS_SOLAR_FLAMES":      {"tier": 3, "hs": 8,  "ema_thresh": 38, "take_edge": 15, "ema_span": 20},
    "GALAXY_SOUNDS_SOLAR_WINDS":       {"tier": 3, "hs": 7,  "ema_thresh": 37, "take_edge": 15, "ema_span": 20},
    "UV_VISOR_RED":                    {"tier": 3, "hs": 8,  "ema_thresh": 38, "take_edge": 15, "ema_span": 20},
    "UV_VISOR_MAGENTA":                {"tier": 3, "hs": 8,  "ema_thresh": 38, "take_edge": 15, "ema_span": 20},
    "UV_VISOR_ORANGE":                 {"tier": 3, "hs": 7,  "ema_thresh": 37, "take_edge": 15, "ema_span": 20},
    "OXYGEN_SHAKE_MINT":               {"tier": 3, "hs": 7,  "ema_thresh": 35, "take_edge": 14, "ema_span": 20},
}

POSITION_LIMIT = 10

# SNACKPACK lead-lag config:
# Negative intra-group correlation means products often diverge then converge.
# Track last-tick moves of the two "leaders" (highest-volume SNACKPACK pair).
SNACK_LEADER = "SNACKPACK_CHOCOLATE"    # moves first statistically (highest |ACF|)
SNACK_FOLLOWERS = [
    "SNACKPACK_PISTACHIO",
    "SNACKPACK_VANILLA",
    "SNACKPACK_RASPBERRY",
    "SNACKPACK_STRAWBERRY",
]
LEAD_LAG_SKEW = 1   # ticks to shift MM prices when leader signal is active


class Trader:

    def run(self, state: TradingState):
        # ── Restore state ──────────────────────────────────────────────────────
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            mem = {}

        emas: Dict[str, float] = mem.get("emas", {})
        prev_mids: Dict[str, float] = mem.get("prev_mids", {})

        result: Dict[str, List[Order]] = {}

        # ── Compute mids & update EMAs ─────────────────────────────────────────
        mids: Dict[str, float] = {}
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = (best_bid + best_ask) / 2.0
            mids[product] = mid

            if product in PRODUCTS:
                span = PRODUCTS[product]["ema_span"]
                alpha = 2.0 / (span + 1)
                emas[product] = mid if product not in emas else \
                    alpha * mid + (1 - alpha) * emas[product]

        # ── Lead-lag signal from SNACKPACK leader ──────────────────────────────
        leader_move = 0.0
        if SNACK_LEADER in mids and SNACK_LEADER in prev_mids:
            leader_move = mids[SNACK_LEADER] - prev_mids[SNACK_LEADER]

        # ── Generate orders per product ────────────────────────────────────────
        for product, cfg in PRODUCTS.items():
            if product not in state.order_depths:
                continue
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue

            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = mids.get(product, (best_bid + best_ask) / 2.0)
            fair = emas.get(product, mid)
            pos = state.position.get(product, 0)
            orders: List[Order] = []
            tier = cfg["tier"]
            hs = cfg["hs"]
            take_edge = cfg["take_edge"]
            thresh = cfg["ema_thresh"]
            dev = mid - fair     # positive = price above EMA

            if tier == 1:
                # ── SNACKPACK: Market-making with inventory skew ───────────────
                # Skew based on inventory: if long, lower ask to clear; if short, raise bid.
                inv_skew = -pos * 0.5   # shift fair value estimate toward clearing inventory
                adj_fair = fair + inv_skew

                # Lead-lag skew for followers
                lag_skew = 0.0
                if product in SNACK_FOLLOWERS and abs(leader_move) > 3:
                    # Leader moved: expect follower to follow (positive correlation overall
                    # at index level even if intra-group correlation is negative on ratio)
                    lag_skew = LEAD_LAG_SKEW * math.copysign(1, leader_move)

                my_bid = round(adj_fair - hs + lag_skew)
                my_ask = round(adj_fair + hs + lag_skew)

                # Aggressive take: if best_ask is very cheap vs fair, lift it
                if best_ask < fair - take_edge and pos < POSITION_LIMIT:
                    qty = min(-od.sell_orders[best_ask], POSITION_LIMIT - pos)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

                # Aggressive take: if best_bid is very rich vs fair, hit it
                if best_bid > fair + take_edge and pos > -POSITION_LIMIT:
                    qty = min(od.buy_orders[best_bid], pos + POSITION_LIMIT)
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))

                # Passive MM – size is 1 (position limit = 10, stay nimble)
                bid_room = POSITION_LIMIT - pos
                ask_room = POSITION_LIMIT + pos
                if bid_room > 0 and my_bid < best_ask:
                    orders.append(Order(product, my_bid, min(bid_room, 5)))
                if ask_room > 0 and my_ask > best_bid:
                    orders.append(Order(product, my_ask, -min(ask_room, 5)))

            elif tier == 2:
                # ── MR SCALP: fade large deviations from EMA ──────────────────
                # Only take aggressively; do not post passive orders for MR products
                # (spread is too tight relative to volatility for safe passive MM)

                if dev > thresh and pos > -POSITION_LIMIT:
                    # Price above EMA by a lot → sell aggressively
                    qty = min(POSITION_LIMIT + pos, 5)
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))

                elif dev < -thresh and pos < POSITION_LIMIT:
                    # Price below EMA by a lot → buy aggressively
                    qty = min(POSITION_LIMIT - pos, 5)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

                elif abs(dev) < thresh * 0.4 and pos != 0:
                    # Mean has reverted → close position
                    if pos > 0:
                        qty = min(pos, 5)
                        orders.append(Order(product, best_bid, -qty))
                    elif pos < 0:
                        qty = min(-pos, 5)
                        orders.append(Order(product, best_ask, qty))

            elif tier == 3:
                # ── TIER 3 MM: symmetric, tighter inventory management ─────────
                inv_skew = -pos * 0.5
                adj_fair = fair + inv_skew
                my_bid = round(adj_fair - hs)
                my_ask = round(adj_fair + hs)

                # Aggressive take only on extreme mispricings
                if best_ask < fair - take_edge and pos < POSITION_LIMIT:
                    qty = min(-od.sell_orders[best_ask], POSITION_LIMIT - pos)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

                if best_bid > fair + take_edge and pos > -POSITION_LIMIT:
                    qty = min(od.buy_orders[best_bid], pos + POSITION_LIMIT)
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))

                bid_room = POSITION_LIMIT - pos
                ask_room = POSITION_LIMIT + pos
                if bid_room > 0 and my_bid < best_ask:
                    orders.append(Order(product, my_bid, min(bid_room, 3)))
                if ask_room > 0 and my_ask > best_bid:
                    orders.append(Order(product, my_ask, -min(ask_room, 3)))

            result[product] = orders

        # ── Persist state ──────────────────────────────────────────────────────
        new_mem = json.dumps({"emas": emas, "prev_mids": mids})
        return result, 0, new_mem