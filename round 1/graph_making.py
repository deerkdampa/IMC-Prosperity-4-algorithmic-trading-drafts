import argparse
import os
import pandas as pd
import matplotlib.pyplot as plt


def load_price_data(round_number: int, day: int):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    df_filename = f"prices_round_{round_number}_day_{day}.csv"
    df_path = os.path.join(base_dir, "ROUND_1", df_filename)
    if not os.path.exists(df_path):
        raise FileNotFoundError(f"Dataset not found: {df_path}")
    df = pd.read_csv(df_path, sep=";")
    return df


def plot_product_prices(ax, df, product_name, mid_color):
    timestamps = df["timestamp"]
    mid = df["mid_price"]
    bid = df["bid_price_1"]
    ask = df["ask_price_1"]

    valid_mid = mid > 0
    ax.plot(timestamps[valid_mid], mid[valid_mid], color=mid_color, linewidth=1.8, label="Mid Price")
    ax.plot(timestamps, bid, color="forestgreen", linewidth=0.9, alpha=0.6, linestyle="--", label="Best Bid")
    ax.plot(timestamps, ask, color="firebrick", linewidth=0.9, alpha=0.6, linestyle="--", label="Best Ask")
    ax.fill_between(timestamps, bid, ask, where=bid.notna() & ask.notna(), interpolate=True, color=mid_color, alpha=0.08)

    ax.set_title(product_name, fontweight="bold")
    ax.set_ylabel("Price")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.25)
    ax.set_xlim(timestamps.min(), timestamps.max())

    mid_min = float(mid[valid_mid].min())
    price_min = float(min(mid_min, float(bid.min()), float(ask.min())))
    price_max = float(max(float(mid[valid_mid].max()), float(bid.max()), float(ask.max())))
    margin = max(10, (price_max - price_min) * 0.08)
    ax.set_ylim(price_min - margin, price_max + margin)

    if valid_mid.any():
        last_mid = mid[valid_mid].iloc[-1]
        ax.annotate(f"Last mid: {last_mid:.1f}", xy=(timestamps[valid_mid].iloc[-1], last_mid), xytext=(5, 12), textcoords="offset points", color=mid_color, fontsize=9)


def main():
    parser = argparse.ArgumentParser(description="Plot Prosperity 4 Round 1 price data")
    parser.add_argument("--round", type=int, default=1, help="Round number")
    parser.add_argument("--day", type=int, default=0, choices=[-2, -1, 0], help="Day to plot")
    parser.add_argument("--output", type=str, default=None, help="Optional output PNG file path")
    args = parser.parse_args()

    df = load_price_data(args.round, args.day)
    ash = df[df["product"] == "ASH_COATED_OSMIUM"].copy().sort_values("timestamp")
    intarian = df[df["product"] == "INTARIAN_PEPPER_ROOT"].copy().sort_values("timestamp")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
    fig.suptitle(f"Prosperity 4 — Round {args.round} Day {args.day}", fontsize=14, fontweight="bold")

    plot_product_prices(ax1, intarian, "INTARIAN_PEPPER_ROOT", mid_color="tomato")
    ax1.set_xlabel("")

    plot_product_prices(ax2, ash, "ASH_COATED_OSMIUM", mid_color="royalblue")
    ax2.set_xlabel("Timestamp")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    if args.output:
        fig.savefig(args.output, dpi=150)
        print(f"Saved plot to {args.output}")
    else:
        plt.show()

    # ── Print quick stats ──────────────────────────────────────
    ash_mid = ash["mid_price"]
    intarian_mid = intarian["mid_price"]

    print("=== ASH_COATED_OSMIUM ===")
    print(f"  Mid price range: {ash_mid.min():.1f} — {ash_mid.max():.1f}")
    print(f"  Std deviation:   {ash_mid.std():.4f}")
    print(f"  Mean:            {ash_mid.mean():.2f}")

    print("\n=== INTARIAN_PEPPER_ROOT ===")
    print(f"  Mid price range: {intarian_mid.min():.1f} — {intarian_mid.max():.1f}")
    print(f"  Std deviation:   {intarian_mid.std():.4f}")
    print(f"  Mean:            {intarian_mid.mean():.2f}")


if __name__ == "__main__":
    main()

