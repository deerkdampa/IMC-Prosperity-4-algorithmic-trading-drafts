from datamodel import OrderDepth, TradingState, Order
from typing import List
import numpy as np
import jsonpickle

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}

class Trader:

    @staticmethod
    def linear_trend_prediction(prices: List[float], lookahead: int = 1):
        """Simple linear regression to predict the next price point."""
        if len(prices) < 2:
            return prices[-1] if prices else 0, 0.0
            
        x = np.arange(len(prices), dtype=float)
        y = np.array(prices, dtype=float)
        mean_x = x.mean()
        mean_y = y.mean()
        
        covariance = np.mean((x - mean_x) * (y - mean_y))
        variance_x = np.mean((x - mean_x) ** 2)
        slope = covariance / variance_x if variance_x > 0 else 0.0
        intercept = mean_y - slope * mean_x
        
        return intercept + slope * (len(prices) + lookahead - 1), slope

    def run(self, state: TradingState):
        """Processes market observations and outputs orders."""
        result = {}
        
        # Load state history for our predictors
        if state.traderData and state.traderData != "SAMPLE":
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"tomato_prices": []}
            
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 80)
            
            # Ensure we have valid order book data before processing
            if not order_depth.sell_orders or not order_depth.buy_orders:
                continue
                
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_amount = order_depth.sell_orders[best_ask]
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_amount = order_depth.buy_orders[best_bid]
            mid_price = (best_ask + best_bid) / 2
            
            # ------------------------------------------------------------------
            # EMERALDS — Hard-Peg Mean Reversion Strategy
            # ------------------------------------------------------------------
            if product == "EMERALDS":
                # Emeralds have a true underlying value of strictly 10,000.
                # We buy anything below 10k and sell anything above 10k.
                acceptable_buy_price = 9998
                acceptable_sell_price = 10002
                
                # Buy orders (taking liquidity from sellers)
                if best_ask <= acceptable_buy_price:
                    buy_volume = min(-best_ask_amount, limit - position)
                    if buy_volume > 0:
                        orders.append(Order(product, best_ask, buy_volume))
                        position += buy_volume
                        
                # Sell orders (taking liquidity from buyers)
                if best_bid >= acceptable_sell_price:
                    sell_volume = min(best_bid_amount, limit + position)
                    if sell_volume > 0:
                        orders.append(Order(product, best_bid, -sell_volume))
                        position -= sell_volume
                            
            # ------------------------------------------------------------------
            # TOMATOES — Pure Trend-Following Strategy
            # ------------------------------------------------------------------
            elif product == "TOMATOES":
                trader_state["tomato_prices"].append(mid_price)
                prices = trader_state["tomato_prices"]
                
                if len(prices) >= 50:
                    predicted_price, slope = self.linear_trend_prediction(prices[-50:])
                    threshold = max(1.5, abs(slope) * 5)
                    
                    # Execute purely based on trend strength, maximizing position
                    if predicted_price > mid_price + threshold and best_ask < predicted_price:
                        buy_volume = min(-best_ask_amount, limit - position)
                        if buy_volume > 0:
                            orders.append(Order(product, best_ask, buy_volume))
                            
                    elif predicted_price < mid_price - threshold and best_bid > predicted_price:
                        sell_volume = min(best_bid_amount, limit + position)
                        if sell_volume > 0:
                            orders.append(Order(product, best_bid, -sell_volume))

            result[product] = orders
            
        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData