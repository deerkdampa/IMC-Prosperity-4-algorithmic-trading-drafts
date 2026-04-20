from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMIT = 80

# --- OSMIUM PARAMETERS (Stable / Mean-Reverting) ---
OSMIUM_WINDOW = 40
OSMIUM_BASE_SPREAD = 3  # The "Goldilocks" spread (between your 4 and teammate's 2)
OSMIUM_SKEW_MULT = 0.05 

# --- ROOTS PARAMETERS (Dynamic / Trending) ---
ROOT_ALPHA = 0.2
ROOT_VOL_WINDOW = 20    # How many ticks to look back for volatility
ROOT_GAMMA = 0.005      # Risk Aversion factor for dynamic skew

class Trader:
    def run(self, state: TradingState):
        # 1. State Management (Initialize or Load)
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_history": [],
                "root_history": [],
                "root_ema": None
            }

        result = {}

        for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
            order_depth: OrderDepth = state.order_depths.get(product, None)
            if not order_depth or not order_depth.sell_orders or not order_depth.buy_orders:
                continue

            orders: List[Order] = []
            pos = state.position.get(product, 0)
            
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            mid_price = (best_bid + best_ask) / 2

            # =========================================================
            # ASH-COATED OSMIUM (The Patient Harvester)
            # =========================================================
            if product == "ASH_COATED_OSMIUM":
                # Use SMA (Simple Moving Average) to ignore sudden spikes
                trader_state["osmium_history"].append(mid_price)
                if len(trader_state["osmium_history"]) > OSMIUM_WINDOW:
                    trader_state["osmium_history"].pop(0)
                
                fair_value = sum(trader_state["osmium_history"]) / len(trader_state["osmium_history"])
                
                # Linear skew for a stable asset
                skew = -int(round(pos * OSMIUM_SKEW_MULT))
                
                my_bid = min(math.floor(fair_value) - OSMIUM_BASE_SPREAD + skew, best_ask - 1)
                my_ask = max(math.ceil(fair_value) + OSMIUM_BASE_SPREAD + skew, best_bid + 1)
                
                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_vol = POSITION_LIMIT - pos
                sell_vol = POSITION_LIMIT + pos

                if buy_vol > 0:
                    orders.append(Order(product, int(my_bid), buy_vol))
                if sell_vol > 0:
                    orders.append(Order(product, int(my_ask), -sell_vol))

            # =========================================================
            # INTARIAN PEPPER ROOT (The Dynamic Ladder)
            # =========================================================
            elif product == "INTARIAN_PEPPER_ROOT":
                # 1. Update EMA
                if trader_state["root_ema"] is None:
                    trader_state["root_ema"] = mid_price
                fair_value = (ROOT_ALPHA * mid_price) + ((1 - ROOT_ALPHA) * trader_state["root_ema"])
                trader_state["root_ema"] = fair_value

                # 2. Track Volatility (Variance)
                trader_state["root_history"].append(mid_price)
                if len(trader_state["root_history"]) > ROOT_VOL_WINDOW:
                    trader_state["root_history"].pop(0)
                
                prices = trader_state["root_history"]
                if len(prices) > 1:
                    mean_p = sum(prices) / len(prices)
                    variance = sum((p - mean_p)**2 for p in prices) / len(prices)
                else:
                    variance = 1.0
                
                sigma = math.sqrt(variance)

                # 3. Dynamic Math (Avellaneda-Stoikov Inspired)
                # Spread expands when volatility is high, shrinks when low
                dynamic_spread_tight = max(2, math.ceil(0.5 * sigma))
                dynamic_spread_wide  = dynamic_spread_tight + max(2, math.ceil(sigma))
                
                # Skew is multiplied by variance: panic sell during chaotic trends
                dynamic_skew = -int(round(pos * ROOT_GAMMA * variance))

                # 4. Ladder Level 1 (Aggressive)
                bid_l1 = min(math.floor(fair_value) - dynamic_spread_tight + dynamic_skew, best_ask - 1)
                ask_l1 = max(math.ceil(fair_value) + dynamic_spread_tight + dynamic_skew, best_bid + 1)
                
                # 5. Ladder Level 2 (Patient / Safety Net)
                bid_l2 = bid_l1 - (dynamic_spread_wide - dynamic_spread_tight)
                ask_l2 = ask_l1 + (dynamic_spread_wide - dynamic_spread_tight)

                # Safety Check
                if bid_l1 >= ask_l1: bid_l1 = ask_l1 - 1
                if bid_l2 >= bid_l1: bid_l2 = bid_l1 - 1

                # Calculate Volumes (Split 50/50 for laddering)
                buy_vol = POSITION_LIMIT - pos
                sell_vol = POSITION_LIMIT + pos
                half_buy = buy_vol // 2
                half_sell = sell_vol // 2

                # Send Orders
                if half_buy > 0:
                    orders.append(Order(product, int(bid_l1), half_buy))
                    orders.append(Order(product, int(bid_l2), buy_vol - half_buy))
                elif buy_vol > 0:
                    orders.append(Order(product, int(bid_l1), buy_vol))

                if half_sell > 0:
                    orders.append(Order(product, int(ask_l1), -half_sell))
                    orders.append(Order(product, int(ask_l2), -(sell_vol - half_sell)))
                elif sell_vol > 0:
                    orders.append(Order(product, int(ask_l1), -sell_vol))

            result[product] = orders

        # Save state
        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData