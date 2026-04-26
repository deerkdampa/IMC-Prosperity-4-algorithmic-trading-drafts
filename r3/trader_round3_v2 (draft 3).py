
from datamodel import Order, TradingState
from typing import Dict, List
from collections import deque
import math
import json

class Trader:

    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
    }

    PRIORITY_STRIKES = ["VEV_5000","VEV_5100","VEV_5200","VEV_5300"]

    STRIKES = {f"VEV_{k}": k for k in [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]}

    for k in STRIKES:
        LIMITS[k] = 300

    def __init__(self):
        self.extract_prices = deque(maxlen=60)
        self.hydro_prices = deque(maxlen=60)
        self.sigma = 0.25
        self.T = 5.0/365.0

    def mid(self, depth):
        if depth.buy_orders and depth.sell_orders:
            return (max(depth.buy_orders) + min(depth.sell_orders)) / 2
        return None

    def norm_cdf(self, x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def bs_call(self, S, K, T, sigma):
        if S <= 0 or K <= 0:
            return 0
        d1 = (math.log(S/K) + 0.5*sigma*sigma*T) / (sigma*math.sqrt(T))
        d2 = d1 - sigma*math.sqrt(T)
        return S*self.norm_cdf(d1) - K*self.norm_cdf(d2)

    def bs_delta(self, S, K, T, sigma):
        if S <= 0 or K <= 0:
            return 0
        d1 = (math.log(S/K) + 0.5*sigma*sigma*T) / (sigma*math.sqrt(T))
        return self.norm_cdf(d1)

    def run(self, state: TradingState) -> Dict[str, List[Order]]:
        try:
            result = {}
            pos = state.position

            # ---------------- HYDRO ----------------
            if "HYDROGEL_PACK" in state.order_depths:
                depth = state.order_depths["HYDROGEL_PACK"]
                orders = []
                p = pos.get("HYDROGEL_PACK", 0)

                mid = self.mid(depth)
                if mid:
                    self.hydro_prices.append(mid)
                    fair = sum(self.hydro_prices)/len(self.hydro_prices)
                else:
                    fair = 10000

                for ask, vol in depth.sell_orders.items():
                    if ask < fair:
                        qty = min(-vol, self.LIMITS["HYDROGEL_PACK"] - p)
                        if qty > 0:
                            orders.append(Order("HYDROGEL_PACK", ask, qty))
                            p += qty

                for bid, vol in depth.buy_orders.items():
                    if bid > fair:
                        qty = min(vol, self.LIMITS["HYDROGEL_PACK"] + p)
                        if qty > 0:
                            orders.append(Order("HYDROGEL_PACK", bid, -qty))
                            p -= qty

                result["HYDROGEL_PACK"] = orders

            # ---------------- EXTRACT ----------------
            hedge = 0

            if "VELVETFRUIT_EXTRACT" in state.order_depths:
                ext_depth = state.order_depths["VELVETFRUIT_EXTRACT"]
                ext_mid = self.mid(ext_depth)

                if ext_mid:
                    self.extract_prices.append(ext_mid)

                    for sym in self.PRIORITY_STRIKES:
                        if sym not in state.order_depths:
                            continue

                        depth = state.order_depths[sym]
                        orders = []
                        p = pos.get(sym, 0)
                        K = self.STRIKES[sym]

                        intrinsic = max(0, ext_mid - K)
                        fair = intrinsic if intrinsic > 600 else self.bs_call(ext_mid, K, self.T, self.sigma)

                        mid = self.mid(depth)
                        if mid is None:
                            continue

                        mis = fair - mid
                        spread = 2

                        strength = min(1.0, abs(mis)/(spread+1))

                        size = int(self.LIMITS[sym] * strength * 0.8)

                        if abs(mis) > 3:
                            size = self.LIMITS[sym]

                        if size > 0:
                            if mis > 0:
                                for ask, vol in depth.sell_orders.items():
                                    if ask <= fair:
                                        qty = min(-vol, size, self.LIMITS[sym] - p)
                                        if qty > 0:
                                            orders.append(Order(sym, ask, qty))
                                            p += qty
                            else:
                                for bid, vol in depth.buy_orders.items():
                                    if bid >= fair:
                                        qty = min(vol, size, self.LIMITS[sym] + p)
                                        if qty > 0:
                                            orders.append(Order(sym, bid, -qty))
                                            p -= qty

                        result[sym] = orders

                        delta = self.bs_delta(ext_mid, K, self.T, self.sigma)
                        hedge += pos.get(sym, 0) * delta

                    # -------- hedge extract --------
                    p_ext = pos.get("VELVETFRUIT_EXTRACT", 0)
                    target = int(-0.4 * hedge)
                    gap = target - p_ext
                    ext_orders = []

                    if gap > 0:
                        for ask, vol in ext_depth.sell_orders.items():
                            qty = min(-vol, gap, self.LIMITS["VELVETFRUIT_EXTRACT"] - p_ext)
                            if qty > 0:
                                ext_orders.append(Order("VELVETFRUIT_EXTRACT", ask, qty))
                                p_ext += qty
                    else:
                        for bid, vol in ext_depth.buy_orders.items():
                            qty = min(vol, -gap, self.LIMITS["VELVETFRUIT_EXTRACT"] + p_ext)
                            if qty > 0:
                                ext_orders.append(Order("VELVETFRUIT_EXTRACT", bid, -qty))
                                p_ext -= qty

                    result["VELVETFRUIT_EXTRACT"] = ext_orders

            return result, 0, json.dumps({})

        except Exception:
            return {}, 0, json.dumps({})
