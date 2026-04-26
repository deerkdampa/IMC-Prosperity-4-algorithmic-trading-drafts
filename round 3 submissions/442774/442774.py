from datamodel import OrderDepth, TradingState, Order
import json
import math

class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 150, "VEV_4500": 150, "VEV_5000": 150,
        "VEV_5100": 150, "VEV_5200": 150, "VEV_5400": 150,
        "VEV_5500": 150, "VEV_6000": 150, "VEV_6500": 150
    }

    STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
        "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5400": 5400,
        "VEV_5500": 5500, "VEV_6000": 6000, "VEV_6500": 6500
    }

    DELTA_LIMIT = 180.0
    MIN_EDGE = 1.5
    HEDGE_THRESHOLD = 5.0

    # --- FIX: constants for VEV standalone block ---
    VEV_HALFSPREAD = 6          # Fixed; do NOT use dynamic book spread (see notes)
    VEV_MOMENTUM_CAP = 4        # Max ticks of momentum lean in either direction
    VEV_POSITION_HARD_CAP = 120 # Hard cap: stop adding if |pos| exceeds this
    VEV_WARMUP_TICKS = 50       # Ticks before activating trend signal

    def load_data(self, trader_data):
        d = {
            'iv_ema': 0.29,
            'hydro_hist': [],
            'last_ts': -1,
            'vev_ema': 5255.0,
            'vev_ema_slow': 5255.0,
            'tick_count': 0,          # NEW: warmup counter for trend signal
        }
        if trader_data:
            try:
                x = json.loads(trader_data)
                d.update(x)
            except:
                pass
        # Defensive defaults for any missing keys
        for key in ('hydro_hist', 'last_ts', 'tick_count'):
            if key not in d:
                d[key] = [] if key == 'hydro_hist' else 0 if key == 'tick_count' else -1
        return d

    def dump_data(self, d):
        return json.dumps(d, separators=(',', ':'))

    # --- OPTIONS MATH ---
    def cdf(self, x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def get_bs_price(self, S, K, T, sigma):
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.cdf(d1) - K * self.cdf(d2)

    def get_bs_delta(self, S, K, T, sigma):
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        return self.cdf(d1)

    def mid_price(self, depth: OrderDepth):
        bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return bid if bid is not None else ask

    def solve_iv(self, S, K, T, market_price):
        low, high = 0.10, 0.50
        for _ in range(10):
            mid = (low + high) / 2.0
            if self.get_bs_price(S, K, T, mid) < market_price:
                low = mid
            else:
                high = mid
        return (low + high) / 2.0

    # --- HELPER FUNCTIONS ---
    def best_bid_ask(self, depth):
        bid = max(depth.buy_orders) if depth.buy_orders else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        return bid, ask

    def room_buy(self, product, pos):
        return max(0, self.LIMITS[product] - pos)

    def room_sell(self, product, pos):
        return max(0, self.LIMITS[product] + pos)

    def take_buy(self, product, depth, max_price, pos, qty_cap, orders):
        if qty_cap <= 0:
            return pos, 0
        done = 0
        for ask in sorted(depth.sell_orders):
            if ask > max_price:
                break
            avail = -depth.sell_orders[ask]
            qty = min(avail, self.room_buy(product, pos), qty_cap - done)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                pos += qty
                done += qty
            if done >= qty_cap:
                break
        return pos, done

    def take_sell(self, product, depth, min_price, pos, qty_cap, orders):
        if qty_cap <= 0:
            return pos, 0
        done = 0
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < min_price:
                break
            avail = depth.buy_orders[bid]
            qty = min(avail, self.room_sell(product, pos), qty_cap - done)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                pos -= qty
                done += qty
            if done >= qty_cap:
                break
        return pos, done

    def quote(self, product, depth, fair, pos, halfspread, size, orders):
        if size <= 0:
            return
        bid, ask = self.best_bid_ask(depth)
        skew = int(round(8.0 * pos / self.LIMITS[product]))
        bpx = int(math.floor(fair - halfspread - skew))
        apx = int(math.ceil(fair + halfspread - skew))
        if bid is not None:
            bpx = min(bpx, bid + 1)
        if ask is not None:
            apx = max(apx, ask - 1)
        if apx <= bpx:
            apx = bpx + 1
        bq = min(size, self.room_buy(product, pos))
        sq = min(size, self.room_sell(product, pos))
        if bq > 0:
            orders.append(Order(product, bpx, bq))
        if sq > 0:
            orders.append(Order(product, apx, -sq))

    def run(self, state: TradingState):
        result = {}
        data = self.load_data(state.traderData)

        progress = min(1.0, state.timestamp / 1000000.0)
        current_tte = (5.0 / 365.0) - progress * (1.0 / 365.0)

        ex_depth = state.order_depths.get('VELVETFRUIT_EXTRACT')
        hyd = state.order_depths.get('HYDROGEL_PACK')

        ex_mid = self.mid_price(ex_depth) if ex_depth else None
        hy_mid = self.mid_price(hyd) if hyd else None

        # --- STATE TRACKING ---
        if state.timestamp != data['last_ts']:
            if hy_mid is not None:
                data['hydro_hist'].append(hy_mid)
                data['hydro_hist'] = data['hydro_hist'][-120:]
            data['tick_count'] = data.get('tick_count', 0) + 1
            data['last_ts'] = state.timestamp

        # =================================================================
        # HYDROGEL_PACK
        # =================================================================
        if hyd:
            orders = []
            pos = state.position.get('HYDROGEL_PACK', 0)
            fair = 9991.0
            window = 10
            if len(data['hydro_hist']) >= window:
                recent = sum(data['hydro_hist'][-window:]) / window
                fair = 9991.0 * 0.1+ 0.9 * recent
            pos, _ = self.take_buy('HYDROGEL_PACK', hyd, fair - 2, pos, 20, orders)
            pos, _ = self.take_sell('HYDROGEL_PACK', hyd, fair + 2, pos, 20, orders)
            self.quote('HYDROGEL_PACK', hyd, fair, pos, 8, 10, orders)
            result['HYDROGEL_PACK'] = orders

        # --- OPTIONAL ADAPTIVE-EMA HYDROGEL (enable in Round 4 after backtesting) ---
        # if hyd and hy_mid is not None:
        #     orders = []
        #     pos = state.position.get('HYDROGEL_PACK', 0)
        #     hist = data['hydro_hist']
        #     if len(hist) >= 5:
        #         mad = sum(abs(hist[i] - hist[i-1]) for i in range(-4, 0)) / 4
        #         # Higher volatility → faster EMA. Effective window ≈ 2/alpha - 1.
        #         # mad/20 targets alpha~0.15 at typical vol, alpha~0.40 if doubling.
        #         alpha = min(0.5, max(0.08, mad / 20.0))
        #     else:
        #         alpha = 0.15  # default ≈ window 12
        #     data['hydro_ema'] = alpha * hy_mid + (1 - alpha) * data.get('hydro_ema', 9990.81)
        #     fair = data['hydro_ema']
        #     pos, _ = self.take_buy('HYDROGEL_PACK', hyd, fair - 2, pos, 20, orders)
        #     pos, _ = self.take_sell('HYDROGEL_PACK', hyd, fair + 2, pos, 20, orders)
        #     self.quote('HYDROGEL_PACK', hyd, fair, pos, 8, 10, orders)
        #     result['HYDROGEL_PACK'] = orders

        # =================================================================
        # VOUCHERS — Dynamic IV + delta-controlled order flow
        # =================================================================
        if ex_mid:
            vev_5200_depth = state.order_depths.get('VEV_5200')
            if vev_5200_depth:
                v_mid = self.mid_price(vev_5200_depth)
                if v_mid:
                    current_iv = self.solve_iv(ex_mid, 5200, current_tte, v_mid)
                    data['iv_ema'] = 0.20 * current_iv + 0.80 * data['iv_ema']

            dynamic_sigma = data['iv_ema']
            agg_delta = 0.0
            opps = []

            for sym, K in self.STRIKES.items():
                agg_delta += state.position.get(sym, 0) * self.get_bs_delta(
                    ex_mid, K, current_tte, dynamic_sigma)

            for sym, K in self.STRIKES.items():
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                bs_fair = self.get_bs_price(ex_mid, K, current_tte, dynamic_sigma)
                d_i = self.get_bs_delta(ex_mid, K, current_tte, dynamic_sigma)
                pos = state.position.get(sym, 0)
                buy_edge_req = self.MIN_EDGE if pos >= 0 else 0.0
                sell_edge_req = self.MIN_EDGE if pos <= 0 else 0.0

                for ask, vol in depth.sell_orders.items():
                    edge = bs_fair - ask
                    if edge > buy_edge_req:
                        opps.append({'sym': sym, 'px': ask, 'qty': -vol,
                                     'edge': edge, 'delta': d_i, 'side': 'BUY'})
                for bid, vol in depth.buy_orders.items():
                    edge = bid - bs_fair
                    if edge > sell_edge_req:
                        opps.append({'sym': sym, 'px': bid, 'qty': vol,
                                     'edge': edge, 'delta': -d_i, 'side': 'SELL'})

            opps.sort(key=lambda x: x['edge'] / max(0.01, abs(x['delta'])), reverse=True)

            for o in opps:
                sym = o['sym']
                pos = state.position.get(sym, 0)
                trade_qty = min(o['qty'],
                                self.LIMITS[sym] - (pos if o['side'] == 'BUY' else -pos))
                new_delta = agg_delta + (
                    trade_qty * o['delta'] if o['side'] == 'BUY'
                    else -trade_qty * abs(o['delta']))
                if abs(new_delta) > self.DELTA_LIMIT and abs(new_delta) > abs(agg_delta):
                    continue
                if trade_qty > 0:
                    orders = result.get(sym, [])
                    orders.append(Order(sym, o['px'],
                                        trade_qty if o['side'] == 'BUY' else -trade_qty))
                    result[sym] = orders
                    agg_delta = new_delta
                    state.position[sym] = pos + (trade_qty if o['side'] == 'BUY' else -trade_qty)

        # =================================================================
        # VELVETFRUIT_EXTRACT — Fixed standalone market-making (Option B)
        # =================================================================
        if ex_depth and ex_mid is not None:
            orders = []
            ex_pos = state.position.get('VELVETFRUIT_EXTRACT', 0)
            limit = self.LIMITS['VELVETFRUIT_EXTRACT']
            pos_ratio = ex_pos / limit  # range: -1.0 to +1.0

            # --- Fair value: fast EMA (alpha=0.7) to avoid stale-tick lag ---
            alpha_fast = 0.7
            data['vev_ema'] = (alpha_fast * ex_mid
                               + (1 - alpha_fast) * data.get('vev_ema', ex_mid))
            vev_fair = data['vev_ema']

            # --- Trend signal: fast EMA minus slow EMA ---
            alpha_slow = 0.05
            data['vev_ema_slow'] = (alpha_slow * ex_mid
                                    + (1 - alpha_slow) * data.get('vev_ema_slow', ex_mid))

            # FIX 1: Warmup guard — suppress trend signal for first 50 ticks
            # while slow EMA is still initialising from the seed value.
            tick_count = data.get('tick_count', 0)
            if tick_count >= self.VEV_WARMUP_TICKS:
                trend = vev_fair - data['vev_ema_slow']
            else:
                trend = 0.0

            # FIX 2: Cap momentum skew to ±VEV_MOMENTUM_CAP ticks.
            # Uncapped, a sustained trend of 5 ticks between EMAs would skew
            # quotes by 2.5 ticks — acceptable. But a sudden spike (e.g. 30
            # ticks on a jump) would skew by 15 ticks, wiping out the halfspread
            # and quoting against ourselves on trend reversal.
            momentum_skew_raw = int(round(trend * 0.5))
            momentum_skew = max(-self.VEV_MOMENTUM_CAP,
                                min(self.VEV_MOMENTUM_CAP, momentum_skew_raw))

            # Inventory skew: lean quotes against position to drive mean reversion.
            inventory_skew = int(round(10.0 * pos_ratio))
            total_skew = momentum_skew + inventory_skew

            # FIX 3: Hard position cap — if |pos| > VEV_POSITION_HARD_CAP,
            # stop quoting on the side that would increase exposure further.
            # This prevents runaway inventory if trend persists and fills keep coming.
            hard_cap_long = (ex_pos > self.VEV_POSITION_HARD_CAP)   # too long → no more buys
            hard_cap_short = (ex_pos < -self.VEV_POSITION_HARD_CAP)  # too short → no more sells

            # --- Take orders: only take with meaningful edge ---
            take_threshold = 4
            take_cap = 10
            if not hard_cap_long:
                pos, _ = self.take_buy('VELVETFRUIT_EXTRACT', ex_depth,
                                       vev_fair - take_threshold, ex_pos, take_cap, orders)
            else:
                pos = ex_pos
            if not hard_cap_short:
                pos, _ = self.take_sell('VELVETFRUIT_EXTRACT', ex_depth,
                                        vev_fair + take_threshold, pos, take_cap, orders)

            # --- Passive quotes: fixed halfspread of 6 ---
            # IMPORTANT: Do NOT use dynamic book halfspread here.
            # At natural spread ~5, dynamic halfspread = 2.5 — too tight
            # to overcome adverse selection in a trending market.
            halfspread = self.VEV_HALFSPREAD

            bid, ask = self.best_bid_ask(ex_depth)
            bpx = int(math.floor(vev_fair - halfspread - total_skew))
            apx = int(math.ceil(vev_fair + halfspread - total_skew))

            if bid is not None:
                bpx = min(bpx, bid + 1)
            if ask is not None:
                apx = max(apx, ask - 1)
            if apx <= bpx:
                apx = bpx + 1

            # Suppress quoting on adding side at 60% utilisation AND hard cap.
            can_buy_quote = (pos_ratio < 0.6) and (not hard_cap_long)
            can_sell_quote = (pos_ratio > -0.6) and (not hard_cap_short)

            bq = min(15, self.room_buy('VELVETFRUIT_EXTRACT', pos)) if can_buy_quote else 0
            sq = min(15, self.room_sell('VELVETFRUIT_EXTRACT', pos)) if can_sell_quote else 0

            if bq > 0:
                orders.append(Order('VELVETFRUIT_EXTRACT', bpx, bq))
            if sq > 0:
                orders.append(Order('VELVETFRUIT_EXTRACT', apx, -sq))

            result['VELVETFRUIT_EXTRACT'] = orders

        data['last_ts'] = state.timestamp
        return result, 0, self.dump_data(data)