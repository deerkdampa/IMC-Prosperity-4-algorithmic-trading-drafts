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
        self.sigma = 0.23

    def mid(self, d):
        if d is None:
            return None
        b = max(d.buy_orders) if d.buy_orders else None
        a = min(d.sell_orders) if d.sell_orders else None
        if b is not None and a is not None: return (b+a)/2
        if b is not None: return float(b)
        if a is not None: return float(a)
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
    def take_buy(self, p, d, fair, edge, pos, out, max_qty=None):
        for ask in sorted(d.sell_orders):
            if ask > fair-edge:
                break
            qty = min(-d.sell_orders[ask], self.can_buy(p, pos))
            if max_qty is not None: qty = min(qty, max_qty)
            if qty > 0:
                out.append(Order(p, ask, qty)); pos += qty
                if max_qty is not None:
                    max_qty -= qty
                    if max_qty <= 0: break
        return pos

    def take_sell(self, p, d, fair, edge, pos, out, max_qty=None):
        for bid in sorted(d.buy_orders, reverse=True):
            if bid < fair+edge:
                break
            qty = min(d.buy_orders[bid], self.can_sell(p, pos))
            if max_qty is not None: qty = min(qty, max_qty)
            if qty > 0:
                out.append(Order(p, bid, -qty)); pos -= qty
                if max_qty is not None:
                    max_qty -= qty
                    if max_qty <= 0: break
        return pos

    def mm(self, p, d, fair, pos, size, spread, out):
        b = max(d.buy_orders) if d.buy_orders else None
        a = min(d.sell_orders) if d.sell_orders else None
        skew = int(round(pos/max(1, self.LIMITS[p]) * 4))
        bid = int(math.floor(fair - spread - skew))
        ask = int(math.ceil(fair + spread - skew))
        if b is not None: bid = min(bid, b+1)
        if a is not None: ask = max(ask, a-1)
        if ask <= bid: ask = bid + 1
        if self.can_buy(p, pos) > 0: out.append(Order(p, bid, min(size, self.can_buy(p, pos))))
        if self.can_sell(p, pos) > 0: out.append(Order(p, ask, -min(size, self.can_sell(p, pos))))
    def run(self, state: TradingState):
        try:
            res = {}
            ext_d = state.order_depths.get("VELVETFRUIT_EXTRACT")
            hyd_d = state.order_depths.get("HYDROGEL_PACK")
            emid = self.mid(ext_d)
            hmid = self.mid(hyd_d)
            if emid is not None: self.extract.append(emid)
            if hmid is not None: self.hydro.append(hmid)
            if len(self.extract) >= 8:
                rets = [math.log(self.extract[i]/self.extract[i-1]) for i in range(1,len(self.extract)) if self.extract[i-1] > 0 and self.extract[i] > 0]
                if len(rets) >= 5:
                    m = sum(rets)/len(rets)
                    v = sum((r-m)**2 for r in rets)/max(1, len(rets)-1)
                    self.sigma = max(0.08, min(0.80, math.sqrt(max(v,1e-12))*math.sqrt(10000)))

            if hyd_d is not None:
                pos = state.position.get("HYDROGEL_PACK", 0)
                orders = []
                fair = 10000.0 if len(self.hydro) < 5 else 0.5*10000.0 + 0.5*(sum(list(self.hydro)[-5:])/5.0)
                pos = self.take_buy("HYDROGEL_PACK", hyd_d, fair, 1.0, pos, orders)
                pos = self.take_sell("HYDROGEL_PACK", hyd_d, fair, 1.0, pos, orders)
                self.mm("HYDROGEL_PACK", hyd_d, fair, pos, 14, 7.0, orders)
                res["HYDROGEL_PACK"] = orders

            hedge = 0.0
            if emid is not None:
                for sym, k in self.STRIKES.items():
                    d = state.order_depths.get(sym)
                    if d is None: continue
                    mid = self.mid(d)
                    if mid is None: continue
                    pos = state.position.get(sym, 0)
                    orders = []
                    intrinsic = max(0.0, emid - k)
                    fair = intrinsic if emid - k >= 700 else self.bs_call(emid, k, self.TTE, self.sigma)
                    if emid - k >= 300:
                        fair = max(fair, 0.85*intrinsic + 0.15*fair)
                    b = max(d.buy_orders) if d.buy_orders else None
                    a = min(d.sell_orders) if d.sell_orders else None
                    spr = (a-b) if b is not None and a is not None else 2
                    mis = fair - mid
                    trade = 0
                    if abs(mis) >= max(1.0, spr/2):
                        trade = min(40, max(1, int(self.LIMITS[sym] * min(1.0, abs(mis)/(spr+1)) * 0.10)))
                    if trade > 0:
                        if mis > 0: pos = self.take_buy(sym, d, fair, 0.2, pos, orders, trade)
                        else: pos = self.take_sell(sym, d, fair, -0.2, pos, orders, trade)
                    if k <= 5500:
                        self.mm(sym, d, fair, pos, 6 if k >= 5400 else 8, max(1.0, spr/2), orders)
                    res[sym] = orders
                    delta = self.bs_delta(emid, k, self.TTE, max(0.10, self.sigma))
                    if emid - k >= 700: delta = 1.0
                    elif emid - k >= 300: delta = max(delta, 0.85)
                    hedge += state.position.get(sym, 0) * delta

            if ext_d is not None and emid is not None:
                pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
                orders = []
                ema = emid
                if len(self.extract) >= 3:
                    alpha = 0.22
                    ema = list(self.extract)[0]
                    for m in list(self.extract)[1:]:
                        ema = alpha*m + (1-alpha)*ema
                fair = ema
                if len(self.extract) >= 6:
                    recent = list(self.extract)[-6:]
                    fair += max(-3.0, min(3.0, 1.25*((recent[-1]-recent[0])/5.0)))
                target = max(-200, min(200, int(round(-hedge))))
                fair += max(-2.0, min(2.0, (target-pos)/45.0))
                pos = self.take_buy("VELVETFRUIT_EXTRACT", ext_d, fair, 1.0, pos, orders)
                pos = self.take_sell("VELVETFRUIT_EXTRACT", ext_d, fair, 1.0, pos, orders)
                self.mm("VELVETFRUIT_EXTRACT", ext_d, fair, pos, 8 if abs(target-pos) < 80 else 6, 3.0, orders)
                res["VELVETFRUIT_EXTRACT"] = orders

            return res, 0, json.dumps({"extract": list(self.extract), "hydro": list(self.hydro), "sigma": self.sigma}, separators=(",", ":"))
        except Exception:
            return {}, 0, json.dumps({})
