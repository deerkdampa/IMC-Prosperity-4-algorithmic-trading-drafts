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

            if product == "INTARIAN_PEPPER_ROOT":
                ema = data.get("root_ema")
                if ema is None:
                    ema = mid
                ema = 0.10 * mid + 0.90 * ema
                data["root_ema"] = ema

                desired = 80 if mid >= ema else 40

                for ask, vol in sorted(depth.sell_orders.items()):
                    if pos >= desired:
                        break
                    if ask <= ema + 1:
                        qty = min(-vol, desired - pos)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            pos += qty

                if pos < desired:
                    bid_px = min(best_bid + 1, best_ask - 1)
                    qty = min(desired - pos, 10)
                    if qty > 0:
                        orders.append(Order(product, bid_px, qty))

            elif product == "ASH_COATED_OSMIUM":
                ema = data.get("osmium_ema", 10000.0)
                ema = 0.05 * mid + 0.95 * ema
                fair = 0.9 * 10000 + 0.1 * ema
                data["osmium_ema"] = ema

                for ask, vol in sorted(depth.sell_orders.items()):
                    if pos >= limit:
                        break
                    if ask <= fair - 2:
                        qty = min(-vol, limit - pos)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            pos += qty

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if pos <= -limit:
                        break
                    if bid >= fair + 2:
                        qty = min(vol, pos + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            pos -= qty

                bid_px = min(best_bid + 1, best_ask - 1)
                ask_px = max(best_ask - 1, bid_px + 1)
                if pos < limit:
                    orders.append(Order(product, bid_px, min(10, limit - pos)))
                if pos > -limit:
                    orders.append(Order(product, ask_px, -min(10, limit + pos)))

            result[product] = orders

        return result, 0, jsonpickle.encode(data)
