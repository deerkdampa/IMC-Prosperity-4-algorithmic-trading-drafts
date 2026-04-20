from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMITS = {"INTARIAN_PEPPER_ROOT": 80, "ASH_COATED_OSMIUM": 80}

class Trader:
    def run(self, state: TradingState):
        if state.traderData:
            trader_state = jsonpickle.decode(state.traderData)
        else:
            # Initialize EMA with a placeholder
            trader_state = {"osmium_ema": None}

        result = {}

        # --- 1. PEPPER ROOT (STAYING WITH THE SUCCESSFUL ACCUMULATION) ---
        product_root = "INTARIAN_PEPPER_ROOT"
        if product_root in state.order_depths:
            depth = state.order_depths[product_root]
            pos = state.position.get(product_root, 0)
            limit = POSITION_LIMITS[product_root]
            root_orders = []
            if pos < limit:
                asks = sorted(depth.sell_orders.items(), key=lambda x: x[0])
                current_pos = pos
                for price, vol in asks:
                    buy_amount = min(abs(vol), limit - current_pos)
                    if buy_amount > 0:
                        root_orders.append(Order(product_root, price, buy_amount))
                        current_pos += buy_amount
                    if current_pos >= limit: break
            result[product_root] = root_orders

        # --- 2. ASH_COATED_OSMIUM (EMA MARKET MAKING) ---
        product_osmium = "ASH_COATED_OSMIUM"
        if product_osmium in state.order_depths:
            depth = state.order_depths[product_osmium]
            pos = state.position.get(product_osmium, 0)
            limit = POSITION_LIMITS[product_osmium]
            
            bids = sorted(depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
            asks = sorted(depth.sell_orders.items(), key=lambda x: x[0])
            
            if bids and asks:
                mid = (bids[0][0] + asks[0][0]) / 2
                
                # --- EMA CALCULATION ---
                # Smoothing factor (alpha). 0.2 means 20% weight on new price.
                alpha = 0.2 
                if trader_state["osmium_ema"] is None:
                    trader_state["osmium_ema"] = mid
                else:
                    trader_state["osmium_ema"] = (alpha * mid) + ((1 - alpha) * trader_state["osmium_ema"])
                
                ema = trader_state["osmium_ema"]

                # --- PRICING ---
                # We place orders at a distance from the EMA.
                # If we are long, we shift the whole range down to encourage selling.
                # If we are short, we shift it up to encourage buying.
                
                # This 'Spread' (7.0) is your main knob. 
                # Larger = more patient/higher profit. Smaller = more frequent.
                base_offset = 7.0 
                inventory_lean = -(pos / limit) * 4.0
                
                buy_price = math.floor(ema - base_offset + inventory_lean)
                sell_price = math.ceil(ema + base_offset + inventory_lean)

                # --- PASSIVE CONSTRAINT ---
                # To ensure bots take us, we must be competitive.
                # We join the best bid/ask if our EMA math is too far away.
                buy_price = max(buy_price, bids[0][0])
                sell_price = min(sell_price, asks[0][0])

                # Safety: Don't cross the mid
                if buy_price >= asks[0][0]: buy_price = asks[0][0] - 1
                if sell_price <= bids[0][0]: sell_price = bids[0][0] + 1

                osmium_orders = []
                if (limit - pos) > 0:
                    osmium_orders.append(Order(product_osmium, int(buy_price), limit - pos))
                if (limit + pos) > 0:
                    osmium_orders.append(Order(product_osmium, int(sell_price), -(limit + pos)))
                
                result[product_osmium] = osmium_orders

        return result, 0, jsonpickle.encode(trader_state)