"""
IMC Prosperity 4 – Round 5 Trader
===================================

BASE: Document-3 trader (your file, not the merged version)

CHANGES IN THIS VERSION
────────────────────────
D1  Disabled scalp + MM for VEV_4000, VEV_4500, VEV_5100
    These were losing money.  Added to SCALP_DISABLED; removed from any
    MM consideration.  They still contribute to smile fitting to anchor
    the parabola.

D2  Mark flow logic audited and rewritten
    BUG: The original generic get_mark_signal() aggregates ALL Mark net
    flow across ALL marks for a symbol, then applies a weak ±0.5 tick
    tilt.  This averages out the strong directional signals found in the
    forward-return chart (Image 1).
    
    NEW APPROACH: Per-signal trackers for every statistically significant
    Mark/product/side combination (|t| > 2 from Image 1).  Each tracker
    decays independently.  A composite fair-value adjustment is computed
    per product and applied before order execution.

MARK SIGNALS IMPLEMENTED (from Image 1, |t| > 2)
──────────────────────────────────────────────────
Signal                  t-stat  Action              Scale
Mark 22 / 4000  / S    +12.5   fade sell → BUY      strong
Mark 22 / 4500  / S    +9.0    fade sell → BUY      strong
Mark 22 / 5100  / S    +3.3    fade sell → BUY      medium
Mark 22 / 5000  / S    +3.0    fade sell → BUY      medium
Mark 67 / RACT  / B    +3.3    follow buy → BUY VEV medium
Mark 14 / 5400  / B    -4.0    fade buy  → SELL     strong
Mark 01 / 5400  / B    -4.0    fade buy  → SELL     strong
Mark 14 / 5400  / S    +2.2    fade sell → BUY      weak
Mark 38 / PACK  / B    +2.5    follow buy → BUY HYD weak
Mark 14 / PACK  / S    +2.5    fade sell → BUY HYD  weak
Mark 22 / PACK  / B    -2.1    fade buy  → SELL HYD (existing C8)

HOW THE SIGNAL IS USED
───────────────────────
Vouchers (5000, 5100, 4000, 4500, 5400):
  A per-strike "mark_edge" value is accumulated from the above signals.
  This edge is added to the bs_fair before the MIN_EDGE gate:
    effective_edge = (bs_fair + mark_edge) - ask   [for buy opportunities]
    effective_edge = bid - (bs_fair - mark_edge)   [for sell opportunities]
  This means a strong Mark signal can unlock trades that would otherwise
  fall below MIN_EDGE, and can suppress trades going the wrong way.

VEV (VELVETFRUIT_EXTRACT):
  Mark 67 buy signal → tilt vev_fair UP (follow)
  Generic fallback via get_mark_signal() retained as minor skew.

HYDROGEL:
  Mark 22 buy → fade DOWN  (existing C8, retained)
  Mark 38 buy → tilt UP    (follow)
  Mark 14 sell → tilt UP   (follow / fade the sell)

NOTE ON 4000/4500
──────────────────
Mark 22/4000/S and Mark 22/4500/S are the two strongest signals (t=12.5
and 9.0).  These strikes are disabled for normal scalping (wide spreads,
no BS edge).  However, when Mark 22 triggers a sell signal on these
strikes, we specifically attempt a targeted buy at the ask — but ONLY
when the mark signal is active.  This is gated separately from normal
scalping via MARK_SIGNAL_STRIKES.  The spread on 4000 is ~20 ticks so
we only enter if ask ≤ bs_fair + mark_edge (i.e. signal must overcome
the spread cost).

RETAINED FROM BASE
───────────────────
  All BS math, smile fitting, wpolyfit2
  FIX-1/2/3 smile convergence gate, dynamic halfspread, sanity check
  Hydrogel anchor blend (your logic: 15% × 9994.65 + 85% × EMA-100)
  VEV EMA-10 market making
  Delta hedge infrastructure (DELTA_LIMIT=60 from base)
"""

from datamodel import OrderDepth, TradingState, Order
import json
import math


class Trader:
    # ------------------------------------------------------------------ #
    #  LIMITS & STRIKES                                                    #
    # ------------------------------------------------------------------ #
    LIMITS = {
        "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
        **{k: 300 for k in [
            "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200",
            "VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500",
        ]},
    }

    STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
        "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
        "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000,
        "VEV_6500": 6500,
    }

    # ------------------------------------------------------------------ #
    #  IV BIAS                                                             #
    # ------------------------------------------------------------------ #
    IV_BIAS = {
        "VEV_4000": -0.025,
        "VEV_4500": +0.068,
        "VEV_5000": -0.024,
        "VEV_5100": -0.013,
        "VEV_5200":  0.000,
        "VEV_5300": +0.001,
        "VEV_5400": -0.015,
        "VEV_5500": -0.016,
        "VEV_6000": +0.029,
        "VEV_6500": -0.003,
    }

    # ------------------------------------------------------------------ #
    #  STRIKE TRADING GATES                                                #
    # ------------------------------------------------------------------ #
    # D1: 4000, 4500, 5100 disabled for normal scalping (losing money)
    # 5400, 5500 disabled as before
    SCALP_DISABLED = {"VEV_4000", "VEV_4500", "VEV_5100", "VEV_5400", "VEV_5500"}

    # Strikes that CAN be traded but ONLY when a strong Mark signal fires
    # (bypasses SCALP_DISABLED gate, subject to its own edge check)
    MARK_SIGNAL_STRIKES = {"VEV_4000", "VEV_4500", "VEV_5100", "VEV_5400"}

    MIN_EDGE       = 0.5
    DELTA_LIMIT    = 60.0
    HEDGE_FRACTION = 0.80

    MM_STRIKES = {"VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500"}
    MM_SIZE    = 5
    MIN_SMILE_FITS    = 20
    MM_HS_START       = 6
    MM_HS_MIN         = 2
    MM_HS_DECAY       = 50
    MM_MAX_MODEL_ERROR = 0.30

    # ------------------------------------------------------------------ #
    #  MARK SIGNAL CONFIGURATION                                           #
    # ------------------------------------------------------------------ #
    # Each entry: (mark_name, symbol, side, action, t_stat_abs, decay)
    #   side:   "B" = when they BUY,  "S" = when they SELL
    #   action: +1 = we should BUY the product,  -1 = we should SELL
    #   t_stat_abs: used to scale the signal strength
    #   decay:  per-tick exponential decay rate for this tracker
    #
    # "RACT" maps to VELVETFRUIT_EXTRACT, "PACK" maps to HYDROGEL_PACK
    MARK_SIGNALS = [
        # Mark 22 voucher sells → price rises → fade (buy)
        ("Mark 22", "VEV_4000",            "S", +1, 12.5, 0.97),
        ("Mark 22", "VEV_4500",            "S", +1,  9.0, 0.97),
        ("Mark 22", "VEV_5100",            "S", +1,  3.3, 0.97),
        ("Mark 22", "VEV_5000",            "S", +1,  3.0, 0.97),
        # Mark 67 buys VEV → price rises → follow (buy VEV)
        ("Mark 67", "VELVETFRUIT_EXTRACT", "B", +1,  3.3, 0.97),
        # Mark 14 / Mark 01 buy 5400 → price falls → fade (sell 5400)
        ("Mark 14", "VEV_5400",            "B", -1,  4.0, 0.97),
        ("Mark 01", "VEV_5400",            "B", -1,  4.0, 0.97),
        # Mark 14 sells 5400 → price rises → fade (buy 5400)
        ("Mark 14", "VEV_5400",            "S", +1,  2.2, 0.98),
        # Hydrogel signals
        ("Mark 22", "HYDROGEL_PACK",       "B", -1,  2.1, 0.98),  # existing C8 fade
        ("Mark 38", "HYDROGEL_PACK",       "B", +1,  2.5, 0.98),  # follow Mark 38 buy
        ("Mark 14", "HYDROGEL_PACK",       "S", +1,  2.5, 0.98),  # fade Mark 14 sell
    ]

    # Scale factor: how many ticks of fair-value shift per unit of normalised signal
    # Vouchers: up to 3 ticks shift for the strongest signal (t=12.5)
    # VEV / Hydrogel: up to 2 ticks
    MARK_SCALE_VOUCHER = 3.0
    MARK_SCALE_VEV     = 2.0
    MARK_SCALE_HYDRO   = 2.0

    # Normalisation: signal saturates at this net-flow volume
    MARK_NORM_VOLUME = 100.0

    # ------------------------------------------------------------------ #
    #  STATE                                                               #
    # ------------------------------------------------------------------ #
    def load_data(self, trader_data: str) -> dict:
        defaults = {
            "hydro_hist":      [],
            "hydro_ema":       None,
            "vev_ema":         5262.0,
            "last_ts":         -1,
            "smile_coeffs":    [5.0, -0.10, 0.27],
            "smile_fit_count": 0,
            "mark_flow":       {},   # generic aggregate (legacy, kept for fallback)
            "mark_signals":    {},   # per-signal trackers: key = (mark, sym, side)
        }
        if trader_data:
            try:
                loaded = json.loads(trader_data)
                defaults.update(loaded)
            except Exception:
                pass
        return defaults

    def dump_data(self, d: dict) -> str:
        if len(d.get("mark_flow", {})) > 200:
            d["mark_flow"] = {}
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
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self._cdf(d1) - K * self._cdf(d2)

    def bs_delta(self, S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
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
    #  SMILE FITTING                                                       #
    # ------------------------------------------------------------------ #
    def fit_smile(self, S: float, T: float, depths: dict, data: dict) -> dict:
        m_vals, iv_vals, w_vals = [], [], []
        for sym, K in self.STRIKES.items():
            depth = depths.get(sym)
            if not depth:
                continue
            mid = self._mid(depth)
            if mid is None:
                continue
            intrinsic = max(0.0, S - K)
            if mid - intrinsic < 0.5:
                continue
            iv = self.solve_iv(S, K, T, mid)
            if iv is None:
                continue
            m = math.log(K / S)
            m_vals.append(m)
            iv_vals.append(iv)
            w_vals.append(math.exp(-2.0 * abs(m)))

        if len(m_vals) >= 3:
            try:
                coeffs = self._wpolyfit2(m_vals, iv_vals, w_vals)
                if coeffs is None:
                    raise ValueError("singular")
                alpha = 0.20
                prev  = data["smile_coeffs"]
                data["smile_coeffs"] = [
                    alpha * c + (1.0 - alpha) * p
                    for c, p in zip(coeffs, prev)
                ]
                data["smile_fit_count"] = data.get("smile_fit_count", 0) + 1
            except Exception:
                pass

        c = data["smile_coeffs"]
        smile_ivs = {}
        for sym, K in self.STRIKES.items():
            m = math.log(K / S)
            raw_iv      = c[0] * m * m + c[1] * m + c[2]
            adjusted_iv = raw_iv + self.IV_BIAS.get(sym, 0.0)
            smile_ivs[sym] = max(0.05, adjusted_iv)
        return smile_ivs

    # ------------------------------------------------------------------ #
    #  WEIGHTED POLYFIT                                                    #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _wpolyfit2(xs, ys, ws):
        sw   = sum(ws)
        sx   = sum(w * x        for w, x    in zip(ws, xs))
        sx2  = sum(w * x**2     for w, x    in zip(ws, xs))
        sx3  = sum(w * x**3     for w, x    in zip(ws, xs))
        sx4  = sum(w * x**4     for w, x    in zip(ws, xs))
        sy   = sum(w * y        for w, y    in zip(ws, ys))
        sxy  = sum(w * x * y    for w, x, y in zip(ws, xs, ys))
        sx2y = sum(w * x**2 * y for w, x, y in zip(ws, xs, ys))
        A = [[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, sw]]
        b = [sx2y, sxy, sy]
        for i in range(3):
            max_row = max(range(i, 3), key=lambda r: abs(A[r][i]))
            A[i], A[max_row] = A[max_row], A[i]
            b[i], b[max_row] = b[max_row], b[i]
            piv = A[i][i]
            if abs(piv) < 1e-12:
                return None
            for j in range(i + 1, 3):
                f = A[j][i] / piv
                A[j] = [A[j][k] - f * A[i][k] for k in range(3)]
                b[j] -= f * b[i]
        c = [0.0] * 3
        for i in range(2, -1, -1):
            c[i] = (b[i] - sum(A[i][k] * c[k] for k in range(i + 1, 3))) / A[i][i]
        return c

    # ------------------------------------------------------------------ #
    #  ORDER BOOK HELPERS                                                  #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _mid(depth: OrderDepth) -> float | None:
        bid = max(depth.buy_orders)  if depth.buy_orders  else None
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
                pos += qty; done += qty
        return pos, done

    def _take_sell(self, sym, depth, min_px, pos, cap, orders):
        done = 0
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < min_px or done >= cap:
                break
            qty = min(depth.buy_orders[bid], self._room_sell(sym, pos), cap - done)
            if qty > 0:
                orders.append(Order(sym, bid, -qty))
                pos -= qty; done += qty
        return pos, done

    def _quote(self, sym, depth, fair, pos, halfspread, size, orders):
        if size <= 0:
            return
        bid_px = max(depth.buy_orders)  if depth.buy_orders  else None
        ask_px = min(depth.sell_orders) if depth.sell_orders else None
        skew   = int(round(6.0 * pos / self.LIMITS[sym]))
        b = int(math.floor(fair - halfspread - skew))
        a = int(math.ceil (fair + halfspread - skew))
        if bid_px is not None:
            b = min(b, bid_px + 1)
        if ask_px is not None:
            a = max(a, ask_px - 1)
        if a <= b:
            a = b + 1
        bq = min(size, self._room_buy (sym, pos))
        sq = min(size, self._room_sell(sym, pos))
        if bq > 0:
            orders.append(Order(sym, b,  bq))
        if sq > 0:
            orders.append(Order(sym, a, -sq))

    # ------------------------------------------------------------------ #
    #  MARK FLOW TRACKING — REWRITTEN (D2)                                #
    # ------------------------------------------------------------------ #
    def update_mark_flow(self, state: TradingState, data: dict):
        """
        Two-layer tracking:
        1. Generic aggregate flow (legacy, used for minor VEV/Hydro skew fallback)
        2. Per-signal trackers keyed by (mark_name, symbol, side) — these map
           directly to the statistically significant signals from Image 1.

        Direction convention:
          t.buyer  → direction = +1  (they bought)
          t.seller → direction = -1  (they sold)
        t.quantity is always positive in market_trades.
        """
        # ── Layer 1: generic aggregate (legacy) ──────────────────────── #
        flow = data.setdefault("mark_flow", {})
        for mark_data in flow.values():
            for sym in list(mark_data.keys()):
                mark_data[sym] *= 0.98

        # ── Layer 2: per-signal trackers ─────────────────────────────── #
        # Initialise tracker dict if not present
        sig_store = data.setdefault("mark_signals", {})

        # Decay all existing per-signal trackers using their configured rate
        # We store decay rates separately keyed by tracker key
        decay_rates = data.setdefault("mark_signal_decay", {})
        for key in list(sig_store.keys()):
            rate = decay_rates.get(key, 0.97)
            sig_store[key] = sig_store[key] * rate

        # Pre-build lookup: (mark_name, sym, side) → (action, t_stat, decay)
        # This avoids rebuilding every tick
        signal_lookup = {}
        for (mark, sym, side, action, t_stat, decay) in self.MARK_SIGNALS:
            signal_lookup[(mark, sym, side)] = (action, t_stat, decay)

        # Process new trades
        for sym, trades in state.market_trades.items():
            for t in trades:
                # Buyer side
                if t.buyer and t.buyer.startswith("Mark"):
                    mark = t.buyer
                    # Layer 1
                    mark_data = flow.setdefault(mark, {})
                    mark_data[sym] = mark_data.get(sym, 0.0) + t.quantity

                    # Layer 2
                    key = f"{mark}|{sym}|B"
                    if (mark, sym, "B") in signal_lookup:
                        _, _, decay = signal_lookup[(mark, sym, "B")]
                        decay_rates[key] = decay
                        sig_store[key] = sig_store.get(key, 0.0) + t.quantity

                # Seller side
                if t.seller and t.seller.startswith("Mark"):
                    mark = t.seller
                    # Layer 1
                    mark_data = flow.setdefault(mark, {})
                    mark_data[sym] = mark_data.get(sym, 0.0) - t.quantity

                    # Layer 2
                    key = f"{mark}|{sym}|S"
                    if (mark, sym, "S") in signal_lookup:
                        _, _, decay = signal_lookup[(mark, sym, "S")]
                        decay_rates[key] = decay
                        sig_store[key] = sig_store.get(key, 0.0) + t.quantity

    def get_mark_signal(self, data: dict, sym: str) -> float:
        """Legacy generic signal — minor skew only, kept as fallback."""
        flow  = data.get("mark_flow", {})
        total = sum(d.get(sym, 0.0) for d in flow.values())
        return max(-1.0, min(1.0, total / 150.0))

    def get_mark_edge(self, data: dict, sym: str, scale: float) -> float:
        """
        Compute a fair-value adjustment for `sym` from all active
        per-signal trackers that relate to this symbol.

        Returns a signed tick adjustment:
          positive → raise our fair value (we want to buy)
          negative → lower our fair value (we want to sell)

        The adjustment is:
          edge += action * normalised_flow * t_stat_weight * scale

        Where:
          normalised_flow = min(1, tracker_value / MARK_NORM_VOLUME)
          t_stat_weight   = t_stat_abs / 12.5   (12.5 = max t in dataset)
          scale           = MARK_SCALE_VOUCHER / VEV / HYDRO
        """
        sig_store = data.get("mark_signals", {})
        edge = 0.0
        for (mark, signal_sym, side, action, t_stat, _) in self.MARK_SIGNALS:
            if signal_sym != sym:
                continue
            key   = f"{mark}|{signal_sym}|{side}"
            flow  = sig_store.get(key, 0.0)
            if flow <= 0:
                continue
            norm_flow    = min(1.0, flow / self.MARK_NORM_VOLUME)
            t_weight     = t_stat / 12.5
            edge        += action * norm_flow * t_weight * scale
        return edge

    # ------------------------------------------------------------------ #
    #  MAIN RUN                                                            #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        result: dict[str, list] = {}
        data = self.load_data(state.traderData)

        progress    = min(1.0, state.timestamp / 1_000_000.0)
        current_tte = max(1e-5, (4.0 - progress) / 365.0)

        ex_depth  = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hyd_depth = state.order_depths.get("HYDROGEL_PACK")
        S      = self._mid(ex_depth)  if ex_depth  else None
        hy_mid = self._mid(hyd_depth) if hyd_depth else None

        # ── State updates ─────────────────────────────────────────────── #
        if hy_mid is not None:
            data["hydro_hist"].append(hy_mid)
            data["hydro_hist"] = data["hydro_hist"][-120:]
            if data["hydro_ema"] is None:
                data["hydro_ema"] = hy_mid
            else:
                data["hydro_ema"] = 0.01 * hy_mid + 0.99 * data["hydro_ema"]

        if S is not None:
            data["vev_ema"] = (2/11) * S + (9/11) * data["vev_ema"]

        self.update_mark_flow(state, data)

        # ================================================================ #
        # HYDROGEL_PACK                                                     #
        # ================================================================ #
        if hyd_depth:
            orders: list = []
            pos = state.position.get("HYDROGEL_PACK", 0)

            long_term_anchor = 9994.65
            if data.get("hydro_ema") is None:
                data["hydro_ema"] = long_term_anchor
            else:
                data["hydro_ema"] = 0.01 * hy_mid + 0.99 * data["hydro_ema"]

            fair = (0.15 * long_term_anchor) + (0.85 * data["hydro_ema"])

            # Mark edge for hydrogel: combines Mark 22 fade, Mark 38 follow,
            # Mark 14 sell fade — all from get_mark_edge
            hydro_mark_edge = self.get_mark_edge(
                data, "HYDROGEL_PACK", self.MARK_SCALE_HYDRO)
            fair += hydro_mark_edge

            snipe_threshold = 25.0
            if hy_mid < fair - snipe_threshold:
                pos, _ = self._take_buy(
                    "HYDROGEL_PACK", hyd_depth, fair - 1, pos, 40, orders)
            elif hy_mid > fair + snipe_threshold:
                pos, _ = self._take_sell(
                    "HYDROGEL_PACK", hyd_depth, fair + 1, pos, 40, orders)

            self._quote("HYDROGEL_PACK", hyd_depth, fair, pos, 3, 15, orders)
            result["HYDROGEL_PACK"] = orders

        # ================================================================ #
        # VOUCHER OPTIONS                                                   #
        # ================================================================ #
        if S is not None and S > 0:
            smile_ivs = self.fit_smile(S, current_tte, state.order_depths, data)

            # ── Normal scalping (SCALP_DISABLED strikes skipped) ─────── #
            opportunities = []
            for sym, K in self.STRIKES.items():
                if sym in self.SCALP_DISABLED:
                    continue
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                smile_iv = smile_ivs.get(sym)
                if smile_iv is None:
                    continue
                bs_fair = self.bs_price(S, K, current_tte, smile_iv)

                # Mark edge tilts the effective fair value for this strike
                mark_edge = self.get_mark_edge(
                    data, sym, self.MARK_SCALE_VOUCHER)
                effective_fair = bs_fair + mark_edge

                for ask, vol in depth.sell_orders.items():
                    edge = effective_fair - ask
                    if edge > self.MIN_EDGE:
                        opportunities.append({
                            "sym": sym, "side": "BUY", "px": ask,
                            "qty": -vol, "edge": edge,
                        })
                for bid, vol in depth.buy_orders.items():
                    edge = bid - effective_fair
                    if edge > self.MIN_EDGE:
                        opportunities.append({
                            "sym": sym, "side": "SELL", "px": bid,
                            "qty": vol, "edge": edge,
                        })

            # ── Mark-signal-only trades on disabled strikes ───────────── #
            # For 4000, 4500, 5100, 5400: only trade when Mark signal is
            # strong enough to overcome the spread cost on its own.
            for sym in self.MARK_SIGNAL_STRIKES:
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                K = self.STRIKES[sym]
                smile_iv = smile_ivs.get(sym)
                if smile_iv is None:
                    continue
                bs_fair   = self.bs_price(S, K, current_tte, smile_iv)
                mark_edge = self.get_mark_edge(
                    data, sym, self.MARK_SCALE_VOUCHER)

                # Only proceed if mark signal is meaningfully active (>0.5 tick)
                if abs(mark_edge) < 0.5:
                    continue

                effective_fair = bs_fair + mark_edge

                # Buy side: signal says price will rise (mark_edge > 0)
                if mark_edge > 0:
                    for ask, vol in depth.sell_orders.items():
                        edge = effective_fair - ask
                        if edge > self.MIN_EDGE:
                            opportunities.append({
                                "sym": sym, "side": "BUY", "px": ask,
                                "qty": -vol, "edge": edge,
                            })
                # Sell side: signal says price will fall (mark_edge < 0)
                elif mark_edge < 0:
                    for bid, vol in depth.buy_orders.items():
                        edge = bid - effective_fair
                        if edge > self.MIN_EDGE:
                            opportunities.append({
                                "sym": sym, "side": "SELL", "px": bid,
                                "qty": vol, "edge": edge,
                            })

            # ── Execute all opportunities sorted by edge ──────────────── #
            opportunities.sort(key=lambda x: x["edge"], reverse=True)
            for opp in opportunities:
                sym = opp["sym"]
                pos = state.position.get(sym, 0)
                room = (self._room_buy(sym, pos) if opp["side"] == "BUY"
                        else self._room_sell(sym, pos))
                qty = min(opp["qty"], room)
                if qty <= 0:
                    continue
                signed_qty = qty if opp["side"] == "BUY" else -qty
                result.setdefault(sym, []).append(Order(sym, opp["px"], signed_qty))
                state.position[sym] = pos + signed_qty

            # ── Passive MM (FIX-1/2/3) ───────────────────────────────── #
            fits = data.get("smile_fit_count", 0)
            if fits >= self.MIN_SMILE_FITS:
                calibration   = min(1.0, fits / self.MM_HS_DECAY)
                mm_halfspread = max(
                    self.MM_HS_MIN,
                    int(self.MM_HS_START * (1.0 - calibration))
                )
                for sym in self.MM_STRIKES:
                    depth = state.order_depths.get(sym)
                    K     = self.STRIKES.get(sym)
                    if not depth or K is None:
                        continue
                    smile_iv = smile_ivs.get(sym)
                    if smile_iv is None:
                        continue
                    bs_fair = self.bs_price(S, K, current_tte, smile_iv)
                    market_mid = self._mid(depth)
                    if market_mid and market_mid > 0:
                        if abs(bs_fair - market_mid) / market_mid > self.MM_MAX_MODEL_ERROR:
                            continue
                    pos       = state.position.get(sym, 0)
                    mm_orders = result.setdefault(sym, [])
                    self._quote(sym, depth, bs_fair, pos,
                                mm_halfspread, self.MM_SIZE, mm_orders)

            # ── Delta hedge ───────────────────────────────────────────── #
            if ex_depth:
                net_delta = 0.0
                for sym, K in self.STRIKES.items():
                    pos = state.position.get(sym, 0)
                    if pos != 0:
                        iv = smile_ivs.get(sym, 0.27)
                        net_delta += pos * self.bs_delta(S, K, current_tte, iv)

                ex_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
                excess = abs(net_delta) - self.DELTA_LIMIT
                if excess > 0:
                    hedge_raw = math.copysign(excess, net_delta) * self.HEDGE_FRACTION
                    target    = int(round(-hedge_raw))
                    clamped   = max(-self.LIMITS["VELVETFRUIT_EXTRACT"],
                                   min(self.LIMITS["VELVETFRUIT_EXTRACT"],
                                       ex_pos + target))
                    need      = clamped - ex_pos
                    ex_orders = result.setdefault("VELVETFRUIT_EXTRACT", [])
                    if need > 0:
                        ask = min(ex_depth.sell_orders) if ex_depth.sell_orders else None
                        if ask:
                            q = min(need, self._room_buy("VELVETFRUIT_EXTRACT", ex_pos))
                            if q > 0:
                                ex_orders.append(Order("VELVETFRUIT_EXTRACT", ask, q))
                                ex_pos += q
                    elif need < 0:
                        bid = max(ex_depth.buy_orders) if ex_depth.buy_orders else None
                        if bid:
                            q = min(-need, self._room_sell("VELVETFRUIT_EXTRACT", ex_pos))
                            if q > 0:
                                ex_orders.append(Order("VELVETFRUIT_EXTRACT", bid, -q))
                                ex_pos -= q

        # ================================================================ #
        # VELVETFRUIT_EXTRACT — standalone MM + hedge                      #
        # ================================================================ #
        if ex_depth and S is not None:
            ex_orders = result.setdefault("VELVETFRUIT_EXTRACT", [])
            ex_pos    = state.position.get("VELVETFRUIT_EXTRACT", 0)
            for o in ex_orders:
                ex_pos += o.quantity

            vev_fair  = data["vev_ema"]
            # Mark 67 buy follow + generic legacy signal
            vev_mark_edge = self.get_mark_edge(
                data, "VELVETFRUIT_EXTRACT", self.MARK_SCALE_VEV)
            vev_fair += vev_mark_edge
            vev_fair += self.get_mark_signal(data, "VELVETFRUIT_EXTRACT") * 0.5

            if self._room_buy("VELVETFRUIT_EXTRACT", ex_pos) > 0 \
               or self._room_sell("VELVETFRUIT_EXTRACT", ex_pos) > 0:
                ex_pos, _ = self._take_buy(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair - 1, ex_pos, 15, ex_orders)
                ex_pos, _ = self._take_sell(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair + 1, ex_pos, 15, ex_orders)
                self._quote("VELVETFRUIT_EXTRACT", ex_depth, vev_fair,
                            ex_pos, 3, 10, ex_orders)

        data["last_ts"] = state.timestamp
        return result, 0, self.dump_data(data)