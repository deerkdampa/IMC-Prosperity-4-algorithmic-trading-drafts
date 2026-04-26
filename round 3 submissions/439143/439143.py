from datamodel import OrderDepth, TradingState, Order
import json
import math


class Trader:

    # ── Position limits ────────────────────────────────────────────────────────
    LIMITS = {
        "HYDROGEL_PACK":        200,
        "VELVETFRUIT_EXTRACT":  200,
        "VEV_4000": 150, "VEV_4500": 150, "VEV_5000": 150,
        "VEV_5100": 150, "VEV_5200": 150, "VEV_5300": 150,
        "VEV_5400": 150, "VEV_5500": 150, "VEV_6000": 150, "VEV_6500": 150,
    }

    # Strike prices for each voucher
    STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
        "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
        "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000, "VEV_6500": 6500,
    }

    # Minimum edge (in price ticks) required to enter a new voucher position.
    # Raising this reduces false signals at the cost of fewer trades.
    MIN_EDGE = 1.5

    # ── Per-strike IV seeds ────────────────────────────────────────────────────
    # Derived from Round-3 Day-2 historical data by inverting Black-Scholes on
    # every market mid-price observation and taking the mean.
    # Deep ITM (4000/4500) have wider std so seeds are less reliable — EMA
    # will adapt quickly for those strikes.
    IV_SEEDS = {
        "VEV_4000": 0.1502,
        "VEV_4500": 0.2258,
        "VEV_5000": 0.2643,
        "VEV_5100": 0.2609,
        "VEV_5200": 0.2690,
        "VEV_5300": 0.2600,   # estimated — blacklisted in previous version
        "VEV_5400": 0.2501,   # KEY FIX: true IV is LOWER than 5200, not higher
        "VEV_5500": 0.2718,
        "VEV_6000": 0.3000,   # estimated — very low liquidity
        "VEV_6500": 0.3200,   # estimated — very low liquidity
    }

    # ── Persistent state helpers ───────────────────────────────────────────────

    def load_data(self, trader_data: str) -> dict:
        defaults = {
            # Per-strike IV EMAs — each strike tracks its own implied vol
            "iv_ema": dict(self.IV_SEEDS),
            # Hydrogel: rolling history for fair-value EMA
            "hydro_hist": [],
            "last_ts": -1,
            # VEV standalone EMA — seeded at actual Round-3 mean (5262)
            "vev_ema":      5262.0,
            "vev_ema_slow": 5262.0,
        }
        if trader_data:
            try:
                saved = json.loads(trader_data)
                # Merge top-level keys
                defaults.update(saved)
                # Ensure iv_ema is a full dict (old code stored a scalar)
                if not isinstance(defaults["iv_ema"], dict):
                    defaults["iv_ema"] = dict(self.IV_SEEDS)
                # Back-fill any missing strikes added later
                for sym, seed in self.IV_SEEDS.items():
                    defaults["iv_ema"].setdefault(sym, seed)
            except Exception:
                pass
        return defaults

    def dump_data(self, d: dict) -> str:
        return json.dumps(d, separators=(",", ":"))

    # ── Maths helpers ──────────────────────────────────────────────────────────

    def cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def get_bs_price(self, S: float, K: float, T: float, sigma: float) -> float:
        """Black-Scholes call price."""
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.cdf(d1) - K * self.cdf(d2)

    def solve_iv(self, S: float, K: float, T: float, market_price: float) -> float:
        """
        Invert Black-Scholes to recover implied volatility via bisection.
        Bounds widened to (0.01, 2.0) and iterations raised to 50 so deep
        ITM / OTM strikes don't silently clamp at 0.10 or 0.50.
        Returns None if market_price <= intrinsic (no time value to solve).
        """
        intrinsic = max(0.0, S - K)
        if market_price <= intrinsic + 0.01:
            return None
        lo, hi = 0.01, 2.0
        for _ in range(50):
            mid = (lo + hi) / 2.0
            if self.get_bs_price(S, K, T, mid) < market_price:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    # ── Order-book helpers ─────────────────────────────────────────────────────

    def mid_price(self, depth: OrderDepth):
        bid = max(depth.buy_orders)  if depth.buy_orders  else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return bid if bid is not None else ask

    def best_bid_ask(self, depth: OrderDepth):
        bid = max(depth.buy_orders)  if depth.buy_orders  else None
        ask = min(depth.sell_orders) if depth.sell_orders else None
        return bid, ask

    def room_buy(self, product: str, pos: int) -> int:
        return max(0, self.LIMITS[product] - pos)

    def room_sell(self, product: str, pos: int) -> int:
        return max(0, self.LIMITS[product] + pos)

    def take_buy(self, product, depth, max_price, pos, qty_cap, orders):
        """Aggress all ask levels up to max_price, up to qty_cap units."""
        if qty_cap <= 0:
            return pos, 0
        done = 0
        for ask in sorted(depth.sell_orders):
            if ask > max_price:
                break
            avail = -depth.sell_orders[ask]
            qty = min(avail, self.room_buy(product, pos), qty_cap - done)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                pos  += qty
                done += qty
            if done >= qty_cap:
                break
        return pos, done

    def take_sell(self, product, depth, min_price, pos, qty_cap, orders):
        """Hit all bid levels down to min_price, up to qty_cap units."""
        if qty_cap <= 0:
            return pos, 0
        done = 0
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < min_price:
                break
            avail = depth.buy_orders[bid]
            qty = min(avail, self.room_sell(product, pos), qty_cap - done)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                pos  -= qty
                done += qty
            if done >= qty_cap:
                break
        return pos, done

    # ── Main entry point ───────────────────────────────────────────────────────

    def quote(self, product, depth, fair, pos, halfspread, size, orders):
        """Post a passive bid and ask around fair, skewed by inventory."""
        if size <= 0:
            return
        bid, ask = self.best_bid_ask(depth)
        skew = int(round(8.0 * pos / self.LIMITS[product]))
        bpx = int(math.floor(fair - halfspread - skew))
        apx = int(math.ceil (fair + halfspread - skew))
        if bid is not None: bpx = min(bpx, bid + 1)
        if ask is not None: apx = max(apx, ask - 1)
        if apx <= bpx: apx = bpx + 1
        bq = min(size, self.room_buy (product, pos))
        sq = min(size, self.room_sell(product, pos))
        if bq > 0: orders.append(Order(product, bpx,  bq))
        if sq > 0: orders.append(Order(product, apx, -sq))

    def run(self, state: TradingState):
        result = {}
        data = self.load_data(state.traderData)

        # progress: 0.0 at tick 0, 1.0 at tick 1 000 000
        progress = min(1.0, state.timestamp / 1_000_000.0)

        # TTE decreases from 5/365 at start of day to 4/365 at end
        current_tte = max(0.0001, (5.0 / 365.0) - progress * (1.0 / 365.0))

        ex_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hyd_depth = state.order_depths.get("HYDROGEL_PACK")

        ex_mid  = self.mid_price(ex_depth)  if ex_depth  else None
        hyd_mid = self.mid_price(hyd_depth) if hyd_depth else None

        # ── Rolling history update (once per timestamp) ────────────────────────
        if state.timestamp != data["last_ts"]:
            if hyd_mid is not None:
                data["hydro_hist"].append(hyd_mid)
                data["hydro_hist"] = data["hydro_hist"][-120:]
            data["last_ts"] = state.timestamp

        # ══════════════════════════════════════════════════════════════════════
        # 1. HYDROGEL_PACK — simple mean-reversion market making
        # ══════════════════════════════════════════════════════════════════════
        # Fair value: 15% anchor on 9990.81 + 85% rolling EMA (window=12)
        # Inventory skew handled by self.quote() built-in (8 * pos / limit)

        if hyd_depth:
            orders = []
            pos    = state.position.get("HYDROGEL_PACK", 0)

            # Original logic — simple EMA blend, self.quote() handles skew
            fair   = 9990.81
            window = 12
            if len(data["hydro_hist"]) >= window:
                recent = sum(data["hydro_hist"][-window:]) / window
                fair   = 9990.81 * 0.15 + 0.85 * recent

            pos, _ = self.take_buy ("HYDROGEL_PACK", hyd_depth, fair - 2, pos, 20, orders)
            pos, _ = self.take_sell("HYDROGEL_PACK", hyd_depth, fair + 2, pos, 20, orders)
            self.quote("HYDROGEL_PACK", hyd_depth, fair, pos, 8, 10, orders)

            result["HYDROGEL_PACK"] = orders

        # ══════════════════════════════════════════════════════════════════════
        # 2. VELVETFRUIT_EXTRACT - standalone EMA market making
        # Backtested on Round 3 Day 2 data:
        #   take_edge=4 fired only 8 times in 2000 ticks (EMA tracked too closely)
        #   take_edge=1 fires on genuine mispricings: PnL improved from ~80 to ~1640
        #   halfspread=3 + quote() clips to mkt_bid+1/mkt_ask-1 = best passive position
        if ex_depth and ex_mid is not None:
            orders  = []
            ex_pos  = state.position.get("VELVETFRUIT_EXTRACT", 0)

            # EMA-10 as fair value
            alpha = 2 / (10 + 1)
            data["vev_ema"] = alpha * ex_mid + (1 - alpha) * data["vev_ema"]
            vev_fair = data["vev_ema"]

            # Taking: fire when market quotes at/inside our fair value
            # take_edge=1: buy if ask <= fair-1, sell if bid >= fair+1
            pos, _ = self.take_buy ("VELVETFRUIT_EXTRACT", ex_depth,
                                    vev_fair - 1, ex_pos, 20, orders)
            pos, _ = self.take_sell("VELVETFRUIT_EXTRACT", ex_depth,
                                    vev_fair + 1, pos,    20, orders)

            # Passive: halfspread=3, quote() applies inventory skew + clips to inside market
            self.quote("VELVETFRUIT_EXTRACT", ex_depth, vev_fair, pos, 3, 15, orders)

            result["VELVETFRUIT_EXTRACT"] = orders

        # ══════════════════════════════════════════════════════════════════════
        # 3. VOUCHERS — per-strike IV mean-reversion
        # ══════════════════════════════════════════════════════════════════════
        #
        # Root cause of previous losses (VEV_5400: −224 PnL):
        #   Old code used VEV_5200's IV (0.2687) to price ALL strikes.
        #   VEV_5400's true IV is 0.2501 — LOWER than VEV_5200.
        #   This made BS fair for VEV_5400 ≈ 19.8 when market was 16.5.
        #   Strategy bought it every tick thinking it was cheap. It wasn't.
        #
        # Fix: every strike maintains its OWN IV EMA, seeded from historical data.
        #   Each tick: invert BS on the market mid → update that strike's EMA.
        #   Trade when market price deviates from BS price at that strike's own IV.
        #
        # No delta hedging. VEV is independent. No DELTA_LIMIT checks.

        if ex_mid is not None:
            opps = []

            for sym, K in self.STRIKES.items():
                depth = state.order_depths.get(sym)
                if not depth:
                    continue

                v_mid = self.mid_price(depth)

                # ── Update this strike's own IV EMA ───────────────────────────
                if v_mid is not None:
                    iv_solved = self.solve_iv(ex_mid, K, current_tte, v_mid)
                    if iv_solved is not None and 0.05 < iv_solved < 1.5:
                        # EMA weight 0.15/0.85: adapts within ~6 ticks but
                        # is not spooked by single outlier quotes
                        data["iv_ema"][sym] = (0.15 * iv_solved
                                               + 0.85 * data["iv_ema"][sym])

                # ── Compute BS fair using THIS strike's own IV ─────────────────
                sigma_i  = data["iv_ema"][sym]
                bs_fair  = self.get_bs_price(ex_mid, K, current_tte, sigma_i)
                pos      = state.position.get(sym, 0)

                # Inventory-aware edge requirements:
                #   Flat/long → need MIN_EDGE to buy more, 0 to cover shorts
                #   Flat/short → need MIN_EDGE to sell more, 0 to close longs
                buy_edge_req  = self.MIN_EDGE if pos >= 0 else 0.0
                sell_edge_req = self.MIN_EDGE if pos <= 0 else 0.0

                for ask, vol in depth.sell_orders.items():
                    edge = bs_fair - ask
                    if edge > buy_edge_req:
                        opps.append({"sym": sym, "px": ask, "qty": -vol,
                                     "edge": edge, "side": "BUY"})

                for bid, vol in depth.buy_orders.items():
                    edge = bid - bs_fair
                    if edge > sell_edge_req:
                        opps.append({"sym": sym, "px": bid, "qty": vol,
                                     "edge": edge, "side": "SELL"})

            # Sort by raw edge (no delta weighting — not hedging)
            opps.sort(key=lambda x: x["edge"], reverse=True)

            for o in opps:
                sym = o["sym"]
                pos = state.position.get(sym, 0)
                room = (self.room_buy(sym, pos)  if o["side"] == "BUY"
                        else self.room_sell(sym, pos))
                trade_qty = min(o["qty"], room)

                if trade_qty > 0:
                    signed_qty = trade_qty if o["side"] == "BUY" else -trade_qty
                    orders = result.get(sym, [])
                    orders.append(Order(sym, o["px"], signed_qty))
                    result[sym] = orders
                    # Track position locally so room calculations stay accurate
                    state.position[sym] = pos + signed_qty

        data["last_ts"] = state.timestamp
        return result, 0, self.dump_data(data)