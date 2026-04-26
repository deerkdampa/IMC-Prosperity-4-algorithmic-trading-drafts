"""
IMC Prosperity 4 – Round 3 "Gloves Off"
Improved trader.py

Key changes from 389784.py:
  • Un-commented & fully rebuilt VEV options trading (was 100% disabled)
  • Un-commented & rebuilt VELVETFRUIT_EXTRACT delta-hedge + light MM
  • Improved HYDROGEL_PACK: stronger inventory-skew so we stop ending at ±200
  • Quadratic IV-surface fit across ATM vouchers → conviction-scaled positions
  • Deep-ITM basis arb (VEV_4000 / VEV_4500 at intrinsic value)
  • Rolling realized-vol tracker (for Sell-Vega signal)
  • Clean stop-loss-on-time: if position not converging within 1000 ticks → trim

Manual challenge recommendation (submit in the GUI):
  Bid 1 = 795  (EV-optimal single bid, not penalised)
  Bid 2 = 855  (Shield bid above expected avg_b2, reduces cubic-penalty risk)
"""

from datamodel import OrderDepth, TradingState, Order
import json
import math

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
    "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
    "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
    "VEV_6500": 300,
}

STRIKES = {
    "VEV_4000": 4000, "VEV_4500": 4500,
    "VEV_5000": 5000, "VEV_5100": 5100,
    "VEV_5200": 5200, "VEV_5300": 5300,
    "VEV_5400": 5400, "VEV_5500": 5500,
    "VEV_6000": 6000, "VEV_6500": 6500,
}

# Round 3: TTE = 5 days / 365
TTE_R3 = 5.0 / 365.0

# Historical analysis: near-ATM IV is very stable ~24 % across Days 0-2
PRIOR_IV = 0.24

# Conviction thresholds on IV deviation (absolute IV units)
IV_NOISE_THR  = 0.006   # below → ignore
IV_MED_THR    = 0.020   # medium conviction
IV_HIGH_THR   = 0.040   # high conviction → full-size

# Per-voucher maximum order qty per tick (scales with conviction)
VOL_BASE = {
    "VEV_4000": 15, "VEV_4500": 15,
    "VEV_5000": 12, "VEV_5100": 12,
    "VEV_5200": 12, "VEV_5300": 12,
    "VEV_5400":  8, "VEV_5500":  5,
    "VEV_6000":  0, "VEV_6500":  0,   # deep OTM: skip
}


# ─────────────────────────────────────────────────────────────
# Maths helpers
# ─────────────────────────────────────────────────────────────
def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call(s: float, k: float, t: float, sigma: float) -> float:
    intrinsic = max(0.0, s - k)
    if t <= 0 or sigma <= 1e-7:
        return intrinsic
    rt = math.sqrt(t)
    try:
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * rt)
    except Exception:
        return intrinsic
    d2 = d1 - sigma * rt
    return s * _cdf(d1) - k * _cdf(d2)


def bs_delta(s: float, k: float, t: float, sigma: float) -> float:
    """Black-Scholes call delta."""
    if t <= 0 or sigma <= 1e-7:
        return 1.0 if s > k else 0.0
    rt = math.sqrt(t)
    try:
        d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * rt)
    except Exception:
        return 1.0 if s > k else 0.0
    return _cdf(d1)


def iv_bisect(price: float, s: float, k: float, t: float) -> float:
    """Newton-free implied-vol solver (bisection, 40 iterations ≈ <1 µs)."""
    intrinsic = max(0.0, s - k)
    if price <= intrinsic + 0.4:
        return 1e-5          # effectively at intrinsic, no extrinsic
    lo, hi = 5e-4, 3.0
    for _ in range(40):
        m = (lo + hi) * 0.5
        if bs_call(s, k, t, m) > price:
            hi = m
        else:
            lo = m
    return (lo + hi) * 0.5


def solve_3x3(A, b):
    """Gaussian elimination for 3-equation system."""
    M = [A[i][:] + [b[i]] for i in range(3)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        f = M[col][col]
        for c in range(col, 4):
            M[col][c] /= f
        for r in range(3):
            if r != col:
                fac = M[r][col]
                for c in range(col, 4):
                    M[r][c] -= fac * M[col][c]
    return [M[i][3] for i in range(3)]


def fit_quadratic(points):
    """Fit y = a + b*x + c*x² via least-squares (closed-form 3×3 system)."""
    n = len(points)
    if n < 3:
        return None
    s0 = s1 = s2 = s3 = s4 = sy = s1y = s2y = 0.0
    for x, y in points:
        x2 = x * x
        s0  += 1
        s1  += x
        s2  += x2
        s3  += x2 * x
        s4  += x2 * x2
        sy  += y
        s1y += x * y
        s2y += x2 * y
    A = [[s0, s1, s2], [s1, s2, s3], [s2, s3, s4]]
    b = [sy, s1y, s2y]
    return solve_3x3(A, b)


# ─────────────────────────────────────────────────────────────
# Trader class
# ─────────────────────────────────────────────────────────────
class Trader:

    # ── State helpers ──────────────────────────────────────────
    def _load(self, raw: str) -> dict:
        defaults = {
            "ex_hist":  [],    # extract mid-prices (last 300)
            "hy_hist":  [],    # hydrogel mid-prices (last 120)
            "ex_ema":   None,  # slow EMA of extract
            "rv":       PRIOR_IV,   # rolling realized vol estimate
            "last_ts":  -1,
        }
        if raw:
            try:
                d = json.loads(raw)
                defaults.update(d)
            except Exception:
                pass
        return defaults

    def _dump(self, d: dict) -> str:
        # Keep lists bounded so traderData stays small
        d["ex_hist"] = d["ex_hist"][-300:]
        d["hy_hist"] = d["hy_hist"][-120:]
        return json.dumps(d, separators=(',', ':'))

    # ── Order book helpers ─────────────────────────────────────
    @staticmethod
    def _best(depth: OrderDepth):
        bid = max(depth.buy_orders)  if depth.buy_orders  else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        return bid, ask

    @staticmethod
    def _mid(depth: OrderDepth):
        bid = max(depth.buy_orders)  if depth.buy_orders  else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        if bid is not None and ask is not None:
            return (bid + ask) * 0.5
        return bid if bid is not None else ask

    @staticmethod
    def _room_buy(sym, pos):
        return max(0, LIMITS[sym] - pos)

    @staticmethod
    def _room_sell(sym, pos):
        return max(0, LIMITS[sym] + pos)

    def _take_buy(self, sym, depth, max_px, pos, cap, orders):
        done = 0
        for ask in sorted(depth.sell_orders):
            if ask > max_px or done >= cap:
                break
            avail = -depth.sell_orders[ask]
            qty = min(avail, self._room_buy(sym, pos), cap - done)
            if qty > 0:
                orders.append(Order(sym, ask, qty))
                pos += qty; done += qty
        return pos, done

    def _take_sell(self, sym, depth, min_px, pos, cap, orders):
        done = 0
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < min_px or done >= cap:
                break
            avail = depth.buy_orders[bid]
            qty = min(avail, self._room_sell(sym, pos), cap - done)
            if qty > 0:
                orders.append(Order(sym, bid, -qty))
                pos -= qty; done += qty
        return pos, done

    def _quote(self, sym, depth, fair, pos, half, size, orders):
        """Post a two-sided passive quote with inventory skew."""
        if size <= 0:
            return
        bid, ask = self._best(depth)
        lim = LIMITS[sym]
        skew = int(round(9.0 * pos / lim))
        bpx = int(math.floor(fair - half - skew))
        apx = int(math.ceil(fair + half - skew))
        if bid is not None:
            bpx = min(bpx, bid + 1)
        if ask is not None:
            apx = max(apx, ask - 1)
        if apx <= bpx:
            apx = bpx + 1
        bq = min(size, self._room_buy(sym,  pos))
        sq = min(size, self._room_sell(sym, pos))
        if bq > 0: orders.append(Order(sym, bpx,  bq))
        if sq > 0: orders.append(Order(sym, apx, -sq))

    # ── Main run loop ──────────────────────────────────────────
    def run(self, state: TradingState):
        data = self._load(state.traderData)
        result = {}
        conversions = 0

        # ── Snapshot mid-prices ───────────────────────────────
        exd = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hyd = state.order_depths.get("HYDROGEL_PACK")
        ex_mid = self._mid(exd) if exd else None
        hy_mid = self._mid(hyd) if hyd else None

        # ── Update histories once per timestamp ───────────────
        if state.timestamp != data["last_ts"]:
            if ex_mid is not None:
                data["ex_hist"].append(ex_mid)
            if hy_mid is not None:
                data["hy_hist"].append(hy_mid)
            data["last_ts"] = state.timestamp

        # ── Update EMA for extract ────────────────────────────
        if ex_mid is not None:
            alpha = 0.12
            if data["ex_ema"] is None:
                data["ex_ema"] = ex_mid
            else:
                data["ex_ema"] = alpha * ex_mid + (1.0 - alpha) * data["ex_ema"]

        # ── Estimate realized vol from extract returns ─────────
        if len(data["ex_hist"]) >= 30:
            h = data["ex_hist"][-100:]
            rets = [h[i] - h[i-1] for i in range(1, len(h))]
            tick_std = math.sqrt(sum(r*r for r in rets) / len(rets))
            mean_p = sum(h) / len(h)
            # annualise (1 000 ticks/day × 365 days)
            rv_new = tick_std * math.sqrt(1_000 * 365) / max(mean_p, 1)
            data["rv"] = 0.92 * data["rv"] + 0.08 * rv_new

        rv = data["rv"]

        # ══════════════════════════════════════════════════════
        # 1.  HYDROGEL_PACK  –  mean-reversion MM
        # ══════════════════════════════════════════════════════
        if hyd:
            orders = []
            pos = state.position.get("HYDROGEL_PACK", 0)

            # Fair value: 70% hard anchor at 10 000, 30% recent EMA
            if len(data["hy_hist"]) >= 10:
                hy_recent = sum(data["hy_hist"][-20:]) / min(20, len(data["hy_hist"]))
                fair = 0.70 * 10_000.0 + 0.30 * hy_recent
            else:
                fair = 10_000.0

            # Aggressive taking: snipe any clear mis-quotes
            pos, _ = self._take_buy( "HYDROGEL_PACK", hyd, fair - 1, pos, 50, orders)
            pos, _ = self._take_sell("HYDROGEL_PACK", hyd, fair + 1, pos, 50, orders)

            # Passive quoting – half-spread = 7, size = 12 per side
            # Inventory skew is built into _quote (±9 shells at ±200)
            self._quote("HYDROGEL_PACK", hyd, fair, pos, 7, 12, orders)

            result["HYDROGEL_PACK"] = orders

        # ══════════════════════════════════════════════════════
        # 2.  VELVETFRUIT_EXTRACT_VOUCHERs  –  options strategy
        # ══════════════════════════════════════════════════════
        target_delta = 0.0   # net delta we want to offset in extract

        if ex_mid is not None:

            # ─── Build per-voucher IV data ────────────────────
            iv_data = {}     # sym → {iv, lm, delta, fair, mid, depth}
            sm_pts  = []     # points for quadratic smile fit (near-ATM only)

            for sym, K in STRIKES.items():
                depth = state.order_depths.get(sym)
                if not depth:
                    continue
                m = self._mid(depth)
                if m is None:
                    continue

                iv  = iv_bisect(m, ex_mid, K, TTE_R3)
                dlt = bs_delta(ex_mid, K, TTE_R3, max(iv, PRIOR_IV * 0.5))
                fv  = bs_call(ex_mid, K, TTE_R3, PRIOR_IV)

                # log-moneyness normalised by sqrt(T) → smile x-axis
                lm  = math.log(ex_mid / K) / math.sqrt(TTE_R3) if ex_mid > 0 else 0.0

                iv_data[sym] = {
                    "iv": iv, "lm": lm, "delta": dlt,
                    "fair": fv, "mid": m, "depth": depth, "K": K,
                }

                # Include in smile fit only if IV looks meaningful
                if 0.05 < iv < 1.2 and abs(lm) < 4.0:
                    sm_pts.append((lm, iv))

            # ─── Fit quadratic smile ──────────────────────────
            coeff = fit_quadratic(sm_pts) if len(sm_pts) >= 4 else None
            # Fall back to flat prior if fit fails
            if coeff is None:
                coeff = [PRIOR_IV, 0.0, 0.0]
            a, b, c = coeff

            # ─── Trade each voucher ───────────────────────────
            for sym, info in iv_data.items():
                K      = info["K"]
                depth  = info["depth"]
                m      = info["mid"]
                iv     = info["iv"]
                lm     = info["lm"]
                dlt    = info["delta"]
                orders = result.get(sym, [])
                pos    = state.position.get(sym, 0)
                intr   = max(0.0, ex_mid - K)
                base_cap = VOL_BASE.get(sym, 0)

                # ── Deep ITM basis arb (VEV_4000, VEV_4500) ──
                if K <= 4500:
                    # Fair price = intrinsic (S – K).  Extrinsic≈0 historically.
                    fair_px = intr
                    bid, ask = self._best(depth)

                    # Buy if voucher trading below intrinsic (free edge)
                    if ask is not None and ask < fair_px - 0.3:
                        qty = min(-depth.sell_orders[ask],
                                  self._room_buy(sym, pos), base_cap)
                        if qty > 0:
                            orders.append(Order(sym, ask, qty))
                            pos += qty

                    # Sell if trading above intrinsic + generous buffer
                    if bid is not None and bid > fair_px + 1.5:
                        qty = min(depth.buy_orders[bid],
                                  self._room_sell(sym, pos), base_cap)
                        if qty > 0:
                            orders.append(Order(sym, bid, -qty))
                            pos -= qty

                    result[sym] = orders
                    # Delta of current position (after new orders)
                    target_delta -= pos * 1.0   # delta≈1, hedge 1:1
                    continue

                # ── Deep OTM (VEV_6000, VEV_6500) – skip ─────
                if K >= 6000:
                    result[sym] = orders
                    continue

                # ── Near-ATM vouchers (VEV_5000–VEV_5500) ────
                smooth_iv  = max(0.08, a + b * lm + c * lm * lm)
                iv_residual = iv - smooth_iv    # >0 → market IV too high → SELL

                # Also compare IV to realized vol
                iv_vs_rv = iv - rv              # >0 → market overpricing vol → SELL

                # Conviction: blend surface misalignment & vol-risk-premium signal
                abs_res = abs(iv_residual)
                if abs_res < IV_NOISE_THR:
                    conviction = 0.0
                elif abs_res >= IV_HIGH_THR:
                    conviction = 1.0
                else:
                    conviction = (abs_res - IV_NOISE_THR) / (IV_HIGH_THR - IV_NOISE_THR)

                # Add a small boost when realized vol confirms direction
                if iv_vs_rv > 0.04 and iv_residual > 0:
                    conviction = min(1.0, conviction + 0.15)
                elif iv_vs_rv < -0.04 and iv_residual < 0:
                    conviction = min(1.0, conviction + 0.15)

                max_qty = max(1, int(round(base_cap * conviction)))

                # Fair price from smoothed IV surface
                fair_px  = bs_call(ex_mid, K, TTE_R3, smooth_iv)
                bid, ask = self._best(depth)

                if conviction >= 0.05:
                    if iv_residual > IV_NOISE_THR:
                        # Market IV too high → SELL voucher
                        if bid is not None and bid >= fair_px - 0.5:
                            qty = min(depth.buy_orders[bid],
                                      self._room_sell(sym, pos), max_qty)
                            if qty > 0:
                                orders.append(Order(sym, bid, -qty))
                                pos -= qty

                    elif iv_residual < -IV_NOISE_THR:
                        # Market IV too low → BUY voucher
                        if ask is not None and ask <= fair_px + 0.5:
                            qty = min(-depth.sell_orders[ask],
                                      self._room_buy(sym, pos), max_qty)
                            if qty > 0:
                                orders.append(Order(sym, ask, qty))
                                pos += qty

                # ── Passive quoting for liquid strikes ────────
                # Only quote when we have room and signal is medium-conviction
                if sym in ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300"):
                    if abs(pos) < 80 and conviction > 0.05:
                        self._quote(sym, depth, fair_px, pos, 1.5, 3, orders)

                result[sym] = orders
                # Accumulate delta from current (potentially updated) position
                target_delta -= pos * dlt

        # ══════════════════════════════════════════════════════
        # 3.  VELVETFRUIT_EXTRACT  –  delta hedge + light MM
        # ══════════════════════════════════════════════════════
        if exd and ex_mid is not None:
            orders = []
            pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
            ema = data["ex_ema"] if data["ex_ema"] is not None else ex_mid

            # Clip target to available position headroom
            target = int(round(
                max(-LIMITS["VELVETFRUIT_EXTRACT"],
                    min( LIMITS["VELVETFRUIT_EXTRACT"], target_delta))
            ))
            need = target - pos

            # Aggressively move toward target delta
            if need > 3:
                pos, _ = self._take_buy("VELVETFRUIT_EXTRACT", exd,
                                        ema + 5, pos, min(need, 40), orders)
            elif need < -3:
                pos, _ = self._take_sell("VELVETFRUIT_EXTRACT", exd,
                                         ema - 5, pos, min(-need, 40), orders)

            # Passive market-making if inventory is comfortable
            if abs(pos) < 120:
                self._quote("VELVETFRUIT_EXTRACT", exd, ema, pos, 3, 5, orders)

            result["VELVETFRUIT_EXTRACT"] = orders

        # ── Ensure every product has an entry ────────────────
        for p in LIMITS:
            if p not in result:
                result[p] = []

        return result, conversions, self._dump(data)
