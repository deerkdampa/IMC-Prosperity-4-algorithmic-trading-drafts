from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import numpy as np
import jsonpickle

# Restoring high limits to maximize trend capture
POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}

class Trader:
    @staticmethod
    def linear_trend_prediction(prices: List[float], lookahead: int = 1):
        if len(prices) < 2: return (prices[-1] if prices else 0), 0
        x = np.arange(len(prices), dtype=float)
        y = np.array(prices, dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        return intercept + slope * (len(prices) + lookahead - 1), slope

    def run(self, state: TradingState):
        result = {}
        if state.traderData and state.traderData != "SAMPLE":
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"tomato_prices": []}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 80)
            
            if not order_depth.sell_orders or not order_depth.buy_orders:
                continue
                
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            mid_price = (best_ask + best_bid) / 2
            
            # --- EMERALDS: Competitive Market Making ---
            if product == "EMERALDS":
                # 1. Market Taking (Instant Profit)
                # If someone sells below 10000 or buys above 10000, take it.
                if best_ask < 10000:
                    vol = min(-order_depth.sell_orders[best_ask], limit - position)
                    if vol > 0:
                        orders.append(Order(product, best_ask, vol))
                        position += vol
                if best_bid > 10000:
                    vol = min(order_depth.buy_orders[best_bid], limit + position)
                    if vol > 0:
                        orders.append(Order(product, best_bid, -vol))
                        position -= vol
                
                # 2. Market Making (The "Discord" Backtester won't show this)
                # We place limit orders to buy at 9999 and sell at 10001.
                # In the LIVE engine, this will generate consistent PnL.
                orders.append(Order(product, 9999, limit - position))
                orders.append(Order(product, 10001, -(limit + position)))

            # --- TOMATOES: Aggressive Trend Following ---
            elif product == "TOMATOES":
                trader_state["tomato_prices"].append(mid_price)
                prices = trader_state["tomato_prices"][-50:]
                
                if len(prices) >= 50:
                    predicted, slope = self.linear_trend_prediction(prices)
                    # We removed the 'skew' and 'spread' filters to allow 
                    # the bot to follow the momentum properly.
                    threshold = max(1.8, abs(slope) * 4)
                    
                    if predicted > mid_price + threshold:
                        vol = limit - position
                        if vol > 0: orders.append(Order(product, best_ask, vol))
                    elif predicted < mid_price - threshold:
                        vol = limit + position
                        if vol > 0: orders.append(Order(product, best_bid, -vol))

            result[product] = orders
            
        return result, 0, jsonpickle.encode(trader_state)