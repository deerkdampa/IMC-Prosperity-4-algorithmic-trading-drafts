import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import glob

def load_and_merge_data():
    all_files = glob.glob("prices_round_3_day_*.csv")
    df_list = []
    for file in all_files:
        try:
            df = pd.read_csv(file, sep=';')
            df_list.append(df)
        except Exception as e:
            print(f"Error reading {file}: {e}")
            
    if not df_list:
        raise ValueError("No CSV files found! Ensure prices_round_3_day_X.csv are in the directory.")
        
    data = pd.concat(df_list, ignore_index=True)
    data.sort_values(by=['day', 'timestamp'], inplace=True)
    return data

def analyze_hydrogel():
    print("Loading historical data...")
    df = load_and_merge_data()
    
    # Isolate HYDROGEL_PACK
    hydro = df[df['product'] == 'HYDROGEL_PACK'].copy()
    
    if hydro.empty:
        print("No HYDROGEL_PACK data found.")
        return
        
    print("Calculating Microstructure Metrics...")
    
    # 1. Basic Price & Spread Metrics
    hydro['mid_price'] = (hydro['bid_price_1'] + hydro['ask_price_1']) / 2
    hydro['spread'] = hydro['ask_price_1'] - hydro['bid_price_1']
    
    # 2. Order Book Imbalance (OBI)
    hydro['obi'] = (hydro['bid_volume_1'] - hydro['ask_volume_1']) / (hydro['bid_volume_1'] + hydro['ask_volume_1'])
    
    # 3. Future Returns (Predictive Power)
    hydro['return_1_tick'] = hydro['mid_price'].shift(-1) - hydro['mid_price']
    hydro['return_5_tick'] = hydro['mid_price'].shift(-5) - hydro['mid_price']
    
    # FIX: Only drop rows where our specific calculated columns are NaN
    hydro.dropna(subset=['mid_price', 'spread', 'obi', 'return_1_tick', 'return_5_tick'], inplace=True)
    
    # --- STATISTICS FOR GEMINI ---
    print("\n" + "="*40)
    print("--- RESULTS FOR GEMINI ---")
    print("="*40)
    
    # Price Stats
    print(f"1. PRICE STATS:")
    print(f"   Mean Mid-Price: {hydro['mid_price'].mean():.2f}")
    print(f"   Price Std Dev:  {hydro['mid_price'].std():.2f}")
    print(f"   Min / Max:      {hydro['mid_price'].min():.2f} / {hydro['mid_price'].max():.2f}")
    
    # Spread Stats
    print(f"\n2. SPREAD STATS:")
    print(f"   Average Spread: {hydro['spread'].mean():.2f}")
    
    # Safe Mode calculation
    mode_spreads = hydro['spread'].mode()
    if not mode_spreads.empty:
        print(f"   Mode Spread:    {mode_spreads.iloc[0]:.2f}")
    else:
        print(f"   Mode Spread:    N/A")
    
    # Autocorrelation (Mean Reversion Check)
    print(f"\n3. MEAN REVERSION (Autocorrelation of Returns):")
    print(f"   Lag 1 Tick:  {hydro['return_1_tick'].autocorr(lag=1):.4f}")
    print(f"   Lag 5 Ticks: {hydro['return_5_tick'].autocorr(lag=1):.4f}")
    
    # Order Book Imbalance Correlation (Momentum Check)
    print(f"\n4. ORDER BOOK IMBALANCE (Predictive Power):")
    corr_1 = hydro['obi'].corr(hydro['return_1_tick'])
    corr_5 = hydro['obi'].corr(hydro['return_5_tick'])
    print(f"   Correlation OBI to 1-Tick Return: {corr_1:.4f}")
    print(f"   Correlation OBI to 5-Tick Return: {corr_5:.4f}")
    print("="*40 + "\n")

    # --- PLOTTING ---
    print("Generating Plots...")
    
    plt.figure(figsize=(12, 5))
    plt.plot(hydro['mid_price'].values, color='teal', linewidth=1)
    plt.title('HYDROGEL_PACK Mid-Price History (Days 0-2)')
    plt.xlabel('Timestamps (Aggregated)')
    plt.ylabel('Mid Price')
    plt.grid(True, alpha=0.3)
    plt.savefig('Hydrogel_Price.png')
    
    hydro['obi_bucket'] = hydro['obi'].round(1)
    obi_moves = hydro.groupby('obi_bucket')['return_1_tick'].mean()
    
    plt.figure(figsize=(10, 5))
    obi_moves.plot(kind='bar', color='coral')
    plt.title('Order Book Imbalance vs Expected Price Change')
    plt.xlabel('Order Book Imbalance (-1.0 = All Sells, 1.0 = All Buys)')
    plt.ylabel('Average Next-Tick Price Change')
    plt.axhline(0, color='black', linewidth=1)
    plt.grid(True, alpha=0.3)
    plt.savefig('Hydrogel_OBI.png')
    
    print("Saved 'Hydrogel_Price.png' and 'Hydrogel_OBI.png'")

if __name__ == "__main__":
    analyze_hydrogel()