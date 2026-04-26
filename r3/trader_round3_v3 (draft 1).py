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

    VOUCHERS = list(STRIKES.keys())
    TTE_YEARS = 5.0 / 365.0

    def __init__(self):
        pass

    # ---------------- persistence ----------------
    def default_state(self):
        return {
            "extract_mids": [],
            "hydro_mids": [],
            "last_surface": 0.23,
            "last_timestamp": -1,
        }

    def load_state(self, trader_data: str):
        if not trader_data:
            return self.default_state()
        try:
            state = json.loads(trader_data)
            base = self.default_state()
            base.update(state)
            return base
        except Exception:
            return self.default_state()

    def dump_state(self, state_dict):
        return json.dumps(state_dict, separators=(",", ":"))

    # ---------------- helpers ----------------
    def best_bid_ask(self, depth: OrderDepth):
        bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bid, ask

    def mid_price(self, depth: OrderDepth):
        bid, ask = self.best_bid_ask(depth)
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        if bid is not None:
            return float(bid)
        if ask is not None:
            return float(ask)
        return None

    def spread(self, depth: OrderDepth, default_value: float = 2.0):
        bid, ask = self.best_bid_ask(depth)
        if bid is not None and ask is not None:
            return max(1.0, ask - bid)
        return default_value

    def clamp(self, x, lo, hi):
        return max(lo, min(hi, x))

    def norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_call(self, s: float, k: float, t: float, sigma: float) -> float:
        intrinsic = max(0.0, s - k)
        if s <= 0 or k <= 0 or t <= 0 or sigma <= 1e-9:
            return intrinsic
        root_t = math.sqrt(t)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * root_t)
        d2 = d1 - sigma * root_t
        return s * self.norm_cdf(d1) - k * self.norm_cdf(d2)

    def bs_delta(self, s: float, k: float, t: float, sigma: float) -> float:
        if s <= 0 or k <= 0 or t <= 0:
            return 1.0 if s > k else 0.0
        sigma = max(sigma, 1e-6)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * math.sqrt(t))
        return self.norm_cdf(d1)

    def implied_vol(self, price: float, s: float, k: float, t: float):
        intrinsic = max(0.0, s - k)
        if price <= intrinsic + 1e-6:
            return 1e-4
        low, high = 1e-4, 3.0
        for _ in range(35):
            mid = 0.5 * (low + high)
            v = self.bs_call(s, k, t, mid)
            if v > price:
                high = mid
            else:
                low = mid
        return 0.5 * (low + high)

    def linear_regression_slope(self, xs, ys):
        n = len(xs)
        if n < 2:
            return 0.0
        mx = sum(xs) / n
        my = sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom <= 1e-9:
            return 0.0
        numer = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        return numer / denom

    def recent_vol(self, mids):
        if len(mids) < 8:
            return 0.23
        rets = []
        for i in range(1, len(mids)):
            a = mids[i - 1]
            b = mids[i]
            if a > 0 and b > 0:
                rets.append(math.log(b / a))
        if len(rets) < 5:
            return 0.23
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
        tick_vol = math.sqrt(max(var, 1e-10))
        annualized = tick_vol * math.sqrt(10000)
        return self.clamp(annualized, 0.08, 0.80)

    def qty_can_buy(self, product, pos):
        return max(0, self.LIMITS[product] - pos)

    def qty_can_sell(self, product, pos):
        return max(0, self.LIMITS[product] + pos)

    def take_buy(self, product, depth, fair, edge, pos, orders, max_qty=None):
        for ask in sorted(depth.sell_orders.keys()):
            avail = -depth.sell_orders[ask]
            if ask > fair - edge:
                break
            cap = self.qty_can_buy(product, pos)
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
        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            avail = depth.buy_orders[bid]
            if bid < fair + edge:
                break
            cap = self.qty_can_sell(product, pos)
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

    def quote_mm(self, product, depth, fair, pos, base_size, base_half_spread, orders):
        bid, ask = self.best_bid_ask(depth)
        skew = int(round(pos / max(1, self.LIMITS[product]) * 6))
        bid_px = int(math.floor(fair - base_half_spread - skew))
        ask_px = int(math.ceil(fair + base_half_spread - skew))

        if bid is not None:
            bid_px = min(bid_px, bid + 1)
        if ask is not None:
            ask_px = max(ask_px, ask - 1)
        if ask_px <= bid_px:
            ask_px = bid_px + 1

        buy_qty = min(base_size, self.qty_can_buy(product, pos))
        sell_qty = min(base_size, self.qty_can_sell(product, pos))

        if buy_qty > 0:
            orders.append(Order(product, bid_px, buy_qty))
        if sell_qty > 0:
            orders.append(Order(product, ask_px, -sell_qty))

    def build_iv_surface(self, extract_mid, order_depths, fallback_sigma):
        points = []
        for sym, k in self.STRIKES.items():
            depth = order_depths.get(sym)
            if depth is None:
                continue
            mid = self.mid_price(depth)
            if mid is None:
                continue
            intrinsic = max(0.0, extract_mid - k)
            extrinsic = mid - intrinsic
            if mid <= 0.5:
                continue
            if k >= 6000 and mid <= 1.0:
                continue
            iv = self.implied_vol(mid, extract_mid, k, self.TTE_YEARS)
            m = math.log(extract_mid / k)
            weight = 1.0
            if 4950 <= k <= 5400:
                weight = 2.0
            if extrinsic < 2.0:
                weight *= 0.5
            points.append((m, iv, weight, sym, k, mid))

        if len(points) < 2:
            return fallback_sigma, {}, {}

        weighted_mean = sum(iv * w for _, iv, w, _, _, _ in points) / sum(w for _, _, w, _, _, _ in points)
        denom = sum((m * m) * w for m, _, w, _, _, _ in points)
        slope = 0.0
        if denom > 1e-9:
            slope = sum(m * (iv - weighted_mean) * w for m, iv, w, _, _, _ in points) / denom
        slope = self.clamp(slope, -2.0, 2.0)

        sigma_map = {}
        iv_map = {}
        for m, iv, _, sym, _, _ in points:
            model = self.clamp(weighted_mean + slope * m, 0.08, 0.90)
            sigma_map[sym] = model
            iv_map[sym] = iv

        return weighted_mean, sigma_map, iv_map

    def voucher_confidence(self, mispricing, half_spread, strike):
        raw = abs(mispricing) / max(1.0, half_spread)
        conf = self.clamp(raw / 2.5, 0.0, 1.0)
        if strike in (6000, 6500):
            conf *= 0.35
        elif strike == 5500:
            conf *= 0.7
        elif strike in (5000, 5100, 5200, 5300):
            conf *= 1.15
        return self.clamp(conf, 0.0, 1.0)

    def voucher_fair(self, s, k, sigma_model):
        intrinsic = max(0.0, s - k)
        bs = self.bs_call(s, k, self.TTE_YEARS, sigma_model)
        m = s - k
        if m >= 700:
            return intrinsic
        if m >= 300:
            return max(intrinsic, 0.85 * intrinsic + 0.15 * bs)
        if m >= 100:
            return max(intrinsic, 0.60 * intrinsic + 0.40 * bs)
        return bs

    def run(self, state: TradingState):
        memory = self.load_state(state.traderData)
        result = {}
        conversions = 0

        # ---------- update mid histories ----------
        extract_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hydro_depth = state.order_depths.get("HYDROGEL_PACK")

        extract_mid = self.mid_price(extract_depth) if extract_depth else None
        hydro_mid = self.mid_price(hydro_depth) if hydro_depth else None

        if extract_mid is not None and state.timestamp != memory.get("last_timestamp", -1):
            memory["extract_mids"].append(extract_mid)
            if len(memory["extract_mids"]) > 60:
                memory["extract_mids"] = memory["extract_mids"][-60:]
        if hydro_mid is not None and state.timestamp != memory.get("last_timestamp", -1):
            memory["hydro_mids"].append(hydro_mid)
            if len(memory["hydro_mids"]) > 60:
                memory["hydro_mids"] = memory["hydro_mids"][-60:]
        memory["last_timestamp"] = state.timestamp

        # ---------- HYDROGEL ----------
        if hydro_depth is not None:
            product = "HYDROGEL_PACK"
            pos = state.position.get(product, 0)
            orders = []
            bid, ask = self.best_bid_ask(hydro_depth)
            hydro_hist = memory["hydro_mids"]
            hydro_anchor = 10000.0
            if len(hydro_hist) >= 8:
                hydro_anchor = 0.7 * 10000.0 + 0.3 * (sum(hydro_hist[-8:]) / 8.0)

            ofi = 0.0
            if hydro_depth.buy_orders:
                ofi += sum(hydro_depth.buy_orders.values())
            if hydro_depth.sell_orders:
                ofi -= sum(-v for v in hydro_depth.sell_orders.values())
            fair = hydro_anchor + self.clamp(ofi / 40.0, -2.5, 2.5)

            pos = self.take_buy(product, hydro_depth, fair, edge=1.0, pos=pos, orders=orders)
            pos = self.take_sell(product, hydro_depth, fair, edge=1.0, pos=pos, orders=orders)
            self.quote_mm(product, hydro_depth, fair, pos, base_size=18, base_half_spread=8, orders=orders)
            result[product] = orders

        # ---------- VOUCHERS first, to infer hedge ----------
        hedge_delta = 0.0
        if extract_mid is not None:
            realized_sigma = self.recent_vol(memory["extract_mids"])
            base_surface, sigma_map, live_iv_map = self.build_iv_surface(
                extract_mid, state.order_depths, memory.get("last_surface", realized_sigma)
            )
            memory["last_surface"] = 0.7 * memory.get("last_surface", base_surface) + 0.3 * base_surface

            for sym in self.VOUCHERS:
                depth = state.order_depths.get(sym)
                if depth is None:
                    continue
                pos = state.position.get(sym, 0)
                orders = []
                k = self.STRIKES[sym]
                mid = self.mid_price(depth)
                if mid is None:
                    result[sym] = orders
                    continue

                half_spread = self.spread(depth, default_value=2.0) / 2.0
                sigma_model = sigma_map.get(sym, memory["last_surface"])
                sigma_live = live_iv_map.get(sym, sigma_model)
                fair = self.voucher_fair(extract_mid, k, sigma_model)
                intrinsic = max(0.0, extract_mid - k)

                mispricing = fair - mid
                conf = self.voucher_confidence(mispricing, half_spread, k)
                if intrinsic <= 1.0 and mid <= 1.0 and k >= 6000:
                    conf *= 0.2

                # Pipe logic: deep ITM should hug intrinsic value tightly.
                if extract_mid - k >= 700:
                    fair = intrinsic
                    mispricing = fair - mid
                    conf = self.clamp(abs(mispricing) / max(1.0, half_spread + 0.5), 0.0, 1.0)

                max_trade = int(max(0, round(self.LIMITS[sym] * conf * 0.45)))
                if abs(mispricing) >= max(1.0, 0.8 * half_spread) and max_trade > 0:
                    if mispricing > 0:
                        pos = self.take_buy(sym, depth, fair, edge=0.2, pos=pos, orders=orders, max_qty=max_trade)
                    else:
                        pos = self.take_sell(sym, depth, fair, edge=-0.2, pos=pos, orders=orders, max_qty=max_trade)

                # Passive quotes around fair only where there is decent liquidity.
                if k <= 5500:
                    quote_edge = max(1.0, half_spread)
                    skew = int(round((state.position.get(sym, 0) / self.LIMITS[sym]) * max(1.0, quote_edge)))
                    bid_px = int(math.floor(fair - quote_edge - skew))
                    ask_px = int(math.ceil(fair + quote_edge - skew))
                    best_bid, best_ask = self.best_bid_ask(depth)
                    if best_bid is not None:
                        bid_px = min(bid_px, best_bid + 1)
                    if best_ask is not None:
                        ask_px = max(ask_px, best_ask - 1)
                    if ask_px <= bid_px:
                        ask_px = bid_px + 1
                    passive_qty = int(max(4, round(10 + 18 * conf)))
                    if self.qty_can_buy(sym, pos) > 0:
                        orders.append(Order(sym, bid_px, min(passive_qty, self.qty_can_buy(sym, pos))))
                    if self.qty_can_sell(sym, pos) > 0:
                        orders.append(Order(sym, ask_px, -min(passive_qty, self.qty_can_sell(sym, pos))))

                result[sym] = orders

                delta_for_hedge = self.bs_delta(extract_mid, k, self.TTE_YEARS, max(0.05, sigma_live))
                if extract_mid - k >= 700:
                    delta_for_hedge = 1.0
                elif extract_mid - k >= 300:
                    delta_for_hedge = max(delta_for_hedge, 0.85)
                hedge_delta += state.position.get(sym, 0) * delta_for_hedge

        # ---------- EXTRACT last: MM + hedge ----------
        if extract_depth is not None and extract_mid is not None:
            product = "VELVETFRUIT_EXTRACT"
            pos = state.position.get(product, 0)
            orders = []
            mids = memory["extract_mids"]
            ema = extract_mid
            if mids:
                alpha = 0.22
                ema = mids[0]
                for m in mids[1:]:
                    ema = alpha * m + (1 - alpha) * ema

            slope = self.linear_regression_slope(list(range(len(mids[-12:]))), mids[-12:]) if len(mids) >= 6 else 0.0
            fair = ema + self.clamp(1.4 * slope, -3.0, 3.0)

            target_extract = int(round(-hedge_delta))
            target_extract = int(self.clamp(target_extract, -self.LIMITS[product], self.LIMITS[product]))
            hedge_gap = target_extract - pos
            fair += self.clamp(hedge_gap / 40.0, -2.5, 2.5)

            pos = self.take_buy(product, extract_depth, fair, edge=1.0, pos=pos, orders=orders)
            pos = self.take_sell(product, extract_depth, fair, edge=1.0, pos=pos, orders=orders)

            if hedge_gap > 12:
                pos = self.take_buy(product, extract_depth, fair + 1.5, edge=-10.0, pos=pos, orders=orders, max_qty=min(40, hedge_gap))
            elif hedge_gap < -12:
                pos = self.take_sell(product, extract_depth, fair - 1.5, edge=10.0, pos=pos, orders=orders, max_qty=min(40, -hedge_gap))

            base_size = 12 if abs(hedge_gap) < 80 else 6
            self.quote_mm(product, extract_depth, fair, pos, base_size=base_size, base_half_spread=3, orders=orders)
            result[product] = orders

        trader_data = self.dump_state(memory)
        return result, conversions, trader_data
