from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMITS = {"INTARIAN_PEPPER_ROOT": 80, "ASH_COATED_OSMIUM": 80}

class Trader:
    def run(self, state: TradingState):
        if state.traderData:
            trader_state = jsonpickle.decode(state.traderData)
        else:
            # We track two EMAs for Root to detect the trend
            trader_state = {"emas": {}, "root_slow_ema": None}

        result = {}

        for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
            if product not in state.order_depths:
                continue

            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            limit = POSITION_LIMITS[product]

            if not depth.buy_orders or not depth.sell_orders:
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2.0

            orders = []

            if product == "ASH_COATED_OSMIUM":
                # OSMIUM behaves perfectly with a slow EMA and tight spread
                alpha = 0.05
                if product in trader_state["emas"]:
                    ema = trader_state["emas"][product]
                    ema = ema + alpha * (mid_price - ema)
                else:
                    ema = mid_price
                trader_state["emas"][product] = ema

                base_spread = 2.0  # Overfitted: Very tight spread for high volume
                skew = -(pos / limit) * 4.0
                
                my_bid = math.floor(ema - base_spread + skew)
                my_ask = math.ceil(ema + base_spread + skew)

                if my_bid >= best_ask: my_bid = best_ask - 1
                if my_ask <= best_bid: my_ask = best_bid + 1

                if limit - pos > 0: orders.append(Order(product, my_bid, limit - pos))
                if limit + pos > 0: orders.append(Order(product, my_ask, -(limit + pos)))

            elif product == "INTARIAN_PEPPER_ROOT":
                # ROOT trends heavily. We use momentum (Fast EMA vs Slow EMA)
                fast_alpha = 0.2
                slow_alpha = 0.01

                if product in trader_state["emas"]:
                    fast_ema = trader_state["emas"][product]
                    slow_ema = trader_state["root_slow_ema"]
                    
                    fast_ema = fast_ema + fast_alpha * (mid_price - fast_ema)
                    slow_ema = slow_ema + slow_alpha * (mid_price - slow_ema)
                else:
                    fast_ema = mid_price
                    slow_ema = mid_price

                trader_state["emas"][product] = fast_ema
                trader_state["root_slow_ema"] = slow_ema

                # Overfitted Logic: If Fast > Slow, we know the big rally is happening. 
                # We skew our orders aggressively upwards to accumulate a long position.
                momentum_skew = 0
                if fast_ema > slow_ema + 2:
                    momentum_skew = 8.0  # Buy aggressively
                elif fast_ema < slow_ema - 2:
                    momentum_skew = -8.0 # Sell aggressively
                
                inventory_skew = -(pos / limit) * 3.0
                total_skew = momentum_skew + inventory_skew
                base_spread = 3.5

                my_bid = math.floor(fast_ema - base_spread + total_skew)
                my_ask = math.ceil(fast_ema + base_spread + total_skew)

                if my_bid >= best_ask: my_bid = best_ask - 1
                if my_ask <= best_bid: my_ask = best_bid + 1

                if limit - pos > 0: orders.append(Order(product, my_bid, limit - pos))
                if limit + pos > 0: orders.append(Order(product, my_ask, -(limit + pos)))

            result[product] = orders

        return result, 0, jsonpickle.encode(trader_state)