from datamodel import OrderDepth, TradingState, Order
import json, math

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
    EMPIRICAL_DELTAS = {
        "VEV_4000": 0.9891237061025678,
        "VEV_4500": 0.9378764863898768,
        "VEV_5000": 0.7225665971451872,
        "VEV_5100": 0.6117570474836605,
        "VEV_5200": 0.49860156040482515,
        "VEV_5300": 0.38322916526954297,
        "VEV_5400": 0.27487281286222253,
        "VEV_5500": 0.18442568241632943,
        "VEV_6000": 0.012508590808903794,
        "VEV_6500": 0.0,
    }
    BASE_CAP = {
        "VEV_4000": 8,
        "VEV_4500": 8,
        "VEV_5000": 10,
        "VEV_5100": 10,
        "VEV_5200": 10,
        "VEV_5300": 10,
        "VEV_5400": 8,
        "VEV_5500": 5,
        "VEV_6000": 2,
        "VEV_6500": 0,
    }
    TTE = 5.0 / 365.0

    def load_data(self, trader_data):
        d = {
            'extract_hist': [],
            'hydro_hist': [],
            'iv_hist': {},
            'last_ts': -1,
        }
        if trader_data:
            try:
                x = json.loads(trader_data)
                d.update(x)
            except Exception:
                pass
        if 'iv_hist' not in d:
            d['iv_hist'] = {}
        for sym in self.STRIKES:
            if sym not in d['iv_hist']:
                d['iv_hist'][sym] = []
        return d

    def dump(self, d):
        return json.dumps(d, separators=(',', ':'))

    def best_bid_ask(self, depth):
        bid = max(depth.buy_orders) if depth.buy_orders else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        return bid, ask

    def mid(self, depth):
        bid, ask = self.best_bid_ask(depth)
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        if bid is not None:
            return float(bid)
        if ask is not None:
            return float(ask)
        return None

    def cdf(self, x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_call(self, s, k, t, sigma):
        intrinsic = max(0.0, s - k)
        if s <= 0 or k <= 0 or t <= 0 or sigma <= 1e-6:
            return intrinsic
        rt = math.sqrt(t)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * rt)
        d2 = d1 - sigma * rt
        return s * self.cdf(d1) - k * self.cdf(d2)

    def bs_delta(self, s, k, t, sigma):
        intrinsic_delta = 1.0 if s > k else 0.0
        if s <= 0 or k <= 0 or t <= 0 or sigma <= 1e-6:
            return intrinsic_delta
        rt = math.sqrt(t)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * rt)
        return self.cdf(d1)

    def iv(self, price, s, k, t):
        intrinsic = max(0.0, s - k)
        if price <= intrinsic + 1e-6:
            return 1e-4
        lo, hi = 1e-4, 2.5
        for _ in range(35):
            mid = (lo + hi) / 2.0
            val = self.bs_call(s, k, t, mid)
            if val > price:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2.0

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

    def solve_3x3(self, A, b):
        M = [A[0][:] + [b[0]], A[1][:] + [b[1]], A[2][:] + [b[2]]]
        for col in range(3):
            pivot = col
            for r in range(col, 3):
                if abs(M[r][col]) > abs(M[pivot][col]):
                    pivot = r
            if abs(M[pivot][col]) < 1e-12:
                return None
            M[col], M[pivot] = M[pivot], M[col]
            fac = M[col][col]
            for c in range(col, 4):
                M[col][c] /= fac
            for r in range(3):
                if r == col:
                    continue
                fac = M[r][col]
                for c in range(col, 4):
                    M[r][c] -= fac * M[col][c]
        return [M[i][3] for i in range(3)]

    def fit_quadratic_smile(self, points):
        # y = a + b x + c x^2
        n = len(points)
        if n < 3:
            return None
        sx = sy = sxx = sxy = sxxx = sxxxx = sxxy = 0.0
        for x, y in points:
            x2 = x * x
            sx += x
            sy += y
            sxx += x2
            sxy += x * y
            sxxx += x2 * x
            sxxxx += x2 * x2
            sxxy += x2 * y
        A = [
            [n, sx, sxx],
            [sx, sxx, sxxx],
            [sxx, sxxx, sxxxx],
        ]
        b = [sy, sxy, sxxy]
        return self.solve_3x3(A, b)

    def cap_for(self, sym, residual_price, pos):
        base = self.BASE_CAP.get(sym, 0)
        mag = abs(residual_price)
        scale = 1
        if mag > 12:
            scale = 3
        elif mag > 8:
            scale = 2
        elif mag > 4:
            scale = 1
        else:
            scale = 0
        cap = base * scale
        if abs(pos) > 80:
            cap = min(cap, 4)
        if abs(pos) > 140:
            cap = min(cap, 2)
        return cap

    def run(self, state: TradingState):
        data = self.load_data(state.traderData)
        result = {}
        conversions = 0

        exd = state.order_depths.get('VELVETFRUIT_EXTRACT')
        hyd = state.order_depths.get('HYDROGEL_PACK')
        ex_mid = self.mid(exd) if exd else None
        hy_mid = self.mid(hyd) if hyd else None

        if state.timestamp != data['last_ts']:
            if ex_mid is not None:
                data['extract_hist'].append(ex_mid)
                data['extract_hist'] = data['extract_hist'][-120:]
            if hy_mid is not None:
                data['hydro_hist'].append(hy_mid)
                data['hydro_hist'] = data['hydro_hist'][-120:]
            data['last_ts'] = state.timestamp

        # HYDROGEL: stable maker around 10000
        if hyd:
            orders = []
            pos = state.position.get('HYDROGEL_PACK', 0)
            fair = 10000.0
            if len(data['hydro_hist']) >= 12:
                recent = sum(data['hydro_hist'][-12:]) / 12.0
                fair = 0.90 * 10000.0 + 0.10 * recent
            pos, _ = self.take_buy('HYDROGEL_PACK', hyd, fair - 2, pos, 20, orders)
            pos, _ = self.take_sell('HYDROGEL_PACK', hyd, fair + 2, pos, 20, orders)
            self.quote('HYDROGEL_PACK', hyd, fair, pos, 8, 10, orders)
            result['HYDROGEL_PACK'] = orders

        target_extract = 0.0
        live = {}

        if ex_mid is not None:
            points = []
            for sym, strike in self.STRIKES.items():
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                mid = self.mid(depth)
                if mid is None:
                    continue
                iv = self.iv(mid, ex_mid, strike, self.TTE)
                x = (strike - ex_mid) / 100.0
                live[sym] = {'strike': strike, 'mid': mid, 'iv': iv, 'x': x, 'depth': depth}
                points.append((x, iv))
                hist = data['iv_hist'].get(sym, [])
                hist.append(iv)
                data['iv_hist'][sym] = hist[-80:]

            coeff = self.fit_quadratic_smile(points)
            if coeff is None:
                coeff = [0.22, 0.0, 0.0]
            a, b, c = coeff

            # prepare residuals
            signals = []
            for sym, info in live.items():
                fit_iv = max(0.05, min(1.20, a + b * info['x'] + c * info['x'] * info['x']))
                fit_price = self.bs_call(ex_mid, info['strike'], self.TTE, fit_iv)
                fit_delta = self.bs_delta(ex_mid, info['strike'], self.TTE, fit_iv)
                residual_price = fit_price - info['mid']
                hist = data['iv_hist'].get(sym, [])
                local_mean = sum(hist) / len(hist) if hist else fit_iv
                local_dev = info['iv'] - local_mean
                signals.append({
                    'sym': sym,
                    'strike': info['strike'],
                    'mid': info['mid'],
                    'fit_iv': fit_iv,
                    'fit_price': fit_price,
                    'fit_delta': fit_delta,
                    'residual_price': residual_price,
                    'iv_dev': local_dev,
                    'depth': info['depth'],
                })

            cheap = [s for s in signals if s['residual_price'] > 3.0]
            rich = [s for s in signals if s['residual_price'] < -3.0]
            cheap.sort(key=lambda z: z['residual_price'], reverse=True)
            rich.sort(key=lambda z: z['residual_price'])

            # paired surface trades first: buy cheap, sell rich, neighboring strikes preferred
            used = set()
            for c_sig in cheap[:4]:
                partner = None
                best_score = -1e18
                for r_sig in rich[:4]:
                    if r_sig['sym'] in used:
                        continue
                    dist = abs(c_sig['strike'] - r_sig['strike'])
                    score = c_sig['residual_price'] + (-r_sig['residual_price']) - 0.004 * dist
                    if score > best_score:
                        best_score = score
                        partner = r_sig
                if partner is None:
                    continue
                used.add(partner['sym'])
                buy_sym = c_sig['sym']
                sell_sym = partner['sym']
                buy_pos = state.position.get(buy_sym, 0)
                sell_pos = state.position.get(sell_sym, 0)
                cap_buy = self.cap_for(buy_sym, c_sig['residual_price'], buy_pos)
                cap_sell = self.cap_for(sell_sym, partner['residual_price'], sell_pos)
                pair_cap = min(cap_buy, cap_sell)
                if pair_cap <= 0:
                    continue
                d_buy = c_sig['depth']
                d_sell = partner['depth']
                buy_orders = result.get(buy_sym, [])
                sell_orders = result.get(sell_sym, [])
                buy_pos, got_buy = self.take_buy(buy_sym, d_buy, c_sig['fit_price'] - 0.2, buy_pos, pair_cap, buy_orders)
                sell_pos, got_sell = self.take_sell(sell_sym, d_sell, partner['fit_price'] + 0.2, sell_pos, pair_cap, sell_orders)
                result[buy_sym] = buy_orders
                result[sell_sym] = sell_orders

            # single-name opportunistic continuation for strongest residuals only
            for sig in signals:
                sym = sig['sym']
                orders = result.get(sym, [])
                pos = state.position.get(sym, 0)
                edge = abs(sig['residual_price'])
                cap = self.cap_for(sym, sig['residual_price'], pos)
                if edge > 6.0 and cap > 0:
                    if sig['residual_price'] > 0:
                        pos, _ = self.take_buy(sym, sig['depth'], sig['fit_price'] - 0.3, pos, cap, orders)
                    else:
                        pos, _ = self.take_sell(sym, sig['depth'], sig['fit_price'] + 0.3, pos, cap, orders)
                # only tiny passive quoting on neighbor strikes, never on dangerous center when inventory exists
                if sym in ('VEV_4000', 'VEV_4500', 'VEV_5300', 'VEV_5400') and abs(pos) <= 10 and edge > 4.5:
                    self.quote(sym, sig['depth'], sig['fit_price'], pos, 1.5, 1, orders)
                result[sym] = orders
                target_extract -= state.position.get(sym, 0) * self.EMPIRICAL_DELTAS.get(sym, sig['fit_delta'])

        # Extract hedge: delta-based only, no ballooning
        if exd and ex_mid is not None:
            orders = []
            pos = state.position.get('VELVETFRUIT_EXTRACT', 0)
            ema = ex_mid
            if data['extract_hist']:
                alpha = 0.18
                ema = data['extract_hist'][0]
                for x in data['extract_hist'][1:]:
                    ema = alpha * x + (1.0 - alpha) * ema
            target_extract = int(round(max(-70, min(70, target_extract))))
            bias = max(-2.0, min(2.0, (target_extract - pos) / 30.0))
            fair = ema + bias
            need = target_extract - pos
            if need > 0:
                pos, _ = self.take_buy('VELVETFRUIT_EXTRACT', exd, fair + 0.3, pos, min(16, need), orders)
            elif need < 0:
                pos, _ = self.take_sell('VELVETFRUIT_EXTRACT', exd, fair - 0.3, pos, min(16, -need), orders)
            if abs(target_extract - pos) <= 15 and abs(pos) <= 50:
                self.quote('VELVETFRUIT_EXTRACT', exd, fair, pos, 3.5, 4, orders)
            result['VELVETFRUIT_EXTRACT'] = orders

        for p in self.LIMITS:
            if p not in result:
                result[p] = []
        return result, conversions, self.dump(data)
