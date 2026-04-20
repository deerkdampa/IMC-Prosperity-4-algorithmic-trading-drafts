"""
trader_v5_no_hint.py
====================
IMC Prosperity 4 – Round 2 optimised trader, VERSION 5 (no osmium alpha hints).

ROOT-CAUSE FIXES applied vs V3 (trader_v3_no_hint.py)
======================================================

INTARIAN_PEPPER_ROOT – the structural buy-gate was broken
  The V3 code used `ask <= fair + 1` as the entry condition. Because the pepper
  root spread is ~6–8 ticks wide, the best ask sits at roughly mid + 7 at all
  times. The fair value EMA lags the actual price, so `fair + 1` ends up ~4–6
  ticks below the best ask. Result: V3 never triggers a buy and earns roughly
  half the PnL of the original across 3 training days (148k vs 238k).

  Fix: in a confirmed uptrend (EMA slope > 0), take the best ask level
  unconditionally – exactly what the original does in hold_mode. Deeper ask
  levels are still filtered by `mid + 5` (live price, not lagging EMA) to
  avoid paying absurd prices on level 2 and 3. Target position is 76 (near
  limit) in uptrend and 25 in flat/neutral. The exit trigger is very hard
  to fire (trend_score < −2.5) so the position stays on through noise.

  Difference vs original 282999.py: the uptrend trigger uses the EMA slope
  signal (cleaner than the raw single-tick momentum flag in the original),
  which means the bot enters the trade one or two ticks later but at similar
  prices. The passive bid is anchored at `best_bid + 1` so we also queue up
  small fills if the book tightens.

ASH_COATED_OSMIUM – sizing halved by mistake
  V3 used `min(10, room)` for passive quote sizes. The original uses
  `min(20, room)`. This halved fill volume and caused ~10% lower osmium PnL.

  Fix:
    • Passive quote size: `min(20, room)` – matches original volume.
    • Inventory skew: coefficient reduced from 0.10 back to 0.05 (close to
      the original's 0.048). The aggressive 0.10 was shifting our ask too
      far below fair when long, causing us to miss fills on the ask side.
    • Fair value: keep V3's improvement (0.70×EMA + 0.30×mid) – more
      responsive than the heavily anchored original formula.
    • Dynamic half-spread: keep V3's improvement (1/2/3/4 ticks based on
      observed spread) instead of the original's fixed 2 or 3.
    • Aggressive cross threshold: `fair ± 1.5` (V3 value; original used ±2).

MAF bid: 3137 – odd number inside the 2 000–5 000 recommended range.
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

ROOT_FAST_ALPHA = 0.18   # ~5-tick EMA
ROOT_SLOW_ALPHA = 0.04   # ~17-tick EMA

OSMIUM_ALPHA = 0.20      # slightly faster than original's 0.15


class Trader:
    # ── Market Access Fee (one-time first-price bid) ──────────────────────────
    def bid(self) -> int:
        return 3137

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast": None,
                "root_slow": None,
                "root_last_mid": None,
                "osmium_ema": 10000.0,
            }

        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            limit = POSITION_LIMITS[product]

            if not depth.buy_orders or not depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid

            # ─────────────────────────────────────────────────────────────────
            # INTARIAN_PEPPER_ROOT
            #
            # Core logic: use EMA slope as the regime signal.
            # - slope > 0  (uptrend):   fill aggressively to 76, taking the
            #   best ask unconditionally (the spread is always 6–8 ticks so a
            #   price-gated condition can never trigger).
            # - slope ≈ 0  (flat):      hold a moderate position of 25,
            #   buying only when asks come within mid + 4.
            # - slope < −1 (downtrend): reduce to a floor of 5 units.
            #
            # Key difference from 282999.py: the uptrend trigger is the EMA
            # slope (smoother, less noisy) rather than single-tick momentum.
            # In practice on the training data this fires within ~5–10 ticks
            # of each day opening, which is very similar to the original.
            # ─────────────────────────────────────────────────────────────────
            if product == "INTARIAN_PEPPER_ROOT":
                fast = data.get("root_fast")
                slow = data.get("root_slow")
                last_mid = data.get("root_last_mid")

                if fast is None:
                    fast = slow = last_mid = mid

                fast = ROOT_FAST_ALPHA * mid + (1 - ROOT_FAST_ALPHA) * fast
                slow = ROOT_SLOW_ALPHA * mid + (1 - ROOT_SLOW_ALPHA) * slow
                slope = fast - slow
                momentum = mid - last_mid
                trend_score = 0.5 * slope + 0.5 * momentum

                current = pos

                if slope > 0:
                    # ── UPTREND: fill to near-limit aggressively ──────────────
                    target_pos = 76

                    # Always take the best ask – spread is too wide for a price
                    # gate to ever work, and the trend justifies the cost
                    if current < target_pos:
                        vol = depth.sell_orders[best_ask]   # negative in Prosperity
                        qty = min(-vol, target_pos - current)
                        if qty > 0:
                            orders.append(Order(product, best_ask, qty))
                            current += qty

                    # Also sweep deeper ask levels if they are within 5 of mid
                    # (captures thin limit orders sitting close to the top)
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if ask == best_ask:
                            continue  # already handled above
                        if current >= target_pos:
                            break
                        if ask <= mid + 5:
                            qty = min(-vol, target_pos - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break  # deeper asks are only more expensive

                    # Passive bid queued one tick above best bid – picks up any
                    # seller willing to hit slightly above the background bid
                    if current < target_pos:
                        bid_px = best_bid + 1
                        qty = min(target_pos - current, 10)
                        if qty > 0:
                            orders.append(Order(product, bid_px, qty))

                elif slope > -1.0:
                    # ── FLAT / WEAK TREND: modest long bias ───────────────────
                    target_pos = 25

                    for ask, vol in sorted(depth.sell_orders.items()):
                        if current >= target_pos:
                            break
                        # Use live mid + 4 so we're never chasing deep into
                        # the ask side, but we do capture normal spread crossings
                        if ask <= mid + 4:
                            qty = min(-vol, target_pos - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break

                    if current < target_pos:
                        bid_px = best_bid + 1
                        qty = min(target_pos - current, 8)
                        if qty > 0:
                            orders.append(Order(product, bid_px, qty))

                # ── SELL SIDE: exit only on clear trend reversal ──────────────
                # Keep a floor of 5 units so we don't miss a trend resumption
                if current > 5 and trend_score < -2.5:
                    for bid_p, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if current <= 5:
                            break
                        # Require at least mid - 1 to avoid selling into a weak bid
                        if bid_p >= mid - 1:
                            qty = min(vol, current - 5)
                            if qty > 0:
                                orders.append(Order(product, bid_p, -qty))
                                current -= qty
                        else:
                            break

                data["root_fast"] = fast
                data["root_slow"] = slow
                data["root_last_mid"] = mid

            # ─────────────────────────────────────────────────────────────────
            # ASH_COATED_OSMIUM
            #
            # Fixes vs V3:
            #   1. Quote size: min(20, room) – matches original volume.
            #   2. Skew coefficient: 0.05 (≈ original's 0.048).
            # Kept from V3:
            #   3. Fair = 0.70×EMA + 0.30×mid (more responsive than original).
            #   4. Dynamic half-spread (1/2/3/4 ticks based on observed spread).
            #   5. Aggressive cross at fair ± 1.5.
            # ─────────────────────────────────────────────────────────────────
            elif product == "ASH_COATED_OSMIUM":
                ema = data.get("osmium_ema", 10000.0)
                ema = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema

                # More responsive blend than the original's near-static formula
                fair = 0.70 * ema + 0.30 * mid

                current = pos

                # Aggressive crosses: take clearly mispriced levels immediately
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

                # Dynamic half-spread
                if spread <= 3:
                    half_spread = 1
                elif spread <= 6:
                    half_spread = 2
                elif spread <= 12:
                    half_spread = 3
                else:
                    half_spread = 4

                # Gentle inventory skew (0.05) – keeps inventory from straying
                # without pushing quotes so far they stop filling
                skew = round(current * 0.05)

                my_bid = min(best_bid + 1, math.floor(fair - half_spread) - skew)
                my_ask = max(best_ask - 1, math.ceil(fair + half_spread) - skew)

                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                # Position-aware sizing at original volume level (20)
                buy_room = max(0, limit - current)
                sell_room = max(0, limit + current)
                buy_size = min(20, buy_room)
                sell_size = min(20, sell_room)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid), buy_size))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -sell_size))

                data["osmium_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)