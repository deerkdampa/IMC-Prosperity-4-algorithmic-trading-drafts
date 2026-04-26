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
    EMPIRICAL_DELTAS = {"VEV_4000":0.745054615800478,"VEV_4500":0.6617923883095481,"VEV_5000":0.6535202277123894,"VEV_5100":0.5773316745588724,"VEV_5200":0.4366593498212041,"VEV_5300":0.2726881916535854,"VEV_5400":0.12886984048408423,"VEV_5500":0.05486331394477844,"VEV_6000":0.0,"VEV_6500":0.0}
    EXTRINSIC_MEANS = {"VEV_4000":0.0117,"VEV_4500":0.011466666666666667,"VEV_5000":4.9243,"VEV_5100":16.70735,"VEV_5200":45.450383333333335,"VEV_5300":46.759933333333336,"VEV_5400":15.951916666666667,"VEV_5500":6.64135,"VEV_6000":0.5,"VEV_6500":0.5}
    HYDRO_SPREAD = 15.721
    EXTRACT_SPREAD = 4.988
    TTE = 5.0 / 365.0

    def __init__(self):
        pass

    def load_data(self, trader_data):
        base = {'extract_mids': [], 'hydro_mids': [], 'last_ts': -1}
        if not trader_data:
            return base
        try:
            x = json.loads(trader_data)
            base.update(x)
            return base
        except Exception:
            return base

    def save_data(self, d):
        return json.dumps(d, separators=(',',':'))

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

    def norm_cdf(self, x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_call(self, s, k, t, sigma):
        intrinsic = max(0.0, s - k)
        if s <= 0 or k <= 0 or t <= 0 or sigma <= 1e-6:
            return intrinsic
        rt = math.sqrt(t)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * rt)
        d2 = d1 - sigma * rt
        return s * self.norm_cdf(d1) - k * self.norm_cdf(d2)

    def implied_vol(self, price, s, k, t):
        intrinsic = max(0.0, s - k)
        if price <= intrinsic + 1e-6:
            return 1e-4
        lo, hi = 1e-4, 3.0
        for _ in range(30):
            mid = (lo + hi) / 2.0
            val = self.bs_call(s, k, t, mid)
            if val > price:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2.0

    def qty_buy(self, product, pos):
        return max(0, self.LIMITS[product] - pos)

    def qty_sell(self, product, pos):
        return max(0, self.LIMITS[product] + pos)

    def take_buy(self, product, depth, fair, edge, pos, orders, max_qty=None):
        for ask in sorted(depth.sell_orders):
            if ask > fair - edge:
                break
            avail = -depth.sell_orders[ask]
            cap = self.qty_buy(product, pos)
            if max_qty is not None:
                cap = min(cap, max_qty)
            qty = min(avail, cap)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                pos += qty
                if max_qty is not None:
                    max_qty -= qty
                    if max_qty <= 0:
                        break
        return pos

    def take_sell(self, product, depth, fair, edge, pos, orders, max_qty=None):
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < fair + edge:
                break
            avail = depth.buy_orders[bid]
            cap = self.qty_sell(product, pos)
            if max_qty is not None:
                cap = min(cap, max_qty)
            qty = min(avail, cap)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                pos -= qty
                if max_qty is not None:
                    max_qty -= qty
                    if max_qty <= 0:
                        break
        return pos

    def mm_quotes(self, product, depth, fair, pos, halfspread, size, orders):
        best_bid, best_ask = self.best_bid_ask(depth)
        skew = int(round(5 * pos / self.LIMITS[product]))
        bid_px = int(math.floor(fair - halfspread - skew))
        ask_px = int(math.ceil(fair + halfspread - skew))
        if best_bid is not None:
            bid_px = min(bid_px, best_bid + 1)
        if best_ask is not None:
            ask_px = max(ask_px, best_ask - 1)
        if ask_px <= bid_px:
            ask_px = bid_px + 1
        bq = min(size, self.qty_buy(product, pos))
        sq = min(size, self.qty_sell(product, pos))
        if bq > 0:
            orders.append(Order(product, bid_px, bq))
        if sq > 0:
            orders.append(Order(product, ask_px, -sq))

    def run(self, state: TradingState):
        data = self.load_data(state.traderData)
        result = {}
        conversions = 0

        ex_depth = state.order_depths.get('VELVETFRUIT_EXTRACT')
        hy_depth = state.order_depths.get('HYDROGEL_PACK')
        ex_mid = self.mid(ex_depth) if ex_depth else None
        hy_mid = self.mid(hy_depth) if hy_depth else None

        if state.timestamp != data['last_ts']:
            if ex_mid is not None:
                data['extract_mids'].append(ex_mid)
                data['extract_mids'] = data['extract_mids'][-80:]
            if hy_mid is not None:
                data['hydro_mids'].append(hy_mid)
                data['hydro_mids'] = data['hydro_mids'][-80:]
            data['last_ts'] = state.timestamp

        # Hydrogel: data confirms stable 16-18ish spread, so keep simple mean reversion and wider passive quotes.
        if hy_depth is not None:
            pos = state.position.get('HYDROGEL_PACK', 0)
            orders = []
            anchor = 10000.0
            if len(data['hydro_mids']) >= 10:
                anchor = 0.8 * 10000.0 + 0.2 * (sum(data['hydro_mids'][-10:]) / 10.0)
            fair = anchor
            pos = self.take_buy('HYDROGEL_PACK', hy_depth, fair, edge=1.0, pos=pos, orders=orders)
            pos = self.take_sell('HYDROGEL_PACK', hy_depth, fair, edge=1.0, pos=pos, orders=orders)
            self.mm_quotes('HYDROGEL_PACK', hy_depth, fair, pos, halfspread=8, size=14, orders=orders)
            result['HYDROGEL_PACK'] = orders

        target_extract = 0.0
        if ex_mid is not None:
            voucher_names = list(self.STRIKES.keys())
            live_ivs = {}
            for sym in voucher_names:
                depth = state.order_depths.get(sym)
                if depth is None:
                    continue
                mid = self.mid(depth)
                if mid is None:
                    continue
                live_ivs[sym] = self.implied_vol(mid, ex_mid, self.STRIKES[sym], self.TTE)

            fit_syms = [s for s in ['VEV_5000','VEV_5100','VEV_5200','VEV_5300','VEV_5400'] if s in live_ivs]
            base_iv = sum(live_ivs[s] for s in fit_syms) / len(fit_syms) if fit_syms else 0.25

            for sym in voucher_names:
                depth = state.order_depths.get(sym)
                if depth is None:
                    continue
                pos = state.position.get(sym, 0)
                orders = []
                k = self.STRIKES[sym]
                intrinsic = max(0.0, ex_mid - k)
                market_mid = self.mid(depth)
                if market_mid is None:
                    result[sym] = orders
                    continue

                # Deep ITM: trade mostly as intrinsic trackers; OTM/ATM: trade around BS with restrained size.
                if ex_mid - k >= 700:
                    fair = intrinsic
                    take_edge = 0.6
                    passive_size = 4
                elif ex_mid - k >= 250:
                    fair = max(intrinsic, 0.8 * intrinsic + 0.2 * self.bs_call(ex_mid, k, self.TTE, max(base_iv, 0.12)))
                    take_edge = 0.8
                    passive_size = 5
                else:
                    model_iv = max(0.10, min(0.9, 0.75 * base_iv + 0.25 * live_ivs.get(sym, base_iv)))
                    fair = self.bs_call(ex_mid, k, self.TTE, model_iv)
                    take_edge = 1.0 if k in (5200,5300) else 1.2
                    passive_size = 6 if k in (5000,5100,5200,5300) else 3

                mis = fair - market_mid
                magnitude = abs(mis)
                max_take = 0
                if magnitude >= 3.0:
                    max_take = 40
                elif magnitude >= 2.0:
                    max_take = 20
                elif magnitude >= 1.0:
                    max_take = 8

                # Losses in the run were dominated by mid strikes, so keep 6000/6500 tiny and avoid overtrading 5400/5500.
                if sym in ('VEV_6000','VEV_6500'):
                    max_take = min(max_take, 3)
                    passive_size = 1
                elif sym in ('VEV_5400','VEV_5500'):
                    max_take = min(max_take, 8)
                    passive_size = min(passive_size, 2)

                if mis > 0 and max_take > 0:
                    pos = self.take_buy(sym, depth, fair, edge=take_edge, pos=pos, orders=orders, max_qty=max_take)
                elif mis < 0 and max_take > 0:
                    pos = self.take_sell(sym, depth, fair, edge=take_edge, pos=pos, orders=orders, max_qty=max_take)

                # Conservative passive quoting near fair.
                best_bid, best_ask = self.best_bid_ask(depth)
                if passive_size > 0:
                    bid_px = int(math.floor(fair - 1))
                    ask_px = int(math.ceil(fair + 1))
                    if best_bid is not None:
                        bid_px = min(bid_px, best_bid + 1)
                    if best_ask is not None:
                        ask_px = max(ask_px, best_ask - 1)
                    if ask_px <= bid_px:
                        ask_px = bid_px + 1
                    if self.qty_buy(sym, pos) > 0:
                        orders.append(Order(sym, bid_px, min(passive_size, self.qty_buy(sym, pos))))
                    if self.qty_sell(sym, pos) > 0:
                        orders.append(Order(sym, ask_px, -min(passive_size, self.qty_sell(sym, pos))))

                result[sym] = orders
                target_extract -= state.position.get(sym, 0) * self.EMPIRICAL_DELTAS.get(sym, 0.0)

        if ex_depth is not None and ex_mid is not None:
            pos = state.position.get('VELVETFRUIT_EXTRACT', 0)
            orders = []
            ema = ex_mid
            mids = data['extract_mids']
            if mids:
                alpha = 0.2
                ema = mids[0]
                for m in mids[1:]:
                    ema = alpha * m + (1 - alpha) * ema
            fair = ema
            target_extract = max(-160, min(160, int(round(target_extract))))
            gap = target_extract - pos
            fair += max(-2.0, min(2.0, gap / 50.0))
            pos = self.take_buy('VELVETFRUIT_EXTRACT', ex_depth, fair, edge=1.0, pos=pos, orders=orders)
            pos = self.take_sell('VELVETFRUIT_EXTRACT', ex_depth, fair, edge=1.0, pos=pos, orders=orders)
            if gap > 20:
                pos = self.take_buy('VELVETFRUIT_EXTRACT', ex_depth, fair + 1.0, edge=-10.0, pos=pos, orders=orders, max_qty=min(30, gap))
            elif gap < -20:
                pos = self.take_sell('VELVETFRUIT_EXTRACT', ex_depth, fair - 1.0, edge=10.0, pos=pos, orders=orders, max_qty=min(30, -gap))
            self.mm_quotes('VELVETFRUIT_EXTRACT', ex_depth, fair, pos, halfspread=3, size=10, orders=orders)
            result['VELVETFRUIT_EXTRACT'] = orders

        return result, conversions, self.save_data(data)
