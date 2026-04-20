from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMIT = 80

# ROOTS: Trending. We will use a faster EMA and multi-level spreads.
ROOT_ALPHA = 0.25
ROOT_SPREAD_TIGHT = 2
ROOT_SPREAD_WIDE = 5

# OSMIUM: Mean-reverting. We will use a 40-tick SMA (Simple Moving Average) and wide spreads.
OSMIUM_WINDOW = 40
OSMIUM_SPREAD = 4

class Trader:
    def run(self, state: TradingState):
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "emas": {},
                "osmium_history": [] # Track history for SMA
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

            # ---------------------------------------------------------
            # OSMIUM LOGIC (Patient, Mean-Reverting)
            # ---------------------------------------------------------
            if product == "ASH_COATED_OSMIUM":
                trader_state["osmium_history"].append(mid_price)
                if len(trader_state["osmium_history"]) > OSMIUM_WINDOW:
                    trader_state["osmium_history"].pop(0)
                
                # Use SMA for stability, avoiding the lag of an EMA
                fair_value = sum(trader_state["osmium_history"]) / len(trader_state["osmium_history"])
                
                skew = -int(round(pos * 0.1))
                
                my_bid = min(math.floor(fair_value) - OSMIUM_SPREAD + skew, best_ask - 1)
                my_ask = max(math.ceil(fair_value) + OSMIUM_SPREAD + skew, best_bid + 1)
                
                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                if pos < POSITION_LIMIT:
                    orders.append(Order(product, int(my_bid), POSITION_LIMIT - pos))
                if pos > -POSITION_LIMIT:
                    orders.append(Order(product, int(my_ask), -POSITION_LIMIT - pos))

            # ---------------------------------------------------------
            # ROOTS LOGIC (Aggressive Laddering)
            # ---------------------------------------------------------
            elif product == "INTARIAN_PEPPER_ROOT":
                if product in trader_state["emas"]:
                    fair_value = trader_state["emas"][product] * (1 - ROOT_ALPHA) + mid_price * ROOT_ALPHA
                else:
                    fair_value = mid_price
                trader_state["emas"][product] = fair_value

                skew = -int(round(pos * 0.1))

                # Level 1: Tight Spread (High Frequency)
                bid_l1 = min(math.floor(fair_value) - ROOT_SPREAD_TIGHT + skew, best_ask - 1)
                ask_l1 = max(math.ceil(fair_value) + ROOT_SPREAD_TIGHT + skew, best_bid + 1)
                
                # Level 2: Wide Spread (Safety / High Margin)
                bid_l2 = bid_l1 - (ROOT_SPREAD_WIDE - ROOT_SPREAD_TIGHT)
                ask_l2 = ask_l1 + (ROOT_SPREAD_WIDE - ROOT_SPREAD_TIGHT)

                # Safety Check
                if bid_l1 >= ask_l1: bid_l1 = ask_l1 - 1
                if bid_l2 >= bid_l1: bid_l2 = bid_l1 - 1

                # Calculate Volumes (Split 50/50)
                buy_vol = POSITION_LIMIT - pos
                sell_vol = POSITION_LIMIT + pos
                
                half_buy = buy_vol // 2
                half_sell = sell_vol // 2

                # Place Laddered Orders
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

        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData