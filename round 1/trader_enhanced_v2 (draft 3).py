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
OSMIUM_ALPHA = 0.10

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
                "osmium_ema": 10000.0,
            }

        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
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
                fair = 0.7 * fast + 0.3 * slow

                if slope > 2 or momentum > 1:
                    hold_mode = True
                if slope < -4 and momentum < -2:
                    hold_mode = False

                current = pos
                desired = 80 if hold_mode else (50 if slope >= 1 else 25)
                take_cap = fair + (1 if not hold_mode else 2)

                for ask, vol in sorted(depth.sell_orders.items()):
                    if current >= desired:
                        break
                    if ask <= take_cap or (hold_mode and ask == best_ask and slope > 3):
                        qty = min(-vol, desired - current)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                if current < desired:
                    bid_px = min(best_bid + 1, math.floor(fair - (0 if hold_mode else 1)))
                    bid_px = min(bid_px, best_ask - 1)
                    qty = min(desired - current, 20)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

                if current > 0 and (slope < -2 or momentum < -2):
                    rich_price = fair + 2
                    for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if bid >= rich_price:
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

            elif product == "ASH_COATED_OSMIUM":
                ema = data.get("osmium_ema", 10000.0)
                ema = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema
                fair = 0.9 * 10000.0 + 0.1 * ema

                current = pos

                for ask, vol in sorted(depth.sell_orders.items()):
                    if current >= limit:
                        break
                    if ask <= fair - 2 or (ask <= fair - 1 and spread >= 7):
                        qty = min(-vol, limit - current)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if current <= -limit:
                        break
                    if bid >= fair + 2 or (bid >= fair + 1 and spread >= 7):
                        qty = min(vol, current + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            current -= qty
                    else:
                        break

                skew = int(round(current * 0.04))
                half_spread = 2 if spread <= 6 else 3
                my_bid = min(best_bid + 1, math.floor(fair - half_spread) - skew)
                my_ask = max(best_ask - 1, math.ceil(fair + half_spread) - skew)

                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_cap = max(0, limit - current)
                sell_cap = max(0, limit + current)
                buy_size = min(18, buy_cap)
                sell_size = min(18, sell_cap)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid), int(buy_size)))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -int(sell_size)))

                data["osmium_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)
