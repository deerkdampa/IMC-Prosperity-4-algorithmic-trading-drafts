from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

OSMIUM_FAIR = 10000
OSMIUM_SKEW_FACTOR = 0.04
OSMIUM_BASE_SPREAD = 2
ROOT_FAST_ALPHA = 0.18
ROOT_SLOW_ALPHA = 0.04

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
                fair = 0.60 * fast + 0.40 * slow

                if slope > 1.5 or momentum > 1:
                    hold_mode = True
                if slope < -5 and momentum < -3:
                    hold_mode = False

                current = pos

                if hold_mode:
                    buy_cap_price = fair + 3
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if current >= limit:
                            break
                        if ask <= buy_cap_price or ask == best_ask:
                            qty = min(-vol, limit - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break
                else:
                    target = 60 if slope >= 0 else 30
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

                desired = limit if hold_mode else (60 if slope >= 0 else 30)
                if current < desired:
                    bid_px = min(best_bid + 1, math.floor(fair))
                    bid_px = min(bid_px, best_ask - 1)
                    qty = min(desired - current, 20)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

                if current > 0 and slope < -4 and momentum < -3:
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

            elif product == "ASH_COATED_OSMIUM":
                current = pos

                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask < OSMIUM_FAIR and current < limit:
                        qty = min(-vol, limit - current)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid > OSMIUM_FAIR and current > -limit:
                        qty = min(vol, current + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            current -= qty
                    else:
                        break

                skew = -int(round(current * OSMIUM_SKEW_FACTOR))
                buy_price = min(OSMIUM_FAIR - OSMIUM_BASE_SPREAD + skew, best_bid + 1)
                sell_price = max(OSMIUM_FAIR + OSMIUM_BASE_SPREAD + skew, best_ask - 1)

                buy_volume = min(limit - current, 60)
                sell_volume = min(limit + current, 60)

                if buy_volume > 0 and buy_price > 0:
                    orders.append(Order(product, int(buy_price), int(buy_volume)))
                if sell_volume > 0 and sell_price > 0:
                    orders.append(Order(product, int(sell_price), -int(sell_volume)))

            result[product] = orders

        return result, 0, jsonpickle.encode(data)
