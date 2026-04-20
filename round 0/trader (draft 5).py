from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import numpy as np
import jsonpickle

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80, 
}

class Trader:
    @staticmethod
    def linear_trend_prediction(prices: List[float], lookahead: int = 1):
        if len(prices) < 10: return (prices[-1] if prices else 0), 0
        x = np.arange(len(prices))
        y = np.array(prices)
        z = np.polyfit(x, y, 1) # Simple linear regression
        return z[1] + z[0] * (len(prices) + lookahead - 1), z[0]

    def run(self, state: TradingState):
        if state.traderData and state.traderData != "SAMPLE":
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"tomato_prices": []}

        result: Dict[str, List[Order]] = {}

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 80)
            
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            mid_price = (best_ask + best_bid) / 2.0

            # ------------------------------------------------------------------
            # EMERALDS — Competitive Market Making
            # ------------------------------------------------------------------
            if product == "EMERALDS":
                # If others are trading at 10000, we must take any price 
                # strictly better than 10000 to get fills.
                if best_ask < 10000:
                    vol = min(-order_depth.sell_orders[best_ask], limit - position)
                    if vol > 0: orders.append(Order(product, best_ask, vol))
                
                if best_bid > 10000:
                    vol = min(order_depth.buy_orders[best_bid], limit + position)
                    if vol > 0: orders.append(Order(product, best_bid, -vol))

                # Limit orders: Stay at 9999/10001 but use the FULL limit.
                # If 10000 is crowded, we wait for the "overflow" volume.
                curr_pos = position + sum(o.quantity for o in orders)
                orders.append(Order(product, 9999, limit - curr_pos))
                orders.append(Order(product, 10001, -(limit + curr_pos)))

            # ------------------------------------------------------------------
            # TOMATOES — High-Limit Trend Following
            # ------------------------------------------------------------------
            elif product == "TOMATOES":
                trader_state["tomato_prices"].append(mid_price)
                prices = trader_state["tomato_prices"][-50:] # Lookback of 50

                if len(prices) >= 50:
                    pred_price, slope = self.linear_trend_prediction(prices)
                    
                    # Instead of a fixed SKEW, we use a "Trend Confidence" threshold.
                    # This ensures we only go Max Long if the slope is strong.
                    threshold = 2.0 
                    
                    if pred_price > mid_price + threshold:
                        # Aggressive Buy: Take the best ask
                        vol = min(-order_depth.sell_orders[best_ask], limit - position)
                        if vol > 0: orders.append(Order(product, best_ask, vol))
                    
                    elif pred_price < mid_price - threshold:
                        # Aggressive Sell: Take the best bid
                        vol = min(order_depth.buy_orders[best_bid], limit + position)
                        if vol > 0: orders.append(Order(product, best_bid, -vol))

            result[product] = orders

        return result, 0, jsonpickle.encode(trader_state)