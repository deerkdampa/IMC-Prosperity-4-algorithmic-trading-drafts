import pandas as pd
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
import matplotlib.pyplot as plt
import glob

# --- 1. Black-Scholes Pricing & IV Root Finder ---
def bs_call_price(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return max(0.0, S - K)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)

def implied_volatility(price, S, K, T, r=0.0):
    # Brent's method to reverse-engineer IV
    def objective(sigma):
        return bs_call_price(S, K, T, r, sigma) - price
    try:
        # Volatility bounds: 0.1% to 500%
        return brentq(objective, 1e-3, 5.0)
    except ValueError:
        return np.nan

# --- 2. Data Loading and Preprocessing ---
def load_and_merge_data():
    all_files = glob.glob("prices_round_3_day_*.csv")
    df_list = []
    for file in all_files:
        df = pd.read_csv(file, sep=';')
        df_list.append(df)
    data = pd.concat(df_list, ignore_index=True)
    data.sort_values(by=['day', 'timestamp'], inplace=True)
    return data

def analyze_iv():
    print("Loading historical data...")
    df = load_and_merge_data()
    
    # Isolate underlying asset
    underlying = df[df['product'] == 'VELVETFRUIT_EXTRACT'].copy()
    underlying['mid_price'] = (underlying['bid_price_1'] + underlying['ask_price_1']) / 2
    underlying_prices = underlying.set_index(['day', 'timestamp'])['mid_price'].to_dict()

    # Isolate Options
    options = df[df['product'].str.startswith('VEV_')].copy()
    options['strike'] = options['product'].str.replace('VEV_', '').astype(float)
    options['mid_price'] = (options['bid_price_1'] + options['ask_price_1']) / 2
    
    print("Calculating Implied Volatilities (This may take a minute)...")
    iv_records = []
    
    for _, row in options.iterrows():
        S = underlying_prices.get((row['day'], row['timestamp']), np.nan)
        K = row['strike']
        price = row['mid_price']
        
        if pd.isna(S) or pd.isna(price): continue
        
        # Assumption: 1 day = 10000 timestamps. Adjust TTE based on exact game rules.
        # Assuming starting TTE is 7 days, decreasing per day.
        T = (7 - row['day']) - (row['timestamp'] / 1000000) 
        if T <= 0: continue
            
        iv = implied_volatility(price, S, K, T)
        moneyness = S / K
        
        iv_records.append({
            'day': row['day'], 'timestamp': row['timestamp'],
            'product': row['product'], 'strike': K, 'S': S,
            'price': price, 'IV': iv, 'moneyness': moneyness
        })
        
    iv_df = pd.DataFrame(iv_records).dropna()
    
    # --- 3. Plotting & Parabola Fitting ---
    print("Fitting Volatility Smile and generating plots...")
    
    plt.figure(figsize=(10, 6))
    plt.scatter(iv_df['moneyness'], iv_df['IV'], alpha=0.1, label='Observed IV')
    
    # Fit 2nd degree polynomial (Parabola)
    coeffs = np.polyfit(iv_df['moneyness'], iv_df['IV'], 2)
    poly_eq = np.poly1d(coeffs)
    
    x_range = np.linspace(iv_df['moneyness'].min(), iv_df['moneyness'].max(), 100)
    plt.plot(x_range, poly_eq(x_range), color='red', linewidth=2, label=f'Fit: {coeffs[0]:.4f}x^2 + {coeffs[1]:.4f}x + {coeffs[2]:.4f}')
    
    plt.title('Implied Volatility Smile (IV vs Moneyness)')
    plt.xlabel('Moneyness (S/K)')
    plt.ylabel('Implied Volatility')
    plt.legend()
    plt.grid(True)
    plt.savefig('IV_Smile.png')
    print("Saved 'IV_Smile.png'")
    
    # Output parameters for Gemini
    print("\n--- RESULTS FOR GEMINI ---")
    print(f"1. Parabola Coefficients [a, b, c]: {coeffs}")
    print(f"2. Average IV per Strike:")
    print(iv_df.groupby('strike')['IV'].mean())
    print(f"3. IV Standard Deviation:")
    print(iv_df.groupby('strike')['IV'].std())
    print("--------------------------\n")

if __name__ == "__main__":
    analyze_iv()