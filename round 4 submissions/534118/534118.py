"""
IMC Prosperity 4 – Round 4 Trader  v2
======================================

ROOT-CAUSE ANALYSIS of trader_r4_upgraded.py failure (-7,135 vs +18,041 original)
──────────────────────────────────────────────────────────────────────────────────
The upgraded file lost primarily from TWO sources:

  KILLER 1 — VEV_6500 MM disaster  (-5,120 XIRECs, 1,954 trades)
    The IV_BIAS recalibrations changed VEV_6000/6500 model prices enough that
    FIX-3 (model-sanity 30% gate) no longer triggered, allowing MM quoting.
    VEV_6500 is deep OTM (delta ≈ 0), essentially worthless.  A fleet of bots
    systematically sold into our bid at exactly -1.0 edge (per-trade chart).
    Fix: remove VEV_6500 (and VEV_6000) from MM_STRIKES and disable all trading.

  KILLER 2 — VELVETFRUIT_EXTRACT delta-hedge bleed  (-10,592 XIRECs)
    MIN_EDGE=0.1 created larger options positions (more scalps accepted).
    DELTA_LIMIT=60 then triggered a large short-VEV hedge.
    VEV trended upward during Round 4 → short hedge bled -10,592.
    The Prosperity 3 2nd-place team (README in context) explicitly chose NOT
    to delta hedge: "delta hedging would have been prohibitively expensive
    bid-ask spreads."  Alpha is in IV scalping (IV deviations), not in delta.
    Fix: DELTA_LIMIT = 400 (effectively no hedging).

SECONDARY ISSUES (smaller magnitude, also fixed):
  • Directed Mark signals (U4) — signals shifted between runs, confirming
    overfitting with n=5-20 per (Mark, product, side) pair.  Removed entirely.
  • HYDROGEL oversizing — take cap 40, quote 20 caused overtrading into a
    mean-reverting product that doesn't sustain large positions.  Reverted.
  • VEV_5000 disabled — spread 6.26, "CAUTION" verdict, consistently losing
    in every run.  Added to disabled scalp set.

CHANGES IN THIS VERSION vs trader_r4_upgraded.py
──────────────────────────────────────────────────
V1  DELTA_LIMIT: 60 → 400  (no real hedge; alpha = IV scalping, not delta)
    Primary fix for the -10,592 VELVETFRUIT_EXTRACT loss.

V2  VEV_6500 and VEV_6000 fully disabled for trading (MM + scalp)
    Both remain in smile fitting to anchor the right wing of the parabola.
    Primary fix for the -5,120 VEV_6500 loss.

V3  MM_STRIKES: {5400, 5500, 6000, 6500} → {5400, 5500}
    Only the two tightest real-volume strikes get passive quotes.

V4  Remove directed Mark signal system (U4)
    Signals shifted between runs (t-stats changed significantly).
    With n=5-20 per signal, this is textbook overfitting.
    Reverted to simple generic Mark flow (original approach).

V5  VEV_5000 added to DISABLED_SCALP_STRIKES
    Spread = 6.26 ("CAUTION"), consistently losing in every run.

V6  HYDROGEL sizing moderated: take cap 40→25, quote size 20→12
    Original was cap=20, quote=7.  New run was too aggressive for a
    mean-reverting product with bid-ask spread of ~16 XIRECS.

V7  VELVETFRUIT_EXTRACT sizing restored to original
    take cap: 8→15, quote size: 6→10, skew_mult: 9→6
    With DELTA_LIMIT=400 the VEV position won't be crowded out by hedge.

RETAINED FROM trader_r4_upgraded.py (and 524749.py)
─────────────────────────────────────────────────────
MIN_EDGE = 0.1 (optimal from threshold sweep, confirmed in both briefs)
IV_BIAS corrections for high-reliability strikes (n=1000, σ<0.004):
  VEV_5400: +0.0253, VEV_5500: +0.0262, VEV_6000: -0.0494
Conservative for noisy strikes (high σ or disabled): 4000, 4500, 5000
FIX-1  Smile convergence gate (MIN_SMILE_FITS = 20)
FIX-2  Dynamic MM halfspread (6 → 2 over 50 fits)
FIX-3  Model sanity check (30% error gate) — now actually relevant again
       since VEV_6000/6500 model sanity is no longer artificially close
       (they're excluded from MM anyway)
U-3    Weighted smile fitting
"""

from datamodel import OrderDepth, TradingState, Order
import json
import math


class Trader:
    # ------------------------------------------------------------------ #
    #  CONFIGURATION                                                       #
    # ------------------------------------------------------------------ #
    LIMITS = {
        "HYDROGEL_PACK":      200,
        "VELVETFRUIT_EXTRACT": 200,
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

    # IV_BIAS: corrections applied where evidence is reliable (n=1000, σ<0.005)
    # Conservative for noisy/disabled strikes (high σ_residual or VEV_6500/6000)
    IV_BIAS = {
        "VEV_4000": +0.000,    # disabled; kept for smile fit only; σ=0.100 too noisy
        "VEV_4500": -0.040,    # original; σ=0.044 moderately noisy; disabled anyway
        "VEV_5000": +0.015,    # original; disabled from scalping
        "VEV_5100": +0.008,    # original; |μ|=0.013 below 0.02 threshold
        "VEV_5200":  0.000,    # |μ|=0.002 negligible
        "VEV_5300":  0.000,    # |μ|=0.001 negligible
        "VEV_5400": +0.0253,   # n=1000, σ=0.002 — reliable; cumulative correction
        "VEV_5500": +0.0262,   # n=1000, σ=0.004 — reliable; cumulative correction
        "VEV_6000": -0.0494,   # n=1000, σ=0.002 — reliable; but disabled for trading
        "VEV_6500":  0.000,    # disabled; deep OTM; keep at 0 to avoid inflating price
    }

    # V1: MIN_EDGE = 0.1 — confirmed optimal in both briefs' threshold sweeps
    MIN_EDGE = 0.1

    # V1: DELTA_LIMIT = 400 — no real hedging.
    # Rationale: alpha is IV scalping (mean-reverting IV deviations), not delta.
    # P3 2nd place explicitly rejected delta hedging due to bid-ask spread cost.
    # DELTA_LIMIT=60 + larger options positions (from MIN_EDGE=0.1) + trending VEV
    # = the -10,592 VELVETFRUIT loss in the upgraded run.
    DELTA_LIMIT    = 400.0
    HEDGE_FRACTION = 0.80   # kept for residual infrastructure

    # V3: Only tightest-spread real-volume strikes get passive MM quotes
    # VEV_6000 and VEV_6500 removed — deep OTM, model unreliable, -5,120 loss
    MM_STRIKES = {"VEV_5400", "VEV_5500"}
    MM_SIZE    = 5

    # V2 + V5: strikes excluded from scalping scan
    # VEV_4000: spread=20.9, disabled
    # VEV_4500: spread=16.0, too wide
    # VEV_5000: spread=6.26, "CAUTION", consistently losing
    # VEV_6000: delta~0, model unreliable for trading
    # VEV_6500: delta~0, -5,120 loss, deep OTM worthless option
    # All kept in smile fitting to anchor the parabola wings
    DISABLED_SCALP_STRIKES = {"VEV_4000", "VEV_4500", "VEV_5000", "VEV_6000", "VEV_6500"}

    # Smile convergence gate (FIX-1 from 524749.py)
    MIN_SMILE_FITS = 20

    # Dynamic halfspread bounds (FIX-2)
    MM_HS_START = 6
    MM_HS_MIN   = 2
    MM_HS_DECAY = 50

    # Model-error sanity gate for MM (FIX-3)
    MM_MAX_MODEL_ERROR = 0.30

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
            "mark_flow":       {},
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
    #  VOLATILITY SMILE FITTING                                            #
    # ------------------------------------------------------------------ #
    def fit_smile(self, S: float, T: float, depths: dict, data: dict) -> dict:
        """
        Weighted quadratic fit across all strikes.
        Disabled-trading strikes are still included to anchor the parabola wings.
        """
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
            # Downweight deep ITM/OTM (noisier IV observations)
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
            m           = math.log(K / S)
            raw_iv      = c[0] * m * m + c[1] * m + c[2]
            adjusted_iv = raw_iv + self.IV_BIAS.get(sym, 0.0)
            smile_ivs[sym] = max(0.05, adjusted_iv)

        return smile_ivs

    # ------------------------------------------------------------------ #
    #  PURE-PYTHON WEIGHTED POLYFIT (degree-2)                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _wpolyfit2(xs, ys, ws):
        sw   = sum(ws)
        sx   = sum(w * x       for w, x    in zip(ws, xs))
        sx2  = sum(w * x**2    for w, x    in zip(ws, xs))
        sx3  = sum(w * x**3    for w, x    in zip(ws, xs))
        sx4  = sum(w * x**4    for w, x    in zip(ws, xs))
        sy   = sum(w * y       for w, y    in zip(ws, ys))
        sxy  = sum(w * x * y   for w, x, y in zip(ws, xs, ys))
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
    #  MARK FLOW TRACKING (simple generic — no per-signal overfitting)    #
    # ------------------------------------------------------------------ #
    def update_mark_flow(self, state: TradingState, data: dict):
        flow = data.setdefault("mark_flow", {})
        for mark_data in flow.values():
            for sym in list(mark_data.keys()):
                mark_data[sym] *= 0.98
        for sym, trades in state.market_trades.items():
            for t in trades:
                for participant in [t.buyer, t.seller]:
                    if participant and participant.startswith("Mark"):
                        mark_data = flow.setdefault(participant, {})
                        direction = 1 if participant == t.buyer else -1
                        mark_data[sym] = mark_data.get(sym, 0.0) + direction * t.quantity

    def get_mark_signal(self, data: dict, sym: str) -> float:
        """Generic net Mark flow signal — minor MM skew only."""
        flow  = data.get("mark_flow", {})
        total = sum(d.get(sym, 0.0) for d in flow.values())
        return max(-1.0, min(1.0, total / 150.0))

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
        S         = self._mid(ex_depth) if ex_depth else None

        hy_mid = self._mid(hyd_depth) if hyd_depth else None

        # ── State updates ──────────────────────────────────────────────── #
        if hy_mid is not None:
            data["hydro_hist"].append(hy_mid)
            data["hydro_hist"] = data["hydro_hist"][-120:]
            if data["hydro_ema"] is None:
                data["hydro_ema"] = hy_mid
            else:
                data["hydro_ema"] = (2/21) * hy_mid + (19/21) * data["hydro_ema"]

        if S is not None:
            data["vev_ema"] = (2/11) * S + (9/11) * data["vev_ema"]

        self.update_mark_flow(state, data)

        # ================================================================ #
        # HYDROGEL_PACK                                                     #
        # V6: moderate sizing (original was 20/7; upgraded 40/20 too big)  #
        # ================================================================ #
        if hyd_depth and data["hydro_ema"] is not None:
            orders: list = []
            pos  = state.position.get("HYDROGEL_PACK", 0)
            fair = data["hydro_ema"]
            fair += self.get_mark_signal(data, "HYDROGEL_PACK") * 1.0

            # take cap = 25 (modest increase from original 20)
            pos, _ = self._take_buy ("HYDROGEL_PACK", hyd_depth, fair - 2, pos, 25, orders)
            pos, _ = self._take_sell("HYDROGEL_PACK", hyd_depth, fair + 2, pos, 25, orders)
            # quote size = 12 (modest increase from original 7)
            self._quote("HYDROGEL_PACK", hyd_depth, fair, pos, 7, 12, orders)

            # Mean-reversion overlay on large deviations (original threshold = 8)
            if hy_mid is not None:
                dev = hy_mid - fair
                if dev < -8 and self._room_buy("HYDROGEL_PACK", pos) >= 5:
                    ask = min(hyd_depth.sell_orders) if hyd_depth.sell_orders else None
                    if ask and ask < fair - 4:
                        orders.append(Order("HYDROGEL_PACK", ask, 5))
                        pos += 5
                elif dev > 8 and self._room_sell("HYDROGEL_PACK", pos) >= 5:
                    bid = max(hyd_depth.buy_orders) if hyd_depth.buy_orders else None
                    if bid and bid > fair + 4:
                        orders.append(Order("HYDROGEL_PACK", bid, -5))
                        pos -= 5

            result["HYDROGEL_PACK"] = orders

        # ================================================================ #
        # VOUCHER OPTIONS                                                   #
        # ================================================================ #
        if S is not None and S > 0:
            smile_ivs = self.fit_smile(S, current_tte, state.order_depths, data)

            # ── Scalping: take edge when available, skip disabled strikes ─ #
            opportunities = []
            for sym, K in self.STRIKES.items():
                if sym in self.DISABLED_SCALP_STRIKES:
                    continue  # V2 + V5: skip wide-spread / deep-OTM strikes
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                smile_iv = smile_ivs.get(sym)
                if smile_iv is None:
                    continue

                bs_fair = self.bs_price(S, K, current_tte, smile_iv)
                pos     = state.position.get(sym, 0)

                for ask, vol in depth.sell_orders.items():
                    edge = bs_fair - ask
                    if edge > self.MIN_EDGE:
                        opportunities.append({
                            "sym": sym, "side": "BUY", "px": ask,
                            "qty": -vol, "edge": edge,
                        })
                for bid, vol in depth.buy_orders.items():
                    edge = bid - bs_fair
                    if edge > self.MIN_EDGE:
                        opportunities.append({
                            "sym": sym, "side": "SELL", "px": bid,
                            "qty": vol, "edge": edge,
                        })

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

            # ── Passive MM on tight-spread strikes (FIX-1/2/3 retained) ── #
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

                    # FIX-3: skip if model too far from market mid
                    market_mid = self._mid(depth)
                    if market_mid and market_mid > 0:
                        if abs(bs_fair - market_mid) / market_mid > self.MM_MAX_MODEL_ERROR:
                            continue

                    pos       = state.position.get(sym, 0)
                    mm_orders = result.setdefault(sym, [])
                    self._quote(sym, depth, bs_fair, pos,
                                mm_halfspread, self.MM_SIZE, mm_orders)

            # ── Delta hedge (V1: DELTA_LIMIT=400, effectively disabled) ── #
            # Kept as safety valve for extreme scenarios only.
            # With DELTA_LIMIT=400 and position limit=300 per option, max
            # theoretical delta ≈ 10 strikes × 300 × 1.0 = 3000, still above
            # 400 in worst case.  This fires only if we somehow accumulate
            # very large delta exposure across many strikes simultaneously.
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
        # VELVETFRUIT_EXTRACT — standalone mean-reversion MM               #
        # V7: original sizing restored (take cap 15, quote 10, skew 6)    #
        # ================================================================ #
        if ex_depth and S is not None:
            ex_orders = result.setdefault("VELVETFRUIT_EXTRACT", [])
            ex_pos    = state.position.get("VELVETFRUIT_EXTRACT", 0)
            for o in ex_orders:
                ex_pos += o.quantity
            vev_fair  = data["vev_ema"]
            vev_fair += self.get_mark_signal(data, "VELVETFRUIT_EXTRACT") * 0.5

            if self._room_buy("VELVETFRUIT_EXTRACT", ex_pos) > 0 \
               or self._room_sell("VELVETFRUIT_EXTRACT", ex_pos) > 0:
                # Original take caps: 15
                ex_pos, _ = self._take_buy(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair - 1, ex_pos, 15, ex_orders)
                ex_pos, _ = self._take_sell(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair + 1, ex_pos, 15, ex_orders)
                # Original quote size: 10, skew_mult: 6 (via _quote default)
                self._quote("VELVETFRUIT_EXTRACT", ex_depth, vev_fair,
                            ex_pos, 3, 10, ex_orders)

        data["last_ts"] = state.timestamp
        return result, 0, self.dump_data(data)