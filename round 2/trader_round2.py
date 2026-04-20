from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

# ─── Position limits ────────────────────────────────────────────────────────
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

# ─── EMA decay factors ───────────────────────────────────────────────────────
ROOT_FAST_ALPHA = 0.18
ROOT_SLOW_ALPHA = 0.04
OSMIUM_ALPHA    = 0.15

# ─── Root strategy parameters ────────────────────────────────────────────────
T_UP   =  2.0   # trend_score above this → target pos 60
T_EXIT = -1.0   # trend_score below this → trim longs back toward 20
CHUNK  = 10     # max lots per take-pass

# ─── Osmium parameters ───────────────────────────────────────────────────────
TAKE_EDGE = 1.5  # only take if mispricing > this
SKEW_K    = 0.10 # inventory skew per-lot (at pos=80 shifts by 8 ticks)
MM_SIZE   = 10   # passive quote size per side

# ─── Market Access Fee bid ───────────────────────────────────────────────────
# Adjust this number before final submission.
# Recommended: 2,000–5,000 with a non-round value to step over bid clusters.
# Only pay if your bid lands in the top 50% of all bids.
MAF_BID = 3487


class Trader:

    def bid(self) -> int:
        """Return the Market Access Fee (XIRECs). Top 50% of bids get +25% order book quotes."""
        return MAF_BID

    def run(self, state: TradingState):
        # ── Restore persistent state ─────────────────────────────────────
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast":     None,
                "root_slow":     None,
                "root_last_mid": None,
                "osmium_ema":    10000.0,
            }

        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            orders: List[Order] = []
            pos   = state.position.get(product, 0)
            limit = POSITION_LIMITS[product]

            if not depth.buy_orders or not depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            mid      = (best_bid + best_ask) / 2.0
            spread   = best_ask - best_bid

            # ════════════════════════════════════════════════════════════
            #  INTARIAN_PEPPER_ROOT  ── trend-following, long-biased
            # ════════════════════════════════════════════════════════════
            if product == "INTARIAN_PEPPER_ROOT":
                fast     = data.get("root_fast")
                slow     = data.get("root_slow")
                last_mid = data.get("root_last_mid")

                if fast is None:
                    fast = slow = last_mid = mid

                fast = ROOT_FAST_ALPHA * mid + (1 - ROOT_FAST_ALPHA) * fast
                slow = ROOT_SLOW_ALPHA * mid + (1 - ROOT_SLOW_ALPHA) * slow

                slope       = fast - slow
                momentum    = mid - last_mid
                trend_score = 0.5 * slope + 0.5 * momentum
                fair        = 0.65 * fast + 0.35 * slow

                # Regime → target position
                if trend_score >= T_UP:
                    target_pos = 60
                elif trend_score >= 0:
                    target_pos = 30
                else:
                    target_pos = 10

                target_pos = min(target_pos, limit)
                current    = pos

                # Step 1: Take asks up to fair+1
                buy_cap_price = fair + 1
                for ask, vol in sorted(depth.sell_orders.items()):
                    if current >= target_pos:
                        break
                    if ask <= buy_cap_price:
                        qty = min(-vol, target_pos - current, CHUNK)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                # Step 2: Passive bid below fair if still short of target
                if current < target_pos:
                    bid_px = min(best_bid + 1, math.floor(fair))
                    bid_px = min(bid_px, best_ask - 1)
                    qty    = min(target_pos - current, MM_SIZE)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

                # Step 3: Trim longs on clear weakening with a good exit price
                if current > 0 and trend_score < T_EXIT:
                    for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if bid >= fair + 2:
                            qty = min(vol, current - 20)   # floor at pos=20
                            if qty > 0:
                                orders.append(Order(product, bid, -qty))
                                current -= qty
                        else:
                            break

                data["root_fast"]     = fast
                data["root_slow"]     = slow
                data["root_last_mid"] = mid

            # ════════════════════════════════════════════════════════════
            #  ASH_COATED_OSMIUM  ── mean-reversion / market-making
            # ════════════════════════════════════════════════════════════
            elif product == "ASH_COATED_OSMIUM":
                ema  = data.get("osmium_ema", 10000.0)
                ema  = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema
                # Blend EMA with current mid: responds faster, stays anchored
                fair = 0.70 * ema + 0.30 * mid

                current = pos

                # Take clearly mispriced levels
                for ask, vol in sorted(depth.sell_orders.items()):
                    if current >= limit:
                        break
                    if ask <= fair - TAKE_EDGE:
                        qty = min(-vol, limit - current)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if current <= -limit:
                        break
                    if bid >= fair + TAKE_EDGE:
                        qty = min(vol, current + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            current -= qty
                    else:
                        break

                # Passive market-making with inventory skew
                if spread <= 3:
                    half_spread = 1
                elif spread <= 6:
                    half_spread = 2
                else:
                    half_spread = 3

                skew    = int(round(current * SKEW_K))
                my_bid  = min(best_bid + 1, math.floor(fair - half_spread) - skew)
                my_ask  = max(best_ask - 1, math.ceil(fair + half_spread) - skew)

                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_cap   = max(0, limit - current)
                sell_cap  = max(0, limit + current)
                buy_size  = min(MM_SIZE, buy_cap)
                sell_size = min(MM_SIZE, sell_cap)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid),  int(buy_size)))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -int(sell_size)))

                data["osmium_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)
