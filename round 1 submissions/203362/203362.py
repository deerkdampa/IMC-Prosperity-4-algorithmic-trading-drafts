from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

class Trader:
    def run(self, state: TradingState):
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_ema": None,
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

            if product == "ASH_COATED_OSMIUM":
                # Simple idea: osmium stays near 10000, so buy below and sell above.
                ema = data.get("osmium_ema", 10000.0)
                ema = 0.10 * mid + 0.90 * ema
                fair = 0.8 * 10000 + 0.2 * ema

                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair - 1 and pos < limit:
                        qty = min(-vol, limit - pos)
                        orders.append(Order(product, ask, qty))
                        pos += qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid >= fair + 1 and pos > -limit:
                        qty = min(vol, pos + limit)
                        orders.append(Order(product, bid, -qty))
                        pos -= qty
                    else:
                        break

                my_bid = min(best_bid + 1, math.floor(fair - 2))
                my_ask = max(best_ask - 1, math.ceil(fair + 2))
                if my_bid < my_ask:
                    if pos < limit:
                        orders.append(Order(product, int(my_bid), min(20, limit - pos)))
                    if pos > -limit:
                        orders.append(Order(product, int(my_ask), -min(20, pos + limit)))

                data["osmium_ema"] = ema

            elif product == "INTARIAN_PEPPER_ROOT":
                # Simple idea: roots trend up often, so try to get long without overpaying too much.
                ema = data.get("root_ema")
                if ema is None:
                    ema = mid
                ema = 0.15 * mid + 0.85 * ema

                target = 80 if mid >= ema else 40

                for ask, vol in sorted(depth.sell_orders.items()):
                    if pos >= target:
                        break
                    if ask <= ema + 1:
                        qty = min(-vol, target - pos)
                        orders.append(Order(product, ask, qty))
                        pos += qty
                    else:
                        break

                if pos < target:
                    my_bid = min(best_bid + 1, math.floor(ema))
                    my_bid = min(my_bid, best_ask - 1)
                    qty = min(15, target - pos)
                    if qty > 0:
                        orders.append(Order(product, int(my_bid), int(qty)))

                if pos > 50:
                    my_ask = max(best_ask - 1, math.ceil(ema + 2))
                    qty = min(15, pos - 50)
                    if qty > 0:
                        orders.append(Order(product, int(my_ask), -int(qty)))

                data["root_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)