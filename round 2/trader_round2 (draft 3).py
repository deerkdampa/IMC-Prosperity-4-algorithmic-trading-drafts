from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

# ── Position limits ──────────────────────────────────────────────────────────
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

# ── IPR tuning ───────────────────────────────────────────────────────────────
ROOT_FAST_ALPHA  = 0.18   # fast EMA decay
ROOT_SLOW_ALPHA  = 0.04   # slow EMA decay
IPR_SLOPE_UP     = 3.0    # min slope to enter strong-trend mode
IPR_SLOPE_DN     = -5.0   # slope must drop below this to exit trend mode
IPR_MOM_DN       = -3.0   # AND momentum must drop below this to exit
IPR_TARGET_TREND = 70     # target position in strong trend
IPR_TARGET_NEUT  = 35     # target position when trend is neutral (slope>=0)
IPR_TARGET_WEAK  = 15     # target position when slope is negative
IPR_ENTRY_MAX    = 1      # max ticks above fair we will pay to enter
IPR_EXIT_MIN     = 2      # min ticks above fair required to sell into
IPR_CHUNK        = 10     # max lots to buy per ask level
IPR_PASSIVE_SIZE = 15     # passive bid size

# ── ACO tuning ───────────────────────────────────────────────────────────────
OSMIUM_ALPHA   = 0.15     # EMA speed
ACO_EMA_WEIGHT = 1.0      # fair = EMA only (pure dynamic fair value)
ACO_TAKE_TICKS = 1.5      # min mispricing to take aggressively
ACO_HALF_SPD   = 2        # passive half-spread (ticks)
ACO_SKEW_K     = 0.08     # inventory skew per unit of position
ACO_PASS_SIZE  = 15       # passive quote size

# ── MAF bid ──────────────────────────────────────────────────────────────────
MAF_BID = 3487            # ← change before final submission if needed


class Trader:

    def bid(self):
        return MAF_BID

    def run(self, state: TradingState):
        # ── Restore state ─────────────────────────────────────────────────────
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast":     None,
                "root_slow":     None,
                "root_last_mid": None,
                "root_trend":    False,   # True = strong-trend mode
                "osmium_ema":    None,    # initialised on first tick
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

            # ── INTARIAN_PEPPER_ROOT ──────────────────────────────────────────
            if product == "INTARIAN_PEPPER_ROOT":
                fast  = data.get("root_fast")
                slow  = data.get("root_slow")
                last  = data.get("root_last_mid")
                trend = data.get("root_trend", False)

                # Seed on first tick
                if fast is None:
                    fast  = mid
                    slow  = mid
                    last  = mid

                # Update EMAs
                fast = ROOT_FAST_ALPHA * mid + (1 - ROOT_FAST_ALPHA) * fast
                slow = ROOT_SLOW_ALPHA * mid + (1 - ROOT_SLOW_ALPHA) * slow

                slope    = fast - slow
                momentum = mid - last
                fair     = 0.65 * fast + 0.35 * slow

                # ── Trend regime ──────────────────────────────────────────────
                # Enter trend mode only when slope is convincingly positive
                if slope > IPR_SLOPE_UP:
                    trend = True
                # Exit trend mode only when BOTH slope AND momentum are clearly negative
                if slope < IPR_SLOPE_DN and momentum < IPR_MOM_DN:
                    trend = False

                # ── Determine target position ─────────────────────────────────
                if trend:
                    target = IPR_TARGET_TREND
                elif slope >= 0:
                    target = IPR_TARGET_NEUT
                else:
                    target = IPR_TARGET_WEAK

                current = pos

                # ── Step 1: Aggressive entry (take asks) ──────────────────────
                # Only buy asks at or below fair + IPR_ENTRY_MAX
                # Buy in chunks so we never slam the whole ladder at once
                buy_cap_price = fair + IPR_ENTRY_MAX
                bought_this_tick = 0
                for ask, vol in sorted(depth.sell_orders.items()):
                    if current >= target:
                        break
                    if bought_this_tick >= IPR_CHUNK:
                        break
                    if ask <= buy_cap_price:
                        qty = min(-vol, target - current, IPR_CHUNK - bought_this_tick)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current          += qty
                            bought_this_tick += qty
                    else:
                        break

                # ── Step 2: Passive bid ───────────────────────────────────────
                if current < target:
                    bid_px = min(best_bid + 1, math.floor(fair))
                    bid_px = min(bid_px, best_ask - 1)
                    qty    = min(target - current, IPR_PASSIVE_SIZE)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), qty))

                # ── Step 3: Sell when trend fades and there's a rich bid ──────
                if current > 0 and slope < -2 and momentum < -1:
                    floor_pos = max(0, IPR_TARGET_WEAK)
                    for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if current <= floor_pos:
                            break
                        if bid >= fair + IPR_EXIT_MIN:
                            qty = min(vol, current - floor_pos)
                            if qty > 0:
                                orders.append(Order(product, bid, -qty))
                                current -= qty
                        else:
                            break

                # ── Persist ───────────────────────────────────────────────────
                data["root_fast"]     = fast
                data["root_slow"]     = slow
                data["root_last_mid"] = mid
                data["root_trend"]    = trend

            # ── ASH_COATED_OSMIUM ─────────────────────────────────────────────
            elif product == "ASH_COATED_OSMIUM":
                ema = data.get("osmium_ema")

                # Seed EMA on first tick from actual market mid
                if ema is None:
                    ema = mid

                ema  = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema
                fair = ema   # purely dynamic; no hardcoded anchor

                current = pos

                # ── Aggressive take: buy clearly cheap, sell clearly rich ──────
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair - ACO_TAKE_TICKS and current < limit:
                        qty = min(-vol, limit - current)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid >= fair + ACO_TAKE_TICKS and current > -limit:
                        qty = min(vol, current + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            current -= qty
                    else:
                        break

                # ── Passive quotes with inventory skew ────────────────────────
                # Dynamic half-spread based on market spread
                if spread <= 3:
                    half_spd = 1
                elif spread <= 6:
                    half_spd = ACO_HALF_SPD
                else:
                    half_spd = 3

                skew   = current * ACO_SKEW_K      # positive pos → skew quotes down
                my_bid = math.floor(fair - half_spd - skew)
                my_ask = math.ceil( fair + half_spd - skew)

                # Ensure bid < ask and inside market
                my_bid = min(my_bid, best_bid + 1)
                my_ask = max(my_ask, best_ask - 1)
                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_cap  = max(0, limit - current)
                sell_cap = max(0, limit + current)
                buy_sz   = min(ACO_PASS_SIZE, buy_cap)
                sell_sz  = min(ACO_PASS_SIZE, sell_cap)

                if buy_sz > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid),  buy_sz))
                if sell_sz > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -sell_sz))

                # ── Persist ───────────────────────────────────────────────────
                data["osmium_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)
