"""
trader_v6_with_hint.py
======================
IMC Prosperity 4 – Round 2 optimised trader, VERSION 6 (with osmium alpha hints).

This file is identical to trader_v5_no_hint.py for INTARIAN_PEPPER_ROOT.
For ASH_COATED_OSMIUM it adds the two statistically-derived alpha signals on
top of the V5 baseline fixes.

Why V4 (the previous "with hint" version) underperformed the original:
  • Same broken buy-gate as V3 for pepper root (inherited the `ask <= fair+1`
    condition) – diagnosed in full above.
  • Quote sizes still capped at 10 despite the osmium alpha additions giving a
    genuine ~+4 000 lift over V3. The alphas worked; the sizing bug cancelled
    part of the gain.

What changed:
  V5 baseline fixes applied (see trader_v5_no_hint.py for full explanation).
  Osmium alpha signals re-applied on top of the fixed baseline.

────────────────────────────────────────────────────────────────────────────
OSMIUM ALPHA 1 – 5-tick mean-reversion (calibrated k = 0.485)
────────────────────────────────────────────────────────────────────────────
  Statistical finding across all 30 000 ticks of Round 2 price data:
    - When momentum_5 > +4  →  expected next change = –3.84
    - When momentum_5 > +2  →  expected next change = –1.35
    - When momentum_5 ≈  0  →  expected next change ≈ –0.08 (no signal)
    - When momentum_5 < –2  →  expected next change = +0.99
    - When momentum_5 < –4  →  expected next change = +3.81

  OLS regression: adjusted_fair = fair_base − 0.485 × momentum_5

  Interpretation: when osmium has recently risen 5 ticks, its expected
  equilibrium is lower than the current mid. Shifting our fair value DOWN
  causes our passive ask to sit at a lower absolute price, making it more
  likely to be hit as the price reverts. Our passive bid also shifts down,
  so we buy less aggressively into a spike – reducing adverse selection.
  The reverse logic applies when the price has recently fallen.

────────────────────────────────────────────────────────────────────────────
OSMIUM ALPHA 2 – order-book volume imbalance
────────────────────────────────────────────────────────────────────────────
  Statistical finding across all 30 000 ticks:
    - Large bid surplus (imbalance > +20)  →  E[next_change] ≈ +0.68
    - Large ask surplus (imbalance < –20)  →  E[next_change] ≈ –0.69

  Implementation: when the book is bid-heavy, add 3 units to buy order
  size and subtract 3 from sell size (lean long). When ask-heavy, reverse.
  This sizes us in the direction of the predicted next-tick move while
  staying within position limits.

MAF bid: 3137 (odd, inside the recommended 2 000–5 000 range).
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

ROOT_FAST_ALPHA = 0.18
ROOT_SLOW_ALPHA = 0.04
OSMIUM_ALPHA    = 0.20

# Alpha 1: OLS-calibrated mean-reversion coefficient
OSMIUM_MR_K          = 0.485
# Alpha 2: minimum imbalance (bid_vol − ask_vol) to activate sizing boost
OSMIUM_IMB_THRESHOLD = 5
# How many historical osmium mids to keep for the 5-tick momentum window
OSMIUM_MOM_WINDOW    = 5


class Trader:
    # ── Market Access Fee ─────────────────────────────────────────────────────
    def bid(self) -> int:
        return 3137

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast":  None,
                "root_slow":  None,
                "root_last_mid": None,
                "osmium_ema":  10000.0,
                "osm_mids":   [],      # rolling window for Alpha 1
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

            # ─────────────────────────────────────────────────────────────────
            # INTARIAN_PEPPER_ROOT  (identical to V5)
            # ─────────────────────────────────────────────────────────────────
            if product == "INTARIAN_PEPPER_ROOT":
                fast     = data.get("root_fast")
                slow     = data.get("root_slow")
                last_mid = data.get("root_last_mid")

                if fast is None:
                    fast = slow = last_mid = mid

                fast  = ROOT_FAST_ALPHA * mid + (1 - ROOT_FAST_ALPHA) * fast
                slow  = ROOT_SLOW_ALPHA * mid + (1 - ROOT_SLOW_ALPHA) * slow
                slope = fast - slow
                momentum    = mid - last_mid
                trend_score = 0.5 * slope + 0.5 * momentum

                current = pos

                if slope > 0:
                    # ── UPTREND: fill to near-limit, unconditional best-ask ──
                    target_pos = 76

                    # Always take the best ask level (the spread is ~6–8 ticks
                    # so any price-gated condition would systematically miss)
                    if current < target_pos:
                        vol = depth.sell_orders[best_ask]
                        qty = min(-vol, target_pos - current)
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            current += qty

                    # Sweep deeper levels if they are within 5 ticks of mid
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if ask == best_ask:
                            continue
                        if current >= target_pos:
                            break
                        if ask <= mid + 5:
                            qty = min(-vol, target_pos - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break

                    # Passive bid to catch sellers willing to cross slightly
                    if current < target_pos:
                        bid_px = best_bid + 1
                        qty    = min(target_pos - current, 10)
                        if qty > 0:
                            orders.append(Order(product, bid_px, qty))

                elif slope > -1.0:
                    # ── FLAT / NEUTRAL: modest long position of 25 ───────────
                    target_pos = 25

                    for ask, vol in sorted(depth.sell_orders.items()):
                        if current >= target_pos:
                            break
                        if ask <= mid + 4:
                            qty = min(-vol, target_pos - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break

                    if current < target_pos:
                        bid_px = best_bid + 1
                        qty    = min(target_pos - current, 8)
                        if qty > 0:
                            orders.append(Order(product, bid_px, qty))

                # Exit only on clear reversal; keep a floor of 5 units
                if current > 5 and trend_score < -2.5:
                    for bid_p, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if current <= 5:
                            break
                        if bid_p >= mid - 1:
                            qty = min(vol, current - 5)
                            if qty > 0:
                                orders.append(Order(product, bid_p, -qty))
                                current -= qty
                        else:
                            break

                data["root_fast"]     = fast
                data["root_slow"]     = slow
                data["root_last_mid"] = mid

            # ─────────────────────────────────────────────────────────────────
            # ASH_COATED_OSMIUM  – V5 baseline + both alpha signals
            # ─────────────────────────────────────────────────────────────────
            elif product == "ASH_COATED_OSMIUM":
                ema = data.get("osmium_ema", 10000.0)
                ema = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema

                # V3/V5 improved fair value (more responsive than original)
                fair_base = 0.70 * ema + 0.30 * mid

                # ── ALPHA 1: mean-reversion fair-value adjustment ─────────────
                # Maintain a rolling window of recent osmium mid prices so we
                # can compute momentum over the last OSMIUM_MOM_WINDOW ticks.
                osm_mids: list = data.get("osm_mids", [])
                osm_mids.append(mid)
                if len(osm_mids) > OSMIUM_MOM_WINDOW:
                    osm_mids = osm_mids[-OSMIUM_MOM_WINDOW:]
                data["osm_mids"] = osm_mids

                if len(osm_mids) >= OSMIUM_MOM_WINDOW:
                    # Positive momentum_5 → price recently rose → expect
                    # reversion DOWN → shift fair down so we lean short.
                    momentum_5  = mid - osm_mids[0]
                    mr_adjustment = OSMIUM_MR_K * momentum_5
                else:
                    mr_adjustment = 0.0

                # Alpha-adjusted fair value for all quoting decisions below
                fair = fair_base - mr_adjustment

                # ── ALPHA 2: book volume imbalance signal ─────────────────────
                # Total visible bid volume minus total visible ask volume.
                # Positive → more buy pressure → next tick move expected UP.
                bid_vol_total = sum(depth.buy_orders.values())
                ask_vol_total = sum(-v for v in depth.sell_orders.values())
                imbalance     = bid_vol_total - ask_vol_total

                current = pos

                # Aggressive crosses (same thresholds as V5)
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair - 1.5 and current < limit:
                        qty = min(-vol, limit - current)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                for bid_p, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid_p >= fair + 1.5 and current > -limit:
                        qty = min(vol, current + limit)
                        if qty > 0:
                            orders.append(Order(product, bid_p, -qty))
                            current -= qty
                    else:
                        break

                # Dynamic half-spread (V5 values)
                if spread <= 3:
                    half_spread = 1
                elif spread <= 6:
                    half_spread = 2
                elif spread <= 12:
                    half_spread = 3
                else:
                    half_spread = 4

                # Gentle inventory skew (0.05, close to original's 0.048)
                skew = round(current * 0.05)

                my_bid = min(best_bid + 1, math.floor(fair - half_spread) - skew)
                my_ask = max(best_ask - 1, math.ceil(fair + half_spread) - skew)

                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                # V5-fixed base sizing: min(20, room) – back to original volume
                buy_room  = max(0, limit - current)
                sell_room = max(0, limit + current)
                buy_size  = min(20, buy_room)
                sell_size = min(20, sell_room)

                # ── Apply Alpha 2: tilt sizing toward the imbalance signal ────
                # When the book has strong bid pressure (more bids than asks),
                # we expect the price to tick up, so we want our buy quote to
                # fill preferentially and our sell quote to step back slightly.
                imb_boost = 3
                if imbalance > OSMIUM_IMB_THRESHOLD:
                    buy_size  = min(buy_size  + imb_boost, buy_room)
                    sell_size = max(sell_size - imb_boost, 0)
                elif imbalance < -OSMIUM_IMB_THRESHOLD:
                    sell_size = min(sell_size + imb_boost, sell_room)
                    buy_size  = max(buy_size  - imb_boost, 0)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid), buy_size))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -sell_size))

                data["osmium_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)