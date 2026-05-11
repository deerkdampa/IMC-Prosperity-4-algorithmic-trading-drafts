"""
IMC Prosperity 4 - Round 4 Trader
Upgrades over Round 3 (486343.py):
  1. VEV_5300 added to STRIKES and LIMITS (was silently missing)
  2. Volatility smile fitting (quadratic on log-moneyness vs IV)
     replaces per-strike IV EMAs → cross-strike fair-value signal
  3. Delta hedging: VELVETFRUIT_EXTRACT used to neutralise net option delta
  4. Counterparty (Mark) tracking to detect informed flow patterns
  5. TTE seeded at 4 days for Round 4
  6. VEV_5300 position limit raised to full 300 (was excluded)
"""

from r4.datamodel import OrderDepth, TradingState, Order
import json
import math
import numpy as np


class Trader:
    # ------------------------------------------------------------------ #
    #  CONFIGURATION                                                       #
    # ------------------------------------------------------------------ #
    LIMITS = {
        "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 150, "VEV_4500": 150, "VEV_5000": 150,
        "VEV_5100": 150, "VEV_5200": 150, "VEV_5300": 150,  # FIX: was missing
        "VEV_5400": 150, "VEV_5500": 150, "VEV_6000": 50, "VEV_6500": 50,
    }

    STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
        "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,  # FIX: was missing
        "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000,
        "VEV_6500": 6500,
    }

    # Minimum IV deviation from smile to enter a trade (in IV units)
    # 0.02 = 2 vol points — calibrate against backtests
    IV_DEV_THRESHOLD = 0.02
    # Maximum IV deviation before we consider the data stale/bad
    IV_DEV_MAX = 0.20

    # Minimum price edge required to cross the spread (shells)
    MIN_EDGE = 1.0

    # Maximum net-delta exposure we will carry before hedging
    DELTA_LIMIT = 60.0          # in underlying units equivalent
    HEDGE_FRACTION = 0.80       # hedge 80% of excess delta per tick

    # ------------------------------------------------------------------ #
    #  STATE                                                               #
    # ------------------------------------------------------------------ #
    def load_data(self, trader_data: str) -> dict:
        defaults = {
            "hydro_hist": [],
            "vev_ema": 5262.0,
            "last_ts": -1,
            # smile EMA: smoothed quadratic coefficients [a, b, c]
            # (IV = a + b*m + c*m^2,  m = log(K/S))
            "smile_coeffs": [0.30, 0.0, 0.50],
            # fallback per-strike IV (used when smile not yet fitted)
            "iv_fallback": {
                "VEV_4000": 0.50, "VEV_4500": 0.40, "VEV_5000": 0.27,
                "VEV_5100": 0.26, "VEV_5200": 0.27, "VEV_5300": 0.28,
                "VEV_5400": 0.27, "VEV_5500": 0.29, "VEV_6000": 0.40,
                "VEV_6500": 0.55,
            },
            # counterparty flow tracking  {mark_id: {sym: net_signed_qty}}
            "mark_flow": {},
            "smile_fit_count": 0,
        }
        if trader_data:
            try:
                loaded = json.loads(trader_data)
                defaults.update(loaded)
            except Exception:
                pass
        return defaults

    def dump_data(self, d: dict) -> str:
        # Keep size under 50k limit
        if len(d.get("mark_flow", {})) > 200:
            d["mark_flow"] = {}  # reset if too large
        return json.dumps(d, separators=(",", ":"))

    # ------------------------------------------------------------------ #
    #  OPTIONS MATHS                                                       #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_price(self, S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self._cdf(d1) - K * self._cdf(d2)

    def bs_delta(self, S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
        return self._cdf(d1)

    def solve_iv(self, S: float, K: float, T: float, price: float,
                 lo: float = 0.01, hi: float = 3.0, iters: int = 60) -> float | None:
        intrinsic = max(0.0, S - K)
        if price <= intrinsic + 0.05:
            return None
        for _ in range(iters):
            mid = (lo + hi) / 2.0
            if self.bs_price(S, K, T, mid) < price:
                lo = mid
            else:
                hi = mid
        iv = (lo + hi) / 2.0
        return iv if 0.02 < iv < 2.5 else None

    # ------------------------------------------------------------------ #
    #  VOLATILITY SMILE FITTING                                            #
    # ------------------------------------------------------------------ #
    def fit_smile(
        self, S: float, T: float, depths: dict, data: dict
    ) -> dict:
        """
        Fit a quadratic to (log(K/S), solved_IV) pairs across all strikes.
        Returns a dict: sym -> smile-fitted IV for that strike.

        Logic
        -----
        1. For each strike with a live mid-price, solve IV from BS.
        2. Filter out near-zero extrinsic value points (unreliable IV).
        3. Fit quadratic: IV = c0 + c1*m + c2*m^2 via numpy polyfit.
        4. EMA-smooth the quadratic coefficients over time.
        5. Return fitted IV per strike.
        """
        m_vals, iv_vals = [], []

        for sym, K in self.STRIKES.items():
            depth = depths.get(sym)
            if not depth:
                continue
            mid = self._mid(depth)
            if mid is None:
                continue
            intrinsic = max(0.0, S - K)
            # skip if extrinsic < 0.5 shells (BS IV numerically unstable)
            if mid - intrinsic < 0.5:
                continue
            iv = self.solve_iv(S, K, T, mid)
            if iv is None:
                continue
            m = math.log(K / S)
            m_vals.append(m)
            iv_vals.append(iv)

        smile_ivs: dict[str, float] = {}

        if len(m_vals) >= 3:
            try:
                coeffs = np.polyfit(m_vals, iv_vals, 2).tolist()
                # EMA-smooth coefficients (alpha = 0.25 → ~3-tick memory)
                alpha = 0.25
                prev = data["smile_coeffs"]
                data["smile_coeffs"] = [
                    alpha * c + (1 - alpha) * p for c, p in zip(coeffs, prev)
                ]
                data["smile_fit_count"] = data.get("smile_fit_count", 0) + 1
            except Exception:
                pass

        # Evaluate smile at each strike
        c = data["smile_coeffs"]  # [a, b, c] for c*m^2 + b*m + a
        for sym, K in self.STRIKES.items():
            m = math.log(K / S)
            fitted_iv = c[2] * m ** 2 + c[1] * m + c[0]
            # Floor at a sensible minimum
            smile_ivs[sym] = max(0.05, fitted_iv)

        return smile_ivs

    # ------------------------------------------------------------------ #
    #  ORDER BOOK HELPERS                                                  #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _mid(depth: OrderDepth) -> float | None:
        bid = max(depth.buy_orders) if depth.buy_orders else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        if bid and ask:
            return (bid + ask) / 2.0
        return bid or ask

    def _room_buy(self, sym: str, pos: int) -> int:
        return max(0, self.LIMITS[sym] - pos)

    def _room_sell(self, sym: str, pos: int) -> int:
        return max(0, self.LIMITS[sym] + pos)

    def _take_buy(self, sym, depth, max_px, pos, cap, orders):
        done = 0
        for ask in sorted(depth.sell_orders):
            if ask > max_px or done >= cap:
                break
            qty = min(-depth.sell_orders[ask], self._room_buy(sym, pos), cap - done)
            if qty > 0:
                orders.append(Order(sym, ask, qty))
                pos += qty
                done += qty
        return pos, done

    def _take_sell(self, sym, depth, min_px, pos, cap, orders):
        done = 0
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < min_px or done >= cap:
                break
            qty = min(depth.buy_orders[bid], self._room_sell(sym, pos), cap - done)
            if qty > 0:
                orders.append(Order(sym, bid, -qty))
                pos -= qty
                done += qty
        return pos, done

    def _quote(self, sym, depth, fair, pos, halfspread, size, orders):
        if size <= 0:
            return
        bid_px = max(depth.buy_orders) if depth.buy_orders else None
        ask_px = min(depth.sell_orders) if depth.sell_orders else None
        skew = int(round(6.0 * pos / self.LIMITS[sym]))
        b = int(math.floor(fair - halfspread - skew))
        a = int(math.ceil(fair + halfspread - skew))
        if bid_px is not None:
            b = min(b, bid_px + 1)
        if ask_px is not None:
            a = max(a, ask_px - 1)
        if a <= b:
            a = b + 1
        bq = min(size, self._room_buy(sym, pos))
        sq = min(size, self._room_sell(sym, pos))
        if bq > 0:
            orders.append(Order(sym, b, bq))
        if sq > 0:
            orders.append(Order(sym, a, -sq))

    # ------------------------------------------------------------------ #
    #  COUNTERPARTY TRACKING                                               #
    # ------------------------------------------------------------------ #
    def update_mark_flow(self, state: TradingState, data: dict):
        """
        Track net signed quantity per Mark per symbol from market_trades.
        Positive = Mark was a net buyer; negative = net seller.
        This lets us detect e.g. a mark that systematically buys VEV_5200
        before large extract moves (informed flow signal).
        """
        flow = data.setdefault("mark_flow", {})
        for sym, trades in state.market_trades.items():
            for t in trades:
                for participant in [t.buyer, t.seller]:
                    if participant and participant.startswith("Mark"):
                        mark_data = flow.setdefault(participant, {})
                        direction = 1 if participant == t.buyer else -1
                        mark_data[sym] = mark_data.get(sym, 0) + direction * t.quantity

    def get_informed_signal(self, data: dict, sym: str) -> float:
        """
        Returns a signal in [-1, +1]:
          +1  → Marks are net buyers of `sym` (bullish signal)
          -1  → Marks are net sellers (bearish signal)
        Used to slightly tighten/widen quotes or shift fair value.
        """
        flow = data.get("mark_flow", {})
        total = 0
        for mark_data in flow.values():
            total += mark_data.get(sym, 0)
        cap = 200.0
        return max(-1.0, min(1.0, total / cap))

    # ------------------------------------------------------------------ #
    #  MAIN RUN                                                            #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        result: dict[str, list] = {}
        data = self.load_data(state.traderData)

        # Round 4: TTE starts at 4 days, decays over 10,000 ticks
        # (Each round = 1 day; 10,000 ticks per round)
        progress = min(1.0, state.timestamp / 1_000_000.0)
        current_tte = max(1e-5, (4.0 - progress) / 365.0)

        ex_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hyd_depth = state.order_depths.get("HYDROGEL_PACK")
        S = self._mid(ex_depth) if ex_depth else None
        hy_mid = self._mid(hyd_depth) if hyd_depth else None

        # ---- State updates ------------------------------------------- #
        if hy_mid is not None:
            data["hydro_hist"].append(hy_mid)
            data["hydro_hist"] = data["hydro_hist"][-120:]
        if S is not None:
            alpha = 2 / 11
            data["vev_ema"] = alpha * S + (1 - alpha) * data["vev_ema"]

        self.update_mark_flow(state, data)

        # ---- HYDROGEL_PACK ------------------------------------------- #
        if hyd_depth:
            orders: list = []
            pos = state.position.get("HYDROGEL_PACK", 0)
            hist = data["hydro_hist"]
            fair = 9991.0
            if len(hist) >= 10:
                fair = 0.1 * 9991.0 + 0.9 * (sum(hist[-10:]) / 10)
            # Tilt fair value slightly based on informed Mark flow
            mark_sig = self.get_informed_signal(data, "HYDROGEL_PACK")
            fair += mark_sig * 2.0  # ±2 shell tilt on strong signal
            pos, _ = self._take_buy("HYDROGEL_PACK", hyd_depth, fair - 2, pos, 20, orders)
            pos, _ = self._take_sell("HYDROGEL_PACK", hyd_depth, fair + 2, pos, 20, orders)
            self._quote("HYDROGEL_PACK", hyd_depth, fair, pos, 8, 10, orders)
            result["HYDROGEL_PACK"] = orders

        # ---- VOUCHER SMILE STRATEGY ---------------------------------- #
        if S is not None and S > 0:
            # Step 1: fit the volatility smile across all strikes
            smile_ivs = self.fit_smile(S, current_tte, state.order_depths, data)

            # Step 2: collect trade opportunities ranked by IV deviation
            opportunities = []
            for sym, K in self.STRIKES.items():
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                mid = self._mid(depth)
                if mid is None:
                    continue

                # Solve actual market IV
                actual_iv = self.solve_iv(S, K, current_tte, mid)
                smile_iv = smile_ivs.get(sym)
                if actual_iv is None or smile_iv is None:
                    continue

                iv_dev = actual_iv - smile_iv  # + = overpriced, - = underpriced

                # Use smile IV as fair-value basis (not actual IV)
                bs_fair = self.bs_price(S, K, current_tte, smile_iv)
                pos = state.position.get(sym, 0)

                # BUY opportunities: market ask is below smile fair value
                for ask, vol in depth.sell_orders.items():
                    price_edge = bs_fair - ask
                    # Require both a price edge AND the IV deviation is negative
                    # (market is underpriced on smile basis)
                    if (price_edge > self.MIN_EDGE
                            and iv_dev < -self.IV_DEV_THRESHOLD
                            and abs(iv_dev) < self.IV_DEV_MAX):
                        opportunities.append({
                            "sym": sym, "side": "BUY", "px": ask,
                            "qty": -vol, "price_edge": price_edge,
                            "iv_dev": iv_dev, "K": K,
                        })

                # SELL opportunities: market bid is above smile fair value
                for bid, vol in depth.buy_orders.items():
                    price_edge = bid - bs_fair
                    if (price_edge > self.MIN_EDGE
                            and iv_dev > self.IV_DEV_THRESHOLD
                            and abs(iv_dev) < self.IV_DEV_MAX):
                        opportunities.append({
                            "sym": sym, "side": "SELL", "px": bid,
                            "qty": vol, "price_edge": price_edge,
                            "iv_dev": iv_dev, "K": K,
                        })

            # Step 3: sort by price edge descending and execute
            opportunities.sort(key=lambda x: x["price_edge"], reverse=True)
            for opp in opportunities:
                sym = opp["sym"]
                pos = state.position.get(sym, 0)
                if opp["side"] == "BUY":
                    room = self._room_buy(sym, pos)
                else:
                    room = self._room_sell(sym, pos)
                qty = min(opp["qty"], room)
                if qty <= 0:
                    continue
                signed_qty = qty if opp["side"] == "BUY" else -qty
                orders = result.setdefault(sym, [])
                orders.append(Order(sym, opp["px"], signed_qty))
                # Update local position tracker for subsequent opps this tick
                state.position[sym] = pos + signed_qty

            # ---- DELTA HEDGE via VELVETFRUIT_EXTRACT ------------------ #
            # Compute net delta of entire voucher book
            if ex_depth:
                net_delta = 0.0
                for sym, K in self.STRIKES.items():
                    pos = state.position.get(sym, 0)
                    if pos != 0:
                        iv = smile_ivs.get(sym, 0.27)
                        delta_i = self.bs_delta(S, K, current_tte, iv)
                        net_delta += pos * delta_i

                ex_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
                # Ideal hedge target: -net_delta from options
                # But we also want to keep the EMA market-making active,
                # so we only hedge the portion that exceeds DELTA_LIMIT.
                excess_delta = abs(net_delta) - self.DELTA_LIMIT
                if excess_delta > 0:
                    hedge_qty_raw = (
                        math.copysign(excess_delta, net_delta) * self.HEDGE_FRACTION
                    )
                    target_hedge = int(round(-hedge_qty_raw))  # opposite sign
                    target_ex_pos = ex_pos + target_hedge
                    target_ex_pos = max(
                        -self.LIMITS["VELVETFRUIT_EXTRACT"],
                        min(self.LIMITS["VELVETFRUIT_EXTRACT"], target_ex_pos),
                    )
                    hedge_need = target_ex_pos - ex_pos
                    ex_orders = result.setdefault("VELVETFRUIT_EXTRACT", [])
                    vev_fair = data["vev_ema"]
                    if hedge_need > 0:
                        # Need to buy extract to hedge short delta
                        best_ask = min(ex_depth.sell_orders) if ex_depth.sell_orders else None
                        if best_ask:
                            qty = min(hedge_need, self._room_buy("VELVETFRUIT_EXTRACT", ex_pos))
                            if qty > 0:
                                ex_orders.append(Order("VELVETFRUIT_EXTRACT", best_ask, qty))
                                ex_pos += qty
                    elif hedge_need < 0:
                        # Need to sell extract to hedge long delta
                        best_bid = max(ex_depth.buy_orders) if ex_depth.buy_orders else None
                        if best_bid:
                            qty = min(-hedge_need, self._room_sell("VELVETFRUIT_EXTRACT", ex_pos))
                            if qty > 0:
                                ex_orders.append(Order("VELVETFRUIT_EXTRACT", best_bid, -qty))
                                ex_pos -= qty

        # ---- VELVETFRUIT_EXTRACT standalone market making ------------ #
        # Run only if we haven't been consumed entirely by delta hedging
        if ex_depth and S is not None:
            ex_orders = result.setdefault("VELVETFRUIT_EXTRACT", [])
            ex_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
            # Adjust for any hedge orders already queued this tick
            for o in ex_orders:
                ex_pos += o.quantity
            vev_fair = data["vev_ema"]
            mark_sig = self.get_informed_signal(data, "VELVETFRUIT_EXTRACT")
            vev_fair += mark_sig * 1.5
            remaining_buy = self._room_buy("VELVETFRUIT_EXTRACT", ex_pos)
            remaining_sell = self._room_sell("VELVETFRUIT_EXTRACT", ex_pos)
            if remaining_buy > 0 or remaining_sell > 0:
                ex_pos, _ = self._take_buy(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair - 1, ex_pos, 15, ex_orders
                )
                ex_pos, _ = self._take_sell(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair + 1, ex_pos, 15, ex_orders
                )
                self._quote("VELVETFRUIT_EXTRACT", ex_depth, vev_fair, ex_pos, 3, 10, ex_orders)

        data["last_ts"] = state.timestamp
        return result, 0, self.dump_data(data)
