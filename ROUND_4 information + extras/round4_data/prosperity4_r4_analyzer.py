"""
IMC Prosperity 4 — Round 4 Analysis Tool
=========================================
Run locally with your Round 4 CSVs to generate all charts + summaries
that Claude needs to build your final strategy.

Usage
-----
  python prosperity4_r4_analyzer.py [--data-dir PATH] [--sample N]

  --data-dir   folder containing the 6 CSVs  (default: current dir)
  --sample     stride for IV computation      (default: 20)
               20 ≈ 1 min runtime; 10 ≈ 3 min but more accurate

Outputs → ./r4_analysis/
  00_summary.txt                ← paste this into Claude first
  *.png                         ← upload all of them
  *.csv                         ← optional extra detail

Dependencies
------------
  pip install pandas numpy matplotlib scipy
"""

import argparse, os, warnings
import numpy as np
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import norm
from scipy.optimize import brentq

warnings.filterwarnings("ignore")

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", default=".")
parser.add_argument("--sample",   type=int, default=20)
args, _ = parser.parse_known_args()

DATA_DIR  = args.data_dir
OUT_DIR   = "r4_analysis"
IV_STRIDE = args.sample
os.makedirs(OUT_DIR, exist_ok=True)

PRICE_FILES = [f"prices_round_4_day_{d}.csv" for d in [1,2,3]]
TRADE_FILES = [f"trades_round_4_day_{d}.csv" for d in [1,2,3]]

# TTE in years (252 trading days / year)
TTE_PER_DAY  = {1: 4/252, 2: 3/252, 3: 2/252}
STRIKES      = [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]
VEV_PRODUCTS = [f"VEV_{k}" for k in STRIKES]
DELTA1_COLOR = {"HYDROGEL_PACK":"#2196F3","VELVETFRUIT_EXTRACT":"#4CAF50"}
VEV_COLORS   = plt.cm.plasma(np.linspace(0.1, 0.9, len(STRIKES)))

# ── Black-Scholes ─────────────────────────────────────────────────────────────

def bs_call(S, K, T, sig, r=0.0):
    if T<=0 or sig<=0: return max(float(S-K),0.0)
    d1=(np.log(S/K)+(r+0.5*sig**2)*T)/(sig*np.sqrt(T)); d2=d1-sig*np.sqrt(T)
    return float(S*norm.cdf(d1)-K*np.exp(-r*T)*norm.cdf(d2))

def bs_delta(S,K,T,sig,r=0.0):
    if T<=0 or sig<=0: return 1.0 if S>K else 0.0
    d1=(np.log(S/K)+(r+0.5*sig**2)*T)/(sig*np.sqrt(T))
    return float(norm.cdf(d1))

def implied_vol(C,S,K,T,r=0.0):
    intr=max(float(S-K),0.0)
    if C<=intr+0.01 or T<=0: return np.nan
    try:
        lo=bs_call(S,K,T,0.001,r); hi=bs_call(S,K,T,30.0,r)
        if C<=lo or C>=hi: return np.nan
        return brentq(lambda s:bs_call(S,K,T,s,r)-C,0.001,30.0,xtol=1e-5,maxiter=100)
    except: return np.nan

# ── Load data ─────────────────────────────────────────────────────────────────

def load_prices():
    frames=[]
    for day,f in enumerate(PRICE_FILES,1):
        p=os.path.join(DATA_DIR,f)
        if not os.path.exists(p): print(f"  [WARN] missing {p}"); continue
        df=pd.read_csv(p,sep=";"); df["day"]=day; frames.append(df)
    if not frames: raise FileNotFoundError("No price CSVs found.")
    df=pd.concat(frames,ignore_index=True)
    for c in ["bid_price_1","bid_volume_1","ask_price_1","ask_volume_1",
              "bid_price_2","bid_volume_2","ask_price_2","ask_volume_2",
              "mid_price","profit_and_loss"]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    df["spread"]   =df["ask_price_1"]-df["bid_price_1"]
    df["global_ts"]=(df["day"]-1)*1_000_000+df["timestamp"]
    return df

def load_trades():
    frames=[]
    for day,f in enumerate(TRADE_FILES,1):
        p=os.path.join(DATA_DIR,f)
        if not os.path.exists(p): print(f"  [WARN] missing {p}"); continue
        df=pd.read_csv(p,sep=";"); df["day"]=day; frames.append(df)
    if not frames: raise FileNotFoundError("No trade CSVs found.")
    df=pd.concat(frames,ignore_index=True)
    df["price"]    =pd.to_numeric(df["price"],   errors="coerce")
    df["quantity"] =pd.to_numeric(df["quantity"],errors="coerce")
    df["global_ts"]=(df["day"]-1)*1_000_000+df["timestamp"]
    return df

def acf_series(s,max_lag=30):
    s=s.dropna()
    return pd.DataFrame([(l,s.autocorr(lag=l)) for l in range(1,max_lag+1)],
                        columns=["lag","acf"])

# ── SECTION 1: Delta-1 ────────────────────────────────────────────────────────

def section_delta1(prices):
    print("[1] Delta-1 overview …")
    fig,axes=plt.subplots(3,2,figsize=(16,14))
    fig.suptitle("Round 4 – HYDROGEL_PACK & VELVETFRUIT_EXTRACT",fontsize=14,fontweight="bold")
    for ci,prod in enumerate(["HYDROGEL_PACK","VELVETFRUIT_EXTRACT"]):
        df=prices[prices["product"]==prod].sort_values("global_ts")
        col=DELTA1_COLOR[prod]
        ax=axes[0,ci]
        for d in [1,2,3]:
            s=df[df["day"]==d]
            ax.plot(s["timestamp"],s["mid_price"],linewidth=0.6,alpha=0.85,label=f"Day {d}")
        ax.set_title(f"{prod.replace('_',' ')} – Mid Price"); ax.legend(fontsize=8)
        ax=axes[1,ci]
        for d in [1,2,3]:
            s=df[df["day"]==d]
            ax.plot(s["timestamp"],s["spread"],linewidth=0.5,alpha=0.7,label=f"Day {d}")
        ax.set_title(f"{prod.replace('_',' ')} – Bid-Ask Spread"); ax.legend(fontsize=8)
        ax=axes[2,ci]; ret=df["mid_price"].pct_change().dropna()
        acf=acf_series(ret,30); ci_=1.96/np.sqrt(len(ret))
        ax.bar(acf["lag"],acf["acf"],color=col,alpha=0.8)
        ax.axhline(ci_,color="red",linestyle="--",linewidth=0.8,label="95% CI")
        ax.axhline(-ci_,color="red",linestyle="--",linewidth=0.8)
        ax.axhline(0,color="black",linewidth=0.6)
        ax.set_title(f"{prod.replace('_',' ')} – Return ACF"); ax.legend(fontsize=8)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"01_delta1_overview.png"),dpi=150); plt.close()
    print("   → 01_delta1_overview.png")

def section_ema_deviation(prices):
    print("[1b] EMA deviation …")
    fig,axes=plt.subplots(2,2,figsize=(16,10))
    fig.suptitle("EMA Deviation – Mean-Reversion Signal",fontsize=14,fontweight="bold")
    for ci,prod in enumerate(["HYDROGEL_PACK","VELVETFRUIT_EXTRACT"]):
        df=prices[prices["product"]==prod].sort_values("global_ts").copy()
        col=DELTA1_COLOR[prod]
        df["ema20"]=df["mid_price"].ewm(span=20).mean()
        df["ema100"]=df["mid_price"].ewm(span=100).mean()
        df["dev20"]=df["mid_price"]-df["ema20"]
        ax=axes[0,ci]
        ax.plot(df["global_ts"],df["mid_price"],color=col,linewidth=0.5,label="Mid")
        ax.plot(df["global_ts"],df["ema20"],color="orange",linewidth=1.0,label="EMA-20")
        ax.plot(df["global_ts"],df["ema100"],color="purple",linewidth=1.0,label="EMA-100")
        ax.set_title(f"{prod.replace('_',' ')} – Price + EMAs"); ax.legend(fontsize=8)
        ax=axes[1,ci]
        p10=df["dev20"].quantile(0.10); p90=df["dev20"].quantile(0.90)
        ax.plot(df["global_ts"],df["dev20"],color=col,linewidth=0.5)
        ax.axhline(p90,color="red",  linestyle="--",linewidth=1,label=f"p90={p90:.1f}")
        ax.axhline(p10,color="green",linestyle="--",linewidth=1,label=f"p10={p10:.1f}")
        ax.axhline(0,color="black",linewidth=0.6)
        ax.set_title(f"{prod.replace('_',' ')} – Deviation from EMA-20"); ax.legend(fontsize=8)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"02_delta1_ema_deviation.png"),dpi=150); plt.close()
    print("   → 02_delta1_ema_deviation.png")

# ── SECTION 2: Options ────────────────────────────────────────────────────────

def build_iv_df(prices):
    print(f"[2] Building IV surface (stride={IV_STRIDE}) …")
    und=(prices[prices["product"]=="VELVETFRUIT_EXTRACT"]
         [["day","timestamp","mid_price"]].rename(columns={"mid_price":"S"})
         .set_index(["day","timestamp"]))
    rows=[]
    for prod in VEV_PRODUCTS:
        K=int(prod.split("_")[1])
        sub=prices[prices["product"]==prod].sort_values(["day","timestamp"])
        # stride in raw timestamp units (100 = 1 tick block)
        ts_vals=sub["timestamp"].unique()[::IV_STRIDE]
        sub=sub[sub["timestamp"].isin(ts_vals)]
        for _,row in sub.iterrows():
            day=int(row["day"]); ts=int(row["timestamp"])
            C=row["mid_price"]; T=TTE_PER_DAY.get(day,np.nan)
            try:
                S=und.loc[(day,ts),"S"]
                if isinstance(S,pd.Series): S=float(S.iloc[0])
            except KeyError: continue
            if pd.isna(C) or pd.isna(S) or S<=0 or C<=0: continue
            iv=implied_vol(C,S,K,T)
            rows.append({"day":day,"timestamp":ts,
                         "global_ts":(day-1)*1_000_000+ts,
                         "product":prod,"strike":K,
                         "mid_price":C,"S":S,"T":T,
                         "moneyness":np.log(S/K),
                         "iv":iv,
                         "delta":bs_delta(S,K,T,iv) if not np.isnan(iv) else np.nan,
                         "fair" :bs_call(S,K,T,iv)  if not np.isnan(iv) else np.nan})
    iv_df=pd.DataFrame(rows)
    print(f"   {len(iv_df):,} samples, {iv_df['iv'].notna().sum():,} valid IVs")
    return iv_df

def section_vol_smile(iv_df):
    print("[2a] Vol smile …")
    fig,axes=plt.subplots(1,3,figsize=(18,6))
    fig.suptitle("Volatility Smile – IV vs ln(S/K) by Day",fontsize=13,fontweight="bold")
    for ax,day in zip(axes,[1,2,3]):
        d=iv_df[(iv_df["day"]==day)&iv_df["iv"].notna()].dropna(subset=["moneyness"])
        if d.empty: ax.set_title(f"Day {day} – no data"); continue
        ax.scatter(d["moneyness"],d["iv"],alpha=0.25,s=8,color="steelblue",label="IV obs")
        try:
            c=np.polyfit(d["moneyness"],d["iv"],2)
            xs=np.linspace(d["moneyness"].min(),d["moneyness"].max(),300)
            ax.plot(xs,np.polyval(c,xs),color="red",linewidth=2,label="Parabola")
        except: pass
        ax.set_title(f"Day {day} – TTE={TTE_PER_DAY[day]*252:.0f}d")
        ax.set_xlabel("ln(S/K)"); ax.set_ylabel("IV" if day==1 else ""); ax.legend(fontsize=8)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"03_vol_smile.png"),dpi=150); plt.close()
    print("   → 03_vol_smile.png")

def section_iv_deviations(iv_df):
    print("[2b] IV price deviations …")
    all_dev=[]
    for day in [1,2,3]:
        d=iv_df[(iv_df["day"]==day)&iv_df["iv"].notna()].copy()
        if len(d)<20: continue
        try:
            c=np.polyfit(d["moneyness"],d["iv"],2)
            d["iv_hat"]=np.polyval(c,d["moneyness"])
            d["price_dev"]=d.apply(lambda r:bs_call(r["S"],r["strike"],r["T"],r["iv"])
                                             -bs_call(r["S"],r["strike"],r["T"],r["iv_hat"]),axis=1)
            all_dev.append(d)
        except: continue
    if not all_dev: print("   [WARN] not enough IV data"); return None
    dev_df=pd.concat(all_dev,ignore_index=True)
    focus=[5000,5200,5400,5500,6000]
    fig,axes=plt.subplots(len(focus),3,figsize=(18,4*len(focus)))
    fig.suptitle("Price Deviation from IV-Fair Value",fontsize=13,fontweight="bold")
    for ri,K in enumerate(focus):
        for ci,day in enumerate([1,2,3]):
            ax=axes[ri,ci]
            sub=dev_df[(dev_df["strike"]==K)&(dev_df["day"]==day)].sort_values("timestamp")
            if sub.empty: ax.set_visible(False); continue
            ax.plot(sub["timestamp"],sub["price_dev"],linewidth=0.8,color="steelblue")
            ax.fill_between(sub["timestamp"],sub["price_dev"],0,
                            where=sub["price_dev"]>0,alpha=0.3,color="red",interpolate=True)
            ax.fill_between(sub["timestamp"],sub["price_dev"],0,
                            where=sub["price_dev"]<0,alpha=0.3,color="green",interpolate=True)
            ax.axhline(0,color="black",linewidth=0.6)
            ax.set_title(f"VEV_{K} – Day {day}",fontsize=9)
            ax.set_xlabel("Timestamp",fontsize=8); ax.set_ylabel("Price Dev",fontsize=8)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"04_iv_price_deviations.png"),dpi=150); plt.close()
    print("   → 04_iv_price_deviations.png")
    return dev_df

def section_option_autocorr(prices):
    print("[2c] Option return ACF …")
    fig,axes=plt.subplots(2,5,figsize=(20,8))
    fig.suptitle("VEV Option Return ACF",fontsize=13,fontweight="bold")
    for ax,K in zip(axes.flat,STRIKES):
        sub=prices[prices["product"]==f"VEV_{K}"].sort_values("global_ts")
        ret=sub["mid_price"].pct_change().replace([np.inf,-np.inf],np.nan).dropna()
        if len(ret)<50: ax.set_visible(False); continue
        acf=acf_series(ret,20); ci_=1.96/np.sqrt(len(ret))
        ax.bar(acf["lag"],acf["acf"],alpha=0.8,color="steelblue")
        ax.axhline(ci_,color="red",linestyle="--",linewidth=0.8)
        ax.axhline(-ci_,color="red",linestyle="--",linewidth=0.8)
        ax.axhline(0,color="black",linewidth=0.5)
        ax.set_title(f"VEV_{K}",fontsize=9); ax.set_xlabel("Lag",fontsize=7)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"05_option_autocorr.png"),dpi=150); plt.close()
    print("   → 05_option_autocorr.png")

def section_delta_surface(iv_df):
    print("[2d] Delta surface …")
    fig,axes=plt.subplots(1,3,figsize=(18,6))
    fig.suptitle("VEV Option Deltas vs Time",fontsize=13,fontweight="bold")
    for ax,day in zip(axes,[1,2,3]):
        d=iv_df[(iv_df["day"]==day)&iv_df["delta"].notna()]
        for i,K in enumerate(STRIKES):
            sub=d[d["strike"]==K].sort_values("timestamp")
            if sub.empty: continue
            ax.plot(sub["timestamp"],sub["delta"],linewidth=0.7,color=VEV_COLORS[i],label=str(K),alpha=0.9)
        ax.set_title(f"Day {day} – TTE={TTE_PER_DAY[day]*252:.0f}d")
        ax.axhline(0.5,color="black",linestyle="--",linewidth=0.7)
        ax.set_xlabel("Timestamp"); ax.set_ylabel("Delta" if day==1 else "")
        if day==1: ax.legend(fontsize=6,ncol=2)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"06_delta_surface.png"),dpi=150); plt.close()
    print("   → 06_delta_surface.png")

def section_fair_vs_market(iv_df):
    print("[2e] Fair vs market …")
    focus=[5000,5200,5400,5500,6000]
    fig,axes=plt.subplots(len(focus),3,figsize=(18,4*len(focus)))
    fig.suptitle("VEV – BS Fair vs Market Mid",fontsize=13,fontweight="bold")
    for ri,K in enumerate(focus):
        for ci,day in enumerate([1,2,3]):
            ax=axes[ri,ci]
            sub=iv_df[(iv_df["strike"]==K)&(iv_df["day"]==day)].sort_values("timestamp")
            if sub.empty or sub["fair"].isna().all(): ax.set_visible(False); continue
            ax.plot(sub["timestamp"],sub["mid_price"],label="Market",linewidth=0.8,color="steelblue")
            ax.plot(sub["timestamp"],sub["fair"],     label="BS Fair",linewidth=0.8,color="orange",linestyle="--")
            ax.fill_between(sub["timestamp"],sub["mid_price"],sub["fair"],alpha=0.15,color="purple")
            ax.set_title(f"VEV_{K} – Day {day}",fontsize=9)
            ax.set_xlabel("Timestamp",fontsize=8); ax.set_ylabel("Price",fontsize=8)
            if ci==0: ax.legend(fontsize=7)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"07_fair_vs_market.png"),dpi=150); plt.close()
    print("   → 07_fair_vs_market.png")

def section_iv_level_trends(iv_df):
    print("[2f] IV level trends …")
    fig,axes=plt.subplots(2,5,figsize=(20,8))
    fig.suptitle("IV Level Over Time per Strike",fontsize=13,fontweight="bold")
    for ax,K in zip(axes.flat,STRIKES):
        sub=iv_df[(iv_df["strike"]==K)&iv_df["iv"].notna()].sort_values("global_ts")
        if sub.empty: ax.set_visible(False); continue
        for day in [1,2,3]:
            d=sub[sub["day"]==day]
            ax.plot(d["timestamp"],d["iv"],linewidth=0.7,label=f"D{day}",alpha=0.85)
        ax.set_title(f"VEV_{K}",fontsize=9); ax.set_xlabel("Timestamp",fontsize=7); ax.legend(fontsize=6)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"08_iv_level_trends.png"),dpi=150); plt.close()
    print("   → 08_iv_level_trends.png")

# ── SECTION 3: Mark Analysis ──────────────────────────────────────────────────

def section_mark_volume(trades):
    print("\n[3] Mark volume heatmaps …")
    all_marks=sorted(set(trades["buyer"].dropna())| set(trades["seller"].dropna()))
    print(f"   {len(all_marks)} counterparties: {all_marks[:6]} …")
    rows=[]
    for mark in all_marks:
        ab=trades[trades["buyer"] ==mark].groupby("symbol")["quantity"].sum().rename("buy")
        as_=trades[trades["seller"]==mark].groupby("symbol")["quantity"].sum().rename("sell")
        m=pd.concat([ab,as_],axis=1).fillna(0); m["net"]=m["buy"]-m["sell"]; m["mark"]=mark
        rows.append(m.reset_index().rename(columns={"symbol":"product"}))
    mark_vol=pd.concat(rows,ignore_index=True)
    mark_vol.to_csv(os.path.join(OUT_DIR,"mark_volume_summary.csv"),index=False)

    pvt_buy =mark_vol.pivot_table(index="mark",columns="product",values="buy", aggfunc="sum").fillna(0)
    pvt_sell=mark_vol.pivot_table(index="mark",columns="product",values="sell",aggfunc="sum").fillna(0)
    pvt_net =mark_vol.pivot_table(index="mark",columns="product",values="net", aggfunc="sum").fillna(0)

    h=max(6,len(all_marks)*0.38+2)
    fig,axes=plt.subplots(1,3,figsize=(24,h))
    fig.suptitle("Mark Activity – Volume Heatmaps",fontsize=13,fontweight="bold")
    for ax,pvt,title,cmap in [(axes[0],pvt_buy,"Buy","Blues"),(axes[1],pvt_sell,"Sell","Reds"),(axes[2],pvt_net,"Net","RdYlGn")]:
        im=ax.imshow(pvt.values,aspect="auto",cmap=cmap)
        ax.set_yticks(range(len(pvt.index)));   ax.set_yticklabels(pvt.index,fontsize=6)
        ax.set_xticks(range(len(pvt.columns))); ax.set_xticklabels(pvt.columns,rotation=45,ha="right",fontsize=6)
        ax.set_title(title); plt.colorbar(im,ax=ax,shrink=0.7)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"09_mark_volume_heatmap.png"),dpi=150); plt.close()
    print("   → 09_mark_volume_heatmap.png + mark_volume_summary.csv")
    return mark_vol, all_marks

def section_mark_timing(trades):
    print("[3b] Mark timing …")
    all_marks=sorted(set(trades["buyer"].dropna())|set(trades["seller"].dropna()))
    fig,axes=plt.subplots(1,3,figsize=(18,6))
    fig.suptitle("Mark Trade Timestamp Distribution",fontsize=13,fontweight="bold")
    for ax,day in zip(axes,[1,2,3]):
        d=trades[trades["day"]==day]
        for mark in all_marks:
            ts=pd.concat([d[d["buyer"]==mark]["timestamp"],d[d["seller"]==mark]["timestamp"]])
            if len(ts)>10: ax.hist(ts,bins=60,alpha=0.35,label=mark)
        ax.set_title(f"Day {day}"); ax.set_xlabel("Timestamp"); ax.set_ylabel("# Trades")
        if day==1: ax.legend(fontsize=5,ncol=2)
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"10_mark_timing.png"),dpi=150); plt.close()
    print("   → 10_mark_timing.png")

def section_mark_signals(trades, prices, horizon=5):
    print(f"[3c] Mark forward-return signals (horizon={horizon}) …")
    all_marks=sorted(set(trades["buyer"].dropna())|set(trades["seller"].dropna()))
    results=[]
    for prod in ["VELVETFRUIT_EXTRACT","HYDROGEL_PACK"]:
        prc=(prices[prices["product"]==prod][["global_ts","mid_price"]]
             .sort_values("global_ts").reset_index(drop=True))
        tr=trades[trades["symbol"]==prod]
        for mark in all_marks:
            for side,col in [("buy","buyer"),("sell","seller")]:
                ts_arr=tr[tr[col]==mark]["global_ts"].values
                if len(ts_arr)<5: continue
                fwd=[]
                for ts in ts_arr:
                    i0=prc["global_ts"].searchsorted(ts,side="right")-1
                    i1=i0+horizon
                    if i0<0 or i1>=len(prc): continue
                    p0=prc.iloc[i0]["mid_price"]; p1=prc.iloc[i1]["mid_price"]
                    if p0>0: fwd.append((p1-p0)/p0)
                if fwd:
                    mu=np.mean(fwd); sd=np.std(fwd)
                    results.append({"mark":mark,"product":prod,"side":side,
                                    "n":len(ts_arr),"avg_bps":mu*1e4,"std_bps":sd*1e4,
                                    "t_stat":mu/(sd/np.sqrt(len(fwd))) if sd>0 else 0})
    if not results: print("   [WARN] no signal data"); return None
    sig_df=pd.DataFrame(results).sort_values("t_stat",key=abs,ascending=False)
    sig_df.to_csv(os.path.join(OUT_DIR,"mark_signal_strength.csv"),index=False)
    fig,axes=plt.subplots(1,2,figsize=(18,8))
    fig.suptitle(f"Mark Signals – {horizon}-tick forward return",fontsize=13,fontweight="bold")
    for ax,prod in zip(axes,["VELVETFRUIT_EXTRACT","HYDROGEL_PACK"]):
        top=sig_df[sig_df["product"]==prod].head(20)
        if top.empty: ax.set_visible(False); continue
        colors=["#E53935" if r<0 else "#43A047" for r in top["avg_bps"]]
        ax.barh(top["mark"]+"/"+top["side"],top["avg_bps"],color=colors)
        ax.axvline(0,color="black",linewidth=0.8)
        ax.set_title(prod.replace("_"," ")); ax.set_xlabel("Avg fwd return (bps)")
        for i,(_,r) in enumerate(top.iterrows()):
            ax.annotate(f"t={r['t_stat']:.1f}",xy=(r["avg_bps"],i),va="center",fontsize=7,
                        xytext=(3 if r["avg_bps"]>=0 else -3,0),textcoords="offset points")
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"11_mark_signals.png"),dpi=150); plt.close()
    print("   → 11_mark_signals.png + mark_signal_strength.csv")
    return sig_df

def section_mark_detail(trades, prices, mark_vol):
    print("[3d] Per-Mark detail plots …")
    top_marks=(mark_vol.groupby("mark")[["buy","sell"]].sum().sum(axis=1).nlargest(6).index.tolist())
    for prod in ["VELVETFRUIT_EXTRACT","HYDROGEL_PACK"]:
        prc=prices[prices["product"]==prod][["global_ts","mid_price"]].sort_values("global_ts")
        tr =trades[trades["symbol"]==prod].sort_values("global_ts")
        fig,axes=plt.subplots(3,2,figsize=(18,14))
        fig.suptitle(f"{prod} – Top-6 Mark Overlay",fontsize=13,fontweight="bold")
        for ax,mark in zip(axes.flat,top_marks):
            ax.plot(prc["global_ts"],prc["mid_price"],color="grey",linewidth=0.4,alpha=0.6,label="Mid")
            b=tr[tr["buyer"]==mark]; s=tr[tr["seller"]==mark]
            if not b.empty: ax.scatter(b["global_ts"],b["price"],marker="^",color="#43A047",s=20,label=f"Buy({len(b)})",zorder=5)
            if not s.empty: ax.scatter(s["global_ts"],s["price"],marker="v",color="#E53935",s=20,label=f"Sell({len(s)})",zorder=5)
            ax.set_title(mark,fontsize=9); ax.legend(fontsize=7)
        plt.tight_layout()
        fname=f"12_mark_{prod[:4].lower()}.png"
        plt.savefig(os.path.join(OUT_DIR,fname),dpi=150); plt.close()
        print(f"   → {fname}")

# ── SECTION 4: Spread ─────────────────────────────────────────────────────────

def section_spread_summary(prices):
    print("\n[4] Spread summary …")
    rows=[]
    for prod in sorted(prices["product"].unique()):
        sub=prices[prices["product"]==prod]
        rows.append({"product":prod,
                     "mean_spread":sub["spread"].mean(),
                     "median_spread":sub["spread"].median(),
                     "mean_mid":sub["mid_price"].mean(),
                     "std_mid":sub["mid_price"].std(),
                     "mean_bid_vol1":sub["bid_volume_1"].mean(),
                     "mean_ask_vol1":sub["ask_volume_1"].mean()})
    df=pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR,"spread_liquidity_summary.csv"),index=False)
    fig,axes=plt.subplots(1,2,figsize=(16,6))
    fig.suptitle("Spread & Liquidity",fontsize=13,fontweight="bold")
    d1=df[df["product"].isin(["HYDROGEL_PACK","VELVETFRUIT_EXTRACT"])]
    vev=df[df["product"].isin(VEV_PRODUCTS)]
    axes[0].bar(d1["product"],d1["mean_spread"],color=["#2196F3","#4CAF50"])
    axes[0].set_title("Delta-1 – Mean Spread"); axes[0].set_ylabel("Spread (ticks)")
    axes[0].set_xticklabels(d1["product"],rotation=15)
    axes[1].bar(vev["product"],vev["mean_spread"],color="steelblue",alpha=0.8)
    axes[1].set_title("VEV Options – Mean Spread"); axes[1].set_ylabel("Spread (ticks)")
    axes[1].set_xticklabels(vev["product"],rotation=30,ha="right")
    plt.tight_layout(); plt.savefig(os.path.join(OUT_DIR,"13_spread_summary.png"),dpi=150); plt.close()
    print("   → 13_spread_summary.png + spread_liquidity_summary.csv")
    return df

# ── Summary ───────────────────────────────────────────────────────────────────

def write_summary(prices, trades, iv_df, mark_vol, spread_df, sig_df):
    print("\n[5] Summary report …")
    L=[]; sep="="*70
    L+=[sep,"IMC Prosperity 4 – Round 4 Analysis Summary",sep]
    L.append("\n── DELTA-1 ──")
    for prod in ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT"]:
        sub=prices[prices["product"]==prod]["mid_price"]
        ret=sub.pct_change().dropna(); acf1=ret.autocorr(lag=1)
        spr=spread_df[spread_df["product"]==prod]["mean_spread"].values
        flag="  ◄ MEAN-REVERT" if acf1<-0.05 else ""
        L.append(f"\n  {prod}")
        L.append(f"    Mean price:   {sub.mean():.2f}")
        L.append(f"    Std price:    {sub.std():.4f}")
        L.append(f"    Return ACF1:  {acf1:.4f}{flag}")
        L.append(f"    Mean spread:  {spr[0]:.2f}" if len(spr) else "    Mean spread:  N/A")
    L.append("\n── VEV IV SUMMARY ──")
    for K in STRIKES:
        sub=iv_df[iv_df["strike"]==K]["iv"].dropna()
        if sub.empty: L.append(f"  VEV_{K}: no valid IV"); continue
        L.append(f"  VEV_{K}: mean={sub.mean():.3f} std={sub.std():.3f} range=[{sub.min():.3f},{sub.max():.3f}]")
    L.append("\n── TOP MARKS ──")
    top=(mark_vol.groupby("mark")[["buy","sell"]].sum().sum(axis=1).nlargest(10))
    for mark,vol in top.items():
        L.append(f"  {mark:15s}  vol={vol:.0f}")
    if sig_df is not None:
        L.append("\n── TOP MARK SIGNALS ──")
        for prod in ["VELVETFRUIT_EXTRACT","HYDROGEL_PACK"]:
            L.append(f"  {prod}:")
            for _,r in sig_df[sig_df["product"]==prod].head(6).iterrows():
                L.append(f"    {r['mark']:12s} {r['side']:5s} avg={r['avg_bps']:+.1f}bps t={r['t_stat']:.2f} n={r['n']}")
    L.append("\n── FILES ──")
    for f in sorted(os.listdir(OUT_DIR)): L.append(f"  {f}")
    L.append("""
── NEXT STEP ──
Upload all PNGs + this 00_summary.txt to Claude and say:
"Round 4 is live. Here are my Round 4 analysis results."
Ask Claude to confirm strategy + produce final trader.py.
""")
    L.append(sep)
    text="\n".join(L)
    with open(os.path.join(OUT_DIR,"00_summary.txt"),"w") as f: f.write(text)
    print(f"   → 00_summary.txt\n"); print(text)

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("="*60,"IMC Prosperity 4 – Round 4 Analyser",
          f"  data-dir={DATA_DIR}  iv-stride={IV_STRIDE}  out={OUT_DIR}","="*60,sep="\n")
    print("\nLoading …")
    prices=load_prices(); trades=load_trades()
    print(f"  prices={len(prices):,}  trades={len(trades):,}")
    section_delta1(prices); section_ema_deviation(prices)
    iv_df=build_iv_df(prices)
    section_vol_smile(iv_df); section_iv_deviations(iv_df)
    section_option_autocorr(prices); section_delta_surface(iv_df)
    section_fair_vs_market(iv_df); section_iv_level_trends(iv_df)
    mark_vol,_=section_mark_volume(trades)
    section_mark_timing(trades)
    sig_df=section_mark_signals(trades,prices)
    section_mark_detail(trades,prices,mark_vol)
    spread_df=section_spread_summary(prices)
    write_summary(prices,trades,iv_df,mark_vol,spread_df,sig_df)
    print(f"\n✓ Done. Upload everything in ./{OUT_DIR}/ to Claude.")

if __name__=="__main__":
    main()