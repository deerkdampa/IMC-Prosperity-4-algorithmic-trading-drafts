import pandas as pd
import math
import sys

def cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_price(S, K, T, sigma):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0: return max(0.0, S - K)
    d1 = (math.log(S / K) + (0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * cdf(d1) - K * cdf(d2)

def implied_vol(S, K, T, market_price):
    low, high = 0.001, 3.0
    for _ in range(50):
        mid = (low + high) / 2
        price = bs_price(S, K, T, mid)
        if price < market_price:
            low = mid
        else:
            high = mid
    return (low + high) / 2

def run_analysis(csv_path):
    print(f"Loading {csv_path}...")
    try:
        df = pd.read_csv(csv_path, sep=";")
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return

    # Extract underlying prices
    extract = df[df['product'] == 'VELVETFRUIT_EXTRACT'][['timestamp', 'mid_price']].set_index('timestamp')
    extract.columns = ['S']
    
    # Extract option prices
    vev = df[df['product'] == 'VEV_5200'][['timestamp', 'mid_price']].set_index('timestamp')
    vev.columns = ['opt_price']
    
    # Merge on timestamp
    merged = extract.join(vev).dropna()
    
    print("Calculating Implied Volatility for VEV_5200...")
    ivs = []
    for ts, row in merged.iterrows():
        # Using the exact TTE from our trader.py
        progress = ts / 1000000.0
        T = (5.0 / 365.0) - progress * (1.0 / 365.0)
        
        iv = implied_vol(row['S'], 5200, T, row['opt_price'])
        ivs.append(iv)
        
    merged['IV'] = ivs
    
    print("\n--- 🧠 MARKET IMPLIED VOLATILITY (DAY 1) ---")
    print(f"Median Sigma: {merged['IV'].median():.4f}")
    print(f"Mean Sigma:   {merged['IV'].mean():.4f}")
    print(f"Min Sigma:    {merged['IV'].min():.4f}")
    print(f"Max Sigma:    {merged['IV'].max():.4f}")
    print("--------------------------------------------")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_analysis(sys.argv[1])
    else:
        print("Please provide the path to your Day 1 CSV.")