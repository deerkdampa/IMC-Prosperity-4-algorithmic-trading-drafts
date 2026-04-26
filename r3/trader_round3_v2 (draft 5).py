
from datamodel import Order, TradingState
from collections import deque
from typing import Dict, List
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

    T = 5.0 / 365.0

    def __init__(self):
        self.extract_mids = deque(maxlen=80)
        self.hydro_mids = deque(maxlen=80)
        self.base_sigma = 0.23

    # ---------- helpers ----------
    def mid(self, depth):
        if depth is None:
            return None
        if depth.buy_orders and depth.sell_orders:
            return (max(depth.buy_orders) + min(depth.sell_orders)) / 2.0
        if depth.buy_orders:
            return float(max(depth.buy_orders))
        if depth.sell_orders:
            return float(min(depth.sell_orders))
        return None

    def best_bid_ask(self, depth):
        bid = max(depth.buy_orders) if depth and depth.buy_orders else None
        ask = min(depth.sell_orders) if depth and depth.sell_orders else None
        return bid, ask

    def cdf(self, x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def clamp(self, x, lo, hi):
        return max(lo, min(hi, x))

    def can_buy(self, product, pos):
        return max(0, self.LIMITS[product] - pos)

    def can_sell(self, product, pos):
        return max(0, self.LIMITS[product] + pos)

    def bs_call(self, s, k, t, sigma):
        intrinsic = max(0.0, s - k)
        if s <= 0 or k <= 0 or t <= 0 or sigma <= 1e-9:
            return intrinsic
        root_t = math.sqrt(t)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * root_t)
        d2 = d1 - sigma * root_t
        return s * self.cdf(d1) - k * self.cdf(d2)

    def bs_delta(self, s, k, t, sigma):
        if s <= 0 or k <= 0 or t <= 0:
            return 1.0 if s > k else 0.0
        sigma = max(sigma, 1e-6)
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * math.sqrt(t))
        return self.cdf(d1)

    def recent_vol(self, mids):
        if len(mids) < 8:
            return self.base_sigma
        rets = []
        for i in range(1, len(mids)):
            a = mids[i - 1]
            b = mids[i]
            if a > 0 and b > 0:
                rets.append(math.log(b / a))
        if len(rets) < 5:
            return self.base_sigma
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
        tick_vol = math.sqrt(max(var, 1e-12))
        annualized = tick_vol * math.sqrt(10000)
        return self.clamp(annualized, 0.10, 0.40)

    def take_buy(self, product, depth, fair, pos, orders, max_qty, edge=0.0):
        for ask in sorted(depth.sell_orders):
            if ask > fair - edge:
                break
            avail = -depth.sell_orders[ask]
            qty = min(avail, self.can_buy(product, pos), max_qty)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                pos += qty
                max_qty -= qty
                if max_qty <= 0:
                    break
        return pos

    def take_sell(self, product, depth, fair, pos, orders, max_qty, edge=0.0):
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < fair + edge:
                break
            avail = depth.buy_orders[bid]
            qty = min(avail, self.can_sell(product, pos), max_qty)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                pos -= qty
                max_qty -= qty
                if max_qty <= 0:
                    break
        return pos

    # ---------- product logic ----------
    def hydro_strategy(self, depth, pos):
        orders = []
        mid = self.mid(depth)
        if mid is not None:
            self.hydro_mids.append(mid)

        anchor = 10000.0
        if len(self.hydro_mids) >= 6:
            anchor = 0.8 * 10000.0 + 0.2 * (sum(self.hydro_mids[-6:]) / 6.0)

        fair = anchor - self.clamp(pos / 45.0, -3.0, 3.0)

        pos = self.take_buy("HYDROGEL_PACK", depth, fair, pos, orders, max_qty=10, edge=1.0)
        pos = self.take_sell("HYDROGEL_PACK", depth, fair, pos, orders, max_qty=10, edge=1.0)

        bid, ask = self.best_bid_ask(depth)
        if bid is not None and ask is not None:
            skew = self.clamp(pos / 55.0, -2.0, 2.0)
            mm_bid = int(math.floor(fair - 4 - skew))
            mm_ask = int(math.ceil(fair + 4 - skew))
            mm_bid = min(mm_bid, bid + 1)
            mm_ask = max(mm_ask, ask - 1)
            if mm_ask <= mm_bid:
                mm_ask = mm_bid + 1
            buy_qty = min(6, self.can_buy("HYDROGEL_PACK", pos))
            sell_qty = min(6, self.can_sell("HYDROGEL_PACK", pos))
            if buy_qty > 0:
                orders.append(Order("HYDROGEL_PACK", mm_bid, buy_qty))
            if sell_qty > 0:
                orders.append(Order("HYDROGEL_PACK", mm_ask, -sell_qty))

        return orders

    def extract_strategy(self, depth, pos):
        orders = []
        mid = self.mid(depth)
        if mid is None:
            return orders, None

        self.extract_mids.append(mid)

        ema = mid
        if len(self.extract_mids) >= 4:
            alpha = 0.20
            ema = self.extract_mids[0]
            for m in list(self.extract_mids)[1:]:
                ema = alpha * m + (1 - alpha) * ema

        recent = list(self.extract_mids)[-8:]
        trend = 0.0
        if len(recent) >= 4:
            trend = (recent[-1] - recent[0]) / max(1, len(recent) - 1)

        fair = ema + self.clamp(1.1 * trend, -2.0, 2.0)
        fair -= self.clamp(pos / 70.0, -2.0, 2.0)

        pos = self.take_buy("VELVETFRUIT_EXTRACT", depth, fair, pos, orders, max_qty=14, edge=1.0)
        pos = self.take_sell("VELVETFRUIT_EXTRACT", depth, fair, pos, orders, max_qty=14, edge=1.0)

        bid, ask = self.best_bid_ask(depth)
        if bid is not None and ask is not None:
            skew = self.clamp(pos / 80.0, -2.0, 2.0)
            mm_bid = int(math.floor(fair - 2 - skew))
            mm_ask = int(math.ceil(fair + 2 - skew))
            mm_bid = min(mm_bid, bid + 1)
            mm_ask = max(mm_ask, ask - 1)
            if mm_ask <= mm_bid:
                mm_ask = mm_bid + 1
            buy_qty = min(8, self.can_buy("VELVETFRUIT_EXTRACT", pos))
            sell_qty = min(8, self.can_sell("VELVETFRUIT_EXTRACT", pos))
            if buy_qty > 0:
                orders.append(Order("VELVETFRUIT_EXTRACT", mm_bid, buy_qty))
            if sell_qty > 0:
                orders.append(Order("VELVETFRUIT_EXTRACT", mm_ask, -sell_qty))

        return orders, fair

    def voucher_fair(self, s, k, sigma):
        intrinsic = max(0.0, s - k)
        bs = self.bs_call(s, k, self.T, sigma)

        moneyness = s - k
        if moneyness >= 700:
            return intrinsic
        if moneyness >= 350:
            return max(intrinsic, 0.90 * intrinsic + 0.10 * bs)
        if moneyness >= 150:
            return max(intrinsic, 0.62 * intrinsic + 0.38 * bs)
        if moneyness >= -100:
            return bs
        return max(0.0, bs)

    def voucher_strategy(self, state, extract_mid):
        result = {}
        hedge_delta = 0.0

        if extract_mid is None:
            return result, hedge_delta

        sigma_base = self.recent_vol(self.extract_mids)
        self.base_sigma = 0.85 * self.base_sigma + 0.15 * sigma_base

        priority = ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300"]
        secondary = ["VEV_4500", "VEV_5400", "VEV_5500"]
        ignore_if_tight = ["VEV_4000", "VEV_6000", "VEV_6500"]

        for sym, k in self.STRIKES.items():
            depth = state.order_depths.get(sym)
            if depth is None:
                continue

            mid = self.mid(depth)
            if mid is None:
                result[sym] = []
                continue

            pos = state.position.get(sym, 0)
            orders = []
            intrinsic = max(0.0, extract_mid - k)

            vol_tilt = 1.0
            if sym in ("VEV_5400", "VEV_5500"):
                vol_tilt = 1.05
            elif sym in ("VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100"):
                vol_tilt = 0.97
            elif sym in ("VEV_6000", "VEV_6500"):
                vol_tilt = 1.10

            sigma = self.clamp(self.base_sigma * vol_tilt, 0.10, 0.38)
            fair = self.voucher_fair(extract_mid, k, sigma)

            # Keep deep ITM / deep OTM quiet unless there is obvious edge.
            if sym in ignore_if_tight:
                if sym == "VEV_4000" and abs(mid - intrinsic) <= 1.0:
                    hedge_delta += pos * self.bs_delta(extract_mid, k, self.T, sigma)
                    result[sym] = []
                    continue
                if sym in ("VEV_6000", "VEV_6500") and mid <= 1.0:
                    hedge_delta += pos * self.bs_delta(extract_mid, k, self.T, sigma)
                    result[sym] = []
                    continue

            mis = fair - mid
            bid, ask = self.best_bid_ask(depth)
            spread = 2.0 if bid is None or ask is None else max(1.0, ask - bid)
            confidence = self.clamp(abs(mis) / (spread + 1.0), 0.0, 2.0) / 2.0

            if sym in priority:
                size_cap = 22
                scale = 0.18
            elif sym in secondary:
                size_cap = 12
                scale = 0.10
            else:
                size_cap = 5
                scale = 0.05

            if abs(mis) >= max(1.5, 0.8 * spread):
                size = int(min(size_cap, self.LIMITS[sym] * scale * (0.30 + confidence)))
                if abs(mis) >= 4.0 and sym in priority:
                    size = min(size_cap, max(size, 14))

                if size > 0:
                    if mis > 0:
                        pos = self.take_buy(sym, depth, fair, pos, orders, size, edge=0.0)
                    else:
                        pos = self.take_sell(sym, depth, fair, pos, orders, size, edge=0.0)

            # Passive quoting only where it matters.
            if sym in priority + ["VEV_4500"]:
                if bid is not None and ask is not None:
                    skew = self.clamp(pos / 140.0, -2.0, 2.0)
                    mm_bid = int(math.floor(fair - max(1.0, spread / 2.0) - skew))
                    mm_ask = int(math.ceil(fair + max(1.0, spread / 2.0) - skew))
                    mm_bid = min(mm_bid, bid + 1)
                    mm_ask = max(mm_ask, ask - 1)
                    if mm_ask <= mm_bid:
                        mm_ask = mm_bid + 1

                    quote_qty = 4 if sym == "VEV_4500" else 5
                    if sym == "VEV_5300":
                        quote_qty = 6

                    buy_qty = min(quote_qty, self.can_buy(sym, pos))
                    sell_qty = min(quote_qty, self.can_sell(sym, pos))
                    if buy_qty > 0:
                        orders.append(Order(sym, mm_bid, buy_qty))
                    if sell_qty > 0:
                        orders.append(Order(sym, mm_ask, -sell_qty))

            result[sym] = orders
            hedge_delta += pos * self.bs_delta(extract_mid, k, self.T, sigma)

        return result, hedge_delta

    # ---------- main ----------
    def run(self, state: TradingState):
        try:
            result = {}

            ext_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
            hyd_depth = state.order_depths.get("HYDROGEL_PACK")
            extract_mid = self.mid(ext_depth) if ext_depth else None

            if hyd_depth is not None:
                pos_h = state.position.get("HYDROGEL_PACK", 0)
                result["HYDROGEL_PACK"] = self.hydro_strategy(hyd_depth, pos_h)

            voucher_orders, hedge_delta = self.voucher_strategy(state, extract_mid)
            result.update(voucher_orders)

            if ext_depth is not None and extract_mid is not None:
                pos_e = state.position.get("VELVETFRUIT_EXTRACT", 0)
                ext_orders, fair_ext = self.extract_strategy(ext_depth, pos_e)

                # Less aggressive than the previous version: keep some directional exposure.
                target = int(self.clamp(-0.60 * hedge_delta, -200, 200))
                gap = target - pos_e

                # Hedge toward the target only when there is a meaningful imbalance.
                if gap > 12:
                    for ask, vol in sorted(ext_depth.sell_orders.items()):
                        qty = min(-vol, gap, self.can_buy("VELVETFRUIT_EXTRACT", pos_e))
                        if qty > 0:
                            ext_orders.append(Order("VELVETFRUIT_EXTRACT", ask, qty))
                            pos_e += qty
                            gap -= qty
                            if gap <= 0:
                                break
                elif gap < -12:
                    for bid, vol in sorted(ext_depth.buy_orders.items(), reverse=True):
                        qty = min(vol, -gap, self.can_sell("VELVETFRUIT_EXTRACT", pos_e))
                        if qty > 0:
                            ext_orders.append(Order("VELVETFRUIT_EXTRACT", bid, -qty))
                            pos_e -= qty
                            gap += qty
                            if gap >= 0:
                                break

                result["VELVETFRUIT_EXTRACT"] = ext_orders

            return result, 0, json.dumps({})
        except Exception:
            return {}, 0, json.dumps({})
