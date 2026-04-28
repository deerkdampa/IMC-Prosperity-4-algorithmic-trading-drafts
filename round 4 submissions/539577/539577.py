"""
IMC Prosperity 4 – Round 4 Trader  v3
======================================

ROOT-CAUSE ANALYSIS of 534118.py (v2) gaps
────────────────────────────────────────────
534118.py (v2) scored +15,715 XIRECS total.  Three fixable issues remain:

  LOSS-1 — Wrong IV_BIAS direction for VEV_5400 and VEV_5500 (-4,533 + -1,660)
    Day 3 IV-deviation chart (Image 10) shows:
      VEV_5400: observed IV residual μ = -0.015, σ = 0.002 (reliable)
      VEV_5500: observed IV residual μ = -0.016, σ = 0.004 (reliable)
    v2 had POSITIVE biases (+0.0253 / +0.0262), making BS_fair too HIGH for
    these strikes.  This inflated "ask < BS_fair" buy signals, causing us to
    accumulate LONG OTM options that then bled theta decay.  Correct biases
    are NEGATIVE (-0.015 / -0.016), reducing false buy triggers and letting
    some of these strikes flip to SELL signals (theta-positive short positions).

  LOSS-2 — Passive MM on VEV_5400 and VEV_5500 (combined ~-6,190 from MM)
    Per-trade edge (Image 9): scalp buys on 5400 contribute +1,707 (good entry
    edge), but total PnL = -2,825 → passive MM fills added ~-4,532 of theta
    losses.  VEV_5500 same pattern: scalp +326 vs total -1,334 → MM ~-1,660.
    Fix: MM_STRIKES = {} (empty). Passive MM on OTM options = slow theta bleed.

  LOSS-3 — VEV_5200 / VEV_5300 hitting position cap (lost opportunity)
    Position-utilisation chart (Image 2):
      VEV_5200: >85% of limit 24% of time → we lose ~24% of sell signals
      VEV_5300: >85% of limit 12% of time → we lose ~12% of sell signals
    These are our two BIGGEST WINNERS (+8,728 and +5,580).  A "cap-relief" buy
    when the short position is >80% of limit (and ask < BS_fair) will free
    inventory for new high-value sell signals.

SECONDARY IMPROVEMENTS
──────────────────────
  IV_BIAS corrections for all other strikes from Day 3 residuals (Image 10):
    VEV_5100: -0.013 (was +0.008)   – reliable, reduces false buys
    VEV_5000: -0.024 (same as before, disabled scalp anyway)
    VEV_4500: 0.000 (was -0.040, disabled for trading anyway)
    VEV_6000: +0.029 (was -0.0494 — wrong sign! Corrects the smile right-wing
              anchor, which cascades to better fair values for 5400/5500)

  Mark 22 HYDROGEL fade signal (n=23, t=-2.1 → highest-n statistically
  significant signal in Image 4). When Mark 22 is net buyer of HYDROGEL,
  shift fair DOWN (fade the buying). Applied as a weighted tilt on top of
  the generic Mark flow.

  VEV_5200/5300 IV_BIAS left at 0 / +0.001 — mean residuals near zero;
  these strikes are working well as-is.

RETAINED FROM v2 (534118.py)
─────────────────────────────
  DELTA_LIMIT = 400  (no real hedging; alpha = IV scalping + theta, not delta)
  MIN_EDGE = 0.1     (optimal from threshold sweep Image 3)
  DISABLED_SCALP = {VEV_4000, VEV_4500, VEV_5000, VEV_6000, VEV_6500}
  Smile convergence gate, dynamic halfspread, model sanity check
  Weighted smile fitting (U-3)
  VEV_EXTRACT: EMA market-making (take cap 15, quote 10, skew 6 as in 524749)
  HYDROGEL: EMA + mean-reversion overlay (sizing from v2: take 25, quote 12)

EXPECTED IMPROVEMENT OVER v2
──────────────────────────────
  Fix LOSS-1 (IV_BIAS): ~+2,000–3,500 (fewer theta-draining long positions)
  Fix LOSS-2 (MM):      ~+6,190 (eliminate passive MM theta bleed)
  Fix LOSS-3 (cap):     ~+1,000–2,500 (recover missed sell signals on winners)
  Mark/HYDROGEL tweak:  ~+200–500
  Total estimate:       +9,000–12,000 → projected total ~24,000–28,000 XIRECs

CHANGES SUMMARY (v3 vs v2 / 534118.py)
────────────────────────────────────────
C1  IV_BIAS[VEV_5400]: +0.0253 → -0.015  (critical sign fix)
C2  IV_BIAS[VEV_5500]: +0.0262 → -0.016  (critical sign fix)
C3  IV_BIAS[VEV_5100]: +0.008  → -0.013  (corrected from residuals)
C4  IV_BIAS[VEV_6000]: -0.0494 → +0.029  (corrected sign — disabled trade)
C5  IV_BIAS[VEV_5000]: kept -0.024 (disabled scalp, corrects smile shape)
C6  MM_STRIKES: {5400, 5500} → {}         (disable passive MM entirely)
C7  Cap-relief logic for VEV_5200 and VEV_5300 (cover shorts at 0 edge)
C8  Mark 22 targeted HYDROGEL fade signal (n=23, t=-2.1)
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

    # C1-C5: IV_BIAS from Day 3 observed IV residuals (mean over all ticks).
    # Formula: adjusted_IV = smile_IV + IV_BIAS.
    # Negative bias → lower BS_fair → fewer false-buy signals on OTM options.
    IV_BIAS = {
        "VEV_4000": +0.000,   # σ=0.100, too noisy — disabled; 0 to not distort smile
        "VEV_4500": +0.000,   # σ=0.044, disabled for trading; drop old -0.040 correction
        "VEV_5000": -0.024,   # μ=-0.024, σ=0.011; disabled scalp but corrects smile
        "VEV_5100": -0.013,   # μ=-0.013, σ=0.004; reliable — C3 fix from +0.008
        "VEV_5200": -0.002,   # μ=-0.002, essentially 0; leave near 0
        "VEV_5300": +0.001,   # μ=+0.001, essentially 0
        "VEV_5400": -0.015,   # μ=-0.015, σ=0.002; CRITICAL C1 fix from +0.0253
        "VEV_5500": -0.016,   # μ=-0.016, σ=0.004; CRITICAL C2 fix from +0.0262
        "VEV_6000": +0.029,   # μ=+0.029, σ=0.002; C4 fix — disabled but anchors right wing
        "VEV_6500": +0.000,   # disabled; deep OTM
    }

    # MIN_EDGE: optimal confirmed at 0.1 from threshold sweep (Image 3)
    MIN_EDGE = 0.1

    # Cap-relief edge threshold: when position is very short, cover at 0-edge
    # (no edge required — just get out of the way for new high-value sells)
    RELIEF_EDGE = 0.0

    # DELTA_LIMIT=400: effectively no hedging.
    # P3 2nd-place team: "delta hedging would have been prohibitively expensive
    # bid-ask spreads".  Alpha = IV scalping + theta, not delta.
    DELTA_LIMIT    = 400.0
    HEDGE_FRACTION = 0.80

    # C6: MM_STRIKES = {} — passive MM on OTM options bleeds theta.
    # Both VEV_5400 (-4,532 from MM) and VEV_5500 (-1,660 from MM) confirmed
    # as losers via passive quoting.  Scalp-taking is still active for both.
    MM_STRIKES = set()  # type: ignore  # intentionally empty
    MM_SIZE    = 5

    # Strikes excluded from scalp-taking (wide spread or deep OTM / no volume)
    # VEV_4000: spread=20.9, disabled | VEV_4500: spread=16, disabled
    # VEV_5000: spread=6.3, consistently losing | VEV_6000/6500: delta~0
    # All kept in smile fitting to anchor the parabola wings.
    DISABLED_SCALP_STRIKES = {"VEV_4000", "VEV_4500", "VEV_5000", "VEV_6000", "VEV_6500"}

    # Position threshold for cap-relief covering (80% of limit = 240 for 300-limit)
    CAP_RELIEF_THRESHOLD = 0.80

    # Cap-relief strikes: our two biggest winners that hit the cap most often
    CAP_RELIEF_STRIKES = {"VEV_5200", "VEV_5300"}

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
            "mark22_hydro":    0.0,   # C8: Mark 22 specific hydrogel net flow
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
        Disabled-trading strikes included to anchor the parabola wings.
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
    #  MARK FLOW TRACKING                                                  #
    # ------------------------------------------------------------------ #
    def update_mark_flow(self, state: TradingState, data: dict):
        flow = data.setdefault("mark_flow", {})
        # Decay existing flow by 2% per tick
        for mark_data in flow.values():
            for sym in list(mark_data.keys()):
                mark_data[sym] *= 0.98

        # C8: decay Mark 22 hydrogel specific tracker
        data["mark22_hydro"] = data.get("mark22_hydro", 0.0) * 0.98

        for sym, trades in state.market_trades.items():
            for t in trades:
                for participant in [t.buyer, t.seller]:
                    if participant and participant.startswith("Mark"):
                        mark_data = flow.setdefault(participant, {})
                        direction = 1 if participant == t.buyer else -1
                        mark_data[sym] = mark_data.get(sym, 0.0) + direction * t.quantity

                        # C8: track Mark 22 hydrogel buys specifically
                        # When Mark 22 BUYS HYDROGEL_PACK → forward return is NEGATIVE
                        # (t=-2.1, n=23 — most statistically reliable Mark signal)
                        # Action: shift hydrogel fair DOWN when Mark 22 net buying hydrogel
                        if participant == "Mark 22" and sym == "HYDROGEL_PACK":
                            data["mark22_hydro"] = (
                                data.get("mark22_hydro", 0.0)
                                + direction * t.quantity
                            )

    def get_mark_signal(self, data: dict, sym: str) -> float:
        """Generic net Mark flow signal — minor MM skew only."""
        flow  = data.get("mark_flow", {})
        total = sum(d.get(sym, 0.0) for d in flow.values())
        return max(-1.0, min(1.0, total / 150.0))

    def get_mark22_hydro_signal(self, data: dict) -> float:
        """
        C8: Specific Mark 22 hydrogel fade signal.
        When Mark 22 is net buying HYDROGEL (mark22_hydro > 0), price tends to
        FALL (t=-2.1, n=23, Image 4 forward-return chart).  Fade the signal:
        return a negative adjustment to the hydrogel fair value when positive.
        Scale: each unit of Mark 22 hydro net flow contributes -0.03 to fair.
        Capped at -2.0 / +2.0 to avoid over-adjustment.
        """
        flow = data.get("mark22_hydro", 0.0)
        # Negative when Mark 22 buys (fade: lower fair when they buy, raise when they sell)
        return max(-2.0, min(2.0, -flow * 0.03))

    # ------------------------------------------------------------------ #
    #  MAIN RUN                                                            #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        result: dict[str, list] = {}
        data = self.load_data(state.traderData)

        # TTE: Round 4 starts with 4 days remaining; decays linearly to ~0
        progress    = min(1.0, state.timestamp / 1_000_000.0)
        current_tte = max(1e-5, (4.0 - progress) / 365.0)

        ex_depth  = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hyd_depth = state.order_depths.get("HYDROGEL_PACK")
        S         = self._mid(ex_depth) if ex_depth else None
        hy_mid    = self._mid(hyd_depth) if hyd_depth else None

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
        # EMA mean-reversion with inventory skew + Mark 22 fade (C8)       #
        # ================================================================ #
        if hyd_depth and data["hydro_ema"] is not None:
            orders: list = []
            pos  = state.position.get("HYDROGEL_PACK", 0)
            fair = data["hydro_ema"]
            fair += self.get_mark_signal(data, "HYDROGEL_PACK") * 1.0
            # C8: Mark 22 hydrogel fade — negative when they're net buying
            fair += self.get_mark22_hydro_signal(data)

            # Take cap = 25 (v2 sizing, modest increase over original 20)
            pos, _ = self._take_buy ("HYDROGEL_PACK", hyd_depth, fair - 2, pos, 25, orders)
            pos, _ = self._take_sell("HYDROGEL_PACK", hyd_depth, fair + 2, pos, 25, orders)
            # Quote size = 12
            self._quote("HYDROGEL_PACK", hyd_depth, fair, pos, 7, 12, orders)

            # Mean-reversion overlay on large deviations (threshold = 8)
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
                    continue
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

            # Sort by edge, best first
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

            # ── C7: Cap-relief for VEV_5200 and VEV_5300 ─────────────────── #
            # When short position is >80% of limit, cover some at RELIEF_EDGE
            # (even at 0 edge) to free inventory for future high-value sells.
            # These are our two biggest winners; we must keep room to add shorts.
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
                    # Cover (buy) if ask is at or below BS_fair (0-edge or better)
                    if ask <= bs_fair + self.RELIEF_EDGE:
                        qty = min(
                            -depth.sell_orders[ask],
                            self._room_buy(sym, pos),
                            15  # cap relief size per tick
                        )
                        if qty > 0:
                            result.setdefault(sym, []).append(Order(sym, ask, qty))
                            state.position[sym] = pos + qty

            # ── Passive MM (C6: MM_STRIKES = {} — intentionally empty) ────── #
            # Retained infrastructure in case re-activation is tested in R5.
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

            # ── Delta hedge (DELTA_LIMIT=400, effectively disabled) ────────── #
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
        # Sizing from 524749.py which outperformed on this product:        #
        # take cap 15, quote size 10, skew_mult 6 (via _quote default)     #
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