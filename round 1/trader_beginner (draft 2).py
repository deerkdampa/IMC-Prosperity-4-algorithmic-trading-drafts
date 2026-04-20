# =============================================================================
# IMC Prosperity 4 — Round 1 Starter Bot
# Strategy: Market Making
# Products: INTARIAN_PEPPER_ROOT, ASH_COATED_OSMIUM
# =============================================================================
#
# ── WHAT IS MARKET MAKING? ───────────────────────────────────────────────────
#
# A market maker simultaneously quotes a BID (price to BUY) and an ASK (price
# to SELL).  The gap between them is called the SPREAD, and it is your profit
# per round-trip trade.
#
# Example: fair value = 10000
#   Your bid  = 9997  (you buy cheap)
#   Your ask  = 10003 (you sell expensive)
#   Spread    =    6  → you earn 6 per share if both sides fill
#
# The key is estimating FAIR VALUE accurately.  If your fair value is wrong
# your quotes will be one-sided and you will lose money.
#
# ── HOW THE EXCHANGE WORKS ───────────────────────────────────────────────────
#
# Each timestep ("tick") you receive a TradingState containing:
#   • order_depths  — the live limit-order book (best bid/ask + sizes)
#   • position      — how many units you currently hold (+ = long, - = short)
#   • traderData    — a string you wrote last tick (use it to persist state)
#
# You return a dict of Order lists.  Each Order is (symbol, price, quantity)
# where quantity > 0 = buy order, quantity < 0 = sell order.
#
# Your orders are matched against the book.  Anything that doesn't cross the
# book rests as a passive limit order until the next tick.
#
# ── POSITION LIMITS ──────────────────────────────────────────────────────────
#
# You cannot hold more than LIMIT units long OR short.  If you try to submit
# an order that would breach the limit it is simply ignored.  Always track
# remaining capacity before submitting.
#
# ── WHAT IS INVENTORY SKEW? ──────────────────────────────────────────────────
#
# If you keep buying you will eventually hit the long limit and be unable to
# buy more — even if the market is cheap.  To avoid this, you "skew" your
# quotes: when long, lower both bid and ask so you sell more easily; when
# short, raise both so you buy more.  The SKEW_FACTOR controls how
# aggressively you do this.
#
# =============================================================================

from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math


# =============================================================================
# ── POSITION LIMITS ──────────────────────────────────────────────────────────
# The maximum number of units you can hold long or short at any time.
# Submitting orders that would exceed these is silently ignored by the engine.
# =============================================================================
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM":    80,
}


# =============================================================================
# ── ASH_COATED_OSMIUM PARAMETERS ─────────────────────────────────────────────
#
# DATA OBSERVATIONS (from prices_round_1_day_*.csv):
#   • Price hovers near 10 000 across all three days
#   • Day-to-day trend is essentially zero (−17, −1, −6 over 10 000 ticks)
#   • Average tick-to-tick move ≈ 0.000  →  no directional drift
#   • Tick-to-tick standard deviation ≈ 3.7  →  noisy oscillation
#   • Average book spread ≈ 16, minimum ≈ 5
#
# STRATEGY: SMA (Simple Moving Average) mean reversion
#   Because the price has no trend, a short window SMA of past mid-prices is
#   a reliable estimate of fair value.  We quote a spread around that average
#   and let the noise fill us on both sides.
#
# THINGS TO TUNE:
#   OSMIUM_WINDOW       — how many past ticks to include in the average.
#                         Shorter = more reactive (follows noise), longer =
#                         smoother (slower to adapt to genuine shifts).
#                         Try values between 20 and 100.
#   OSMIUM_BASE_SPREAD  — minimum half-spread we quote.  Must be > 0.
#                         Smaller → more fills but less profit per fill.
#                         Larger  → more profit per fill but fewer fills.
#                         The book spread averages 16, so anything ≤ 8 keeps
#                         you inside the book.  Try 2–6.
#   OSMIUM_SKEW_FACTOR  — how many ticks to shift per unit of position.
#                         Higher = reverts inventory faster but narrows
#                         effective spread.  Try 0.02–0.15.
# =============================================================================
OSMIUM_WINDOW      = 50
OSMIUM_BASE_SPREAD = 3
OSMIUM_SKEW_FACTOR = 0.05


# =============================================================================
# ── INTARIAN_PEPPER_ROOT PARAMETERS ──────────────────────────────────────────
#
# DATA OBSERVATIONS (from prices_round_1_day_*.csv):
#   • Price rises by ~1 000 every day without fail  (~0.1 per tick)
#   • Tick-to-tick standard deviation ≈ 3.0  →  oscillates ±~300 around trend
#   • Average book spread ≈ 13, minimum ≈ 2
#
# STRATEGY: Mid-price as fair value
#   Because the price trends upward continuously, ANY backward-looking average
#   will lag behind.  A 200-step SMA lags by ~10 ticks ≈ 1 full spread worth.
#   That means your sell quotes will always be priced below the true market,
#   so you get picked off on every sell and slowly build a losing short.
#
#   The fix is simple: use the CURRENT mid-price ((best_bid + best_ask) / 2)
#   as fair value.  It has zero lag and sits exactly at today's price level.
#   The short-term oscillation (stdev ≈ 3) is what fills our spread quotes —
#   we don't need history for that.
#
# THINGS TO TUNE:
#   ROOT_BASE_SPREAD   — minimum half-spread.  Book spread averages 13 so
#                        values of 4–8 keep you competitive.  Start at 5.
#   ROOT_SKEW_FACTOR   — same role as OSMIUM_SKEW_FACTOR.  Because the price
#                        trends up, even a flat inventory will drift long over
#                        time, so you may want a slightly higher skew than
#                        Osmium.  Try 0.05–0.20.
# =============================================================================
ROOT_BASE_SPREAD   = 6
ROOT_SKEW_FACTOR   = 0.05


# =============================================================================
# ── HOW TO FIND GOOD PARAMETER VALUES ────────────────────────────────────────
#
# OPTION A — Manual grid search (recommended first step):
#   Pick one parameter at a time.  Run the backtester with a range of values
#   (e.g. BASE_SPREAD in [2, 3, 4, 5, 6, 7, 8]) and plot final PnL vs value.
#   You will typically see a curve that peaks somewhere in the middle.
#
# OPTION B — Mathematical / analytical approach:
#
#   Optimal spread (Avellaneda-Stoikov model):
#     spread* = γ·σ²·T  +  (2/γ) · ln(1 + γ/κ)
#   where:
#     γ  = risk aversion (start at 0.1)
#     σ  = price volatility per tick (stdev of tick-to-tick moves, see above)
#     T  = time horizon (1 day = 1.0, set to fraction of day remaining)
#     κ  = order arrival rate (how often the book trades; ≈ trades/tick)
#   For OSMIUM:  σ ≈ 3.7,  κ ≈ 0.1  →  spread* ≈ 5–8
#   For ROOTS:   σ ≈ 3.0,  κ ≈ 0.1  →  spread* ≈ 4–7
#   These are rough guides — the exact fit depends on γ which you must tune.
#
#   Optimal skew (same model):
#     skew = -position · γ · σ²· T
#   For OSMIUM with γ=0.1, σ=3.7, T=1: skew ≈ -position · 1.4
#   That is far too aggressive for a 80-unit limit.  Scale γ down until the
#   skew at max position (80) gives ~3–6 ticks of shift.
#   Example: SKEW_FACTOR = 0.05 → max skew = 80 * 0.05 = 4 ticks ✓
#
# OPTION C — Let the data tell you:
#   Look at your trade history in the .log file.  If you fill mostly on the
#   BUY side and drift long → lower bid, raise ask (increase skew).
#   If you rarely fill at all → tighten BASE_SPREAD.
#   If your PnL decreases steadily → fair value is lagging (for ROOTS, switch
#   to mid_price; for OSMIUM, shorten the SMA window).
#
# =============================================================================


class Trader:

    def run(self, state: TradingState):
        # ── 1. RESTORE STATE FROM LAST TICK ──────────────────────────────────
        # traderData is a string we encoded last tick.  It persists any data
        # we need across ticks (price history, running averages, etc.).
        # On the very first tick it is empty, so we initialise defaults.
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],   # price history for the SMA
            }

        result = {}   # will hold {product: [Order, ...]} for each product

        # ── 2. LOOP OVER EVERY TRADEABLE PRODUCT ─────────────────────────────
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            # ── 2a. SKIP if the book is one-sided ────────────────────────────
            # A healthy book always has both buyers and sellers.
            # If one side is missing we cannot compute mid-price safely.
            if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
                result[product] = orders
                continue

            # ── 2b. READ CURRENT POSITION ────────────────────────────────────
            # state.position is a dict.  If we have never traded a product it
            # won't appear, so we use .get() with a default of 0.
            position = state.position.get(product, 0)
            limit    = POSITION_LIMITS.get(product, 80)

            # ── 2c. READ BEST BID AND BEST ASK ───────────────────────────────
            # sell_orders keys are ASK prices (sorted ascending → min = best ask)
            # buy_orders  keys are BID prices (sorted descending → max = best bid)
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())

            # MID-PRICE: the midpoint of the current bid-ask spread.
            # This is the most basic estimate of "where the market is" right now.
            mid_price = (best_ask + best_bid) / 2

            # BOOK SPREAD: the raw gap between the best ask and best bid.
            # Our quotes must stay inside this gap to have any chance of filling
            # (or at least match it — quoting wider means we don't trade).
            book_spread = best_ask - best_bid

            # =================================================================
            # ── PRODUCT: INTARIAN_PEPPER_ROOT ─────────────────────────────────
            # =================================================================
            if product == "INTARIAN_PEPPER_ROOT":

                # FAIR VALUE: use the current mid-price with zero lag.
                # Do NOT use a backward-looking average here — see the parameter
                # comments at the top of the file for the full explanation.
                fair_value = mid_price

                # SPREAD CALCULATION ──────────────────────────────────────────
                # We quote at least ROOT_BASE_SPREAD ticks away from fair value
                # on each side.  If the book's own spread is wide, we can afford
                # to be a bit wider too (floor of half the book spread).
                # Using floor() (not ceil()) makes quotes slightly more
                # aggressive — more likely to fill.
                spread = max(ROOT_BASE_SPREAD, math.floor(book_spread / 2))

                # INVENTORY SKEW ──────────────────────────────────────────────
                # If position > 0 (we are long), skew is negative → we lower
                # both bid and ask to encourage sells and discourage buys.
                # If position < 0 (we are short), skew is positive → opposite.
                skew = -int(round(position * ROOT_SKEW_FACTOR))

                # QUOTE PRICES ────────────────────────────────────────────────
                # buy_price:  our bid — we want to pay LESS than fair value.
                #   min(..., best_ask - 1) ensures we NEVER cross the spread
                #   (we don't want to immediately lift the ask — that is a
                #   market order and gives up the spread).
                # sell_price: our ask — we want to receive MORE than fair value.
                #   max(..., best_bid + 1) ensures we NEVER cross the spread
                #   (we don't want to immediately hit the bid).
                buy_price  = min(math.floor(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(math.ceil(fair_value)  + spread + skew, best_bid + 1)

                # ORDER SIZES ─────────────────────────────────────────────────
                # We want to use the full remaining capacity on each side.
                # buy_volume:  how much more can we buy before hitting +limit?
                # sell_volume: how much more can we sell before hitting -limit?
                # Both are clamped to ≥ 0 by the if-guards below.
                buy_volume  = limit - position    # e.g. limit=80, pos=20 → 60
                sell_volume = limit + position    # e.g. limit=80, pos=20 → 100... capped below

                # Only send orders if there is capacity left
                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            # =================================================================
            # ── PRODUCT: ASH_COATED_OSMIUM ────────────────────────────────────
            # =================================================================
            elif product == "ASH_COATED_OSMIUM":

                # PRICE HISTORY ───────────────────────────────────────────────
                # Append today's mid-price to the rolling history list.
                trader_state["osmium_prices"].append(mid_price)
                prices = trader_state["osmium_prices"]

                # FAIR VALUE: Simple Moving Average (SMA) ─────────────────────
                # We take the most recent OSMIUM_WINDOW prices and average them.
                # If we have fewer ticks than the window (start of the day) we
                # simply average whatever we have — no blackout period, so we
                # trade from tick 1.
                window_size = min(len(prices), OSMIUM_WINDOW)
                fair_value  = sum(prices[-window_size:]) / window_size

                # The rest of the logic is identical to ROOTS — the only
                # difference is the fair_value computation above.
                spread = max(OSMIUM_BASE_SPREAD, math.floor(book_spread / 2))

                skew = -int(round(position * OSMIUM_SKEW_FACTOR))

                buy_price  = min(round(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(round(fair_value) + spread + skew, best_bid + 1)

                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            # ── Attach this product's orders to the result ────────────────────
            result[product] = orders

        # ── 3. PERSIST STATE FOR NEXT TICK ───────────────────────────────────
        # jsonpickle serialises any Python object to a string.
        # The engine stores this string and hands it back next tick.
        traderData = jsonpickle.encode(trader_state)

        # conversions is used for currency conversion in later rounds — not
        # relevant for Round 1, so always return 0.
        conversions = 0

        return result, conversions, traderData
