
from datamodel import Order, TradingState
from collections import deque
import math, json

class Trader:

    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
    }

    STRIKES = {f"VEV_{k}": k for k in [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]}
    for k in STRIKES:
        LIMITS[k] = 300

    PRIORITY = ["VEV_5000","VEV_5100","VEV_5200","VEV_5300"]

    T = 5.0/365.0

    def __init__(self):
        self.extract = deque(maxlen=60)
        self.sigma = 0.25

    def mid(self, d):
        if d.buy_orders and d.sell_orders:
            return (max(d.buy_orders)+min(d.sell_orders))/2
        return None

    def cdf(self,x):
        return 0.5*(1+math.erf(x/math.sqrt(2)))

    def bs_call(self,s,k):
        if s<=0 or k<=0: return 0
        sig = self.sigma
        t = self.T
        d1 = (math.log(s/k)+0.5*sig*sig*t)/(sig*math.sqrt(t))
        d2 = d1 - sig*math.sqrt(t)
        return s*self.cdf(d1)-k*self.cdf(d2)

    def bs_delta(self,s,k):
        sig = self.sigma
        t = self.T
        d1 = (math.log(s/k)+0.5*sig*sig*t)/(sig*math.sqrt(t))
        return self.cdf(d1)

    def run(self, state: TradingState):
        try:
            result = {}
            pos = state.position

            ext_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
            ext_mid = self.mid(ext_depth) if ext_depth else None

            hedge = 0

            # ---------- VOUCHERS ----------
            if ext_mid:
                self.extract.append(ext_mid)

                for sym, K in self.STRIKES.items():

                    # Skip garbage strikes (fix #1)
                    if sym not in self.PRIORITY:
                        continue

                    depth = state.order_depths.get(sym)
                    if not depth:
                        continue

                    p = pos.get(sym,0)
                    orders = []

                    intrinsic = max(0, ext_mid-K)

                    # safer pricing (fix #2)
                    if intrinsic > 600:
                        fair = intrinsic
                    else:
                        fair = self.bs_call(ext_mid,K)

                    mid = self.mid(depth)
                    if not mid:
                        continue

                    mis = fair - mid
                    spread = 2

                    # aggressive but capped (fix #3)
                    strength = min(1.0, abs(mis)/(spread+1))
                    size = int(self.LIMITS[sym] * strength * 0.7)

                    # conviction override (kept)
                    if abs(mis) > 4:
                        size = min(self.LIMITS[sym], max(size, 40))

                    # prevent runaway positions (fix #4)
                    if abs(p) > 200:
                        size = int(size * 0.3)

                    if size > 0:
                        if mis > 0:
                            for ask, vol in depth.sell_orders.items():
                                if ask <= fair:
                                    qty = min(-vol, size, self.LIMITS[sym]-p)
                                    if qty>0:
                                        orders.append(Order(sym, ask, qty))
                                        p += qty
                        else:
                            for bid, vol in depth.buy_orders.items():
                                if bid >= fair:
                                    qty = min(vol, size, self.LIMITS[sym]+p)
                                    if qty>0:
                                        orders.append(Order(sym, bid, -qty))
                                        p -= qty

                    result[sym] = orders

                    hedge += pos.get(sym,0)*self.bs_delta(ext_mid,K)

            # ---------- EXTRACT (hedge but not kill edge) ----------
            if ext_depth and ext_mid:
                p = pos.get("VELVETFRUIT_EXTRACT",0)
                orders = []

                target = int(-0.5 * hedge)  # balanced hedge

                gap = target - p

                if gap > 0:
                    for ask, vol in ext_depth.sell_orders.items():
                        qty = min(-vol, gap, self.LIMITS["VELVETFRUIT_EXTRACT"]-p)
                        if qty>0:
                            orders.append(Order("VELVETFRUIT_EXTRACT", ask, qty))
                            p += qty
                else:
                    for bid, vol in ext_depth.buy_orders.items():
                        qty = min(vol, -gap, self.LIMITS["VELVETFRUIT_EXTRACT"]+p)
                        if qty>0:
                            orders.append(Order("VELVETFRUIT_EXTRACT", bid, -qty))
                            p -= qty

                result["VELVETFRUIT_EXTRACT"] = orders

            return result, 0, json.dumps({})

        except Exception:
            return {}, 0, json.dumps({})
