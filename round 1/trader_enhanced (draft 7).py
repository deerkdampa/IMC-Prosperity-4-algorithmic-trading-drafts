from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMITS = {"INTARIAN_PEPPER_ROOT": 80, "ASH_COATED_OSMIUM": 80}

class Trader:
    def run(self, state: TradingState):
        # 1. Initialize or load state
        if state.traderData:
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"emas": {}}

        result = {}

        for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
            if product not in state.order_depths:
                continue

            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            limit = POSITION_LIMITS[product]

            # Safety check: ensure book isn't empty
            if not depth.buy_orders or not depth.sell_orders:
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2.0

            # 2. Update EMA (Fair Value)
            alpha = 0.1 # General responsive alpha
            if product in trader_state["emas"]:
                ema = trader_state["emas"][product]
                ema = ema + alpha * (mid_price - ema)
            else:
                ema = mid_price
            trader_state["emas"][product] = ema

            # 3. Dynamic Pricing & Inventory Lean
            # Base spread determines how wide our quotes are
            base_spread = 4.0 if product == "INTARIAN_PEPPER_ROOT" else 3.0
            
            # Inventory lean forces the bot back to neutral (0)
            skew = -(pos / limit) * 5.0 

            my_bid = math.floor(ema - base_spread + skew)
            my_ask = math.ceil(ema + base_spread + skew)

            # 4. Safety Constraints: Be competitive, but don't cross the spread
            my_bid = min(my_bid, best_bid + 1)
            my_ask = max(my_ask, best_ask - 1)

            if my_bid >= best_ask: my_bid = best_ask - 1
            if my_ask <= best_bid: my_ask = best_bid + 1

            # 5. Place Orders
            orders = []
            if limit - pos > 0:
                orders.append(Order(product, my_bid, limit - pos))
            if limit + pos > 0:
                orders.append(Order(product, my_ask, -(limit + pos)))

            result[product] = orders

        # Save state for the next tick
        return result, 0, jsonpickle.encode(trader_state)