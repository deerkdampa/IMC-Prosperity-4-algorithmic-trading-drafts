from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

# ─── Position limits ─────────────────────────────────────────────────────────
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

# ─── EMA decay factors ───────────────────────────────────────────────────────
ROOT_FAST_ALPHA = 0.25   # faster reaction than before (was 0.18)
ROOT_SLOW_ALPHA = 0.06   # slightly faster slow EMA   (was 0.04)
OSMIUM_ALPHA    = 0.15

# ─── Root strategy parameters ────────────────────────────────────────────────
# FIX #2: Thresholds lowered so target=70 fires ~70% of the time instead of 16%
T_UP    = 0.5    # was 2.0 — fires much more often on a steady uptrend
T_DOWN  = -0.5   # was -1.0

# FIX #2: Higher targets — use more of the ±80 limit
TARGET_STRONG = 70   # was 60
TARGET_NEUTRAL = 50  # was 30
TARGET_WEAK    = 10

CHUNK = 15           # lots per take-pass (was 10)

# FIX #1: Entry threshold relative to mid, not lagging fair
# Only take asks within BUY_MAX_ABOVE ticks above mid
BUY_MAX_ABOVE = 3    # was "fair + 1" (which almost never fired)

# ─── Osmium parameters ───────────────────────────────────────────────────────
MM_SIZE  = 30        # was 10 — triple quote size to capture more spread volume
SKEW_K   = 0.08      # inventory skew per-lot

# ─── Market Access Fee bid ───────────────────────────────────────────────────
MAF_BID = 3487       # Change before final submission if desired


class Trader:

    def bid(self) -> int:
        """Return the Market Access Fee (XIRECs).
        Top 50% of bids get +25% order book quotes.
        Only pay if your bid lands in the top 50% of all bids.
        """
        return MAF_BID

    def run(self, state: TradingState):
        # ── Restore persistent state ──────────────────────────────────────
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast":      None,
                "root_slow":      None,
                "root_last_mid":  None,
                "osmium_ema":     10000.0,
            }

        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            orders: List[Order] = []
            pos   = state.position.get(product, 0)
            limit = POSITION_LIMITS[product]

            if not depth.buy_orders or not depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            mid      = (best_bid + best_ask) / 2.0
            spread   = best_ask - best_bid

            # ════════════════════════════════════════════════════════════════
            # INTARIAN_PEPPER_ROOT ── trend-following, long-biased
            # ════════════════════════════════════════════════════════════════
            if product == "INTARIAN_PEPPER_ROOT":
                fast     = data.get("root_fast")
                slow     = data.get("root_slow")
                last_mid = data.get("root_last_mid")

                if fast is None:
                    fast = slow = last_mid = mid

                fast = ROOT_FAST_ALPHA * mid + (1 - ROOT_FAST_ALPHA) * fast
                slow = ROOT_SLOW_ALPHA * mid + (1 - ROOT_SLOW_ALPHA) * slow

                slope      = fast - slow
                momentum   = mid - last_mid
                trend_score = 0.5 * slope + 0.5 * momentum

                # FIX #1: Use fast EMA as fair (much less lag than blended EMA)
                fair = fast

                # FIX #2: Lower thresholds → higher targets fire more often
                if trend_score >= T_UP:
                    target_pos = TARGET_STRONG
                elif trend_score >= 0:
                    target_pos = TARGET_NEUTRAL
                else:
                    target_pos = TARGET_WEAK

                target_pos = min(target_pos, limit)
                current    = pos

                # ── Step 1: Take asks aggressively up to mid + BUY_MAX_ABOVE ──
                # FIX #1: Threshold is now relative to mid (not lagging fair)
                # This fires whenever the ask is reasonably close to current price
                buy_cap_price = mid + BUY_MAX_ABOVE
                for ask, vol in sorted(depth.sell_orders.items()):
                    if current >= target_pos:
                        break
                    if ask <= buy_cap_price:
                        qty = min(-vol, target_pos - current, CHUNK)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                # ── Step 2: Passive bid at best_bid+1 (always at top of queue) ──
                # FIX #3: No longer clamped to lagging fair — just join best bid
                if current < target_pos:
                    bid_px = best_bid + 1
                    bid_px = min(bid_px, best_ask - 1)   # must stay below ask
                    qty    = min(target_pos - current, MM_SIZE)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

                # ── Step 3: Trim longs on clear weakening ──
                # Only exit when trend flips negative AND there is a decent bid
                if current > 0 and trend_score < T_DOWN:
                    for bid_p, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if bid_p >= fair - 1:   # only exit at fair or better
                            floor_pos = TARGET_WEAK   # never sell below 10
                            qty = min(vol, current - floor_pos)
                            if qty > 0:
                                orders.append(Order(product, bid_p, -qty))
                                current -= qty
                        else:
                            break

                data["root_fast"]     = fast
                data["root_slow"]     = slow
                data["root_last_mid"] = mid

            # ════════════════════════════════════════════════════════════════
            # ASH_COATED_OSMIUM ── passive market-making on wide-spread product
            # ════════════════════════════════════════════════════════════════
            elif product == "ASH_COATED_OSMIUM":
                ema  = data.get("osmium_ema", 10000.0)
                ema  = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema

                # FIX #4 & #5: ACO has a ~16-tick real spread.
                # Don't try to take "mispricings" (never fired).
                # Instead focus entirely on passive quoting with larger size.
                # Place quotes at mid ± quarter_spread to sit competitively
                # inside the real spread and earn it consistently.

                current = pos

                # Dynamic half-spread: quote ~25% inside the real spread
                # This keeps us as best bid/ask while earning meaningful edge
                quarter = max(1, spread // 4)

                skew    = int(round(current * SKEW_K))
                my_bid  = math.floor(mid) - quarter - skew
                my_ask  = math.ceil(mid)  + quarter - skew

                # Safety: bid must be below ask
                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                # FIX #4: Bigger quote sizes (30 vs 10) to capture more volume
                buy_cap  = max(0, limit - current)
                sell_cap = max(0, limit + current)
                buy_size  = min(MM_SIZE, buy_cap)
                sell_size = min(MM_SIZE, sell_cap)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid), int(buy_size)))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -int(sell_size)))

                data["osmium_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)
