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
    STRIKES = {"VEV_4000":4000,"VEV_4500":4500,"VEV_5000":5000,"VEV_5100":5100,"VEV_5200":5200,"VEV_5300":5300,"VEV_5400":5400,"VEV_5500":5500,"VEV_6000":6000,"VEV_6500":6500}
    EMPIRICAL_DELTAS = {"VEV_4000":0.745054615800478,"VEV_4500":0.6617923883095481,"VEV_5000":0.6535202277123894,"VEV_5100":0.5773316745588724,"VEV_5200":0.4366593498212041,"VEV_5300":0.2726881916535854,"VEV_5400":0.12886984048408423,"VEV_5500":0.05486331394477844,"VEV_6000":0.0,"VEV_6500":0.0}
    RISK_CAPS = {"VEV_4000":3,"VEV_4500":3,"VEV_5000":1,"VEV_5100":1,"VEV_5200":1,"VEV_5300":2,"VEV_5400":2,"VEV_5500":1,"VEV_6000":0,"VEV_6500":0}
    TTE = 5.0 / 365.0

    def load_data(self, trader_data):
        d = {'extract_mids': [], 'hydro_mids': [], 'voucher_pos_ema': {}, 'last_ts': -1}
        if trader_data:
            try:
                x = json.loads(trader_data)
                d.update(x)
            except Exception:
                pass
        if 'voucher_pos_ema' not in d:
            d['voucher_pos_ema'] = {}
        return d

    def dump(self, d):
        return json.dumps(d, separators=(',',':'))

    def ba(self, depth):
        bid = max(depth.buy_orders) if depth.buy_orders else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        return bid, ask

    def mid(self, depth):
        bid, ask = self.ba(depth)
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return float(bid if bid is not None else ask) if (bid is not None or ask is not None) else None

    def cdf(self, x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_call(self, s, k, t, sigma):
        intrinsic = max(0.0, s-k)
        if s <= 0 or k <= 0 or t <= 0 or sigma <= 1e-6:
            return intrinsic
        rt = math.sqrt(t)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * rt)
        d2 = d1 - sigma * rt
        return s * self.cdf(d1) - k * self.cdf(d2)

    def iv(self, price, s, k, t):
        intrinsic = max(0.0, s-k)
        if price <= intrinsic + 1e-6:
            return 1e-4
        lo, hi = 1e-4, 3.0
        for _ in range(30):
            mid = (lo+hi)/2
            if self.bs_call(s,k,t,mid) > price:
                hi = mid
            else:
                lo = mid
        return (lo+hi)/2

    def buy_room(self, p, pos):
        return max(0, self.LIMITS[p] - pos)

    def sell_room(self, p, pos):
        return max(0, self.LIMITS[p] + pos)

    def hit_buys(self, p, depth, thresh, pos, orders, cap=None):
        for ask in sorted(depth.sell_orders):
            if ask > thresh:
                break
            qty = min(-depth.sell_orders[ask], self.buy_room(p, pos))
            if cap is not None:
                qty = min(qty, cap)
            if qty > 0:
                orders.append(Order(p, ask, qty))
                pos += qty
                if cap is not None:
                    cap -= qty
                    if cap <= 0:
                        break
        return pos

    def hit_sells(self, p, depth, thresh, pos, orders, cap=None):
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < thresh:
                break
            qty = min(depth.buy_orders[bid], self.sell_room(p, pos))
            if cap is not None:
                qty = min(qty, cap)
            if qty > 0:
                orders.append(Order(p, bid, -qty))
                pos -= qty
                if cap is not None:
                    cap -= qty
                    if cap <= 0:
                        break
        return pos

    def quote(self, p, depth, fair, pos, orders, halfspread, size):
        bid, ask = self.ba(depth)
        skew = int(round(10 * pos / self.LIMITS[p]))
        bpx = int(math.floor(fair - halfspread - skew))
        apx = int(math.ceil(fair + halfspread - skew))
        if bid is not None:
            bpx = min(bpx, bid + 1)
        if ask is not None:
            apx = max(apx, ask - 1)
        if apx <= bpx:
            apx = bpx + 1
        bq = min(size, self.buy_room(p, pos))
        sq = min(size, self.sell_room(p, pos))
        if bq > 0:
            orders.append(Order(p, bpx, bq))
        if sq > 0:
            orders.append(Order(p, apx, -sq))

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
                data['extract_mids'].append(ex_mid)
                data['extract_mids'] = data['extract_mids'][-100:]
            if hy_mid is not None:
                data['hydro_mids'].append(hy_mid)
                data['hydro_mids'] = data['hydro_mids'][-100:]
            for sym in self.STRIKES:
                cur = state.position.get(sym, 0)
                prev = data['voucher_pos_ema'].get(sym, 0.0)
                data['voucher_pos_ema'][sym] = 0.2 * cur + 0.8 * prev
            data['last_ts'] = state.timestamp

        if hyd:
            pos = state.position.get('HYDROGEL_PACK', 0)
            fair = 10000.0
            if len(data['hydro_mids']) >= 10:
                fair = 0.85 * 10000.0 + 0.15 * (sum(data['hydro_mids'][-10:]) / 10.0)
            orders = []
            pos = self.hit_buys('HYDROGEL_PACK', hyd, fair - 1, pos, orders)
            pos = self.hit_sells('HYDROGEL_PACK', hyd, fair + 1, pos, orders)
            self.quote('HYDROGEL_PACK', hyd, fair, pos, orders, halfspread=9, size=8)
            result['HYDROGEL_PACK'] = orders

        target_extract = 0.0
        if ex_mid is not None:
            live_ivs = {}
            for sym, k in self.STRIKES.items():
                d = state.order_depths.get(sym)
                m = self.mid(d) if d else None
                if m is not None:
                    live_ivs[sym] = self.iv(m, ex_mid, k, self.TTE)
            core = [s for s in ['VEV_5000','VEV_5100','VEV_5200','VEV_5300'] if s in live_ivs]
            base_iv = sum(live_ivs[s] for s in core) / len(core) if core else 0.22

            for sym, k in self.STRIKES.items():
                d = state.order_depths.get(sym)
                orders = []
                if d is None:
                    result[sym] = orders
                    continue
                pos = state.position.get(sym, 0)
                pos_ema = data['voucher_pos_ema'].get(sym, 0.0)
                m = self.mid(d)
                if m is None:
                    result[sym] = orders
                    continue

                intrinsic = max(0.0, ex_mid - k)
                if ex_mid - k >= 700:
                    fair = intrinsic
                    edge = 1.5
                    psize = 1
                elif ex_mid - k >= 250:
                    fair = max(intrinsic, 0.92 * intrinsic + 0.08 * self.bs_call(ex_mid, k, self.TTE, max(base_iv, 0.10)))
                    edge = 1.8
                    psize = 2
                else:
                    fair = self.bs_call(ex_mid, k, self.TTE, max(0.10, min(0.80, 0.85 * base_iv + 0.15 * live_ivs.get(sym, base_iv))))
                    edge = 3.0 if sym in ('VEV_5000','VEV_5100','VEV_5200') else (2.4 if sym in ('VEV_5300','VEV_5400') else 2.0)
                    psize = 1 if sym in ('VEV_5300','VEV_5400','VEV_4000','VEV_4500') else 0

                cap = self.RISK_CAPS.get(sym, 1)
                if abs(pos_ema) > 6:
                    cap = max(1, cap // 2)
                if abs(pos) > 6:
                    psize = 0
                if abs(pos) > 14:
                    cap = 1
                if abs(pos) > 24:
                    if pos > 0:
                        pos = self.hit_sells(sym, d, fair - 0.2, pos, orders, cap=abs(pos))
                    else:
                        pos = self.hit_buys(sym, d, fair + 0.2, pos, orders, cap=abs(pos))
                    result[sym] = orders
                    target_extract -= state.position.get(sym, 0) * self.EMPIRICAL_DELTAS.get(sym, 0.0)
                    continue

                mis = fair - m
                if mis > edge:
                    pos = self.hit_buys(sym, d, fair - edge/3, pos, orders, cap=cap)
                elif mis < -edge:
                    pos = self.hit_sells(sym, d, fair + edge/3, pos, orders, cap=cap)

                if psize > 0 and abs(pos) <= 30:
                    hs = 2.0 if sym in ('VEV_5000','VEV_5100','VEV_5200') else 1.0
                    self.quote(sym, d, fair, pos, orders, halfspread=hs, size=psize)

                result[sym] = orders
                target_extract -= state.position.get(sym, 0) * self.EMPIRICAL_DELTAS.get(sym, 0.0)

        if exd and ex_mid is not None:
            pos = state.position.get('VELVETFRUIT_EXTRACT', 0)
            orders = []
            ema = ex_mid
            if data['extract_mids']:
                alpha = 0.2
                ema = data['extract_mids'][0]
                for x in data['extract_mids'][1:]:
                    ema = alpha * x + (1-alpha) * ema
            target_extract = max(-50, min(50, int(round(target_extract))))
            fair = ema + max(-2.0, min(2.0, (target_extract - pos) / 35.0))
            if target_extract > pos:
                pos = self.hit_buys('VELVETFRUIT_EXTRACT', exd, fair + 0.2, pos, orders, cap=min(18, target_extract - pos))
            elif target_extract < pos:
                pos = self.hit_sells('VELVETFRUIT_EXTRACT', exd, fair - 0.2, pos, orders, cap=min(18, pos - target_extract))
            self.quote('VELVETFRUIT_EXTRACT', exd, fair, pos, orders, halfspread=4, size=5)
            result['VELVETFRUIT_EXTRACT'] = orders

        return result, conversions, self.dump(data)
