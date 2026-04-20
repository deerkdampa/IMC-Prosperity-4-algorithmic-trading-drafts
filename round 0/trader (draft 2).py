from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import numpy as np
import jsonpickle

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}


class Trader:

    def bid(self):
        return 15

    @staticmethod
    def linear_trend_prediction(prices: List[float], lookahead: int = 1):
        x = np.arange(len(prices), dtype=float)
        y = np.array(prices, dtype=float)
        mean_x = x.mean()
        mean_y = y.mean()
        covariance = np.mean((x - mean_x) * (y - mean_y))
        variance_x = np.mean((x - mean_x) ** 2)
        slope = covariance / variance_x if variance_x > 0 else 0.0
        intercept = mean_y - slope * mean_x
        return intercept + slope * (len(prices) + lookahead - 1), slope

    def run(self, state: TradingState):
        """Only method required. It takes all buy and sell orders for all
        symbols as an input, and outputs a list of orders to be sent."""

        print("traderData: " + state.traderData)
        print("Observations: " + str(state.observations))

        if state.traderData and state.traderData != "SAMPLE":
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "tomato_prices": [],
                "emerald_prices": [],
            }

        result: Dict[str, List[Order]] = {}

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 80)

            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            best_ask_amount = order_depth.sell_orders[best_ask]
            best_bid_amount = order_depth.buy_orders[best_bid]
            mid_price = (best_ask + best_bid) / 2.0

            # ------------------------------------------------------------------
            # EMERALDS — Market Making Strategy
            #
            # WHY THE OLD CODE EARNED ZERO:
            #   EMERALDS mid-price only ever equals 9996, 10000, or 10004.
            #   When the old mean-reversion signal fired (e.g. mid=10004 →
            #   sell signal), it sold at best_bid which equals exactly 10000
            #   (fair value). Symmetrically, buy signals fired when mid=9996
            #   but bought at best_ask = 10000. Every trade executed at 10000
            #   so PnL was always zero.
            #
            # THE FIX — post limit orders INSIDE the spread:
            #   The order book sits at bid=9992 / ask=10008 with fair value
            #   10000. By posting a buy at 9999 and a sell at 10001, bots that
            #   would have sold at 9992 now sell to us at 9999 instead (better
            #   for them), and bots buying at 10008 buy from us at 10001. We
            #   capture ~2 ticks of edge per round trip with near-zero risk
            #   because we always buy below and sell above fair value.
            # ------------------------------------------------------------------
            if product == "EMERALDS":
                trader_state["emerald_prices"].append(mid_price)
                fair_value = 10000.0

                # Step 1: Aggressively take any orders that are clearly
                # mispriced vs fair value (rare but free money when it occurs).
                if best_ask < fair_value:
                    buy_volume = min(-best_ask_amount, limit - position)
                    if buy_volume > 0:
                        orders.append(Order(product, best_ask, buy_volume))

                if best_bid > fair_value:
                    sell_volume = min(best_bid_amount, limit + position)
                    if sell_volume > 0:
                        orders.append(Order(product, best_bid, -sell_volume))

                # Step 2: Post limit orders inside the spread to market make.
                # We quote 9999 on the buy side and 10001 on the sell side.
                # Incoming bots will trade with us at these prices rather than
                # the worse prices currently in the book (9992 / 10008).
                #
                # Account for any positions already ordered above so we never
                # breach the position limit.
                already_buying = sum(o.quantity for o in orders if o.quantity > 0)
                already_selling = sum(-o.quantity for o in orders if o.quantity < 0)

                remaining_buy = limit - position - already_buying
                remaining_sell = limit + position - already_selling

                mm_buy_price = int(fair_value) - 1    # 9999
                mm_sell_price = int(fair_value) + 1   # 10001

                if remaining_buy > 0:
                    orders.append(Order(product, mm_buy_price, remaining_buy))
                if remaining_sell > 0:
                    orders.append(Order(product, mm_sell_price, -remaining_sell))

            # ------------------------------------------------------------------
            # TOMATOES — Trend-Following Strategy (unchanged from original)
            # ------------------------------------------------------------------
            elif product == "TOMATOES":
                trader_state["tomato_prices"].append(mid_price)
                prices = trader_state["tomato_prices"]

                if len(prices) >= 50:
                    predicted_price, slope = self.linear_trend_prediction(prices[-50:])
                    threshold = max(1.5, abs(slope) * 5)

                    if predicted_price > mid_price + threshold and best_ask < predicted_price:
                        buy_volume = min(-best_ask_amount, limit - position)
                        if buy_volume > 0:
                            orders.append(Order(product, best_ask, buy_volume))
                    elif predicted_price < mid_price - threshold and best_bid > predicted_price:
                        sell_volume = min(best_bid_amount, limit + position)
                        if sell_volume > 0:
                            orders.append(Order(product, best_bid, -sell_volume))

            print(
                f"{product} mid={mid_price:.1f} ask={best_ask} bid={best_bid} pos={position} orders={len(orders)}"
            )
            result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData
