from datamodel import OrderDepth, TradingState, Order
import math
import json

POSITION_LIMITS = {
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

TTE = 5 / 365
OPTION_EDGE = 2.0
HYDRO_EDGE = 1.5
SIZE_PER_POINT = 10
MAX_CLIP = 40
HISTORY_LEN = 40


class Trader:
    def norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def best_bid_ask(self, od: OrderDepth):
        bid = max(od.buy_orders) if od.buy_orders else None
        ask = min(od.sell_orders) if od.sell_orders else None
        return bid, ask

    def mid(self, od: OrderDepth):
        bid, ask = self.best_bid_ask(od)
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        if bid is not None:
            return float(bid)
        if ask is not None:
            return float(ask)
        return None

    def bs_call(self, s: float, k: float, t: float, sigma: float) -> float:
        if s <= 0 or t <= 0 or sigma <= 1e-9:
            return max(s - k, 0.0)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)
        return s * self.norm_cdf(d1) - k * self.norm_cdf(d2)

    def implied_vol(self, price: float, s: float, k: float, t: float):
        intrinsic = max(s - k, 0.0)
        if price is None or s <= 0 or price < intrinsic or price > s:
            return None

        lo, hi = 1e-4, 3.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            val = self.bs_call(s, k, t, mid)
            if val > price:
                hi = mid
            else:
                lo = mid
        return 0.5 * (lo + hi)

    def fit_quadratic(self, xs, ys):
        n = len(xs)
        if n < 3:
            avg = sum(ys) / len(ys)
            return (0.0, 0.0, avg)

        s0 = n
        s1 = sum(xs)
        s2 = sum(x * x for x in xs)
        s3 = sum(x * x * x for x in xs)
        s4 = sum(x * x * x * x for x in xs)

        t0 = sum(ys)
        t1 = sum(x * y for x, y in zip(xs, ys))
        t2 = sum(x * x * y for x, y in zip(xs, ys))

        A = [
            [s4, s3, s2],
            [s3, s2, s1],
            [s2, s1, s0],
        ]
        b = [t2, t1, t0]

        # Gaussian elimination
        for i in range(3):
            pivot = A[i][i]
            if abs(pivot) < 1e-12:
                avg = sum(ys) / len(ys)
                return (0.0, 0.0, avg)
            for j in range(i, 3):
                A[i][j] /= pivot
            b[i] /= pivot
            for r in range(3):
                if r == i:
                    continue
                factor = A[r][i]
                for c in range(i, 3):
                    A[r][c] -= factor * A[i][c]
                b[r] -= factor * b[i]

        return (b[0], b[1], b[2])

    def eval_quad(self, coeffs, x):
        a, b, c = coeffs
        return a * x * x + b * x + c

    def clip_size(self, edge, cap):
        return min(MAX_CLIP, max(0, int(edge * SIZE_PER_POINT)), cap)

    def take_edge(self, product, od, fv, pos, limit, edge_needed):
        orders = []
        bid, ask = self.best_bid_ask(od)
        buy_cap = limit - pos
        sell_cap = limit + pos

        if ask is not None and fv - ask > edge_needed:
            qty = self.clip_size(fv - ask - edge_needed, buy_cap)
            if qty > 0:
                orders.append(Order(product, ask, qty))

        if bid is not None and bid - fv > edge_needed:
            qty = self.clip_size(bid - fv - edge_needed, sell_cap)
            if qty > 0:
                orders.append(Order(product, bid, -qty))

        return orders

    def run(self, state: TradingState):
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except:
                trader_data = {}

        result = {}
        pos = state.position

        extract_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hydro_od = state.order_depths.get("HYDROGEL_PACK")

        extract_mid = self.mid(extract_od) if extract_od else None
        hydro_mid = self.mid(hydro_od) if hydro_od else None

        # Hydrogel: rolling mean-reversion / light market making
        hydro_hist = trader_data.get("hydro_hist", [])
        if hydro_mid is not None:
            hydro_hist.append(hydro_mid)
            hydro_hist = hydro_hist[-HISTORY_LEN:]
            trader_data["hydro_hist"] = hydro_hist

            fair_h = sum(hydro_hist) / len(hydro_hist)
            result["HYDROGEL_PACK"] = self.take_edge(
                "HYDROGEL_PACK",
                hydro_od,
                fair_h,
                pos.get("HYDROGEL_PACK", 0),
                POSITION_LIMITS["HYDROGEL_PACK"],
                HYDRO_EDGE,
            )

        # Extract: simple market making around current mid
        if extract_od and extract_mid is not None:
            result["VELVETFRUIT_EXTRACT"] = self.take_edge(
                "VELVETFRUIT_EXTRACT",
                extract_od,
                extract_mid,
                pos.get("VELVETFRUIT_EXTRACT", 0),
                POSITION_LIMITS["VELVETFRUIT_EXTRACT"],
                1.0,
            )

        # Vouchers: compute raw IVs, fit smooth IV curve vs log-moneyness, trade outliers
        if extract_mid is not None:
            xs, ys = [], []
            mids = {}

            for sym, strike in STRIKES.items():
                od = state.order_depths.get(sym)
                if not od:
                    continue
                mid = self.mid(od)
                if mid is None:
                    continue
                iv = self.implied_vol(mid, extract_mid, strike, TTE)
                if iv is None:
                    continue
                x = math.log(strike / extract_mid)
                xs.append(x)
                ys.append(iv)
                mids[sym] = mid

            coeffs = self.fit_quadratic(xs, ys) if len(xs) >= 3 else (0.0, 0.0, 0.25)

            for sym, strike in STRIKES.items():
                od = state.order_depths.get(sym)
                if not od:
                    continue
                x = math.log(strike / extract_mid)
                sigma = max(0.05, min(1.50, self.eval_quad(coeffs, x)))
                fv = self.bs_call(extract_mid, strike, TTE, sigma)

                result[sym] = self.take_edge(
                    sym,
                    od,
                    fv,
                    pos.get(sym, 0),
                    POSITION_LIMITS[sym],
                    OPTION_EDGE,
                )

        return result, 0, json.dumps(trader_data)