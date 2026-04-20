from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

# --- STRATEGY PARAMETERS ---
POSITION_LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80,
}

# OSMIUM (Mean-Reverting)
OSMIUM_WINDOW = 20
OSMIUM_BASE_SPREAD = 2
OSMIUM_SKEW_FACTOR = 0.05

# ROOTS (Dynamic Trending)
ROOT_EMA_ALPHA = 0.25
ROOT_MIN_SPREAD = 2.0        # The absolute tightest we will quote
ROOT_RISK_AVERSION = 0.01    # Gamma (γ) from Avellaneda-Stoikov
ROOT_VOL_WINDOW = 20         # Ticks to look back for volatility

class Trader:

    def run(self, state: TradingState):
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],
                "root_ema": None,
                "root_prices": [] # NEW: We need history to calculate volatility
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
            # ASH-COATED OSMIUM LOGIC (Unchanged)
            # -------------------------------------------------------
            if product == "ASH_COATED_OSMIUM":
                trader_state["osmium_prices"].append(mid_price)
                prices = trader_state["osmium_prices"]
                window_size = min(len(prices), OSMIUM_WINDOW)
                fair_value = sum(prices[-window_size:]) / window_size
                
                spread = max(OSMIUM_BASE_SPREAD, math.floor((best_ask - best_bid) / 2))
                skew = -int(round(position * OSMIUM_SKEW_FACTOR))

                buy_price  = min(math.floor(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(math.ceil(fair_value) + spread + skew, best_bid + 1)

                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            # -------------------------------------------------------
            # INTARIAN PEPPER ROOT LOGIC (Dynamic Math Applied)
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
                    trader_state["root_prices"].pop(0) # Keep array small
                
                prices = trader_state["root_prices"]
                
                # 3. Calculate Volatility (Variance = Sigma^2)
                if len(prices) > 1:
                    mean_price = sum(prices) / len(prices)
                    variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
                else:
                    variance = 1.0 # Default fallback
                
                sigma = math.sqrt(variance)

                # 4. Dynamic Spread (Base + Volatility factor)
                # When market goes crazy, we widen the spread automatically.
                dynamic_spread = math.ceil(ROOT_MIN_SPREAD + (0.5 * sigma))

                # 5. Dynamic Skew (Avellaneda-Stoikov: q * gamma * sigma^2)
                # If we have high inventory AND high volatility, we panic-sell.
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