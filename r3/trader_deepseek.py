from datamodel import OrderDepth, TradingState, Order
import json
import math
from typing import Dict, List, Optional, Tuple

class Trader:
    # Position limits
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }
    
    # Strike prices for options
    STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
        "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
        "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000,
        "VEV_6500": 6500
    }
    
    # Empirical deltas for hedging (calculated from historical data)
    EMPIRICAL_DELTAS = {
        "VEV_4000": 0.745, "VEV_4500": 0.662, "VEV_5000": 0.654,
        "VEV_5100": 0.577, "VEV_5200": 0.437, "VEV_5300": 0.273,
        "VEV_5400": 0.129, "VEV_5500": 0.055, "VEV_6000": 0.0,
        "VEV_6500": 0.0
    }
    
    # Time to expiry (5 days remaining in Round 3)
    TTE = 5.0 / 365.0  # Annualized
    RISK_FREE_RATE = 0.0  # Assume zero risk-free rate
    
    def __init__(self):
        self.data = self.load_data(None)
        
    def load_data(self, trader_data: str) -> Dict:
        """Load trader state data"""
        d = {
            'extract_mids': [], 
            'hydro_mids': [], 
            'voucher_pos_ema': {},
            'last_ts': -1,
            'volatility_surface': {},
            'hedge_ratio': 0.0
        }
        if trader_data:
            try:
                x = json.loads(trader_data)
                d.update(x)
            except Exception:
                pass
        return d
    
    def dump(self, d: Dict) -> str:
        """Serialize trader state"""
        return json.dumps(d, separators=(',', ':'))
    
    def ba(self, depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        """Get best bid and ask"""
        bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bid, ask
    
    def mid(self, depth: OrderDepth) -> Optional[float]:
        """Calculate mid price"""
        bid, ask = self.ba(depth)
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return float(bid if bid is not None else ask) if (bid or ask) else None
    
    def normal_cdf(self, x: float) -> float:
        """Standard normal cumulative distribution function"""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    
    def normal_pdf(self, x: float) -> float:
        """Standard normal probability density function"""
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    
    def black_scholes_price(self, S: float, K: float, T: float, sigma: float, 
                           is_call: bool = True) -> float:
        """
        Black-Scholes option pricing
        S: spot price
        K: strike price
        T: time to expiry (annualized)
        sigma: implied volatility
        is_call: True for call, False for put
        """
        if T <= 0 or sigma <= 1e-6:
            return max(0.0, S - K) if is_call else max(0.0, K - S)
        
        d1 = (math.log(S / K) + (self.RISK_FREE_RATE + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        if is_call:
            return S * self.normal_cdf(d1) - K * math.exp(-self.RISK_FREE_RATE * T) * self.normal_cdf(d2)
        else:
            return K * math.exp(-self.RISK_FREE_RATE * T) * self.normal_cdf(-d2) - S * self.normal_cdf(-d1)
    
    def black_scholes_delta(self, S: float, K: float, T: float, sigma: float, 
                           is_call: bool = True) -> float:
        """Calculate Black-Scholes delta"""
        if T <= 0 or sigma <= 1e-6:
            return 1.0 if (is_call and S > K) else 0.0
        
        d1 = (math.log(S / K) + (self.RISK_FREE_RATE + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        return self.normal_cdf(d1) if is_call else self.normal_cdf(d1) - 1
    
    def implied_volatility(self, market_price: float, S: float, K: float, T: float,
                          is_call: bool = True) -> float:
        """
        Calculate implied volatility using Newton-Raphson method
        """
        intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
        if market_price <= intrinsic + 1e-6:
            return 0.0001  # Minimum volatility
        
        sigma = 0.3  # Initial guess
        for _ in range(50):  # Max iterations
            price = self.black_scholes_price(S, K, T, sigma, is_call)
            vega = self.black_scholes_vega(S, K, T, sigma)
            
            if abs(vega) < 1e-10:
                break
                
            diff = price - market_price
            if abs(diff) < 1e-8:
                return sigma
                
            sigma = sigma - diff / vega
            
            # Bounds checking
            sigma = max(0.001, min(5.0, sigma))
        
        return sigma
    
    def black_scholes_vega(self, S: float, K: float, T: float, sigma: float) -> float:
        """Calculate Black-Scholes vega"""
        if T <= 0 or sigma <= 1e-6:
            return 0.0
        
        d1 = (math.log(S / K) + (self.RISK_FREE_RATE + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        return S * math.sqrt(T) * self.normal_pdf(d1)
    
    def get_fair_value(self, sym: str, S: float, base_iv: float, 
                       individual_iv: Optional[float] = None) -> float:
        """
        Calculate fair value for options using Black-Scholes
        """
        if sym not in self.STRIKES:
            return 0.0
            
        K = self.STRIKES[sym]
        T = self.TTE
        
        # Use smoothed IV for fair value calculation
        iv = individual_iv if individual_iv else base_iv
        
        # For deep ITM options, use a blend of intrinsic and BS
        intrinsic = max(0.0, S - K)
        if S - K > 700:
            # Deep ITM: mostly intrinsic value
            return 0.98 * intrinsic + 0.02 * self.black_scholes_price(S, K, T, iv)
        elif S - K > 250:
            # ITM: blend
            bs_price = self.black_scholes_price(S, K, T, iv)
            return 0.92 * intrinsic + 0.08 * bs_price
        else:
            # OTM/ATM: pure BS
            return self.black_scholes_price(S, K, T, iv)
    
    def calculate_delta_exposure(self, positions: Dict[str, int], extract_mid: float) -> float:
        """
        Calculate total delta exposure from options positions
        """
        total_delta = 0.0
        for sym, pos in positions.items():
            if sym in self.EMPIRICAL_DELTAS:
                total_delta += pos * self.EMPIRICAL_DELTAS[sym]
        return total_delta
    
    def calculate_hedge_size(self, delta_exposure: float, extract_position: int) -> int:
        """
        Calculate how much extract to buy/sell to hedge delta
        """
        target_hedge = -delta_exposure
        adjustment = target_hedge - extract_position
        
        # Cap hedge adjustments to prevent over-trading
        max_adjustment = 50  # Maximum single-round adjustment
        adjustment = max(-max_adjustment, min(max_adjustment, adjustment))
        
        return int(round(adjustment))
    
    def build_volatility_surface(self, live_ivs: Dict[str, float], extract_mid: float) -> Dict[str, float]:
        """
        Build and smooth volatility surface
        """
        # Separate liquid and illiquid strikes
        liquid_strikes = ['VEV_5000', 'VEV_5100', 'VEV_5200', 'VEV_5300']
        core_ivs = [live_ivs[s] for s in liquid_strikes if s in live_ivs]
        
        if core_ivs:
            base_iv = sum(core_ivs) / len(core_ivs)
        else:
            base_iv = 0.22  # Default IV
            
        # Smooth the surface
        smoothed = {}
        for sym in self.STRIKES:
            if sym in live_ivs:
                # Weight individual IV with base IV for smoothness
                smoothed[sym] = 0.7 * live_ivs[sym] + 0.3 * base_iv
            else:
                smoothed[sym] = base_iv
                
        return smoothed
    
    def identify_mispriced_options(self, market_prices: Dict[str, float], 
                                  fair_prices: Dict[str, float]) -> Dict[str, float]:
        """
        Identify options where market price deviates significantly from fair value
        """
        mispricing = {}
        for sym in self.STRIKES:
            if sym in market_prices and sym in fair_prices:
                deviation = fair_prices[sym] - market_prices[sym]
                # Normalize by fair value for percentage deviation
                if fair_prices[sym] > 0.5:
                    deviation_pct = deviation / fair_prices[sym]
                    if abs(deviation_pct) > 0.05:  # >5% mispricing
                        mispricing[sym] = deviation
                        
        return mispricing
    
    def market_make_hydrogel(self, state: TradingState, 
                            fair_price: float) -> List[Order]:
        """
        Market-making strategy for HYDROGEL_PACK
        """
        ord_depth = state.order_depths.get('HYDROGEL_PACK')
        if not ord_depth:
            return []
            
        pos = state.position.get('HYDROGEL_PACK', 0)
        orders = []
        
        # Calculate dynamic spread based on position
        position_skew = pos / self.LIMITS['HYDROGEL_PACK']
        
        # Base spread with position adjustment
        base_spread = 12
        skew_adjustment = int(base_spread * position_skew * 2)
        
        bid_price = int(fair_price - base_spread - skew_adjustment)
        ask_price = int(fair_price + base_spread - skew_adjustment)
        
        # Take aggressive positions when favorable
        for ask in sorted(ord_depth.sell_orders.keys()):
            if ask < fair_price - 3:  # Significantly below fair
                qty = min(-ord_depth.sell_orders[ask], 
                         self.LIMITS['HYDROGEL_PACK'] - pos)
                if qty > 0:
                    orders.append(Order('HYDROGEL_PACK', ask, qty))
                    pos += qty
        
        for bid in sorted(ord_depth.buy_orders.keys(), reverse=True):
            if bid > fair_price + 3:  # Significantly above fair
                qty = min(ord_depth.buy_orders[bid],
                         self.LIMITS['HYDROGEL_PACK'] + pos)
                if qty > 0:
                    orders.append(Order('HYDROGEL_PACK', bid, -qty))
                    pos -= qty
        
        # Place market-making orders
        buy_qty = min(15, self.LIMITS['HYDROGEL_PACK'] - pos)
        sell_qty = min(15, self.LIMITS['HYDROGEL_PACK'] + pos)
        
        if buy_qty > 0:
            orders.append(Order('HYDROGEL_PACK', bid_price, buy_qty))
        if sell_qty > 0:
            orders.append(Order('HYDROGEL_PACK', ask_price, -sell_qty))
            
        return orders
    
    def trade_options_strategy(self, state: TradingState, 
                               extract_mid: float) -> Dict[str, List[Order]]:
        """
        Execute options trading strategy with volatility sniping and delta hedging
        """
        result = {}
        live_ivs = {}
        market_prices = {}
        
        # Calculate IVs and collect market prices
        for sym, strike in self.STRIKES.items():
            ord_depth = state.order_depths.get(sym)
            if ord_depth:
                mid_price = self.mid(ord_depth)
                if mid_price and mid_price > 0.5:
                    live_ivs[sym] = self.implied_volatility(mid_price, extract_mid, strike, self.TTE)
                    market_prices[sym] = mid_price
        
        # Build smoothed volatility surface
        vol_surface = self.build_volatility_surface(live_ivs, extract_mid)
        self.data['volatility_surface'] = vol_surface
        
        # Calculate fair prices
        fair_prices = {}
        base_iv = sum(vol_surface.values()) / len(vol_surface) if vol_surface else 0.22
        for sym in self.STRIKES:
            individual_iv = vol_surface.get(sym, base_iv)
            fair_prices[sym] = self.get_fair_value(sym, extract_mid, base_iv, individual_iv)
        
        # Identify mispriced options
        mispricing = self.identify_mispriced_options(market_prices, fair_prices)
        
        # Trade each option
        for sym in self.STRIKES:
            ord_depth = state.order_depths.get(sym)
            if not ord_depth:
                result[sym] = []
                continue
                
            pos = state.position.get(sym, 0)
            orders = []
            fair = fair_prices.get(sym, 0)
            
            # Determine if option is over/under valued
            is_mispriced = sym in mispricing
            deviation = mispricing.get(sym, 0)
            
            # Aggressive trading for significant mispricing
            if is_mispriced and abs(deviation) > 1.0:
                # Determine position sizing based on mispricing magnitude
                position_size = min(20, int(abs(deviation) * 3))
                position_size = max(5, position_size)
                
                if deviation > 0:  # Undervalued - buy
                    for ask in sorted(ord_depth.sell_orders.keys()):
                        if ask < fair - 0.5:  # Still below fair value
                            qty = min(-ord_depth.sell_orders[ask],
                                     self.LIMITS[sym] - pos,
                                     position_size)
                            if qty > 0:
                                orders.append(Order(sym, ask, qty))
                                pos += qty
                                position_size -= qty
                                if position_size <= 0:
                                    break
                
                elif deviation < 0:  # Overvalued - sell
                    for bid in sorted(ord_depth.buy_orders.keys(), reverse=True):
                        if bid > fair + 0.5:  # Still above fair value
                            qty = min(ord_depth.buy_orders[bid],
                                     self.LIMITS[sym] + pos,
                                     position_size)
                            if qty > 0:
                                orders.append(Order(sym, bid, -qty))
                                pos -= qty
                                position_size -= qty
                                if position_size <= 0:
                                    break
            
            # Market-making for ATM/near-ATM options
            if extract_mid - self.STRIKES[sym] < 300 and abs(pos) < 25:
                spread = 2
                bid_price = int(fair - spread)
                ask_price = int(fair + spread)
                
                buy_qty = min(3, self.LIMITS[sym] - pos)
                sell_qty = min(3, self.LIMITS[sym] + pos)
                
                if buy_qty > 0:
                    orders.append(Order(sym, bid_price, buy_qty))
                if sell_qty > 0:
                    orders.append(Order(sym, ask_price, -sell_qty))
            
            result[sym] = orders
            
        return result
    
    def delta_hedge_extract(self, state: TradingState, extract_mid: float,
                           options_positions: Dict[str, int]) -> List[Order]:
        """
        Delta hedge the options portfolio using VELVETFRUIT_EXTRACT
        """
        orders = []
        extract_pos = state.position.get('VELVETFRUIT_EXTRACT', 0)
        ord_depth = state.order_depths.get('VELVETFRUIT_EXTRACT')
        
        if not ord_depth or not extract_mid:
            return orders
        
        # Calculate total delta exposure
        delta_exposure = self.calculate_delta_exposure(options_positions, extract_mid)
        
        # Calculate required hedge
        hedge_size = self.calculate_hedge_size(delta_exposure, extract_pos)
        
        if hedge_size > 0:  # Need to buy extract to hedge
            for ask in sorted(ord_depth.sell_orders.keys()):
                qty = min(-ord_depth.sell_orders[ask],
                         self.LIMITS['VELVETFRUIT_EXTRACT'] - extract_pos,
                         hedge_size)
                if qty > 0:
                    orders.append(Order('VELVETFRUIT_EXTRACT', ask, qty))
                    extract_pos += qty
                    hedge_size -= qty
                    if hedge_size <= 0:
                        break
        
        elif hedge_size < 0:  # Need to sell extract to hedge
            hedge_size = abs(hedge_size)
            for bid in sorted(ord_depth.buy_orders.keys(), reverse=True):
                qty = min(ord_depth.buy_orders[bid],
                         self.LIMITS['VELVETFRUIT_EXTRACT'] + extract_pos,
                         hedge_size)
                if qty > 0:
                    orders.append(Order('VELVETFRUIT_EXTRACT', bid, -qty))
                    extract_pos -= qty
                    hedge_size -= qty
                    if hedge_size <= 0:
                        break
        
        # Additional market-making for residual position
        if abs(extract_pos) > 50:
            spread = 5
            fair = extract_mid
            
            bid_price = int(fair - spread)
            ask_price = int(fair + spread)
            
            if extract_pos > 50:  # Long, want to sell
                qty = min(10, self.LIMITS['VELVETFRUIT_EXTRACT'] + extract_pos)
                if qty > 0:
                    orders.append(Order('VELVETFRUIT_EXTRACT', ask_price, -qty))
            elif extract_pos < -50:  # Short, want to buy
                qty = min(10, self.LIMITS['VELVETFRUIT_EXTRACT'] - extract_pos)
                if qty > 0:
                    orders.append(Order('VELVETFRUIT_EXTRACT', bid_price, qty))
        
        return orders
    
    def run(self, state: TradingState):
        """Main trading logic"""
        # Load state data
        if state.traderData:
            self.data = self.load_data(state.traderData)
        
        result = {}
        conversions = 0
        
        # Get market data
        extract_depth = state.order_depths.get('VELVETFRUIT_EXTRACT')
        hydrogel_depth = state.order_depths.get('HYDROGEL_PACK')
        
        extract_mid = self.mid(extract_depth) if extract_depth else None
        hydrogel_mid = self.mid(hydrogel_depth) if hydrogel_depth else None
        
        # Update price history
        if state.timestamp != self.data.get('last_ts', -1):
            if extract_mid:
                self.data['extract_mids'].append(extract_mid)
                self.data['extract_mids'] = self.data['extract_mids'][-100:]
            if hydrogel_mid:
                self.data['hydro_mids'].append(hydrogel_mid)
                self.data['hydro_mids'] = self.data['hydro_mids'][-100:]
            
            # Update position EMAs for risk management
            for sym in self.STRIKES:
                cur = state.position.get(sym, 0)
                prev = self.data.get('voucher_pos_ema', {}).get(sym, 0.0)
                if 'voucher_pos_ema' not in self.data:
                    self.data['voucher_pos_ema'] = {}
                self.data['voucher_pos_ema'][sym] = 0.2 * cur + 0.8 * prev
            
            self.data['last_ts'] = state.timestamp
        
        # Trade HYDROGEL_PACK
        if hydrogel_depth and hydrogel_mid:
            # Calculate fair price with trend
            fair_hydrogel = 10000.0
            if len(self.data['hydro_mids']) >= 20:
                sma_20 = sum(self.data['hydro_mids'][-20:]) / 20
                fair_hydrogel = 0.85 * 10000.0 + 0.15 * sma_20
            
            result['HYDROGEL_PACK'] = self.market_make_hydrogel(state, fair_hydrogel)
        
        # Trade options series
        if extract_mid and extract_mid > 0:
            # Trade options
            options_results = self.trade_options_strategy(state, extract_mid)
            result.update(options_results)
            
            # Collect all options positions for delta hedging
            options_positions = {}
            for sym in self.STRIKES:
                options_positions[sym] = state.position.get(sym, 0)
            
            # Execute delta hedge using extract
            extract_orders = self.delta_hedge_extract(state, extract_mid, options_positions)
            
            # Add extract market-making if no hedge orders
            if not extract_orders and extract_depth:
                extract_pos = state.position.get('VELVETFRUIT_EXTRACT', 0)
                if abs(extract_pos) < 30:
                    spread = 4
                    fair = extract_mid
                    
                    bid_price = int(fair - spread)
                    ask_price = int(fair + spread)
                    
                    buy_qty = min(5, self.LIMITS['VELVETFRUIT_EXTRACT'] - extract_pos)
                    sell_qty = min(5, self.LIMITS['VELVETFRUIT_EXTRACT'] + extract_pos)
                    
                    if buy_qty > 0:
                        extract_orders.append(Order('VELVETFRUIT_EXTRACT', bid_price, buy_qty))
                    if sell_qty > 0:
                        extract_orders.append(Order('VELVETFRUIT_EXTRACT', ask_price, -sell_qty))
            
            result['VELVETFRUIT_EXTRACT'] = extract_orders
        
        return result, conversions, self.dump(self.data)