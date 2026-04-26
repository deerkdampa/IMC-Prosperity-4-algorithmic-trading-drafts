"""
IMC Prosperity 4 – Round 3 Trader
Products: HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VEV_4000…VEV_6500

Strategy Summary:
  HYDROGEL_PACK   → Mean-reversion to 10 000, inventory-skewed market making
  VELVETFRUIT_EXTRACT → EMA fair value + passive quoting; position reserved for delta hedge
  VEV (ITM: 4000–4500) → Pure basis arb (buy if ask < intrinsic)
  VEV (Near/ATM: 5000–5300) → BS fair-value arb, IV-deviation sizing
  VEV (OTM: 5400–5500) → Vol-arb with reduced size
  VEV (Deep OTM: 6000–6500) → Ignore (noise, ½-shell ticks only)
"""

import math
import collections
from datamodel import OrderDepth, TradingState, Order


# ──────────────────────────────────────────
#  Black-Scholes helpers (no numpy needed)
# ──────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def bs_call(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """European call price via Black-Scholes."""
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Delta of a European call."""
    if T <= 0:
        return 1.0 if S > K else 0.0
    if sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


def implied_vol(S: float, K: float, T: float, market_price: float,
                r: float = 0.0, fallback: float = 0.24) -> float:
    """
    Newton-Raphson IV solver.  Returns fallback if the option is effectively
    intrinsic (deep ITM with no extrinsic) or if convergence fails.
    """
    intrinsic = max(0.0, S - K)
    if market_price <= intrinsic + 0.5:
        return 0.0          # deep ITM / no extrinsic – skip IV
    sigma = fallback
    for _ in range(60):
        price = bs_call(S, K, T, sigma, r)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        vega = S * _norm_cdf(d1) * math.sqrt(T)
        if abs(vega) < 1e-12:
            break
        diff = price - market_price
        sigma -= diff / vega
        sigma = max(0.005, min(sigma, 5.0))
        if abs(diff) < 1e-5:
            break
    return sigma


# ──────────────────────────────────────────
#  Trader class
# ──────────────────────────────────────────

class Trader:

    # ── constants ──────────────────────────
    HYDROGEL_FAIR   = 10_000
    HYDROGEL_LIMIT  = 200
    EXTRACT_LIMIT   = 200
    VOUCHER_LIMIT   = 300

    # Round 3 TTE: 5 days (per spec: TTE=7 in R1, 6 in R2, 5 in R3)
    TTE             = 5.0 / 365.0
    GLOBAL_IV       = 0.24      # calibrated from historical days 0-2

    STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
        "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
        "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000,
        "VEV_6500": 6500,
    }
    # Liquid strikes used for IV surface fitting (sufficient extrinsic, active book)
    IV_FIT_STRIKES  = {"VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"}
    # Deep ITM: trade as pure intrinsic basis (no extrinsic, delta≈1)
    DEEP_ITM        = {"VEV_4000", "VEV_4500"}
    # Deep OTM: skip (½-shell noise)
    DEEP_OTM        = {"VEV_6000", "VEV_6500"}

    def __init__(self):
        self._ema_extract  = None
        self._ema_alpha    = 2 / (20 + 1)          # 20-period EMA
        self._extract_hist = collections.deque(maxlen=100)

        # Per-voucher IV misalignment tracking for stop-loss-on-time
        self._iv_signal_age: dict[str, int] = {s: 0 for s in self.STRIKES}

    # ── utilities ──────────────────────────

    @staticmethod
    def _mid(depth: OrderDepth):
        if depth.buy_orders and depth.sell_orders:
            return (max(depth.buy_orders) + min(depth.sell_orders)) / 2
        return None

    @staticmethod
    def _best_bid(depth: OrderDepth):
        return max(depth.buy_orders) if depth.buy_orders else None

    @staticmethod
    def _best_ask(depth: OrderDepth):
        return min(depth.sell_orders) if depth.sell_orders else None

    def _update_ema(self, price: float):
        if self._ema_extract is None:
            self._ema_extract = price
        else:
            self._ema_extract = (self._ema_alpha * price
                                 + (1 - self._ema_alpha) * self._ema_extract)

    def _fit_iv(self, S: float, depths: dict) -> float:
        """
        Compute a weighted-average implied volatility from the liquid OTM/ATM
        strikes to get the current 'surface IV'. Falls back to GLOBAL_IV.
        """
        ivs, weights = [], []
        for sym in self.IV_FIT_STRIKES:
            if sym not in depths:
                continue
            d = depths[sym]
            mid = self._mid(d)
            if mid is None:
                continue
            K = self.STRIKES[sym]
            iv = implied_vol(S, K, self.TTE, mid, fallback=self.GLOBAL_IV)
            if 0.05 < iv < 1.5:
                # weight by liquidity proxy: total best-level volume
                vol_wt = (abs(list(d.buy_orders.values())[0]) if d.buy_orders else 0
                          + abs(list(d.sell_orders.values())[0]) if d.sell_orders else 0)
                ivs.append(iv)
                weights.append(max(vol_wt, 1))
        if not ivs:
            return self.GLOBAL_IV
        return sum(iv * w for iv, w in zip(ivs, weights)) / sum(weights)

    # ── HYDROGEL_PACK ──────────────────────

    def _trade_hydrogel(self, depth: OrderDepth, position: int) -> list:
        orders = []
        fair = self.HYDROGEL_FAIR
        lim  = self.HYDROGEL_LIMIT

        # inventory skew: shift fair by up to ±10 to lean against the position
        skew = -position * 0.05          # e.g. position=+100 → skew=-5
        skew = max(-10, min(10, skew))
        fair += skew

        # ── aggressive: take any mispriced orders ──
        for ask in sorted(depth.sell_orders):
            if ask < fair and position < lim:
                qty = min(-depth.sell_orders[ask], lim - position)
                if qty > 0:
                    orders.append(Order("HYDROGEL_PACK", ask, qty))
                    position += qty

        for bid in sorted(depth.buy_orders, reverse=True):
            if bid > fair and position > -lim:
                qty = min(depth.buy_orders[bid], position + lim)
                if qty > 0:
                    orders.append(Order("HYDROGEL_PACK", bid, -qty))
                    position -= qty

        # ── passive: quote inside the spread ──
        half = 8   # half-spread (observed market spread 16-18)
        my_bid = math.floor(fair - half)
        my_ask = math.ceil(fair  + half)

        bid_room = lim - position
        ask_room = lim + position
        if bid_room > 0:
            orders.append(Order("HYDROGEL_PACK", my_bid,  min(bid_room, 20)))
        if ask_room > 0:
            orders.append(Order("HYDROGEL_PACK", my_ask, -min(ask_room, 20)))

        return orders

    # ── VELVETFRUIT_EXTRACT ────────────────

    def _trade_extract(self, depth: OrderDepth, position: int,
                       net_voucher_delta: float) -> list:
        """
        Market-make around EMA.  Also: if net_voucher_delta != 0, absorb up to
        EXTRACT_LIMIT to delta-hedge the voucher book.
        """
        orders = []
        lim = self.EXTRACT_LIMIT
        mid = self._mid(depth)
        if mid is None:
            return orders

        self._update_ema(mid)
        fair = self._ema_extract

        # ── delta hedge first (highest priority) ──
        hedge_need = int(round(-net_voucher_delta))   # short delta → buy extract
        hedge_need = max(-lim - position, min(lim - position, hedge_need))
        if abs(hedge_need) > 0:
            if hedge_need > 0:
                ask = self._best_ask(depth)
                if ask is not None:
                    orders.append(Order("VELVETFRUIT_EXTRACT", ask, hedge_need))
                    position += hedge_need
            else:
                bid = self._best_bid(depth)
                if bid is not None:
                    orders.append(Order("VELVETFRUIT_EXTRACT", bid, hedge_need))
                    position += hedge_need

        # ── passive market making ──
        half = 3
        my_bid = math.floor(fair - half)
        my_ask = math.ceil(fair  + half)

        bid_room = lim - position
        ask_room = lim + position

        # aggressive: snipe anything crossing fair
        for ask in sorted(depth.sell_orders):
            if ask < fair and position < lim:
                qty = min(-depth.sell_orders[ask], lim - position)
                if qty > 0:
                    orders.append(Order("VELVETFRUIT_EXTRACT", ask, qty))
                    position += qty

        for bid in sorted(depth.buy_orders, reverse=True):
            if bid > fair and position > -lim:
                qty = min(depth.buy_orders[bid], position + lim)
                if qty > 0:
                    orders.append(Order("VELVETFRUIT_EXTRACT", bid, -qty))
                    position -= qty

        if bid_room > 5:
            orders.append(Order("VELVETFRUIT_EXTRACT", my_bid,  min(bid_room, 15)))
        if ask_room > 5:
            orders.append(Order("VELVETFRUIT_EXTRACT", my_ask, -min(ask_room, 15)))

        return orders

    # ── VOUCHERS ───────────────────────────

    def _trade_voucher(self, symbol: str, depth: OrderDepth, position: int,
                       S: float, surface_iv: float) -> tuple[list, float]:
        """
        Returns (orders, delta_contribution) where delta_contribution is the
        net delta added by these orders (for extract hedging).
        """
        orders = []
        K   = self.STRIKES[symbol]
        lim = self.VOUCHER_LIMIT
        T   = self.TTE

        intrinsic   = max(0.0, S - K)
        bs_fair     = bs_call(S, K, T, surface_iv)
        delta       = bs_delta(S, K, T, surface_iv)

        best_ask = self._best_ask(depth)
        best_bid = self._best_bid(depth)
        mid      = self._mid(depth)

        # ── DEEP ITM: pure basis arb ──────────────────────
        if symbol in self.DEEP_ITM:
            # Buy if ask < intrinsic (free money arb)
            if best_ask is not None and best_ask < intrinsic - 0.5:
                qty = min(-depth.sell_orders[best_ask], lim - position)
                if qty > 0:
                    orders.append(Order(symbol, best_ask, qty))
            # Sell if bid > intrinsic (overpriced basis)
            if best_bid is not None and best_bid > intrinsic + 0.5:
                qty = min(depth.buy_orders[best_bid], position + lim)
                if qty > 0:
                    orders.append(Order(symbol, best_bid, -qty))
            delta_added = sum(o.quantity for o in orders) * delta
            return orders, delta_added

        # ── DEEP OTM: skip ────────────────────────────────
        if symbol in self.DEEP_OTM:
            return orders, 0.0

        # ── ATM / OTM: IV-surface arb ────────────────────
        if mid is None:
            return orders, 0.0

        # Compute IV of this specific strike
        iv_market = implied_vol(S, K, T, mid, fallback=surface_iv)
        iv_surface = surface_iv  # from the fitted surface

        # epsilon = market_IV - surface_IV  (positive = overpriced, sell)
        if iv_surface > 0:
            epsilon = iv_market - iv_surface
        else:
            epsilon = 0.0

        # Track signal age for stop-loss-on-time
        if abs(epsilon) > 0.005:
            self._iv_signal_age[symbol] += 1
        else:
            self._iv_signal_age[symbol] = 0

        # Downgrade conviction if signal has not converged in 1000 ticks
        age_penalty = 1.0
        if self._iv_signal_age[symbol] > 1000:
            age_penalty = 0.25

        # Conviction sizing (Hint 3: scale to signal strength)
        abs_eps = abs(epsilon)
        if abs_eps < 0.005:          # noise threshold
            max_pos = 0
        elif abs_eps < 0.02:         # medium conviction
            max_pos = int(lim * 0.25 * age_penalty)
        elif abs_eps < 0.05:         # high conviction
            max_pos = int(lim * 0.60 * age_penalty)
        else:                        # very high conviction
            max_pos = int(lim * 1.00 * age_penalty)

        # Direction: epsilon < 0 → market IV below surface → voucher underpriced → buy
        #            epsilon > 0 → market IV above surface → voucher overpriced  → sell
        if epsilon < -0.005 and best_ask is not None:
            # Buy underpriced voucher
            target = min(max_pos, lim)
            qty = min(-depth.sell_orders[best_ask], target - position)
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        elif epsilon > 0.005 and best_bid is not None:
            # Sell overpriced voucher
            target = min(max_pos, lim)
            qty = min(depth.buy_orders[best_bid], position + target)
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        # Also snipe any obvious mispricing vs BS fair (>1 shell edge)
        if best_ask is not None and best_ask < bs_fair - 1.0:
            room = lim - position - sum(o.quantity for o in orders if o.quantity > 0)
            qty  = min(-depth.sell_orders[best_ask], max(0, room))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        if best_bid is not None and best_bid > bs_fair + 1.0:
            room = position + lim - sum(-o.quantity for o in orders if o.quantity < 0)
            qty  = min(depth.buy_orders[best_bid], max(0, room))
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        # Net delta this set of orders adds
        delta_added = sum(o.quantity for o in orders) * delta
        return orders, delta_added

    # ── MAIN RUN LOOP ──────────────────────

    def run(self, state: TradingState):
        result     = {}
        orders_log = {}

        depths   = state.order_depths
        positions = state.position   # may be missing symbols (default 0)

        # ─── 1. Get extract spot price ───────────────────────────────────
        S = None
        if "VELVETFRUIT_EXTRACT" in depths:
            S = self._mid(depths["VELVETFRUIT_EXTRACT"])
            if S:
                self._extract_hist.append(S)

        # ─── 2. Fit IV surface ───────────────────────────────────────────
        surface_iv = self._fit_iv(S, depths) if S else self.GLOBAL_IV

        # ─── 3. Trade vouchers, track portfolio delta ────────────────────
        portfolio_delta = 0.0    # sum of (voucher_position × delta)

        for sym in self.STRIKES:
            if sym not in depths:
                continue
            pos = positions.get(sym, 0)
            v_orders, d_added = self._trade_voucher(
                sym, depths[sym], pos, S or 5250.0, surface_iv)
            if v_orders:
                result[sym] = v_orders

        # Compute current portfolio delta from existing positions
        if S:
            for sym, K in self.STRIKES.items():
                pos = positions.get(sym, 0)
                if pos != 0:
                    delta = bs_delta(S, K, self.TTE, surface_iv)
                    portfolio_delta += pos * delta

        # ─── 4. Trade HYDROGEL_PACK ──────────────────────────────────────
        if "HYDROGEL_PACK" in depths:
            pos = positions.get("HYDROGEL_PACK", 0)
            result["HYDROGEL_PACK"] = self._trade_hydrogel(depths["HYDROGEL_PACK"], pos)

        # ─── 5. Trade VELVETFRUIT_EXTRACT (last, for delta hedging) ──────
        if "VELVETFRUIT_EXTRACT" in depths:
            pos = positions.get("VELVETFRUIT_EXTRACT", 0)
            # net voucher delta tells extract how much hedge is needed
            extract_pos_delta = pos  # each extract unit = delta 1
            net_delta_to_hedge = portfolio_delta + extract_pos_delta
            result["VELVETFRUIT_EXTRACT"] = self._trade_extract(
                depths["VELVETFRUIT_EXTRACT"], pos, net_delta_to_hedge)

        return result, 0, ""