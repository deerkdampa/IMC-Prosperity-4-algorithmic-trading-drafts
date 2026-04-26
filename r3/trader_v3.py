from datamodel import OrderDepth, TradingState, Order
import json
import math

# ============================================================
# trader_v3.py  —  IMC Prosperity 4, Round 3
# Key upgrades vs gemini_draft_2:
#   1. VEV_5300 added (was silently missing — critical strike)
#   2. solve_iv bounds widened: [0.001, 10.0] — old [0.10, 0.50]
#      was clipping near-ATM IV (~0.04) to 0.10, wrecking fair prices
#   3. IV smile fit: quadratic IV(m) across all smile strikes per tick,
#      so each strike gets its own fair IV — not a single global sigma
#   4. Smile coefficients are EMA-smoothed tick-to-tick for stability
#   5. iv_ema seed corrected: 0.08 (was 0.29 — far too high for ATM)
#   6. VEV limits raised to 200 for near-ATM strikes (5000-5400)
#   7. Fallback to global iv_ema if smile fit has < 3 points
# ============================================================


class Trader:

    # --- Position limits (game: 300 for VEVs; we use 200 near-ATM, 100 wings) ---
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 100, "VEV_4500": 100,
        "VEV_5000": 200, "VEV_5100": 200, "VEV_5200": 200,
        "VEV_5300": 200, "VEV_5400": 200,   # <-- VEV_5300 was MISSING
        "VEV_5500": 100,
        "VEV_6000": 30,  "VEV_6500": 30,    # near worthless; tiny limit
    }

    STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500,
        "VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200,
        "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500,
        "VEV_6000": 6000, "VEV_6500": 6500,
    }

    # Strikes used in smile fit — must have real extrinsic value
    SMILE_STRIKES = [
        "VEV_4500",
        "VEV_5000", "VEV_5100", "VEV_5200",
        "VEV_5300", "VEV_5400", "VEV_5500",
    ]

    DELTA_LIMIT   = 150.0  # aggregate option delta cap (in VFE units)
    MIN_EDGE      = 1.0    # minimum price edge to trigger option trade
    SMILE_ALPHA   = 0.3    # EMA blend for smile coefficients each tick

    # VFE market-making constants
    VEV_HALFSPREAD       = 6
    VEV_MOMENTUM_CAP     = 4
    VEV_POSITION_HARD_CAP = 120
    VEV_WARMUP_TICKS     = 50

    # ------------------------------------------------------------------ #
    #  State persistence                                                   #
    # ------------------------------------------------------------------ #
    def load_data(self, trader_data):
        d = {
            'iv_ema': 0.08,          # corrected seed — near-ATM IV ~0.04-0.08
            'smile_coeffs': None,    # [a, b, c] for IV = a*m^2 + b*m + c
            'hydro_hist': [],
            'last_ts': -1,
            'vev_ema': 5255.0,
            'vev_ema_slow': 5255.0,
            'tick_count': 0,
        }
        if trader_data:
            try:
                d.update(json.loads(trader_data))
            except Exception:
                pass
        return d

    def dump_data(self, d):
        return json.dumps(d, separators=(',', ':'))

    # ------------------------------------------------------------------ #
    #  Options math (pure Python — no scipy/numpy)                         #
    # ------------------------------------------------------------------ #
    def _cdf(self, x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_price(self, S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        return S * self._cdf(d1) - K * self._cdf(d1 - sigma * math.sqrt(T))

    def bs_delta(self, S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        return self._cdf(d1)

    def solve_iv(self, S, K, T, market_price):
        """
        Bisection IV solver.
        FIX: bounds now [0.001, 10.0] — old [0.10, 0.50] was clipping
        near-ATM IV (~0.04) to 0.10, making every ATM option look cheap.
        Returns None if no solution (e.g. no extrinsic value left).
        """
        intrinsic = max(0.0, S - K)
        if market_price <= intrinsic + 0.05:
            return None           # no extrinsic → BS cannot solve
        lo, hi = 0.001, 10.0
        if self.bs_price(S, K, T, hi) < market_price:
            return None           # market price exceeds even extreme sigma
        for _ in range(35):
            mid = (lo + hi) * 0.5
            if self.bs_price(S, K, T, mid) < market_price:
                lo = mid
            else:
                hi = mid
        iv = (lo + hi) * 0.5
        return iv if 0.001 < iv < 9.9 else None

    # ------------------------------------------------------------------ #
    #  IV smile fitting — quadratic, pure Python least-squares             #
    # ------------------------------------------------------------------ #
    def fit_smile(self, pts):
        """
        Fit IV = a*m^2 + b*m + c  (m = log(S/K)) to a list of (m, iv) pairs.
        Returns (a, b, c) or None. No external libraries.
        """
        n = len(pts)
        if n < 3:
            return None
        # Build normal equations for [a, b, c]
        s = [0.0] * 5       # sum of m^0 ... m^4
        t = [0.0] * 3       # sum of iv * m^0, m^1, m^2
        for m, iv in pts:
            pw = 1.0
            for i in range(5):
                s[i] += pw
                pw *= m
            pw = 1.0
            for i in range(3):
                t[i] += iv * pw
                pw *= m
        # A * x = b  where A[i][j] = s[i+j], b[i] = t[i], x = [c, b, a]
        A = [[s[i + j] for j in range(3)] for i in range(3)]
        b = list(t)
        # Gaussian elimination with partial pivoting
        for col in range(3):
            pivot = max(range(col, 3), key=lambda r: abs(A[r][col]))
            if abs(A[pivot][col]) < 1e-12:
                return None
            A[col], A[pivot] = A[pivot], A[col]
            b[col], b[pivot] = b[pivot], b[col]
            p = A[col][col]
            A[col] = [v / p for v in A[col]]
            b[col] /= p
            for row in range(3):
                if row != col:
                    f = A[row][col]
                    A[row] = [A[row][j] - f * A[col][j] for j in range(3)]
                    b[row] -= f * b[col]
        c_, b_, a_ = b[0], b[1], b[2]
        return (a_, b_, c_)   # IV = a*m^2 + b*m + c

    def smile_iv(self, coeffs, S, K):
        """Evaluate smile IV at strike K; clamp to safe range."""
        m = math.log(S / K)
        iv = coeffs[0] * m * m + coeffs[1] * m + coeffs[2]
        return max(0.005, min(8.0, iv))

    # ------------------------------------------------------------------ #
    #  Order book helpers                                                  #
    # ------------------------------------------------------------------ #
    def mid(self, depth):
        b = max(depth.buy_orders)  if depth.buy_orders  else None
        a = min(depth.sell_orders) if depth.sell_orders else None
        if b is not None and a is not None:
            return (b + a) / 2.0
        return b if b is not None else a

    def best_ba(self, depth):
        b = max(depth.buy_orders)  if depth.buy_orders  else None
        a = min(depth.sell_orders) if depth.sell_orders else None
        return b, a

    def room_b(self, sym, pos): return max(0, self.LIMITS[sym] - pos)
    def room_s(self, sym, pos): return max(0, self.LIMITS[sym] + pos)

    def take_buy(self, sym, depth, max_px, pos, cap, orders):
        done = 0
        for ask in sorted(depth.sell_orders):
            if ask > max_px or done >= cap: break
            qty = min(-depth.sell_orders[ask], self.room_b(sym, pos), cap - done)
            if qty > 0:
                orders.append(Order(sym, ask, qty))
                pos += qty; done += qty
        return pos, done

    def take_sell(self, sym, depth, min_px, pos, cap, orders):
        done = 0
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < min_px or done >= cap: break
            qty = min(depth.buy_orders[bid], self.room_s(sym, pos), cap - done)
            if qty > 0:
                orders.append(Order(sym, bid, -qty))
                pos -= qty; done += qty
        return pos, done

    def passive_quote(self, sym, depth, fair, pos, halfspread, size, orders):
        if size <= 0: return
        bid, ask = self.best_ba(depth)
        skew = int(round(8.0 * pos / self.LIMITS[sym]))
        bpx = int(math.floor(fair - halfspread - skew))
        apx = int(math.ceil(fair  + halfspread - skew))
        if bid is not None: bpx = min(bpx, bid + 1)
        if ask is not None: apx = max(apx, ask - 1)
        if apx <= bpx: apx = bpx + 1
        bq = min(size, self.room_b(sym, pos))
        sq = min(size, self.room_s(sym, pos))
        if bq > 0: orders.append(Order(sym, bpx,  bq))
        if sq > 0: orders.append(Order(sym, apx, -sq))

    # ------------------------------------------------------------------ #
    #  Main run loop                                                       #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        result = {}
        data = self.load_data(state.traderData)

        # TTE: Round 3 opens at 5 days remaining, ends at 4.
        progress = min(1.0, state.timestamp / 1_000_000.0)
        tte = (5.0 - progress) / 365.0

        ex_depth = state.order_depths.get('VELVETFRUIT_EXTRACT')
        hy_depth = state.order_depths.get('HYDROGEL_PACK')
        ex_mid   = self.mid(ex_depth) if ex_depth else None
        hy_mid   = self.mid(hy_depth) if hy_depth else None

        if state.timestamp != data['last_ts']:
            if hy_mid is not None:
                data['hydro_hist'].append(hy_mid)
                data['hydro_hist'] = data['hydro_hist'][-120:]
            data['tick_count'] = data.get('tick_count', 0) + 1
            data['last_ts'] = state.timestamp

        # ============================================================
        # 1. HYDROGEL_PACK — mean reversion around 10 000
        # ============================================================
        if hy_depth:
            orders = []
            pos  = state.position.get('HYDROGEL_PACK', 0)
            fair = 9991.0
            hist = data['hydro_hist']
            if len(hist) >= 10:
                fair = 0.1 * 9991.0 + 0.9 * (sum(hist[-10:]) / 10)
            pos, _ = self.take_buy ('HYDROGEL_PACK', hy_depth, fair - 2, pos, 20, orders)
            pos, _ = self.take_sell('HYDROGEL_PACK', hy_depth, fair + 2, pos, 20, orders)
            self.passive_quote('HYDROGEL_PACK', hy_depth, fair, pos, 8, 10, orders)
            result['HYDROGEL_PACK'] = orders

        # ============================================================
        # 2. VEV OPTIONS — smile-based IV scalping
        # ============================================================
        if ex_mid and ex_mid > 0:

            # --- 2a. Collect per-strike IVs for smile fit ---
            smile_pts = []
            for sym in self.SMILE_STRIKES:
                K = self.STRIKES[sym]
                dep = state.order_depths.get(sym)
                if not dep: continue
                v_mid = self.mid(dep)
                if v_mid is None or v_mid <= 0: continue
                iv = self.solve_iv(ex_mid, K, tte, v_mid)
                if iv is not None:
                    smile_pts.append((math.log(ex_mid / K), iv))

            # --- 2b. Fit / update smile coefficients ---
            if len(smile_pts) >= 3:
                new_c = self.fit_smile(smile_pts)
                if new_c is not None:
                    old = data['smile_coeffs']
                    if old is None:
                        data['smile_coeffs'] = list(new_c)
                    else:
                        a = self.SMILE_ALPHA
                        data['smile_coeffs'] = [
                            a * new_c[i] + (1 - a) * old[i] for i in range(3)
                        ]

            coeffs = data['smile_coeffs']

            # --- 2c. Update fallback ATM IV EMA from VEV_5200 ---
            dep52 = state.order_depths.get('VEV_5200')
            if dep52:
                vm = self.mid(dep52)
                if vm:
                    iv_atm = self.solve_iv(ex_mid, 5200, tte, vm)
                    if iv_atm:
                        data['iv_ema'] = 0.2 * iv_atm + 0.8 * data['iv_ema']

            # --- 2d. Compute net portfolio delta ---
            agg_delta = 0.0
            for sym, K in self.STRIKES.items():
                p = state.position.get(sym, 0)
                if p == 0: continue
                sigma = (self.smile_iv(coeffs, ex_mid, K) if coeffs
                         else data['iv_ema'])
                agg_delta += p * self.bs_delta(ex_mid, K, tte, sigma)

            # --- 2e. Collect mispricing opportunities ---
            opps = []
            for sym, K in self.STRIKES.items():
                dep = state.order_depths.get(sym)
                if not dep: continue

                # Per-strike fair IV from smile (fallback: global EMA)
                sigma = (self.smile_iv(coeffs, ex_mid, K) if coeffs
                         else data['iv_ema'])

                fair_px = self.bs_price(ex_mid, K, tte, sigma)
                delta_i = self.bs_delta(ex_mid, K, tte, sigma)
                pos_i   = state.position.get(sym, 0)
                req_b   = self.MIN_EDGE if pos_i >= 0 else 0.0
                req_s   = self.MIN_EDGE if pos_i <= 0 else 0.0

                for ask, vol in dep.sell_orders.items():
                    if fair_px - ask > req_b:
                        opps.append(dict(sym=sym, px=ask, qty=-vol,
                                         edge=fair_px - ask,
                                         delta=delta_i, side='BUY'))
                for bid, vol in dep.buy_orders.items():
                    if bid - fair_px > req_s:
                        opps.append(dict(sym=sym, px=bid, qty=vol,
                                         edge=bid - fair_px,
                                         delta=-delta_i, side='SELL'))

            # Sort by edge / |delta| — best risk-adjusted PnL first
            opps.sort(key=lambda o: o['edge'] / max(0.01, abs(o['delta'])),
                      reverse=True)

            # --- 2f. Execute, respecting delta cap ---
            for o in opps:
                sym   = o['sym']
                pos_i = state.position.get(sym, 0)
                room  = (self.LIMITS[sym] - pos_i
                         if o['side'] == 'BUY'
                         else self.LIMITS[sym] + pos_i)
                qty   = min(o['qty'], room)
                if qty <= 0: continue

                new_d = agg_delta + qty * o['delta']
                if abs(new_d) > self.DELTA_LIMIT and abs(new_d) > abs(agg_delta):
                    continue   # would push delta beyond cap in bad direction

                signed = qty if o['side'] == 'BUY' else -qty
                lst = result.get(sym, [])
                lst.append(Order(sym, o['px'], signed))
                result[sym] = lst
                agg_delta = new_d
                state.position[sym] = pos_i + signed

        # ============================================================
        # 3. VELVETFRUIT_EXTRACT — market making with inventory skew
        # ============================================================
        if ex_depth and ex_mid is not None:
            orders = []
            pos   = state.position.get('VELVETFRUIT_EXTRACT', 0)
            limit = self.LIMITS['VELVETFRUIT_EXTRACT']

            # Fast EMA for fair value
            a_fast = 0.7
            data['vev_ema'] = a_fast * ex_mid + (1 - a_fast) * data.get('vev_ema', ex_mid)
            fair = data['vev_ema']

            # Slow EMA for trend
            a_slow = 0.05
            data['vev_ema_slow'] = (a_slow * ex_mid
                                    + (1 - a_slow) * data.get('vev_ema_slow', ex_mid))

            tc = data.get('tick_count', 0)
            trend = (fair - data['vev_ema_slow']) if tc >= self.VEV_WARMUP_TICKS else 0.0

            mom_skew = max(-self.VEV_MOMENTUM_CAP,
                           min(self.VEV_MOMENTUM_CAP, int(round(trend * 0.5))))
            inv_skew = int(round(10.0 * pos / limit))
            total_skew = mom_skew + inv_skew

            hcl = pos >  self.VEV_POSITION_HARD_CAP
            hcs = pos < -self.VEV_POSITION_HARD_CAP

            if not hcl:
                pos, _ = self.take_buy ('VELVETFRUIT_EXTRACT', ex_depth,
                                        fair - 4, pos, 10, orders)
            if not hcs:
                pos, _ = self.take_sell('VELVETFRUIT_EXTRACT', ex_depth,
                                        fair + 4, pos, 10, orders)

            bid, ask = self.best_ba(ex_depth)
            bpx = int(math.floor(fair - self.VEV_HALFSPREAD - total_skew))
            apx = int(math.ceil (fair + self.VEV_HALFSPREAD - total_skew))
            if bid is not None: bpx = min(bpx, bid + 1)
            if ask is not None: apx = max(apx, ask - 1)
            if apx <= bpx: apx = bpx + 1

            pr = pos / limit
            bq = min(15, self.room_b('VELVETFRUIT_EXTRACT', pos)) if pr < 0.6  and not hcl else 0
            sq = min(15, self.room_s('VELVETFRUIT_EXTRACT', pos)) if pr > -0.6 and not hcs else 0

            if bq > 0: orders.append(Order('VELVETFRUIT_EXTRACT', bpx,  bq))
            if sq > 0: orders.append(Order('VELVETFRUIT_EXTRACT', apx, -sq))

            result['VELVETFRUIT_EXTRACT'] = orders

        data['last_ts'] = state.timestamp
        return result, 0, self.dump_data(data)
