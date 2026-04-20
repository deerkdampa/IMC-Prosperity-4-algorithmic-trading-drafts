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
# Osmium fair: EMA on blended reference (mid + microprice); same anchor blend as baseline.
OSMIUM_ALPHA = 0.062
OSMIUM_FAIR_ANCHOR_WEIGHT = 0.352
OSMIUM_FAIR_EMA_WEIGHT = 0.648
OSMIUM_SHAVE_MULT = 5
OSMIUM_MM_SIZE = 20
OSMIUM_INV_QUOTE_EXTRA = 1
# Microprice weight in reference price (0 = mid only, 1 = micro only).
OSMIUM_MICRO_W = 0.42
# Tick volatility EMA — widens quotes when the book is jumping.
OSMIUM_VOL_ALPHA = 0.14
OSMIUM_VOL_WIDE_THRESH = 3.5
OSMIUM_VOL_HALF_SPREAD_BUMP = 1

MAF_BID = 3888


def _osmium_book_spread(best_bid: int, best_ask: int) -> int:
    return max(0, best_ask - best_bid)


def _osmium_half_spread_base(book_spread: int) -> int:
    return 2 if book_spread <= 14 else 3


def _osmium_take_edge(book_spread: int) -> int:
    return 1 if book_spread <= 22 else 2


def _microprice_at_touch(depth: OrderDepth, best_bid: int, best_ask: int, mid: float) -> float:
    vb = depth.buy_orders.get(best_bid, 0)
    vs = depth.sell_orders.get(best_ask, 0)
    abs_b = abs(vb)
    abs_a = abs(vs)
    denom = abs_b + abs_a
    if denom <= 0:
        return mid
    return (best_bid * abs_a + best_ask * abs_b) / denom


class Trader:
    def bid(self) -> int:
        return int(MAF_BID)

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
                "osmium_prev_mid": None,
                "osmium_vol_ema": 0.0,
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

            if product == "INTARIAN_PEPPER_ROOT":
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

                if slope > 2 or momentum > 1:
                    hold_mode = True
                if slope < -4 and momentum < -2:
                    hold_mode = False

                current = pos

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

                desired = limit if hold_mode else (40 if slope >= 0 else 20)
                if current < desired:
                    bid_px = min(best_bid + 1, math.floor(fair))
                    bid_px = min(bid_px, best_ask - 1)
                    qty = min(desired - current, 20)
                    if qty > 0 and bid_px > 0:
                        orders.append(Order(product, int(bid_px), int(qty)))

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
                micro = _microprice_at_touch(depth, best_bid, best_ask, mid)
                ref = (1.0 - OSMIUM_MICRO_W) * mid + OSMIUM_MICRO_W * micro

                prev_m = data.get("osmium_prev_mid")
                if prev_m is None:
                    prev_m = mid
                tick_move = abs(mid - prev_m)
                vol_ema = data.get("osmium_vol_ema", 0.0)
                vol_ema = OSMIUM_VOL_ALPHA * tick_move + (1.0 - OSMIUM_VOL_ALPHA) * vol_ema
                data["osmium_prev_mid"] = mid
                data["osmium_vol_ema"] = vol_ema

                ema = data.get("osmium_ema", 10000.0)
                ema = OSMIUM_ALPHA * ref + (1 - OSMIUM_ALPHA) * ema
                fair = OSMIUM_FAIR_ANCHOR_WEIGHT * 10000.0 + OSMIUM_FAIR_EMA_WEIGHT * ema

                current = pos
                load_factor = current / limit
                shave = int(round(load_factor * OSMIUM_SHAVE_MULT))

                book_spread = _osmium_book_spread(best_bid, best_ask)
                half_spread = _osmium_half_spread_base(book_spread)
                if vol_ema > OSMIUM_VOL_WIDE_THRESH:
                    half_spread += OSMIUM_VOL_HALF_SPREAD_BUMP
                take_edge = _osmium_take_edge(book_spread)

                inv = max(-1.0, min(1.0, load_factor))
                bid_extra = int(round(OSMIUM_INV_QUOTE_EXTRA * max(0.0, inv)))
                ask_extra = int(round(OSMIUM_INV_QUOTE_EXTRA * max(0.0, -inv)))

                my_bid = min(best_bid + 1, math.floor(fair - half_spread) - shave - bid_extra)
                my_ask = max(best_ask - 1, math.ceil(fair + half_spread) - shave + ask_extra)

                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_cap = max(0, limit - current)
                sell_cap = max(0, limit + current)
                buy_size = min(OSMIUM_MM_SIZE, buy_cap)
                sell_size = min(OSMIUM_MM_SIZE, sell_cap)

                if buy_size > 0 and my_bid > 0:
                    orders.append(Order(product, int(my_bid), int(buy_size)))
                if sell_size > 0 and my_ask > 0:
                    orders.append(Order(product, int(my_ask), -int(sell_size)))

                buy_room = max(0, limit - current)
                sell_room = max(0, limit + current)

                buy_take_adj = int(round(max(0.0, inv)))
                sell_take_adj = int(round(max(0.0, -inv)))

                for ask, vol in sorted(depth.sell_orders.items()):
                    if buy_room <= 0:
                        break
                    if ask <= fair - take_edge - buy_take_adj:
                        qty = min(-vol, buy_room)
                        if qty > 0:
                            orders.append(Order(product, ask, qty))
                            current += qty
                            buy_room -= qty
                    else:
                        break

                for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if sell_room <= 0:
                        break
                    if bid >= fair + take_edge + sell_take_adj:
                        qty = min(vol, sell_room)
                        if qty > 0:
                            orders.append(Order(product, bid, -qty))
                            current -= qty
                            sell_room -= qty
                    else:
                        break

                data["osmium_ema"] = ema

            result[product] = orders

        return result, 0, jsonpickle.encode(data)
