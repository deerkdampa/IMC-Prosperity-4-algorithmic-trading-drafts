import math
from datamodel import Order, Symbol, TradingState

class Trader:
    # Parabola coefficients generated from our local tool
    COEFF_A = 0.13697587
    COEFF_B = -0.33649674
    COEFF_C = 0.2136357
    
    # Fast Normal CDF approximation for engine limits
    def norm_cdf(self, x):
        # Abramowitz and Stegun approximation
        sign = 1 if x > 0 else -1
        x = abs(x) / math.sqrt(2.0)
        t = 1.0 / (1.0 + 0.3275911 * x)
        erf = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-x * x)
        return 0.5 * (1.0 + sign * erf)

    def bs_call_price(self, S, K, T, sigma, r=0.0):
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.norm_cdf(d1) - K * math.exp(-r * T) * self.norm_cdf(d2)
    
    def calculate_delta(self, S, K, T, sigma, r=0.0):
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        return self.norm_cdf(d1)

    def run(self, state: TradingState):
        result = {}
        
        # 1. Get Underlying Price
        underlying = "VELVETFRUIT_EXTRACT"
        if underlying not in state.listings or underlying not in state.order_depths:
            return result, 0, ""
            
        underlying_depth = state.order_depths[underlying]
        if not underlying_depth.sell_orders or not underlying_depth.buy_orders:
            return result, 0, ""
            
        best_ask_u = min(underlying_depth.sell_orders.keys())
        best_bid_u = max(underlying_depth.buy_orders.keys())
        S_mid = (best_ask_u + best_bid_u) / 2.0
        
        # Calculate time to expiry (Example: Assume 6 days left, scaled by timestamp)
        # T = 6.0 - (state.timestamp / 1000000.0) # Adjust based on precise round rules
        T = 6.0 # Simplified for illustration
        
        # 2. Iterate through safe strikes only
        safe_strikes = [5000, 5100, 5200, 5300, 5400, 5500]
        
        for strike in safe_strikes:
            symbol = f"VEV_{strike}"
            if symbol not in state.order_depths: continue
            
            # Calculate Fair IV and Fair Price
            moneyness = S_mid / strike
            fair_iv = (self.COEFF_A * (moneyness**2)) + (self.COEFF_B * moneyness) + self.COEFF_C
            fair_price = self.bs_call_price(S_mid, strike, T, fair_iv)
            
            orders = []
            order_depth = state.order_depths[symbol]
            margin = 1.5 # The edge we require to take a trade
            
            # Buy undervalued
            for ask_price, ask_vol in list(order_depth.sell_orders.items()):
                if ask_price < fair_price - margin:
                    # ask_vol is negative, so we use abs() or just pass the negative to represent taking it
                    qty = min(abs(ask_vol), 20) # Respect position limits
                    orders.append(Order(symbol, ask_price, qty))
                    
            # Sell overvalued
            for bid_price, bid_vol in list(order_depth.buy_orders.items()):
                if bid_price > fair_price + margin:
                    qty = min(bid_vol, 20) 
                    orders.append(Order(symbol, bid_price, -qty))
                    
            result[symbol] = orders
            
        # ==========================================
        # TODO REPLACEMENT: DYNAMIC DELTA HEDGING
        # ==========================================
        
        net_portfolio_delta = 0.0
        
        # 1. Calculate the total delta of our current options inventory
        for strike in safe_strikes:
            symbol = f"VEV_{strike}"
            
            # Check if we hold a position in this specific option
            if symbol in state.position and state.position[symbol] != 0:
                current_position = state.position[symbol]
                
                # We reuse the parabola to find the IV for this specific strike's delta
                moneyness = S_mid / strike
                fair_iv = (self.COEFF_A * (moneyness**2)) + (self.COEFF_B * moneyness) + self.COEFF_C
                
                # Calculate the exact delta for 1 contract
                contract_delta = self.calculate_delta(S_mid, strike, T, fair_iv)
                
                # Add to our net exposure
                net_portfolio_delta += (current_position * contract_delta)
        
        # 2. Determine required underlying position to neutralize the options delta
        # If options delta is +10, we want underlying position to be -10
        target_underlying_position = -round(net_portfolio_delta)
        
        # 3. Get current underlying position
        current_underlying_position = state.position.get(underlying, 0)
        
        # 4. Calculate how many shares of VELVETFRUIT_EXTRACT we need to trade
        underlying_qty_to_trade = target_underlying_position - current_underlying_position
        
        # 5. Execute the Hedge
        if underlying_qty_to_trade != 0:
            underlying_orders = []
            
            # Note: For strict hedging, we take liquidity (market order) to guarantee neutrality.
            # If underlying_qty_to_trade is positive, we BUY at the ask.
            # If underlying_qty_to_trade is negative, we SELL at the bid.
            
            if underlying_qty_to_trade > 0:
                underlying_orders.append(Order(underlying, best_ask_u, underlying_qty_to_trade))
            else:
                underlying_orders.append(Order(underlying, best_bid_u, underlying_qty_to_trade))
                
            result[underlying] = underlying_orders
            
        # ==========================================
        
        # ==========================================
        # HYDROGEL_PACK: OBI-Skewed Market Making
        # ==========================================
        hydrogel = "HYDROGEL_PACK"
        
        if hydrogel in state.order_depths:
            hydro_depth = state.order_depths[hydrogel]
            
            # Ensure we have a two-sided market to calculate metrics
            if len(hydro_depth.buy_orders) > 0 and len(hydro_depth.sell_orders) > 0:
                best_bid_h = max(hydro_depth.buy_orders.keys())
                best_bid_vol_h = hydro_depth.buy_orders[best_bid_h]
                
                best_ask_h = min(hydro_depth.sell_orders.keys())
                best_ask_vol_h = abs(hydro_depth.sell_orders[best_ask_h]) # Ensure positive volume for math
                
                mid_price_h = (best_bid_h + best_ask_h) / 2.0
                
                # 1. Calculate Order Book Imbalance [-1.0 to 1.0]
                total_vol = best_bid_vol_h + best_ask_vol_h
                obi = (best_bid_vol_h - best_ask_vol_h) / total_vol if total_vol > 0 else 0
                
                # 2. Calculate Skew
                # The max spread is ~16, so max shift should be around half of that (8)
                MAX_SKEW = 10.0
                skew = obi * MAX_SKEW
                
                # 3. Determine Skewed Fair Value
                skewed_fair = mid_price_h + skew
                
                # 4. Place Quotes (Market Making)
                # We want to capture the spread but lean with the momentum
                my_bid = int(round(skewed_fair - 4)) # Bid slightly below skewed fair
                my_ask = int(round(skewed_fair + 4)) # Ask slightly above skewed fair
                
                # Check position limits (Assuming limit is 80, adjust if different for Round 3)
                current_hydro_pos = state.position.get(hydrogel, 0)
                pos_limit = 80 
                
                bid_qty = pos_limit - current_hydro_pos
                ask_qty = -pos_limit - current_hydro_pos
                
                hydro_orders = []
                
                # Only place orders if we have room in our inventory
                if bid_qty > 0:
                    hydro_orders.append(Order(hydrogel, my_bid, bid_qty))
                if ask_qty < 0:
                    hydro_orders.append(Order(hydrogel, my_ask, ask_qty))
                    
                result[hydrogel] = hydro_orders
        # ==========================================
        
        return result, 0, "Solvenar Options Scalper Active"