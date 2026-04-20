from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Any
import jsonpickle
import math

POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

class Trader:
    def run(self, state: TradingState):
        if state.traderData:
            data = jsonpickle.decode(state.traderData)
        else:
            data = {
                "root_fast": None,
                "root_slow": None,
                "root_last_mid": None,
                "osmium_ema": 10000.0,
                "osmium_abs_dev": 3.0,
            }

        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 0)

            if not depth.buy_orders or not depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            if product == "ASH_COATED_OSMIUM":
                # Stable anchored market making with mild adaptation.
                ema = data.get("osmium_ema", 10000.0)
                abs_dev = data.get("osmium_abs_dev", 3.0)
                ema = 0.10 * mid + 0.90 * ema
                abs_dev = 0.10 * abs(mid - ema) + 0.90 * abs_dev

                # Keep a strong anchor to 10000, but allow slight drift from EMA.
                fair = 0.75 * 10000.0 + 0.25 * ema
                take_edge = max(1, int(round(1.0 + 0.4 * abs_dev)))
                base_half = max(2, int(round(2.0 + 0.3 * abs_dev + 0.15 * max(spread - 4, 0))))
                skew = int(round(pos * 0.05))

                # Aggressively take obvious mispricings.
                cur_pos = pos
                for ask, vol in sorted(depth.sell_orders.items()):
                    if ask <= fair - take_edge and cur_pos < limit:
                        qty = min(-vol, limit - cur_pos)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            cur_pos += qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if bid >= fair + take_edge and cur_pos > -limit:
                        qty = min(vol, cur_pos + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            cur_pos -= qty
                    else:
                        break

                # Passive quotes with inventory control.
                bid_px = min(best_bid + 1, math.floor(fair - base_half) - skew)
                ask_px = max(best_ask - 1, math.ceil(fair + base_half) - skew)
                if bid_px >= ask_px:
                    bid_px = ask_px - 1

                buy_cap = max(0, limit - cur_pos)
                sell_cap = max(0, limit + cur_pos)

                # Lean smaller near extremes.
                buy_size = min(buy_cap, max(0, 30 - max(cur_pos, 0) // 2))
                sell_size = min(sell_cap, max(0, 30 - max(-cur_pos, 0) // 2))

                if buy_size > 0 and bid_px > 0:
                    orders.append(Order(product, int(bid_px), int(buy_size)))
                if sell_size > 0 and ask_px > 0:
                    orders.append(Order(product, int(ask_px), -int(sell_size)))

                data["osmium_ema"] = ema
                data["osmium_abs_dev"] = abs_dev

            elif product == "INTARIAN_PEPPER_ROOT":
                # Trend-following accumulation without blindly paying any price.
                fast = data.get("root_fast")
                slow = data.get("root_slow")
                last_mid = data.get("root_last_mid")
                if fast is None:
                    fast = mid
                    slow = mid
                    last_mid = mid

                fast = 0.25 * mid + 0.75 * fast
                slow = 0.06 * mid + 0.94 * slow
                slope = fast - slow
                momentum = mid - last_mid
                trend_score = slope + 0.6 * momentum
                fair = 0.55 * fast + 0.45 * slow

                cur_pos = pos

                # Determine target inventory from trend strength.
                if trend_score > 6:
                    target = 80
                elif trend_score > 3:
                    target = 60
                elif trend_score > 1:
                    target = 35
                elif trend_score < -6:
                    target = -50
                elif trend_score < -3:
                    target = -20
                else:
                    target = 10

                # Buy undervalued asks while building target.
                buy_threshold = fair + max(1, 0.15 * max(trend_score, 0))
                for ask, vol in sorted(depth.sell_orders.items()):
                    if cur_pos >= min(target, limit):
                        break
                    if ask <= buy_threshold:
                        qty = min(-vol, min(target, limit) - cur_pos)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            cur_pos += qty
                    else:
                        break

                # Sell overpriced bids, especially if trend weakens or position is too long.
                sell_threshold = fair + max(2, 0.35 * max(trend_score, 0))
                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    should_reduce = cur_pos > max(target, 0) or bid >= sell_threshold
                    if cur_pos <= -limit:
                        break
                    if should_reduce and bid >= fair:
                        qty = min(vol, cur_pos + limit)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            cur_pos -= qty
                    else:
                        break

                # Passive accumulation if still below target and quote is not too eager.
                desired_long = max(0, min(target, limit))
                if cur_pos < desired_long:
                    bid_px = min(best_bid + 1, math.floor(fair - 1))
                    bid_px = min(bid_px, best_ask - 1)
                    qty = min(desired_long - cur_pos, max(0, 20))
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

                # Passive profit-taking when very long.
                if cur_pos > 40:
                    ask_px = max(best_ask - 1, math.ceil(fair + 2))
                    ask_px = max(ask_px, best_bid + 1)
                    qty = min(cur_pos - 40, 20)
                    if qty > 0:
                        orders.append(Order(product, int(ask_px), -int(qty)))

                data["root_fast"] = fast
                data["root_slow"] = slow
                data["root_last_mid"] = mid

            result[product] = orders

        trader_data = jsonpickle.encode(data)
        return result, 0, trader_data