from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

ROOT_FAST_ALPHA = 0.18
ROOT_SLOW_ALPHA = 0.04

# Slightly smoother EMA for a flat, mean-reverting product
OSMIUM_ALPHA = 0.06
OSMIUM_ANCHOR = 10000.0      # structural anchor from CSV behaviour
OSMIUM_ANCHOR_WEIGHT = 0.7   # 70% anchor, 30% EMA

class Trader:
    def run(self, state: TradingState):
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast": None,
                "root_slow": None,
                "root_last_mid": None,
                "root_hold_mode": False,
                "osmium_ema": OSMIUM_ANCHOR,
            }

        result: Dict[str, List[Order]] = {}

        # Explicit processing order for queue priority on Osmium
        for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
            if product not in state.order_depths:
                continue

            depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            limit = POSITION_LIMITS[product]

            if not depth.buy_orders or not depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            if product == "INTARIAN_PEPPER_ROOT":
                # --- same ROOT logic as 229986 ---
                fast = data.get("root_fast")
                slow = data.get("root_slow")
                last_mid = data.get("root_last_mid")
                hold_mode = data.get("root_hold_mode", False)

                if fast is None:
                    fast = mid
                    slow = mid
                    last_mid = mid

                fast = ROOT_FAST_ALPHA * mid + (1 - ROOT_FAST_ALPHA) * fast
                slow = ROOT_SLOW_ALPHA * mid + (1 - ROOT_SLOW_ALPHA) * slow
                slope = fast - slow
                momentum = mid - last_mid
                fair = 0.65 * fast + 0.35 * slow

                if slope > 2 or momentum > 1:
                    hold_mode = True
                if slope < -4 and momentum < -2:
                    hold_mode = False

                current = pos

                # Step 1: controlled taking of asks
                if hold_mode and current < limit:
                    buy_cap_price = fair + 2
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if current >= limit:
                            break
                        if ask <= buy_cap_price or ask <= best_ask:
                            qty = min(-vol, limit - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break
                else:
                    target = 40 if slope >= 0 else 20
                    buy_cap_price = fair + 1
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if current >= target:
                            break
                        if ask <= buy_cap_price:
                            qty = min(-vol, target - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break

                # Step 2: passive bid if we still want more
                desired = limit if hold_mode else (40 if slope >= 0 else 20)
                if current < desired:
                    bid_px = min(best_bid + 1, math.floor(fair))
                    bid_px = min(bid_px, best_ask - 1)
                    qty = min(desired - current, 20)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

                # Step 3: trim if trend weakens a lot and bids are rich
                if current > 0 and (slope < -2 or momentum < -2):
                    for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if bid >= fair + 2:
                            qty = min(vol, current)
                            if qty > 0:
                                orders.append(Order(product, bid, -qty))
                                current -= qty
                        else:
                            break

                data["root_fast"] = fast
                data["root_slow"] = slow
                data["root_last_mid"] = mid
                data["root_hold_mode"] = hold_mode

            else:
                # --- improved OSMIUM, keeping 229986 structure but cleaner fair + spread-aware passive ---
                ema = data.get("osmium_ema", OSMIUM_ANCHOR)
                ema = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema
                data["osmium_ema"] = ema

                # Blend anchor and EMA so we stay near 10k but adapt if needed
                fair = OSMIUM_ANCHOR_WEIGHT * OSMIUM_ANCHOR + (1 - OSMIUM_ANCHOR_WEIGHT) * ema

                current = pos

                # 1. Take only clearly mispriced levels (same ±1 tick idea as 229986)
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair - 1 and current < limit:
                        qty = min(-vol, limit - current)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid >= fair + 1 and current > -limit:
                        qty = min(vol, current + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            current -= qty
                    else:
                        break

                # 2. Passive market making with modest inventory skew
                skew = int(round(current * 0.05))

                # Spread-aware half-spread: stay aggressive (3) most of the time
                if spread <= 8:
                    half_spread = 2
                else:
                    half_spread = 3 if spread <= 18 else 4

                my_bid = min(best_bid + 1, math.floor(fair - half_spread) - skew)
                my_ask = max(best_ask - 1, math.ceil(fair + half_spread) - skew)

                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_cap = max(0, limit - current)
                sell_cap = max(0, limit + current)
                buy_size = min(20, buy_cap)
                sell_size = min(20, sell_cap)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid), int(buy_size)))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -int(sell_size)))

            result[product] = orders

        return result, 0, jsonpickle.encode(data)