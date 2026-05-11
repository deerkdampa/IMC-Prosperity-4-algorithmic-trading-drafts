from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json

# ── POSITION LIMIT ────────────────────────────────────────────────────────────
LIMIT = 10

# ── PRODUCT CONFIG ────────────────────────────────────────────────────────────
# strategy: "mm"  = symmetric market making with inventory skew
#           "mr"  = mean-reversion (aggressively take when EMA deviation is large)
# ema_span       : EMA lookback
# half_spread    : (mm only) ticks each side of fair value to quote
# threshold      : (mr only) min EMA deviation to trigger aggressive entry
# aggr_threshold : (mr only) deviation for sweeping multiple levels

PRODUCTS_CONFIG = {
    # ── SNACKPACK – tier-S MM (spread/noise 2.6–3.0×) ──────────────────────
    "SNACKPACK_PISTACHIO":          {"strategy": "mm", "ema_span": 20, "half_spread": 4},
    "SNACKPACK_VANILLA":            {"strategy": "mm", "ema_span": 20, "half_spread": 4},
    "SNACKPACK_RASPBERRY":          {"strategy": "mm", "ema_span": 20, "half_spread": 4},
    "SNACKPACK_CHOCOLATE":          {"strategy": "mm", "ema_span": 20, "half_spread": 4},
    "SNACKPACK_STRAWBERRY":         {"strategy": "mm", "ema_span": 20, "half_spread": 5},

    # ── ROBOT – tier-A mean reversion (ACF −0.23 / −0.13) ──────────────────
    "ROBOT_DISHES":                 {"strategy": "mr", "ema_span": 20, "threshold": 15, "aggr_threshold": 30},
    "ROBOT_IRONING":                {"strategy": "mr", "ema_span": 20, "threshold": 12, "aggr_threshold": 22},

    # ── OXYGEN_SHAKE – tier-A mean reversion (ACF −0.12 / −0.09) ───────────
    "OXYGEN_SHAKE_EVENING_BREATH":  {"strategy": "mr", "ema_span": 20, "threshold": 12, "aggr_threshold": 22},
    "OXYGEN_SHAKE_CHOCOLATE":       {"strategy": "mr", "ema_span": 20, "threshold": 11, "aggr_threshold": 20},

    # ── GALAXY_SOUNDS – tier-B MM (spread/noise 1.26–1.27×) ────────────────
    "GALAXY_SOUNDS_DARK_MATTER":    {"strategy": "mm", "ema_span": 20, "half_spread": 6},
    "GALAXY_SOUNDS_SOLAR_FLAMES":   {"strategy": "mm", "ema_span": 20, "half_spread": 6},

    # ── UV_VISOR – tier-B MM (spread/noise 1.26–1.27×) ─────────────────────
    "UV_VISOR_RED":                 {"strategy": "mm", "ema_span": 20, "half_spread": 6},
    "UV_VISOR_MAGENTA":             {"strategy": "mm", "ema_span": 20, "half_spread": 6},

    # ── OXYGEN_SHAKE – tier-B MM (spread/noise 1.25–1.27×) ─────────────────
    "OXYGEN_SHAKE_MINT":            {"strategy": "mm", "ema_span": 20, "half_spread": 5},
    "OXYGEN_SHAKE_MORNING_BREATH":  {"strategy": "mm", "ema_span": 20, "half_spread": 5},
}


class Trader:

    def run(self, state: TradingState):
        # ── Restore EMA state ─────────────────────────────────────────────────
        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            saved = {}
        ema_map: Dict[str, float] = saved.get("ema", {})

        result: Dict[str, List[Order]] = {}

        for product, cfg in PRODUCTS_CONFIG.items():
            if product not in state.order_depths:
                continue

            od: OrderDepth = state.order_depths[product]
            pos: int = state.position.get(product, 0)

            # ── Mid price ─────────────────────────────────────────────────────
            best_bid = max(od.buy_orders)  if od.buy_orders  else None
            best_ask = min(od.sell_orders) if od.sell_orders else None

            if best_bid is None and best_ask is None:
                result[product] = []
                continue

            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2.0
            elif best_bid is not None:
                mid = float(best_bid)
            else:
                mid = float(best_ask)

            # ── EMA update ────────────────────────────────────────────────────
            span = cfg["ema_span"]
            alpha = 2.0 / (span + 1.0)
            ema = alpha * mid + (1.0 - alpha) * ema_map.get(product, mid)
            ema_map[product] = ema

            # ── Dispatch ──────────────────────────────────────────────────────
            if cfg["strategy"] == "mm":
                orders = self._mm(product, od, pos, ema, cfg)
            else:
                orders = self._mr(product, od, pos, ema, cfg)

            result[product] = orders

        # ── Persist EMA state ─────────────────────────────────────────────────
        return result, 0, json.dumps({"ema": ema_map})

    # ─────────────────────────────────────────────────────────────────────────
    def _mm(self, product: str, od: OrderDepth, pos: int,
            fair: float, cfg: dict) -> List[Order]:
        """
        Symmetric MM with inventory skew.
        1. Snipe any bot order that crosses our fair-value window.
        2. Post passive quotes using remaining capacity.
        """
        hs = cfg["half_spread"]
        orders: List[Order] = []

        # Inventory skew: push quotes against the position to mean-revert
        # Skew is mild – never widen to 0 on one side unintentionally
        skew = int(round(pos * 0.3))
        bid_px = round(fair - hs - skew)
        ask_px = round(fair + hs - skew)

        buy_cap  = LIMIT - pos   # max additional longs
        sell_cap = LIMIT + pos   # max additional shorts

        # Take obviously mispriced bot orders first
        if best_ask := (min(od.sell_orders) if od.sell_orders else None):
            if best_ask <= bid_px and buy_cap > 0:
                vol = min(-od.sell_orders[best_ask], buy_cap)
                orders.append(Order(product, best_ask, vol))
                buy_cap -= vol

        if best_bid := (max(od.buy_orders) if od.buy_orders else None):
            if best_bid >= ask_px and sell_cap > 0:
                vol = min(od.buy_orders[best_bid], sell_cap)
                orders.append(Order(product, best_bid, -vol))
                sell_cap -= vol

        # Post passive resting orders for the remainder
        if buy_cap > 0:
            orders.append(Order(product, bid_px, buy_cap))
        if sell_cap > 0:
            orders.append(Order(product, ask_px, -sell_cap))

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    def _mr(self, product: str, od: OrderDepth, pos: int,
            ema: float, cfg: dict) -> List[Order]:
        """
        Mean-reversion strategy.
        - When price is far below EMA  → buy aggressively.
        - When price is far above EMA  → sell aggressively.
        - Always post a passive unwind order near EMA so inventory drains
          as price reverts.
        """
        thr  = cfg["threshold"]
        aggr = cfg["aggr_threshold"]
        orders: List[Order] = []
        buy_cap  = LIMIT - pos
        sell_cap = LIMIT + pos

        # ── BUY leg: ask is depressed below EMA ──────────────────────────────
        if od.sell_orders and buy_cap > 0:
            sorted_asks = sorted(od.sell_orders.keys())
            for ask in sorted_asks:
                dev = ema - ask
                if dev < thr:
                    break
                vol = min(-od.sell_orders[ask], buy_cap)
                if vol > 0:
                    orders.append(Order(product, ask, vol))
                    buy_cap -= vol
                if buy_cap == 0:
                    break
                if dev < aggr:      # only sweep multiple levels at high dev
                    break

        # ── SELL leg: bid is elevated above EMA ──────────────────────────────
        if od.buy_orders and sell_cap > 0:
            sorted_bids = sorted(od.buy_orders.keys(), reverse=True)
            for bid in sorted_bids:
                dev = bid - ema
                if dev < thr:
                    break
                vol = min(od.buy_orders[bid], sell_cap)
                if vol > 0:
                    orders.append(Order(product, bid, -vol))
                    sell_cap -= vol
                if sell_cap == 0:
                    break
                if dev < aggr:
                    break

        # ── Passive unwind quote near EMA ─────────────────────────────────────
        # Post a small resting order to drain inventory as price reverts.
        # Only post if we actually have a directional position.
        unwind_vol = min(3, abs(pos))
        if pos > 0 and sell_cap > 0:
            orders.append(Order(product, round(ema + thr * 0.4), -unwind_vol))
        elif pos < 0 and buy_cap > 0:
            orders.append(Order(product, round(ema - thr * 0.4), unwind_vol))

        return orders