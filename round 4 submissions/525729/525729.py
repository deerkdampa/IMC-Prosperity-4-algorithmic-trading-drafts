"""
IMC Prosperity 4 – Round 4 Trader  (UPGRADED from 524749.py)
=============================================================

CHANGES IN THIS VERSION  (vs 524749.py)
─────────────────────────────────────────
U1  MIN_EDGE 0.5 → 0.1
    Threshold-sweep analysis (chart 10) shows optimal total PnL at 0.1.
    Lowering captures ~60 extra trades with positive avg edge (+3.4 XIRECS/trade).
    Trade count 202 → no degradation in avg edge at 0.1.

U2  IV_BIAS recalibrated from IV-deviation analysis (chart 03)
    VEV_4000:  0.0000 → +0.0252  (μ=-0.0252, correct systematic underpricing)
    VEV_4500: -0.0400 → -0.1084  (μ=+0.0684, correct systematic overpricing)
    VEV_5000: +0.0150 → +0.0393  (μ=-0.0243)
    VEV_5400: +0.0100 → +0.0253  (μ=-0.0153)
    VEV_5500: +0.0100 → +0.0262  (μ=-0.0162)
    VEV_6000: -0.0200 → -0.0494  (μ=+0.0294)

U3  DISABLE scalping on VEV_4000
    avg spread = 20.9 (>20 threshold), PnL = -163. Not worth scalping.
    Strike kept in smile fit to inform model but removed from opportunity scan.

U4  Directed Mark-flow signal system (replaces/augments generic flow)
    Implements per-(Mark, product, side) signals derived from forward-return
    analysis (chart 09, brief section 5).  Each signal decays at 0.97/tick.
    Signals encode: FADE (do opposite of Mark) or FOLLOW (do same as Mark).
    Applied as a fair-value skew in XIRECS at execution time.

U5  Hydrogel position sizing increased
    avg utilisation only 12% (chart 11) — leaving money on the table.
    take cap: 20 → 40;  quote size: 7 → 20; MR overlay threshold: 8 → 6.

U6  VelvetFruit Extract position exposure reduced
    hitting position limit 36% of time (chart 11) — orders blocked.
    take cap: 15 → 8;  quote size: 10 → 6; skew multiplier: 6 → 9.

U7  VEV_5100 / VEV_5000 utilisation notes
    These improve naturally from MIN_EDGE 0.1 (wider opportunity scan).
    No explicit sizing change needed beyond the threshold fix.

RETAINED FROM 524749.py
────────────────────────
FIX-1  Smile convergence gate (MIN_SMILE_FITS = 20)
FIX-2  Dynamic MM halfspread (6 → 2 over 50 fits)
FIX-3  Sanity check before MM quoting (30% model-error gate)
BUG-1  Correct polyfit coefficient ordering
BUG-2  Pure adaptive EMA for HYDROGEL
BUG-3  Single price-edge gate
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

    # U2: per-strike IV bias — corrected from deviation analysis (brief §7)
    IV_BIAS = {
        "VEV_4000": +0.0252,   # was 0.0000
        "VEV_4500": -0.1084,   # was -0.0400
        "VEV_5000": +0.0393,   # was +0.0150
        "VEV_5100": +0.0080,   # unchanged (|μ|=0.013 < 0.02)
        "VEV_5200":  0.0000,   # unchanged (|μ|=0.002)
        "VEV_5300":  0.0000,   # unchanged (|μ|=0.001)
        "VEV_5400": +0.0253,   # was +0.0100
        "VEV_5500": +0.0262,   # was +0.0100
        "VEV_6000": -0.0494,   # was -0.0200
        "VEV_6500":  0.0000,   # unchanged (|μ|=0.003)
    }

    # U1: optimal min-edge from threshold sweep (brief §4, chart 10)
    MIN_EDGE       = 0.1
    DELTA_LIMIT    = 60.0
    HEDGE_FRACTION = 0.80

    # MM_STRIKES: only quote passively here (tight spread ≤ 1.5 avg)
    MM_STRIKES = {"VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500"}
    MM_SIZE    = 5

    # U3: strikes excluded from scalping scan (spread too wide, PnL negative)
    DISABLED_SCALP_STRIKES = {"VEV_4000"}

    # Smile convergence gate (FIX-1)
    MIN_SMILE_FITS = 20

    # Dynamic halfspread bounds (FIX-2)
    MM_HS_START = 6
    MM_HS_MIN   = 2
    MM_HS_DECAY = 50

    # Model-error sanity gate (FIX-3)
    MM_MAX_MODEL_ERROR = 0.30

    # ------------------------------------------------------------------ #
    #  U4: DIRECTED MARK-FLOW SIGNALS                                     #
    # ------------------------------------------------------------------ #
    # Format: (mark_id, sym): (skew_when_they_BUY, skew_when_they_SELL)
    #   Positive skew → we think fair value is higher → favour buying
    #   Negative skew → we think fair value is lower  → favour selling
    #   None          → this side is not a significant signal
    #
    #  FADE  = do opposite: they sell → price reverts up → we want +skew
    #  FOLLOW = do same:    they buy  → price continues  → we want +skew
    #
    # Strengths proportional to |avg_bps| * clip(|t_stat| / 12, 0, 1)
    DIRECTED_CONFIG = {
        # t=12.69, FADE SELL → positive skew when Mark22 sells
        ("Mark 22", "VEV_4000"):            (None,  +3.0),
        # t=8.69,  FADE SELL
        ("Mark 22", "VEV_4500"):            (None,  +2.5),
        # t=-3.61, FADE BUY → negative skew when Mark14 buys
        ("Mark 14", "VEV_5400"):            (-2.0,  None),
        # t=3.54,  FOLLOW BUY → positive skew when Mark67 buys
        ("Mark 67", "VELVETFRUIT_EXTRACT"): (+1.0,  None),
        # t=3.24,  FADE SELL
        ("Mark 22", "VEV_5100"):            (None,  +1.5),
        # t=3.11,  FADE SELL
        ("Mark 22", "VEV_5000"):            (None,  +1.5),
        # t=-2.87, FADE BUY, large n=105
        ("Mark 01", "VEV_5400"):            (-1.5,  None),
        # t=2.58,  FOLLOW BUY
        ("Mark 38", "HYDROGEL_PACK"):       (+1.0,  None),
        # t=2.50,  FADE SELL
        ("Mark 14", "HYDROGEL_PACK"):       (None,  +1.0),
        # t=-2.36, FADE BUY
        ("Mark 22", "HYDROGEL_PACK"):       (-1.0,  None),
    }
    # Decay per timestamp tick and signal normalisation
    DIRECTED_DECAY   = 0.97
    DIRECTED_NORM    = 10.0   # divide accumulated qty * strength by this
    DIRECTED_CAP     = 5.0    # max abs fair-value adjustment (XIRECS)

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
            "mark_flow":       {},   # legacy generic signal (kept for VELVETFRUIT follow)
            "d_flow":          {},   # U4: directed signal buckets
        }
        if trader_data:
            try:
                loaded = json.loads(trader_data)
                defaults.update(loaded)
            except Exception:
                pass
        return defaults

    def dump_data(self, d: dict) -> str:
        # Prevent state bloat
        if len(d.get("mark_flow", {})) > 200:
            d["mark_flow"] = {}
        if len(d.get("d_flow", {})) > 100:
            d["d_flow"] = {}
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
        VEV_4000 is still included in smile fitting (its market price gives
        useful IV info for the left wing) but excluded from scalping.
        Returns dict: sym → adjusted smile IV (including IV_BIAS).
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

    def _quote(self, sym, depth, fair, pos, halfspread, size, orders,
               skew_mult: float = 6.0):
        """Post passive bid+ask around fair, with inventory skew."""
        if size <= 0:
            return
        bid_px = max(depth.buy_orders)  if depth.buy_orders  else None
        ask_px = min(depth.sell_orders) if depth.sell_orders else None
        skew   = int(round(skew_mult * pos / self.LIMITS[sym]))
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
    #  U4: DIRECTED MARK SIGNAL SYSTEM                                    #
    # ------------------------------------------------------------------ #
    def update_mark_signals(self, state: TradingState, data: dict):
        """
        Update BOTH legacy generic flow (mark_flow) AND new directed signals (d_flow).
        """
        # — generic flow (legacy, used for broad VELVETFRUIT bias) —
        flow = data.setdefault("mark_flow", {})
        for mark_data in flow.values():
            for sym in list(mark_data.keys()):
                mark_data[sym] *= 0.98

        # — directed signal buckets —
        d_flow = data.setdefault("d_flow", {})
        for k in list(d_flow.keys()):
            d_flow[k] *= self.DIRECTED_DECAY

        # accumulate from this tick's market trades
        for sym, trades in state.market_trades.items():
            for t in trades:
                for participant, side in [(t.buyer, "BUY"), (t.seller, "SELL")]:
                    if not participant or not participant.startswith("Mark"):
                        continue

                    # legacy generic
                    mark_data = flow.setdefault(participant, {})
                    direction = 1 if participant == t.buyer else -1
                    mark_data[sym] = mark_data.get(sym, 0.0) + direction * t.quantity

                    # directed
                    cfg = self.DIRECTED_CONFIG.get((participant, sym))
                    if cfg is None:
                        continue
                    skew_val = cfg[0] if side == "BUY" else cfg[1]
                    if skew_val is None:
                        continue
                    key = f"{participant}|{sym}"
                    # accumulate: quantity * per-unit-strength / normaliser
                    d_flow[key] = d_flow.get(key, 0.0) + skew_val * t.quantity / self.DIRECTED_NORM

    def get_directed_signal(self, data: dict, sym: str) -> float:
        """
        Returns a fair-value skew in XIRECS for this product.
        Positive = we think true fair value is higher than model says → favour buying.
        Negative = we think true fair value is lower  → favour selling.
        """
        d_flow = data.get("d_flow", {})
        signal = 0.0
        for (mark_id, s) in self.DIRECTED_CONFIG:
            if s != sym:
                continue
            key = f"{mark_id}|{sym}"
            signal += d_flow.get(key, 0.0)
        return max(-self.DIRECTED_CAP, min(self.DIRECTED_CAP, signal))

    def get_generic_mark_signal(self, data: dict, sym: str) -> float:
        """Legacy generic signal, kept as a small supplementary nudge."""
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

        self.update_mark_signals(state, data)

        # ================================================================ #
        # HYDROGEL_PACK                                                     #
        # U5: increased sizing (was take_cap=20, quote_size=7)             #
        # ================================================================ #
        if hyd_depth and data["hydro_ema"] is not None:
            orders: list = []
            pos  = state.position.get("HYDROGEL_PACK", 0)
            fair = data["hydro_ema"]

            # apply directed signal first, then generic nudge
            fair += self.get_directed_signal(data, "HYDROGEL_PACK")
            fair += self.get_generic_mark_signal(data, "HYDROGEL_PACK") * 0.5

            # U5: take cap 20 → 40
            pos, _ = self._take_buy ("HYDROGEL_PACK", hyd_depth, fair - 2, pos, 40, orders)
            pos, _ = self._take_sell("HYDROGEL_PACK", hyd_depth, fair + 2, pos, 40, orders)
            # U5: quote size 7 → 20
            self._quote("HYDROGEL_PACK", hyd_depth, fair, pos, 7, 20, orders)

            # Mean-reversion overlay (U-5): threshold tightened 8 → 6
            if hy_mid is not None:
                dev = hy_mid - fair
                if dev < -6 and self._room_buy("HYDROGEL_PACK", pos) >= 5:
                    ask = min(hyd_depth.sell_orders) if hyd_depth.sell_orders else None
                    if ask and ask < fair - 3:
                        orders.append(Order("HYDROGEL_PACK", ask, 5))
                        pos += 5
                elif dev > 6 and self._room_sell("HYDROGEL_PACK", pos) >= 5:
                    bid = max(hyd_depth.buy_orders) if hyd_depth.buy_orders else None
                    if bid and bid > fair + 3:
                        orders.append(Order("HYDROGEL_PACK", bid, -5))
                        pos -= 5

            result["HYDROGEL_PACK"] = orders

        # ================================================================ #
        # VOUCHER OPTIONS                                                   #
        # ================================================================ #
        if S is not None and S > 0:
            smile_ivs = self.fit_smile(S, current_tte, state.order_depths, data)

            # ── Scalping: scan all enabled strikes for positive edge ───── #
            opportunities = []
            for sym, K in self.STRIKES.items():
                # U3: skip disabled strikes
                if sym in self.DISABLED_SCALP_STRIKES:
                    continue
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                smile_iv = smile_ivs.get(sym)
                if smile_iv is None:
                    continue

                bs_fair = self.bs_price(S, K, current_tte, smile_iv)

                # U4: apply directed mark signal as fair-value skew
                bs_fair_adj = bs_fair + self.get_directed_signal(data, sym)

                pos = state.position.get(sym, 0)

                for ask, vol in depth.sell_orders.items():
                    edge = bs_fair_adj - ask
                    if edge > self.MIN_EDGE:
                        opportunities.append({
                            "sym": sym, "side": "BUY", "px": ask,
                            "qty": -vol, "edge": edge,
                        })
                for bid, vol in depth.buy_orders.items():
                    edge = bid - bs_fair_adj
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

                    # FIX-3: skip if model too far from market
                    market_mid = self._mid(depth)
                    if market_mid and market_mid > 0:
                        if abs(bs_fair - market_mid) / market_mid > self.MM_MAX_MODEL_ERROR:
                            continue

                    pos       = state.position.get(sym, 0)
                    mm_orders = result.setdefault(sym, [])
                    self._quote(sym, depth, bs_fair, pos,
                                mm_halfspread, self.MM_SIZE, mm_orders)

            # ── Delta hedge via VELVETFRUIT_EXTRACT ───────────────────── #
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
        # VELVETFRUIT_EXTRACT — standalone MM + hedge (U6: reduced sizing) #
        # ================================================================ #
        if ex_depth and S is not None:
            ex_orders = result.setdefault("VELVETFRUIT_EXTRACT", [])
            ex_pos    = state.position.get("VELVETFRUIT_EXTRACT", 0)
            for o in ex_orders:
                ex_pos += o.quantity
            vev_fair  = data["vev_ema"]

            # directed signal + legacy nudge
            vev_fair += self.get_directed_signal(data, "VELVETFRUIT_EXTRACT")
            vev_fair += self.get_generic_mark_signal(data, "VELVETFRUIT_EXTRACT") * 0.5

            if self._room_buy("VELVETFRUIT_EXTRACT", ex_pos) > 0 \
               or self._room_sell("VELVETFRUIT_EXTRACT", ex_pos) > 0:
                # U6: take cap 15 → 8
                ex_pos, _ = self._take_buy(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair - 1, ex_pos, 8, ex_orders)
                ex_pos, _ = self._take_sell(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair + 1, ex_pos, 8, ex_orders)
                # U6: quote size 10 → 6, skew_mult 6 → 9 (stronger position relief)
                self._quote("VELVETFRUIT_EXTRACT", ex_depth, vev_fair,
                            ex_pos, 3, 6, ex_orders, skew_mult=9.0)

        data["last_ts"] = state.timestamp
        return result, 0, self.dump_data(data)