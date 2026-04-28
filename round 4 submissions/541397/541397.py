"""
IMC Prosperity 4 – Round 5 Trader  (merged)
=============================================

MERGE BASIS
───────────
Base file:  your trader (document context)
Donor file: teammate 539577.py

CHANGES FROM YOUR FILE
───────────────────────
M1  MIN_EDGE: 0.5 → 0.1
    Teammate's threshold sweep (Image 3) confirms 0.1 is optimal.
    Fires ~5× more often on 5200/5300, the two biggest winners.

M2  DELTA_LIMIT: 60 → 400 (effectively disabled hedging)
    At DELTA_LIMIT=60, the hedge triggers every tick and buys/sells VEV
    at the ask/bid, burning spread.  P3 2nd-place team confirmed delta
    hedging is net-negative given bid-ask costs.  VEV drag eliminated.

M3  MM_STRIKES: {5400,5500,6000,6500} → {} (empty)
    Passive MM on OTM options bleeds theta.  Per teammate's analysis:
      VEV_5400 MM contribution: ~−4,532
      VEV_5500 MM contribution: ~−1,660
    Infrastructure retained in case re-activation is tested later.

M4  DISABLED_SCALP_STRIKES: 5400/5500 kept disabled
    These produced negligible PnL even with corrected IV_BIAS.
    Disabled set: {4000, 4500, 5000, 5400, 5500, 6000, 6500}

M5  Cap-relief logic added for VEV_5200 and VEV_5300  (C7 from teammate)
    When short position > 80% of limit (−240), cover at 0-edge to free
    inventory for new high-value sell signals.  Expected gain ~+1,000–2,500.

M6  Mark 22 hydrogel fade signal added  (C8 from teammate)
    Mark 22 buying HYDROGEL predicts negative forward return (t=−2.1, n=23).
    Fades fair value down when Mark 22 net-buying.  Expected gain ~+200–500.

RETAINED FROM YOUR FILE
────────────────────────
  Hydrogel: 15% anchor (9994.65) + 85% slow EMA-100, snipe at 25 ticks,
    halfspread=3, quote size=15  (outperforms teammate's pure EMA)
  IV_BIAS values (identical between both files after the round 4 fixes)
  FIX-1/2/3 smile convergence gate, dynamic halfspread, sanity check
  VEV standalone MM (take cap 15, quote size 10, halfspread 3)
  Weighted smile fitting (U-3)
  Decayed Mark flow (U-4)
  All BS math, solve_iv bounds, wpolyfit2

EXPECTED IMPROVEMENT
─────────────────────
  M1 (MIN_EDGE):    ~+2,000–4,000  (more 5200/5300 fills)
  M2 (DELTA):       ~+500–1,500    (stop bleeding VEV spread)
  M3 (MM off):      ~+6,000        (eliminate theta bleed)
  M5 (cap relief):  ~+1,000–2,500
  M6 (Mark 22):     ~+200–500
  Total:            ~+10,000–15,000 over your current file
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

    # IV_BIAS: adjusted_IV = smile_IV + IV_BIAS
    # Negative → lower BS_fair → fewer false buy signals on OTM options.
    # Values from Day 3/4 IV residual analysis (structural means).
    IV_BIAS = {
        "VEV_4000":  0.000,   # σ=0.100, too noisy — disabled; 0 avoids smile distortion
        "VEV_4500":  0.000,   # σ=0.044, disabled for trading; drop old correction
        "VEV_5000": -0.024,   # μ=−0.024, disabled scalp but anchors smile left wing
        "VEV_5100": -0.013,   # μ=−0.013, σ=0.004; reliable
        "VEV_5200": -0.002,   # μ=−0.002, essentially 0; near-ATM working well
        "VEV_5300": +0.001,   # μ=+0.001, essentially 0; near-ATM working well
        "VEV_5400": -0.015,   # μ=−0.015, σ=0.002; corrected from wrong +0.010
        "VEV_5500": -0.016,   # μ=−0.016, σ=0.004; corrected from wrong +0.010
        "VEV_6000": +0.029,   # μ=+0.029, σ=0.002; anchors right wing of smile
        "VEV_6500":  0.000,   # disabled; deep OTM
    }

    # M1: MIN_EDGE=0.1 — optimal from threshold sweep (Image 3)
    # Your file had 0.5 which left ~80% of valid signals on the table
    MIN_EDGE = 0.1

    # Cap-relief: cover shorts at 0-edge when position > 80% of limit
    # Only for our biggest winners which hit the cap frequently
    RELIEF_EDGE             = 0.0
    CAP_RELIEF_THRESHOLD    = 0.80
    CAP_RELIEF_STRIKES      = {"VEV_5200", "VEV_5300"}

    # M2: DELTA_LIMIT=400 — effectively disables delta hedging.
    # At 60 the hedge fired every tick and bled VEV spread.
    # Our alpha is IV scalping + theta, not delta.
    DELTA_LIMIT    = 400.0
    HEDGE_FRACTION = 0.80

    # M3: MM_STRIKES={} — passive MM on OTM options bleeds theta.
    # VEV_5400 MM: ~−4,532 | VEV_5500 MM: ~−1,660 (teammate analysis)
    # Infrastructure retained; re-enable by adding strikes back if needed.
    MM_STRIKES = set()   # intentionally empty
    MM_SIZE    = 5

    # DISABLED_SCALP_STRIKES: 5400/5500 kept disabled — analysis showed they
    # produce negligible PnL even with corrected IV_BIAS. Not worth the risk.
    DISABLED_SCALP_STRIKES = {"VEV_4000", "VEV_4500", "VEV_5000", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500"}

    # Smile convergence gate (FIX-1)
    MIN_SMILE_FITS = 20

    # Dynamic MM halfspread bounds (FIX-2)
    MM_HS_START = 6
    MM_HS_MIN   = 2
    MM_HS_DECAY = 50

    # MM model sanity check (FIX-3)
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
            "mark22_hydro":    0.0,   # M6: Mark 22 specific hydrogel net flow
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
        Disabled-trading strikes still included to anchor the parabola wings.
        Returns: sym -> adjusted smile IV (including IV_BIAS correction).
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
            # U-3: downweight deep ITM/OTM (noisier IV observations)
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
    #  MARK FLOW TRACKING                                                  #
    # ------------------------------------------------------------------ #
    def update_mark_flow(self, state: TradingState, data: dict):
        flow = data.setdefault("mark_flow", {})
        # Decay existing flow 2% per tick
        for mark_data in flow.values():
            for sym in list(mark_data.keys()):
                mark_data[sym] *= 0.98

        # M6: decay Mark 22 hydrogel specific tracker
        data["mark22_hydro"] = data.get("mark22_hydro", 0.0) * 0.98

        for sym, trades in state.market_trades.items():
            for t in trades:
                for participant in [t.buyer, t.seller]:
                    if participant and participant.startswith("Mark"):
                        mark_data = flow.setdefault(participant, {})
                        direction = 1 if participant == t.buyer else -1
                        mark_data[sym] = mark_data.get(sym, 0.0) + direction * t.quantity

                        # M6: track Mark 22 hydrogel buys specifically.
                        # When Mark 22 BUYS HYDROGEL_PACK → forward return is NEGATIVE
                        # (t=−2.1, n=23 — most statistically reliable Mark signal).
                        # Fade: shift fair DOWN when Mark 22 is net buying.
                        if participant == "Mark 22" and sym == "HYDROGEL_PACK":
                            data["mark22_hydro"] = (
                                data.get("mark22_hydro", 0.0)
                                + direction * t.quantity
                            )

    def get_mark_signal(self, data: dict, sym: str) -> float:
        """Generic net Mark flow — minor MM skew only."""
        flow  = data.get("mark_flow", {})
        total = sum(d.get(sym, 0.0) for d in flow.values())
        return max(-1.0, min(1.0, total / 150.0))

    def get_mark22_hydro_signal(self, data: dict) -> float:
        """
        M6: Mark 22 hydrogel fade.
        Mark 22 buying HYDROGEL predicts negative forward return (t=−2.1, n=23).
        Returns a negative fair-value adjustment when they are net buying.
        Scaled at −0.03 per unit of net flow, capped at ±2.0.
        """
        flow = data.get("mark22_hydro", 0.0)
        return max(-2.0, min(2.0, -flow * 0.03))

    # ------------------------------------------------------------------ #
    #  MAIN RUN                                                            #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        result: dict[str, list] = {}
        data = self.load_data(state.traderData)

        # TTE: Round 4 starts with 4 days remaining, decays to ~0
        progress    = min(1.0, state.timestamp / 1_000_000.0)
        current_tte = max(1e-5, (4.0 - progress) / 365.0)

        ex_depth  = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hyd_depth = state.order_depths.get("HYDROGEL_PACK")
        S      = self._mid(ex_depth)  if ex_depth  else None
        hy_mid = self._mid(hyd_depth) if hyd_depth else None

        # ── State updates ──────────────────────────────────────────────── #
        if hy_mid is not None:
            data["hydro_hist"].append(hy_mid)
            data["hydro_hist"] = data["hydro_hist"][-120:]
            # M7: pure adaptive EMA-20, seeded from first observation
            if data["hydro_ema"] is None:
                data["hydro_ema"] = hy_mid
            else:
                data["hydro_ema"] = (2/21) * hy_mid + (19/21) * data["hydro_ema"]

        if S is not None:
            data["vev_ema"] = (2/11) * S + (9/11) * data["vev_ema"]

        self.update_mark_flow(state, data)

        # ================================================================ #
        # HYDROGEL_PACK  (your logic — outperforms teammate's pure EMA)   #
        # Anchor blend: 15% fixed mean + 85% slow EMA-100 tracks drift.   #
        # Snipe threshold at 25 ticks (~0.75 std dev) for large deviations.#
        # Tight halfspread=3 for passive fills + Mark 22 fade (M6).       #
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
            # M6: Mark 22 specific fade (negative when they net-buy hydrogel)
            fair += self.get_mark22_hydro_signal(data)

            snipe_threshold = 25.0
            if hy_mid < fair - snipe_threshold:
                pos, _ = self._take_buy("HYDROGEL_PACK", hyd_depth, fair - 1, pos, 40, orders)
            elif hy_mid > fair + snipe_threshold:
                pos, _ = self._take_sell("HYDROGEL_PACK", hyd_depth, fair + 1, pos, 40, orders)

            self._quote("HYDROGEL_PACK", hyd_depth, fair, pos, 3, 15, orders)

            result["HYDROGEL_PACK"] = orders

        # ================================================================ #
        # VOUCHER OPTIONS                                                   #
        # ================================================================ #
        if S is not None and S > 0:
            smile_ivs = self.fit_smile(S, current_tte, state.order_depths, data)

            # ── Scalping: take edge when available, skip disabled strikes ─ #
            # 5400/5500 kept in DISABLED_SCALP_STRIKES — negligible PnL.
            opportunities = []
            for sym, K in self.STRIKES.items():
                if sym in self.DISABLED_SCALP_STRIKES:
                    continue
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                smile_iv = smile_ivs.get(sym)
                if smile_iv is None:
                    continue

                bs_fair = self.bs_price(S, K, current_tte, smile_iv)

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

            # ── M5: Cap-relief for VEV_5200 and VEV_5300 ─────────────────── #
            # When short position > 80% of limit, cover at 0-edge to free
            # inventory for future high-value sell signals.
            for sym in self.CAP_RELIEF_STRIKES:
                pos = state.position.get(sym, 0)
                relief_threshold = -int(self.CAP_RELIEF_THRESHOLD * self.LIMITS[sym])
                if pos <= relief_threshold:
                    depth = state.order_depths.get(sym)
                    if not depth or not depth.sell_orders:
                        continue
                    smile_iv = smile_ivs.get(sym)
                    if smile_iv is None:
                        continue
                    bs_fair = self.bs_price(S, self.STRIKES[sym], current_tte, smile_iv)
                    ask = min(depth.sell_orders)
                    # Cover (buy) only if ask is at or below BS_fair (0-edge or better)
                    if ask <= bs_fair + self.RELIEF_EDGE:
                        qty = min(
                            -depth.sell_orders[ask],
                            self._room_buy(sym, pos),
                            15   # cap relief size per tick
                        )
                        if qty > 0:
                            result.setdefault(sym, []).append(Order(sym, ask, qty))
                            state.position[sym] = pos + qty

            # ── Passive MM (M3: MM_STRIKES={} — intentionally empty) ───────── #
            # Infrastructure retained; re-enable by adding strikes to MM_STRIKES.
            fits = data.get("smile_fit_count", 0)
            if fits >= self.MIN_SMILE_FITS and self.MM_STRIKES:
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

            # ── Delta hedge (M2: DELTA_LIMIT=400, effectively disabled) ──────── #
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
        # Accounts for hedge orders already queued above before quoting.   #
        # Sizing: take cap 15, quote size 10, halfspread 3 (unchanged)     #
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
                ex_pos, _ = self._take_buy(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair - 1, ex_pos, 15, ex_orders)
                ex_pos, _ = self._take_sell(
                    "VELVETFRUIT_EXTRACT", ex_depth, vev_fair + 1, ex_pos, 15, ex_orders)
                self._quote("VELVETFRUIT_EXTRACT", ex_depth, vev_fair,
                            ex_pos, 3, 10, ex_orders)

        data["last_ts"] = state.timestamp
        return result, 0, self.dump_data(data)