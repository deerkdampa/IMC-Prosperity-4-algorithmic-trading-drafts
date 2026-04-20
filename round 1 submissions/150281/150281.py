from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

# --- STRATEGY PARAMETERS ---
POSITION_LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80,
}

# OSMIUM (Stable Peg Strategy)
OSMIUM_FAIR_VALUE = 10000
OSMIUM_BASE_SPREAD = 2

# ROOTS (Dynamic Trending)
ROOT_EMA_ALPHA = 0.15        # Smoothed down from 0.25 for a slightly more stable trendline
ROOT_MIN_SPREAD = 2.0        
ROOT_RISK_AVERSION = 0.002   # Drastically reduced from 0.01 to allow higher position limits
ROOT_VOL_WINDOW = 20         

class Trader:

    def run(self, state: TradingState):
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                # Removed osmium_prices since we are using a peg strategy
                "root_ema": None,
                "root_prices": [] 
            }

        result = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
                result[product] = orders
                continue

            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 80)
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            mid_price = (best_ask + best_bid) / 2

            # -------------------------------------------------------
            # ASH-COATED OSMIUM LOGIC (Updated to Stable Peg)
            # -------------------------------------------------------
            if product == "ASH_COATED_OSMIUM":
                # Osmium hovers tightly around 10,000. 
                fair_value = OSMIUM_FAIR_VALUE
                
                # Soft Inventory Management: 
                # Instead of a crazy mathematical skew, we just shift quotes 
                # by 1 tick if we get dangerously close to our position limit.
                skew = 0
                if position > 40:
                    skew = -1
                elif position < -40:
                    skew = 1

                # Pennying the peg
                buy_price  = min(fair_value - OSMIUM_BASE_SPREAD + skew, best_ask - 1)
                sell_price = max(fair_value + OSMIUM_BASE_SPREAD + skew, best_bid + 1)

                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            # -------------------------------------------------------
            # INTARIAN PEPPER ROOT LOGIC (Optimized Math)
            # -------------------------------------------------------
            elif product == "INTARIAN_PEPPER_ROOT":
                # 1. Update EMA (Fair Value)
                if trader_state["root_ema"] is None:
                    trader_state["root_ema"] = mid_price
                current_ema = (ROOT_EMA_ALPHA * mid_price) + ((1 - ROOT_EMA_ALPHA) * trader_state["root_ema"])
                trader_state["root_ema"] = current_ema
                fair_value = current_ema

                # 2. Track Prices for Volatility (Sigma)
                trader_state["root_prices"].append(mid_price)
                if len(trader_state["root_prices"]) > ROOT_VOL_WINDOW:
                    trader_state["root_prices"].pop(0)
                
                prices = trader_state["root_prices"]
                
                # 3. Calculate Volatility (Variance)
                if len(prices) > 1:
                    mean_price = sum(prices) / len(prices)
                    variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
                else:
                    variance = 0.0 # FIX: Start at 0 to avoid artificial spread jump on tick 0
                
                sigma = math.sqrt(variance)

                # 4. Dynamic Spread (Base + Volatility factor)
                dynamic_spread = math.ceil(ROOT_MIN_SPREAD + (0.5 * sigma))

                # 5. Dynamic Skew (Avellaneda-Stoikov: q * gamma * sigma^2)
                dynamic_skew = -int(round(position * ROOT_RISK_AVERSION * variance))

                # 6. Calculate Final Prices & Penny the Market
                buy_price  = min(math.floor(fair_value) - dynamic_spread + dynamic_skew, best_ask - 1)
                sell_price = max(math.ceil(fair_value) + dynamic_spread + dynamic_skew, best_bid + 1)

                # 7. CRITICAL SAFETY: Never cross your own spread
                if buy_price >= sell_price:
                    buy_price = sell_price - 1

                # 8. Send Orders
                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData