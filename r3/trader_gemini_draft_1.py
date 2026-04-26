from datamodel import OrderDepth, TradingState, Order
import json
import math

class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300,
        "VEV_4500": 300,
        "VEV_5000": 300,
        "VEV_5100": 300,
        "VEV_5200": 300,
        "VEV_5300": 300,
        "VEV_5400": 300,
        "VEV_5500": 300,
        "VEV_6000": 300,
        "VEV_6500": 300,
    }

    STRIKES = {
        "VEV_4000": 4000,
        "VEV_4500": 4500,
        "VEV_5000": 5000,
        "VEV_5100": 5100,
        "VEV_5200": 5200,
        "VEV_5300": 5300,
        "VEV_5400": 5400,
        "VEV_5500": 5500,
        "VEV_6000": 6000,
        "VEV_6500": 6500,
    }

    VOLATILITY = 0.187

    def load_data(self, trader_data):
        d = {'ema': None}
        if trader_data:
            try:
                d = json.loads(trader_data)
            except Exception:
                pass
        return d

    def dump(self, d):
        return json.dumps(d, separators=(',', ':'))

    def get_tte(self, timestamp):
        # Linearly scale TTE from 5/365 to 4/365 across 1,000,000 ticks
        start_tte = 5.0 / 365.0
        end_tte = 4.0 / 365.0
        progress = timestamp / 1000000.0
        return max(1e-6, start_tte - progress * (start_tte - end_tte))

    def cdf(self, x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def get_bs_price(self, S, K, T, sigma):
        intrinsic = max(0.0, S - K)
        if S <= 0 or K <= 0 or T <= 1e-6 or sigma <= 1e-6:
            return intrinsic
        rt = math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * rt)
        d2 = d1 - sigma * rt
        return S * self.cdf(d1) - K * self.cdf(d2)

    def get_bs_delta(self, S, K, T, sigma):
        intrinsic_delta = 1.0 if S > K else 0.0
        if S <= 0 or K <= 0 or T <= 1e-6 or sigma <= 1e-6:
            return intrinsic_delta
        rt = math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * rt)
        return self.cdf(d1)

    def mid_price(self, depth):
        bids = depth.buy_orders
        asks = depth.sell_orders
        if not bids and not asks:
            return None
        if bids and asks:
            return (max(bids.keys()) + min(asks.keys())) / 2.0
        if bids:
            return float(max(bids.keys()))
        return float(min(asks.keys()))

    def get_room(self, product, pos, is_buy):
        if is_buy:
            return max(0, self.LIMITS[product] - pos)
        else:
            return max(0, self.LIMITS[product] + pos)

    def run(self, state: TradingState):
        result = {p: [] for p in self.LIMITS}
        conversions = 0
        data = self.load_data(state.traderData)

        # 1. Update Extract EMA
        extract_depth = state.order_depths.get('VELVETFRUIT_EXTRACT')
        extract_mid = self.mid_price(extract_depth) if extract_depth else None
        
        if extract_mid is not None:
            if data['ema'] is None:
                data['ema'] = extract_mid
            else:
                data['ema'] = 0.18 * extract_mid + 0.82 * data['ema']

        ema_price = data.get('ema', extract_mid)

        # 2. HYDROGEL_PACK Mean Reversion Strategy
        hydrogel_depth = state.order_depths.get('HYDROGEL_PACK')
        if hydrogel_depth:
            pos_hydro = state.position.get('HYDROGEL_PACK', 0)
            hydro_mean = 10000
            spread = 2
            inventory_factor = 0.05
            
            bpx = int(round(hydro_mean - spread - (inventory_factor * pos_hydro)))
            apx = int(round(hydro_mean + spread - (inventory_factor * pos_hydro)))
            
            bq = self.get_room('HYDROGEL_PACK', pos_hydro, is_buy=True)
            sq = self.get_room('HYDROGEL_PACK', pos_hydro, is_buy=False)
            
            if bq > 0:
                result['HYDROGEL_PACK'].append(Order('HYDROGEL_PACK', bpx, bq))
            if sq > 0:
                result['HYDROGEL_PACK'].append(Order('HYDROGEL_PACK', apx, -sq))

        # Ensure we have an underlying price before pricing options
        if ema_price is None:
            return result, conversions, self.dump(data)

        tte = self.get_tte(state.timestamp)

        # 3. Aggregate Delta Calculation
        total_delta = 0.0
        for sym, K in self.STRIKES.items():
            pos = state.position.get(sym, 0)
            if pos != 0:
                delta = self.get_bs_delta(ema_price, K, tte, self.VOLATILITY)
                total_delta += pos * delta

        # 4. "Treachery of Images" VEV Execution & Safety Clause
        extract_pos = state.position.get('VELVETFRUIT_EXTRACT', 0)
        safety_mode = abs(extract_pos) > 170

        for sym, K in self.STRIKES.items():
            depth = state.order_depths.get(sym)
            if not depth:
                continue

            bs_fair = self.get_bs_price(ema_price, K, tte, self.VOLATILITY)
            bs_delta = self.get_bs_delta(ema_price, K, tte, self.VOLATILITY)
            pos = state.position.get(sym, 0)
            orders = []

            # Buy undervalued options
            for ask_price, ask_vol in sorted(depth.sell_orders.items()):
                if ask_price < bs_fair - 2.0:
                    # Safety Mode Check: Buying increases Delta. 
                    # If total_delta > 0, buying makes abs(delta) larger -> Skip.
                    if safety_mode and total_delta > 0:
                        break
                        
                    qty = min(-ask_vol, self.get_room(sym, pos, is_buy=True))
                    if qty > 0:
                        orders.append(Order(sym, ask_price, qty))
                        pos += qty
                        total_delta += qty * bs_delta
                else:
                    break

            # Sell overvalued options
            for bid_price, bid_vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid_price > bs_fair + 2.0:
                    # Safety Mode Check: Selling decreases Delta.
                    # If total_delta < 0, selling makes abs(delta) larger -> Skip.
                    if safety_mode and total_delta < 0:
                        break
                        
                    qty = min(bid_vol, self.get_room(sym, pos, is_buy=False))
                    if qty > 0:
                        orders.append(Order(sym, bid_price, -qty))
                        pos -= qty
                        total_delta -= qty * bs_delta
                else:
                    break

            result[sym] = orders

        # 5. Extract Delta Hedging
        if extract_depth:
            target_extract = -total_delta
            hedge_required = int(round(target_extract)) - extract_pos
            orders = []
            
            # Using market orders to cross book with ~0.3 price bias equivalent
            if hedge_required > 0:
                buy_qty = min(hedge_required, self.get_room('VELVETFRUIT_EXTRACT', extract_pos, is_buy=True))
                # Take liquidity from the book
                for ask, vol in sorted(extract_depth.sell_orders.items()):
                    if buy_qty <= 0: break
                    take = min(-vol, buy_qty)
                    orders.append(Order('VELVETFRUIT_EXTRACT', ask, take))
                    buy_qty -= take
                # Residual market order using aggressive bias
                if buy_qty > 0:
                    orders.append(Order('VELVETFRUIT_EXTRACT', int(round(ema_price + 0.3)), buy_qty))
                    
            elif hedge_required < 0:
                sell_qty = min(abs(hedge_required), self.get_room('VELVETFRUIT_EXTRACT', extract_pos, is_buy=False))
                for bid, vol in sorted(extract_depth.buy_orders.items(), reverse=True):
                    if sell_qty <= 0: break
                    take = min(vol, sell_qty)
                    orders.append(Order('VELVETFRUIT_EXTRACT', bid, -take))
                    sell_qty -= take
                # Residual market order using aggressive bias
                if sell_qty > 0:
                    orders.append(Order('VELVETFRUIT_EXTRACT', int(round(ema_price - 0.3)), -sell_qty))
            
            result['VELVETFRUIT_EXTRACT'] = orders

            # Mandatory Logger Requirements
            print(f"Timestamp: {state.timestamp} | Extract_EMA: {ema_price:.4f} | Aggregate_Delta: {total_delta:.4f} | Hedge_Required: {hedge_required}")

        return result, conversions, self.dump(data)