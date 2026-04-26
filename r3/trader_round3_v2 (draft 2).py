
from datamodel import OrderDepth, TradingState, Order
from collections import deque
import json, math

class Trader:
    LIMITS = {"HYDROGEL_PACK":200, "VELVETFRUIT_EXTRACT":200,
              "VEV_4000":300, "VEV_4500":300, "VEV_5000":300, "VEV_5100":300,
              "VEV_5200":300, "VEV_5300":300, "VEV_5400":300, "VEV_5500":300,
              "VEV_6000":300, "VEV_6500":300}

    STRIKES = {f"VEV_{k}": k for k in [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]}
    TTE = 5.0/365.0

    def __init__(self):
        self.extract = deque(maxlen=60)
        self.hydro = deque(maxlen=60)
        self.sigma = 0.25

    def mid(self, d):
        if d is None: return None
        b = max(d.buy_orders) if d.buy_orders else None
        a = min(d.sell_orders) if d.sell_orders else None
        if b and a: return (b+a)/2
        if b: return float(b)
        if a: return float(a)
        return None

    def cdf(self, x):
        return 0.5*(1+math.erf(x/math.sqrt(2)))

    def bs_call(self, s, k, t, sig):
        if s<=0 or k<=0 or t<=0 or sig<=1e-9:
            return max(0.0, s-k)
        rt = math.sqrt(t)
        d1 = (math.log(s/k) + 0.5*sig*sig*t)/(sig*rt)
        d2 = d1 - sig*rt
        return s*self.cdf(d1) - k*self.cdf(d2)

    def bs_delta(self, s, k, t, sig):
        if s<=0 or k<=0 or t<=0:
            return 1.0 if s>k else 0.0
        sig = max(sig, 1e-6)
        d1 = (math.log(s/k) + 0.5*sig*sig*t)/(sig*math.sqrt(t))
        return self.cdf(d1)

    def can_buy(self, p, pos): return max(0, self.LIMITS[p]-pos)
    def can_sell(self, p, pos): return max(0, self.LIMITS[p]+pos)

    def take_buy(self, p, d, fair, pos, out, max_qty):
        for ask in sorted(d.sell_orders):
            if ask > fair: break
            qty = min(-d.sell_orders[ask], self.can_buy(p, pos), max_qty)
            if qty > 0:
                out.append(Order(p, ask, qty))
                pos += qty
                max_qty -= qty
                if max_qty <= 0: break
        return pos

    def take_sell(self, p, d, fair, pos, out, max_qty):
        for bid in sorted(d.buy_orders, reverse=True):
            if bid < fair: break
            qty = min(d.buy_orders[bid], self.can_sell(p, pos), max_qty)
            if qty > 0:
                out.append(Order(p, bid, -qty))
                pos -= qty
                max_qty -= qty
                if max_qty <= 0: break
        return pos

    def run(self, state: TradingState):
        try:
            res = {}

            ext_d = state.order_depths.get("VELVETFRUIT_EXTRACT")
            hyd_d = state.order_depths.get("HYDROGEL_PACK")

            emid = self.mid(ext_d)
            hmid = self.mid(hyd_d)

            if emid: self.extract.append(emid)
            if hmid: self.hydro.append(hmid)

            # HYDRO
            if hyd_d:
                pos = state.position.get("HYDROGEL_PACK", 0)
                orders = []
                fair = 10000 if len(self.hydro) < 5 else sum(self.hydro)/len(self.hydro)
                pos = self.take_buy("HYDROGEL_PACK", hyd_d, fair-1, pos, orders, 50)
                pos = self.take_sell("HYDROGEL_PACK", hyd_d, fair+1, pos, orders, 50)
                res["HYDROGEL_PACK"] = orders

            hedge = 0.0

            # VOUCHERS
            if emid:
                for sym, k in self.STRIKES.items():
                    d = state.order_depths.get(sym)
                    if not d: continue

                    pos = state.position.get(sym, 0)
                    orders = []

                    intrinsic = max(0, emid-k)

                    # crude smile
                    sigma = self.sigma
                    if k >= 6000: sigma *= 1.3
                    if k <= 5000: sigma *= 0.9

                    fair = intrinsic if emid-k > 600 else self.bs_call(emid, k, self.TTE, sigma)

                    mid = self.mid(d)
                    if not mid: continue

                    mis = fair - mid
                    spread = 2

                    strength = min(1.0, abs(mis)/(spread+1))

                    size = int(self.LIMITS[sym] * strength * 0.5)

                    if size > 0:
                        if mis > 0:
                            pos = self.take_buy(sym, d, fair, pos, orders, size)
                        else:
                            pos = self.take_sell(sym, d, fair, pos, orders, size)

                    res[sym] = orders

                    delta = self.bs_delta(emid, k, self.TTE, sigma)
                    hedge += state.position.get(sym, 0) * delta

            # EXTRACT
            if ext_d and emid:
                pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
                orders = []

                fair = emid

                target = int(-0.6 * hedge)

                gap = target - pos

                if gap > 0:
                    pos = self.take_buy("VELVETFRUIT_EXTRACT", ext_d, fair, pos, orders, min(100, gap))
                else:
                    pos = self.take_sell("VELVETFRUIT_EXTRACT", ext_d, fair, pos, orders, min(100, -gap))

                res["VELVETFRUIT_EXTRACT"] = orders

            return res, 0, json.dumps({})
        except Exception:
            return {}, 0, json.dumps({})
