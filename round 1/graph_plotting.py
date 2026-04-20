import pandas as pd
import matplotlib.pyplot as plt

# Load the data — semicolon separated
df = pd.read_csv("prices_round_1_day_0.csv", sep=";")

# Split into separate dataframes per product
ash = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
pepper = df[df["product"] == "INTARIAN_PEPPER_ROOT"].copy()

# Filter out missing/pre-market rows where mid_price is 0
ash = ash[ash["mid_price"] > 0]
pepper = pepper[pepper["mid_price"] > 0]

# Create two separate subplots stacked vertically
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
fig.suptitle("Prosperity 4 — Round 1 Data", fontsize=14, fontweight="bold")

# ── Ash-Coated Osmium ─────────────────────────────────────
ax1.plot(ash["timestamp"], ash["mid_price"], color="royalblue", linewidth=1.5, label="Mid Price")
ax1.plot(ash["timestamp"], ash["bid_price_1"], color="green", linewidth=0.8, alpha=0.5, linestyle="--", label="Best Bid")
ax1.plot(ash["timestamp"], ash["ask_price_1"], color="red", linewidth=0.8, alpha=0.5, linestyle="--", label="Best Ask")
ax1.set_title("ASH-COATED OSMIUM", fontweight="bold")
ax1.set_ylabel("Price")
ax1.legend(loc="upper right")
ax1.grid(True, alpha=0.3)
ash_mid = ash["mid_price"]
ax1.set_ylim(ash_mid.min() - 20, ash_mid.max() + 20)

# ── Intarian Pepper Root ──────────────────────────────────
ax2.plot(pepper["timestamp"], pepper["mid_price"], color="tomato", linewidth=1.5, label="Mid Price")
ax2.plot(pepper["timestamp"], pepper["bid_price_1"], color="green", linewidth=0.8, alpha=0.5, linestyle="--", label="Best Bid")
ax2.plot(pepper["timestamp"], pepper["ask_price_1"], color="red", linewidth=0.8, alpha=0.5, linestyle="--", label="Best Ask")
ax2.set_title("INTARIAN PEPPER ROOT", fontweight="bold")
ax2.set_xlabel("Timestamp")
ax2.set_ylabel("Price")
ax2.legend(loc="upper right")
ax2.grid(True, alpha=0.3)
pepper_mid = pepper["mid_price"]
ax2.set_ylim(pepper_mid.min() - 20, pepper_mid.max() + 20)

plt.tight_layout()
plt.show()

# ── Print quick stats ──────────────────────────────────────
print("=== ASH-COATED OSMIUM ===")
print(f"  Mid price range: {ash_mid.min():.1f} — {ash_mid.max():.1f}")
print(f"  Std deviation:   {ash_mid.std():.4f}")
print(f"  Mean:            {ash_mid.mean():.2f}")

print("\n=== INTARIAN PEPPER ROOT ===")
print(f"  Mid price range: {pepper_mid.min():.1f} — {pepper_mid.max():.1f}")
print(f"  Std deviation:   {pepper_mid.std():.4f}")
print(f"  Mean:            {pepper_mid.mean():.2f}")
