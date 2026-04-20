from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

# --- STRATEGY PARAMETERS ---
POSITION_LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80,
}

# OSMIUM: Mean-Reverting (Stable)
OSMIUM_WINDOW       = 20     # Short window to catch local averages
OSMIUM_BASE_SPREAD  = 2      # Very tight spread for maximum fills
OSMIUM_SKEW_FACTOR  = 0.05   # Low risk aversion; willing to hold inventory

# ROOTS: Trending (Volatile)
ROOT_EMA_ALPHA      = 0.25   # Fast EMA to track the climbing/falling price
ROOT_BASE_SPREAD    = 3      # Slightly wider to account for sudden spikes
ROOT_SKEW_FACTOR    = 0.08   # Higher skew to pull back from the trend if inventory gets heavy

class Trader:

    def run(self, state: TradingState):
        # Load memory (traderData) across timestamps
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],
                "root_ema": None
            }

        result = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            # Skip if book is empty
            if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
                result[product] = orders
                continue

            # Get current state
            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 80)
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            mid_price = (best_ask + best_bid) / 2

            # -------------------------------------------------------
            # ASH-COATED OSMIUM LOGIC (The Yo-Yo)
            # -------------------------------------------------------
            if product == "ASH_COATED_OSMIUM":
                trader_state["osmium_prices"].append(mid_price)
                prices = trader_state["osmium_prices"]

                # Calculate Fair Value (SMA)
                window_size = min(len(prices), OSMIUM_WINDOW)
                fair_value = sum(prices[-window_size:]) / window_size
                
                # Dynamic Spread & Skew
                book_spread = best_ask - best_bid
                spread = max(OSMIUM_BASE_SPREAD, math.floor(book_spread / 2))
                skew = -int(round(position * OSMIUM_SKEW_FACTOR))

                # Calculate Prices (Pennying the book safely)
                buy_price  = min(math.floor(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(math.ceil(fair_value) + spread + skew, best_bid + 1)

                # Send Orders
                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            # -------------------------------------------------------
            # INTARIAN PEPPER ROOT LOGIC (The Hiker)
            # -------------------------------------------------------
            elif product == "INTARIAN_PEPPER_ROOT":
                # Initialize EMA on first tick
                if trader_state.get("root_ema") is None:
                    trader_state["root_ema"] = mid_price

                # Calculate Fair Value (EMA)
                current_ema = (ROOT_EMA_ALPHA * mid_price) + ((1 - ROOT_EMA_ALPHA) * trader_state["root_ema"])
                trader_state["root_ema"] = current_ema
                fair_value = current_ema

                # Dynamic Spread & Skew
                book_spread = best_ask - best_bid
                spread = max(ROOT_BASE_SPREAD, math.floor(book_spread / 2))
                skew = -int(round(position * ROOT_SKEW_FACTOR))

                # Calculate Prices (Pennying the book safely)
                buy_price  = min(math.floor(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(math.ceil(fair_value) + spread + skew, best_bid + 1)

                # Prevent crossing our own orders
                if buy_price >= sell_price:
                    buy_price = sell_price - 1

                # Send Orders
                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            result[product] = orders

        # Save memory for next timestamp
        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData