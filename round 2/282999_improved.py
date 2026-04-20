from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math

POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

ROOT_FAST_ALPHA = 0.18
ROOT_SLOW_ALPHA = 0.04
OSMIUM_ALPHA = 0.15

class Trader:
    def run(self, state: TradingState):
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast": None,
                "root_slow": None,
                "root_last_mid": None,
                "root_hold_mode": False,
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
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            if product == "INTARIAN_PEPPER_ROOT":
                # V2 roots: keep teammate's strong core idea (long the trend),
                # but enter more calmly and avoid obviously eager fills.
                fast = data.get("root_fast")
                slow = data.get("root_slow")
                last_mid = data.get("root_last_mid")
                hold_mode = data.get("root_hold_mode", False)

                if fast is None:
                    fast = mid
                    slow = mid
                    last_mid = mid

                fast = ROOT_FAST_ALPHA * mid + (1 - ROOT_FAST_ALPHA) * fast
                slow = ROOT_SLOW_ALPHA * mid + (1 - ROOT_SLOW_ALPHA) * slow
                slope = fast - slow
                momentum = mid - last_mid
                fair = 0.65 * fast + 0.35 * slow

                # Once the trend is established, behave more like the teammate's successful hold-to-80 logic.
                if slope > 2 or momentum > 1:
                    hold_mode = True
                if slope < -4 and momentum < -2:
                    hold_mode = False

                current = pos

                # Step 1: Take asks, but not blindly. If trend is up, allow paying slightly above fair.
                # This keeps the strong roots edge while reducing very bad entries.
                if hold_mode and current < limit:
                    buy_cap_price = fair + 2
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if current >= limit:
                            break
                        if ask <= buy_cap_price or ask <= best_ask:
                            qty = min(-vol, limit - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break
                else:
                    target = 40 if slope >= 0 else 20
                    buy_cap_price = fair + 1
                    for ask, vol in sorted(depth.sell_orders.items()):
                        if current >= target:
                            break
                        if ask <= buy_cap_price:
                            qty = min(-vol, target - current)
                            if qty > 0:
                                orders.append(Order(product, ask, qty))
                                current += qty
                        else:
                            break

                # Step 2: Passive bid if we still want more and quote can look calm.
                desired = limit if hold_mode else (40 if slope >= 0 else 20)
                if current < desired:
                    bid_px = min(best_bid + 1, math.floor(fair))
                    bid_px = min(bid_px, best_ask - 1)
                    qty = min(desired - current, 20)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

                # Step 3: Only reduce if the trend weakens a lot and there is a rich bid.
                if current > 0 and (slope < -2 or momentum < -2):
                    for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                        if bid >= fair + 2:
                            qty = min(vol, current)
                            if qty > 0:
                                orders.append(Order(product, bid, -qty))
                                current -= qty
                        else:
                            break

                data["root_fast"] = fast
                data["root_slow"] = slow
                data["root_last_mid"] = mid
                data["root_hold_mode"] = hold_mode
            
            elif product == "ASH_COATED_OSMIUM":
                # Osmium: dynamic fair value + two small overlays:
                #  - order-book imbalance nudge (hacky alpha A)
                #  - snap-back on extreme deviations (hacky alpha B)
                ema = data.get("osmium_ema", 10000.0)
                ema = OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * ema

                # Basic dynamic fair: mostly EMA, a bit of current mid
                fair = 0.7 * ema + 0.3 * mid

                current = pos

                # ---------- Hacky alpha A: imbalance-based fair adjustment ----------
                bid_vol = sum(v for v in depth.buy_orders.values())
                ask_vol = sum(-v for v in depth.sell_orders.values())
                total_vol = bid_vol + ask_vol
                imbalance = 0.0
                if total_vol > 0:
                    imbalance = (bid_vol - ask_vol) / total_vol  # in [-1, 1]

                # Nudge fair by 1 tick in direction of net demand
                imb_boost = 1.0
                fair_adj = fair + imb_boost * imbalance

                # ---------- Hacky alpha B: snap-back after extreme deviations ----------
                spread = best_ask - best_bid
                dev = mid - fair  # positive: mid above fair, negative: below
                extreme_threshold = 3 * spread  # can tune (e.g. 30 ticks if spread is tiny)

                # If price is very far from fair, push harder toward mean-reversion
                if abs(dev) >= extreme_threshold and spread >= 2:
                    if dev > 0:
                        # Mid far above fair -> want to be short / sell aggressively
                        for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                            if current <= -limit:
                                break
                            if bid >= fair + 1.0:
                                qty = min(vol, current + limit, 10)
                                if qty > 0:
                                    orders.append(Order(product, bid, -qty))
                                    current -= qty
                            else:
                                break
                    else:
                        # Mid far below fair -> want to be long / buy aggressively
                        for ask, vol in sorted(depth.sell_orders.items()):
                            if current >= limit:
                                break
                            if ask <= fair - 1.0:
                                qty = min(-vol, limit - current, 10)
                                if qty > 0:
                                    orders.append(Order(product, ask, qty))
                                    current += qty
                            else:
                                break

                # ---------- Normal aggressive mean-reversion around fair_adj ----------
                take_edge = 1.5  # ticks away from fair_adj

                # Buy clearly cheap
                for ask, vol in sorted(depth.sell_orders.items()):
                    if current >= limit:
                        break
                    if ask <= fair_adj - take_edge:
                        qty = min(-vol, limit - current, 10)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                    else:
                        break

                # Sell clearly rich
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if current <= -limit:
                        break
                    if bid >= fair_adj + take_edge:
                        qty = min(vol, current + limit, 10)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            current -= qty
                    else:
                        break

                # ---------- Passive market-making with stronger inventory skew ----------
                skew = float(round(current * 0.10))
                half_spread = 1 if spread <= 3 else (2 if spread <= 6 else 3)
                my_bid = min(best_bid + 1, math.floor(fair_adj - half_spread) - skew)
                my_ask = max(best_ask - 1, math.ceil(fair_adj + half_spread) - skew)

                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_cap = max(0, limit - current)
                sell_cap = max(0, limit + current)
                buy_size = min(10, buy_cap)
                sell_size = min(10, sell_cap)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid), int(buy_size)))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -int(sell_size)))

                data["osmium_ema"] = ema
                
            result[product] = orders

        return result, 0, jsonpickle.encode(data)