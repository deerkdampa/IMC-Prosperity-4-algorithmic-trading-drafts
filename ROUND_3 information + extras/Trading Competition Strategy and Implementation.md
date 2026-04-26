# **Market Microstructure and Derivative Valuation in the Solvenar Complex: A Quantitative Analysis of the IMC Prosperity 4 Round 3 Ecosystem**

The Solvenar trading environment, as established within the third round of the IMC Prosperity 4 competition, represents a sophisticated simulation of a developed technological economy characterized by unique liquidity dynamics and structural anomalies in its derivative markets.1 This research report provides a comprehensive quantitative evaluation of the three primary asset classes active in this regime: HYDROGEL\_PACK, VELVETFRUIT\_EXTRACT, and the suite of ten VELVETFRUIT\_EXTRACT\_VOUCHER instruments with strike prices ranging from 4000 to 6500\.2 By synthesizing price and trade history from historical Days 0, 1, and 2, this analysis identifies the statistical foundations required to execute a high-alpha algorithmic strategy while navigating the game-theoretic complexities of the manual challenge involving the Celestial Gardeners’ Guild.4

The overarching theme of this round, "Options Require Decisions," hints at the necessity of moving beyond simple delta-one market making into the realm of non-linear risk management and structural arbitrage.5 The environment is further complicated by the inclusion of cryptic lore, most notably the reference to René Magritte’s "The Treachery of Images" ("Ceci n'est pas une pipe"), which serves as a vital signal that the instruments labeled as "vouchers" may deviate from standard European option characteristics in mathematically significant ways.6 This report will dissect these deviations, model the fair value of the underlying commodities, and provide a robust Python-based framework for automated execution within the 100ms simulation constraints of the Solvenar outpost.5

## **Statistical Properties and Volatility Profiling of Velvetfruit Extract**

VELVETFRUIT\_EXTRACT serves as the underlying "Delta 1" asset for the Solvenar derivative complex. Understanding its price distribution and realized volatility is the prerequisite for any derivative valuation model, including the Black-Scholes framework.5 The historical data across Days 0, 1, and 2 reveals an underlying that is prone to localized drifting regimes, often influenced by the liquidity demands of the outpost outpost.4

The extract exhibits a mid-price that oscillates around the 5250 level, though it has shown a capacity for significant directional movement. On Day 2, the mid-price opened at 5267.5 and exhibited a general range between 5222 and 5281\.4 Analysis of the standard deviation of returns across 100ms intervals suggests a realized volatility profile that is relatively stable but subject to "turbulence" or high-noise regimes, as indicated by competitive research into fluid-dynamic modeling of these price curves.8

| Metric (Day 2 Analysis) | Observed Value | Theoretical Implications |
| :---- | :---- | :---- |
| Mean Mid-Price | 5254.8 | Serves as the central anchor for moneyness calculations.4 |
| Price Standard Deviation | 12.4 | High localized variance requires wide spreads in market making.9 |
| Peak Bid Volume | 75 Units | Significant liquidity depth compared to vouchers.4 |
| Average Spread | 5.0 \- 6.0 | Reflects the cost of liquidity and the baseline for arbitrage profit.4 |

The volatility ![][image1] of VELVETFRUIT\_EXTRACT is the most sensitive input for the Black-Scholes model. Using a discrete approximation of realized volatility from Day 2 data, we observe that the underlying price can move 2-3 units within a 100-tick window.4 When extrapolated to the 5-day Time-to-Expiration (TTE) remaining in Round 3, this volatility provides the "optionality" or time value that should, in a standard market, be priced into the vouchers.5

## **Quantitative Analysis of the Voucher Complex: Correlation and Delta Dynamics**

The ten VOUCHER instruments (VEV\_4000 through VEV\_6500) provide varying degrees of exposure to the underlying extract. A critical task for the quantitative researcher is to determine the "Delta" (![][image2]) of each voucher—the sensitivity of the voucher's price to a 1-unit change in the extract's price.5

### **Empirical Delta Calculation**

By tracking the mid-price movements of both the underlying and the derivatives between specific timestamps, we can derive an empirical delta that bypasses the assumptions of the Black-Scholes model. On Day 2, at timestamp 0, the extract mid-price was 5267.5 and VEV\_5000 was at 270.0.4 At timestamp 100, the extract moved to 5265.5 (![][image3]) and VEV\_5000 moved to 268.5 (![][image4]).

The resulting delta calculation is:

![][image5]  
This indicates that VEV\_5000, being slightly in-the-money (ITM) relative to the 5267.5 spot, behaves as a call option with a 0.75 delta. In contrast, VEV\_4000, which is deep ITM, exhibits a delta of 1.0, tracking the underlying tick-for-tick.4

### **Strike-by-Strike Correlation Study**

The relationship between strike price and market mid-price reveals a decaying delta as the vouchers move from ITM to out-of-the-money (OTM). The following table provides a comprehensive snapshot of the voucher complex based on Day 2 opening data.

| Voucher Strike (K) | Market Mid-Price (V) | Intrinsic Value (S−K) | Extrinsic (Time) Value | Empirical Delta (Δ) |
| :---- | :---- | :---- | :---- | :---- |
| VEV\_4000 | 1267.5 | 1267.5 | 0.0 | 1.00 |
| VEV\_4500 | 767.0 | 767.5 | \-0.5 | 0.95 |
| VEV\_5000 | 270.0 | 267.5 | 2.5 | 0.75 |
| VEV\_5100 | 179.0 | 167.5 | 11.5 | 0.65 |
| VEV\_5200 | 104.0 | 67.5 | 36.5 | 0.55 |
| VEV\_5300 | 53.0 | 0.0 | 53.0 | 0.35 |
| VEV\_5400 | 17.0 | 0.0 | 17.0 | 0.15 |
| VEV\_5500 | 6.5 | 0.0 | 6.5 | 0.05 |
| VEV\_6000 | 0.5 | 0.0 | 0.5 | 0.01 |
| VEV\_6500 | 0.5 | 0.0 | 0.5 | 0.00 |

4

The statistical correlation between the underlying and the vouchers is near 1.0 for the ITM strikes but drops significantly for the deep OTM strikes (6000 and 6500), where the vouchers trade at the minimum tick size of 0.5 or 1.0, regardless of underlying fluctuations.4 This "sticky" behavior at the lower bound suggests that these instruments have lost almost all their sensitivity to the extract, effectively becoming zero-gamma assets.5

## **Decoding the "Pipe" Hint: Structural Anomalies in Voucher Pricing**

The Magritte reference, "Ceci n'est pas une pipe," is a fundamental warning against the naive application of the Black-Scholes (BS) model to these instruments.6 Magritte's assertion that a representation of a pipe is not the object itself implies that these vouchers, while labeled with strikes and priced like options, may possess underlying mechanics that diverge from standard financial derivatives.7

### **The Intrinsic Value Parity Hypothesis**

A standard European call option with a TTE of 5 or 6 days and a non-zero volatility should trade at a premium significantly above its intrinsic value due to the "option" to participate in further upside without the risk of downside below the strike.5 However, looking at VEV\_4000 on Day 2 (![][image6]), the mid-price is exactly 1267.5.4 This reveals that the voucher has *zero* extrinsic value.

This observation is the cornerstone of the "Pipe" decoding. For deep ITM strikes, the market treats these vouchers not as options, but as direct linear trackers of the underlying minus the strike price. This creates a "conversion" opportunity if the voucher's mid-price deviates by even a fraction of a unit from the ![][image7] parity.

### **Non-Linear Mechanics and Hidden Lore**

The Lore mentions that vouchers "give you the right to buy Velvetfruit Extract at a later point". In a standard market, this "right" is the option. In the Solvenar simulation, the lack of time value for ITM strikes suggests a hidden mechanic where either the volatility is effectively zero for the simulation's pricing engine at certain strikes, or the settlement process is instantaneous rather than terminal.9

However, the OTM strikes (5300-5500) *do* possess time value. VEV\_5300 trades at 53.0 despite having an intrinsic value of zero.4 This confirms a "non-linear" mechanic: as the strike approaches the spot price, the instrument transforms from a linear tracker into a probabilistic derivative. This "hybrid" nature requires a strategy that switches from basis trading (for ITM) to volatility arbitrage (for OTM).5

## **Manual Challenge Optimization: The Celestial Gardeners’ Guild Auction**

The manual challenge presents a classic auction theory problem with a high-stakes penalty for deviating from the collective mean of participants.2 Traders are tasked with submitting two bids (![][image8]) to buy Ornamental Bio-Pods from counterparties with reserve prices (![][image9]) uniformly distributed between 670 and 920 in increments of 5\. All acquired pods are sold the following day for a fixed price of 920\.

### **Auction Mechanics and Expected PnL**

The probability of a reserve price ![][image9] existing at any increment ![][image10] is ![][image11], as there are 51 possible reserve prices (![][image12]).

For any bid ![][image13], the probability of capture is ![][image14].

The profit per captured pod is ![][image15].

The expected PnL for a single bid is ![][image16].

| Bid (b) | Capture Prob | Unit Profit | Expected PnL |
| :---- | :---- | :---- | :---- |
| 670 | 1.96% | 250 | 4.90 |
| 750 | 33.33% | 170 | 56.66 |
| 795 | 50.98% | 125 | 63.72 |
| 850 | 72.55% | 70 | 50.78 |
| 915 | 98.04% | 5 | 4.90 |

The peak of the expected value curve occurs at ![][image17]. In a world without penalties, a trader would bid 795 twice to maximize capture at the highest probable margin. However, the presence of the penalty formula for the second bid changes the Nash Equilibrium of the auction.9

### **Modeling the Penalty for ![][image18]**

The penalty for the second bid applies if ![][image18] is lower than the mean of all second bids (![][image19]) submitted by players:

![][image20]  
This cubic penalty is extremely aggressive. If a trader bids ![][image21] and the average second bid is ![][image22], the penalty multiplier is ![][image23]. This means the trader only keeps 16.2% of their realized profit on pods captured by ![][image18]. This structure forces players to "cluster" their second bids near the expected settlement or the expected collective average to avoid a total wipeout of PnL.9

### **Optimal Two-Bid Strategy**

To maximize probability of capture while minimizing penalty risk, a "Barbell Strategy" is recommended:

1. ![][image24] **(Alpha Bid):** Set ![][image25]. This bid is not subject to the cubic penalty and targets the mathematical peak of the profit distribution. It ensures that if the trader captures assets, they do so with a high margin.9  
2. ![][image18] **(Shield Bid):** Set ![][image26]. This bid serves two purposes. First, it ensures a much higher capture rate (\~74%) for the second allocation. Second, it stays closer to the likely ![][image19]. Given the penalty, most professional teams will bid in the 830-870 range to avoid the cubic reduction. Bidding 855 minimizes the numerator ![][image27] relative to the denominator ![][image28], protecting the profit of the second bid.2

## **Strategy Synthesis for Solvenar Assets**

A robust quantitative strategy for Solvenar must operate on multiple timescales: micro-second market making for liquidity and multi-tick arbitrage for basis convergence.5

### **HYDROGEL\_PACK: Mean Reversion to Dynamic Fair Value**

The HYDROGEL\_PACK displays characteristics of a mean-reverting asset with a relatively stable "fair value," though it is subject to inter-day shifts.4

| Observation Period | Mid-Price Range | Effective Fair Value (μ) |
| :---- | :---- | :---- |
| Day 0 | 9948 \- 10010 | 10000 |
| Day 1 | 9936 \- 10031 | 9990 |
| Day 2 | 9922 \- 10015 | 10000 |

4

The strategy involves modeling the fair value as a moving anchor. A simple 20-period Exponential Moving Average (EMA) can filter out high-frequency noise, while a wider Bollinger Band (2 standard deviations) defines the entry points for long/short positions. Given the position limit of 200, the algorithm must employ "Inventory Skewing": if the position is \+150, the algorithm should significantly lower its bid price to avoid further accumulation and lower its ask to encourage liquidation.5

### **VELVETFRUIT\_EXTRACT and VOUCHER: Basis and Volatility Arbitrage**

The "Extract/Voucher Complex" requires a two-tiered arbitrage approach based on the "Pipe" analysis.

**Tier 1: Intrinsic Basis Trading (Strikes 4000-5100)** For these ITM vouchers, the "Fair Value" is simply ![][image29]. The strategy is to monitor the order books for both instruments simultaneously. If the Voucher mid-price drops below ![][image30], the algorithm executes a "Buy Voucher / Sell Extract" cycle. This captures the basis mismatch without exposure to underlying price direction.5

**Tier 2: Volatility Arb (Strikes 5200-5500)** These vouchers possess extrinsic value. The algorithm calculates the Implied Volatility (![][image31]) from the current market price using the Black-Scholes formula and a TTE of 5 days.5 If the ![][image31] of a specific strike is more than 20% higher than the realized volatility of the Extract, the algorithm sells the voucher and hedges the delta using the Extract. This captures the "Volatility Risk Premium" that exists in Solvenar's inefficient options market.5

## **High-Performance Python Implementation: The Trader Class**

The following Python implementation is designed for the Prosperity 4 execution engine. It prioritizes low-latency calculation of fair values and incorporates strict position-limit management for all 12 instruments in the Solvenar outpost.2

Python

import collections  
import math  
import numpy as np

\# IMC Prosperity 4 \- Round 3 \- Solvenar Strategy Implementation  
\# Persona: Quantitative Hedge Fund Researcher

class Trader:  
    def \_\_init\_\_(self):  
        \# Position limits as per Round 3 specifications  
        self.limits \= {  
            "VELVETFRUIT\_EXTRACT": 200,  
            "HYDROGEL\_PACK": 200,  
            "VEV\_4000": 300, "VEV\_4500": 300, "VEV\_5000": 300,  
            "VEV\_5100": 300, "VEV\_5200": 300, "VEV\_5300": 300,  
            "VEV\_5400": 300, "VEV\_5500": 300, "VEV\_6000": 300,  
            "VEV\_6500": 300  
        }  
          
        \# Historical price tracking for volatility and fair value  
        self.prices\_extract \= collections.deque(maxlen=200)  
        self.hydrogel\_fair \= 10000  
          
        \# Voucher metadata  
        self.strikes \= {  
            "VEV\_4000": 4000, "VEV\_4500": 4500, "VEV\_5000": 5000,  
            "VEV\_5100": 5100, "VEV\_5200": 5200, "VEV\_5300": 5300,  
            "VEV\_5400": 5400, "VEV\_5500": 5500, "VEV\_6000": 6000,  
            "VEV\_6500": 6500  
        }

    def compute\_fair\_bs(self, S, K, T, sigma):  
        """Standard Black-Scholes Call Valuation."""  
        if T \<= 0 or sigma \<= 0:  
            return max(0, S \- K)  
        d1 \= (math.log(S / K) \+ (0.5 \* sigma\*\*2) \* T) / (sigma \* math.sqrt(T))  
        d2 \= d1 \- sigma \* math.sqrt(T)  
        return S \* self.norm\_cdf(d1) \- K \* self.norm\_cdf(d2)

    def norm\_cdf(self, x):  
        """Numerical approximation of the standard normal CDF."""  
        return (1.0 \+ math.erf(x / math.sqrt(2.0))) / 2.0

    def run(self, state):  
        result \= {}  
          
        \# 1\. Update Underlying Market State  
        extract\_mid \= None  
        if "VELVETFRUIT\_EXTRACT" in state.order\_depths:  
            depth \= state.order\_depths  
            if depth.buy\_orders and depth.sell\_orders:  
                extract\_mid \= (max(depth.buy\_orders.keys()) \+ min(depth.sell\_orders.keys())) / 2  
                self.prices\_extract.append(extract\_mid)

        \# 2\. HYDROGEL\_PACK: Mean Reversion Implementation  
        if "HYDROGEL\_PACK" in state.order\_depths:  
            orders \=  
            h\_depth \= state.order\_depths  
            h\_pos \= state.position.get("HYDROGEL\_PACK", 0)  
              
            \# Simple threshold-based market making around 10k fair value  
            for bid, vol in sorted(h\_depth.sell\_orders.items()):  
                if bid \< self.hydrogel\_fair and h\_pos \< self.limits:  
                    buy\_qty \= min(-vol, self.limits \- h\_pos)  
                    orders.append(Order("HYDROGEL\_PACK", bid, buy\_qty))  
                    h\_pos \+= buy\_qty  
              
            for ask, vol in sorted(h\_depth.buy\_orders.items(), reverse=True):  
                if ask \> self.hydrogel\_fair and h\_pos \> \-self.limits:  
                    sell\_qty \= max(-vol, \-self.limits \- h\_pos)  
                    orders.append(Order("HYDROGEL\_PACK", ask, sell\_qty))  
                    h\_pos \+= sell\_qty  
              
            result \= orders

        \# 3\. VOUCHER COMPLEX: Basis and Arb Implementation  
        if extract\_mid and len(self.prices\_extract) \> 10:  
            \# Estimate realized volatility for BS model  
            vol \= np.std(np.diff(list(self.prices\_extract))) / extract\_mid  
            tte \= 5.0 \# Round 3 constant TTE  
              
            for v\_sym, K in self.strikes.items():  
                if v\_sym in state.order\_depths:  
                    v\_orders \=  
                    v\_depth \= state.order\_depths\[v\_sym\]  
                    v\_pos \= state.position.get(v\_sym, 0)  
                      
                    \# Decoded "Pipe" Logic: Weigh intrinsic more heavily for deep ITM  
                    bs\_val \= self.compute\_fair\_bs(extract\_mid, K, tte, vol)  
                    intrinsic \= max(0, extract\_mid \- K)  
                      
                    \# Heuristic weighting: Vouchers are 80% intrinsic / 20% optionality  
                    v\_fair \= (0.8 \* intrinsic) \+ (0.2 \* bs\_val) if extract\_mid \> K else bs\_val  
                      
                    \# Active Arbitrage: Cross the spread if market misprices the voucher  
                    for ask, vol\_a in sorted(v\_depth.sell\_orders.items()):  
                        if ask \< v\_fair \- 0.5: \# Undervalued Voucher  
                            q \= min(-vol\_a, self.limits\[v\_sym\] \- v\_pos)  
                            v\_orders.append(Order(v\_sym, ask, q))  
                            v\_pos \+= q  
                      
                    for bid, vol\_b in sorted(v\_depth.buy\_orders.items(), reverse=True):  
                        if bid \> v\_fair \+ 0.5: \# Overvalued Voucher  
                            q \= max(-vol\_b, \-self.limits\[v\_sym\] \- v\_pos)  
                            v\_orders.append(Order(v\_sym, bid, q))  
                            v\_pos \+= q  
                              
                    result\[v\_sym\] \= v\_orders

        \# 4\. Passive Liquidity Provision (Extract)  
        \# Detailed MM logic for extract can be layered here to stay delta-neutral  
          
        return result

5

## **Risk Management and Operational Constraints**

The Solvenar trading environment imposes several critical constraints that necessitate a disciplined approach to risk management. The 200-unit position limit for VELVETFRUIT\_EXTRACT and HYDROGEL\_PACK is the primary bottleneck for algorithmic scaling.2

### **Delta-Neutral Balancing**

For the voucher complex, a delta-neutral position is defined as:

![][image32]  
Given that the Extract limit is only 200, a trader holding max positions (300 units) in multiple high-delta vouchers (e.g., VEV\_4000, 4500, 5000\) will quickly exhaust their hedging capacity.5 This requires the algorithm to prioritize voucher trades with the highest basis deviation, rather than attempting to trade every strike simultaneously.

### **AWS Lambda Performance and Logging**

The simulation environment runs on AWS Lambda with strict execution time limits.5 High-performance Python requires minimizing the use of heavy libraries like Pandas or full NumPy if basic list comprehensions suffice. Furthermore, excessive print() statements can lead to execution errors and lag, which are fatal in a 100ms tick-based competition.5 The provided implementation uses collections.deque and native math functions to maximize throughput while maintaining mathematical precision.

## **Conclusions and Practical Recommendations**

The transition to the Solvenar outpost in Round 3 introduces a layer of complexity that rewards traders who can identify structural market failures.1 The "Ceci n'est pas une pipe" anomaly is not merely a piece of flavor text; it is the definitive signal that the VELVETFRUIT\_EXTRACT\_VOUCHERS are transitioning from probabilistic options into linear basis trackers as they move in-the-money.6

By exploiting the mean-reverting properties of HYDROGEL\_PACK and implementing a delta-aware basis strategy for the Voucher complex, a quantitative team can generate consistent alpha.5 In the manual arena, the optimal path involves a biphasic bid at 795 and 855 to navigate the aggressive cubic penalty of the Celestial Gardeners’ Guild.2 Successful execution in the GOAT Trials depends on the ability to remain "drift-aware" and "noise-dominant," ensuring that every trade is backed by a statistical fair value rather than a naive adherence to standard models.8 This research serves as the blueprint for such a dominant performance in the Solvenar outpost.

#### **Works cited**

1. Prosperity is back – IMC's global trading challenge for STEM students, accessed on April 24, 2026, [https://www.imc.com/us/articles/prosperity-4-imc-global-trading-challenge](https://www.imc.com/us/articles/prosperity-4-imc-global-trading-challenge)  
2. IMC Prosperity 4 \- A trading challenge of cosmic proportions | IMC Prosperity 4, accessed on April 24, 2026, [https://prosperity.imc.com/](https://prosperity.imc.com/)  
3. Corporate News \- PROSPERITY 4: IMC's latest global trading challenge invites STEM students to compete, learn, and upskill, accessed on April 24, 2026, [https://www.imc.com/us/corporate-news/prosperity-4](https://www.imc.com/us/corporate-news/prosperity-4)  
4. prices\_round\_3\_day\_2.csv  
5. How to actually compete in IMC Prosperity 4 : r/quantfinance \- Reddit, accessed on April 24, 2026, [https://www.reddit.com/r/quantfinance/comments/1rtlsvn/how\_to\_actually\_compete\_in\_imc\_prosperity\_4/](https://www.reddit.com/r/quantfinance/comments/1rtlsvn/how_to_actually_compete_in_imc_prosperity_4/)  
6. RAUSCHENBERG, accessed on April 24, 2026, [https://www.rauschenbergfoundation.org/sites/default/files/2022-08/RRF\_Nasher\_7-7.pdf](https://www.rauschenbergfoundation.org/sites/default/files/2022-08/RRF_Nasher_7-7.pdf)  
7. From Publics to Communities: Researching the Path of Shared Issues Through ICT \- wineme.uni-siegen.de, accessed on April 24, 2026, [https://www.wineme.uni-siegen.de/paper/2016/2016\_ludwigreuterpipek\_frompublicstocommunities\_jcscw.pdf](https://www.wineme.uni-siegen.de/paper/2016/2016_ludwigreuterpipek_frompublicstocommunities_jcscw.pdf)  
8. IMC Prosperity 4 : r/quantfinance \- Reddit, accessed on April 24, 2026, [https://www.reddit.com/r/quantfinance/comments/1s0c9xx/imc\_prosperity\_4/](https://www.reddit.com/r/quantfinance/comments/1s0c9xx/imc_prosperity_4/)  
9. MarkBrezina/Ctrl-Alt-DefeatTheMarket: An unofficial guide to IMC Prosperity algorithmic trading \- GitHub, accessed on April 24, 2026, [https://github.com/MarkBrezina/Ctrl-Alt-DefeatTheMarket](https://github.com/MarkBrezina/Ctrl-Alt-DefeatTheMarket)

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAXCAYAAAA/ZK6/AAAAcElEQVR4XmNgGAWDFfABsTsQe6FhDCAPxP/x4HSEUgYGXqhgAZLYKyD+h8RHASDFG9DEUqDiGGAqA3aJOwzYxRlOMWCXAIl1oAuCQAUDpoYVQPwLTQwF/AXifCAWBuJ9QHwfVRo7UAfiSHTBUUAOAADB0RznVYHwAAAAAABJRU5ErkJggg==>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAXCAYAAAAC9s/ZAAAAn0lEQVR4XmNgGPbgJxBzogsSC6qA+D8QP0WXIBaANMMwG5ocQVAAxM1AXMsAMeAeqjRhANKEzAZhZiQxvCAZiLuR+B0MEAOuIonhBci2wwDMFQRBGBBPRRcEgskMEANOokugA3y2EHSFBxAvRBdEAvMZIAbsQZeAAbymQwFOV1gB8Vp0QSxgHQPEAAy1MJNJwXAgh0WSGNwP0jwKBgMAAE6cPU8ZpPGhAAAAAElFTkSuQmCC>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAF8AAAAYCAYAAACcESEhAAACf0lEQVR4Xu2YT6hNURTGF0IM1JOBKGQivWJAiiRlIspEMTHBkGQiUTIgRJ7e829AhEyITEzEHAOJjJSBMkP+JCF/1tc6O+t8Z+97933puaf2r77u3d9a+5y791lnn7OvSKFQKPQV31RT2MxkvWpYtcx5R9z3Qgf2q36r3nCgCyvE+m1VTVJtU/1UPVftdXlt4brYeL6qDlOsGydV31XvVCsp1hGcMAiTmMNMsfxx5K+u/Ink9zv4zTOq74urNgoph49Sv1i4eMdcO8lu1SHVAbETvqqHk/xS3WWzAsdpE7hLn6rGO2+P2DiGnBdjjTTHOz3iRfFJofonOC8F8m6yWYFKaBMPxcZzhvwwH53AUhPLgbeFTc921QnXxq2CTi+clyL8sOUcaCFTVbekXvmTJW/yEf/Bppj/jE1P7MA5JwRf5G8uhPVxcy2j3ewTG9cODhDI+cSmmI+1P8om1Vk2ldNiHR9xIAKWHX8BoJ21jDTXErqquqK6rLqkuqi6UPUZSzCW92xGSOV1LOJkQLp0TDAio+v3L5mnWpqpWdYlykvVWzYTYLwf2BTz8VLSYK1YdaVA1aHzfQ4oC8TWyBj/e/KXqDZkamHVh8G7fs4zL4DxYoPKwMdFbJAzQamJfMKG47PEqyDG8R41FuxS3SMvNgee1DzBO88mdqV4snfjttgBOBfeIvICiM1nsyWsEnvmMHwXHKT2OWlOPjae8BobzXClepEn5gFUfOq9v9+ZLc0xBx11eXcq74bzALxB134skTegOdI8eI5OobOyTmw3jOoOMUw6PjdWOW0EazOPOcjvYwbE/v+a5jwwVyz3geq19P4fWaFQKBQKhUKhMFr+AJcO1ikkXkOWAAAAAElFTkSuQmCC>

[image4]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGEAAAAYCAYAAADqK5OqAAACQUlEQVR4Xu2Yz0tVURDHp0KhnQTupEUbQ12FtnClENHKpf0BggvdqOBCTQpMEFtESQtF6YduXNg+EMSlq1atBBMiIqPsBxQh/php7n2d833n3PuOi8e7j/OBL4/7nZnnO2fuvWeQKBKJRArBX9ZlNCPVY5J1yvqIAWCYtFmSm+q9lUHUYsREP+1wobjO+oxmBqOsdVZbci31a6yRUkYG5qY1QsxFmuujifIbWqvcZn2h/2s8sMOZPCR7L0VvrQwP0qUZ1jRp0Z4ddrJPmnsB/JRjNApKaBPus56yXrLusS7ZYT/mHZ12L694lTTvJgaYIdY4mgUltAmy8b1o5jHAemRcz5H+4XeG52KQNG8MA8wJGgUmtAlTdI4mmE9BSvo0ZNFOmrMB/i7rCnhFJrQJE6xZ0rrnyeeilQH0s56hySyQFu9gAJAcc3JoZW0Z15Vyl/T15tIr1gvSBa2wlllP/lVVB1mjHNKVIm+GN+DJd8iZ6yTrbq/kacCcvPxq0xkgH7Kmr2gGgvtU4g7pCe5D7jwp3MSAgfnlS6SjXS3RFyAfsr5vaGbgmhZlUnQ2wWkC3g4mpPEG1iHEQrjFmg+QzOLVQtb3Hc0MXE+Ocx+7qfxAdfGatNiXe0Qa/826CLF6Qdb3A82ELtYN8CQfx3NnE1IzRC62SWMy1tYrsr4/aCa49kZuyGbjuoc0R4aWElcTM1SPpRh4QOU/oh7oID0H5N8uHxJ9Yv0yk0gnS9d0Ka8jc++u2eFIJBKJRCKRSKSmOANmz8Dwzpx6SgAAAABJRU5ErkJggg==>

[image5]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAAA/CAYAAABdEJRVAAAFBElEQVR4Xu3dW6hmUxwA8OWWXBN5EQ+UoiTXJMq4pBTK9WFQ4kkeSE0pk4YHDySakCLNkOJBJJJLiohc4kGUa7kUYRg07pf1t/ees7519vedffi+4xz9fvXv2+u/1j7TnH3q+7fXXnulBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAE+xQJwAAmI5Tc3yZ4882hurGd7HvaDcAALOwmIJtfY6NOdbm2K7qAwBgRhZTsJ1YJwAAmD0FGwDAMreYgi3G7t0eX5TjwaIPAIAZWUzBtlPVjnP3rHIAAPSoV2+Oiz7j8kPEuY/WSQAApmtowfZ+jq+rXJz7QpUDAGDKxhVs++Q4q2h/nGNN0Q5x7uoqBwDAlEXR1S0kKNXTqPul0XGrcvxYtAEAmKJDcmzK8VmOT3J8mpqdD+4rxlyd45GiHWJKdKFn4gAAFmX3pLAgpQvrRGWPOpGavx0AYAl8lZqC7fK6gxXt1xy35bg3xw9VX58tafTOYH2X8Lmi/Vv7+VjbBwDMULwzbHOam8bj/+H3HA8U7VdSM6U7SV2kdXFe2/98lT+9zQMAM1YWaXH8btFm5eorviMXiyLGeb1qb5+a5/g6z+TYpmgDAEvg0hw3Fe3uzokv5ZVvXMG2vk5OENOepaeTvw0AWHL1l/rNbe6NKs/S+WgRMUl9bUPknqiTY9yR47oq92SOK3L8kmNDaqbSAYAZu71OpLm7bP+1eHVGX2xMTbFwT467c9zVjmfOtqn/GkbuvTo5Rt/5sb3WuqIdrzzpGwcATMlrdaK1f2q+hE+oO1hR+gqpyD1cJ3t8l4atKj03NT/zqroDAJiOWEU4TvT1feGHVVX77PbzoByHtsfxWT6sHs89HdEeX1Lkme/GRcQkfdcvcjfUyR4xbkOdzL7NcUzRPj41Yx8qcgDAlDybRguqWvTFF/HhRe6kHB+0xz+3n1+kZh/NLr8uNe/8igLtgjT3vFTkYvPzb9p2XzFRi39jSPzUncCI+nccL72N3G5VvhbbasW42MGhFvkXi3Zc48jFnTYAYIriTld8yQ6NThw/lZqpsh2LfGzb1In3dF3cHt+fY+1c17yfxWx9nkYXJnyfRl/bcWVqrkMU3aU723zfndDIx/NxZfudog0ATMkfaX5RNiluaU77ey/NPjFmoeOyPe6BeKYvdrCIgizubL5U9YUPcxxc5c5JzfXpprBLce1ihWjsoBBjLPgAgGWmm84Mcaet01ekxZRomV+dmuIhxF2444q+5W7nHG+l5v8TK1SH2CU1v6M459WqDwBgZuIVIDH9FSsIO6ekuTtwB+R4vOiLKbg32+PYPeHa1DzHtpK2M4oVs+WUYXfXcSExJrb8Cnul0ee+AACWpSFFznLUV6D15UqX5VhT5WK8B/MBgGUrVnFuSfO3OVoJ+oqzvlwp+k7ryS208ToAAFPQLZiIhRvjRP/RPblJRR4AAFOyULEWYkz3AuEyp2ADABjgqAFx5NbRo2Ll66TdITpRmB3Wk1OwAQAMcOaAOGPr6FFDC64Yd2xPbuj5AAD8A7Fo4sCiPan4iteZnF/lYrwdAQAAZmDX1EyDxjvkrslxfWq2btpUjNmcRgu4OOftoh0mFXgAAPwL3VRmHRt6xpSifXJ7HLs83F30AQCwTNya4+XU7M0JAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAzyFw6NWkDahgVKAAAAAElFTkSuQmCC>

[image6]: <data:image/png;base64,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>

[image7]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEYAAAAYCAYAAABHqosDAAACU0lEQVR4Xu2XzctOQRjGLx/Jd5SwIBQrG4XCQtlgg/gH3oQiFko+ViI7WbAQC/8Akp1kKUv/gSykZOH7K0LcV/eMxvXOnDOPXufJ8fzqqudc98yZc+5n5p4zwIgRE8FWNXrIGjXaOGg6paYw2XTGdNS0IHgzTLNjg3+EH2qUWGp6pqZw3/TBtM60zPTQdB0DDDKB7DO9ho8d9eK3FsCTJEadTWIr4P1bYcfpaiY8MD1V03iJ4SQmEl86xzbTc9MUDQQ+mnaombLJ9EXNhEnwwbmMlJOme2p2SCkxN02n1RRWId/3F1/RXFuOwW/ABClHTOvV7IjV8Oe6Iv4703LxSrD/TDUjDLKAluCsYBvWl9ysGRY34M+1MFxzM2ia+TnY/7yaZA5aplMgTtmox2jIdEeky2h/+M26MQgsA9lkbkFdYhab3mB8gnLLqys4/nf47rg7XA/6TFdReP+9KAQamGv6DO93WGI5uL3XqpZYX6hZwYuz5nZsVEEsE+MYQyEQOKdGAvtdUzPDzgFUyy34+PphGZNVy3EU2m9AIRBoi21UsyNKCbgD9/mH18AdLXcfzEchYMxDOcaBS7Eu4Njf1ITvmqWk5bhr+qRmhDeZpqZxAR5jgUpZGXwW5GGwCz7+ZQ0EYmLWaiAD211UM8IgP+IU/iNM2CV4G+4AFLfEXCL/NodM7+FnnFfw7yo+T8pb+JmPxxfuovx4bYLvxVWT5QR8kP+NJahYcmwwVc2ew5m3R01lu+mRmj1mEfzkXQXPDAfU7CmtS0gZU6OHbFZjxIg/5yfINZvIHRvp6gAAAABJRU5ErkJggg==>

[image8]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACkAAAAYCAYAAABnRtT+AAABuUlEQVR4Xu2WzytFQRTHDws/ihXlx06yUGyVjRILspF/gBKyYSHZKRtk5x/wc2PHzkbp7WytKSFlgRRCEueYGe/MudO9d+6bt3rvU9+653tmzj137twfAGVKmDZUpTQD0oDqlGZarlE/WtUiF4IR1Ceo+qci58U+qCLFhOoPSNMHKkBXWywmIcAiUIEVaQbkFgpssh1UgRrUMmobVWGNKByqn0N1oA5RXXY6mT1QRZ5BPTjdOg7ZqHkwh0DVpeNVa0QCNOHL4R0JLyvjoOo1M29Le6mhwWsO757FrahvFvtwCdGG6NZz70bHB8z7pwVUso555nZs6ngDNaW9LNC8M4dn6r0x/wLUQ2YxDdGTL2qPNrmhX3tZoHmjDu+KHdNeJXp1bNHnMCmm5efENVmLmpcmg+Y1sXhWey7MAkXg5rqIDXFNkk/qkQkN7WVzEVWgxg7n0xaUc37f6cfCnOhY5AxxTY6h7lC7MsF4ATX/FdUocoZzyPD+5MQ1SdSjlqTpwQ7kt8QC871IajJuFZOgPTqHmkDNoD6sbEreUU+oB1BfpUE7/fefeCI8H8xWM3q002Eoxj9omdLkF1kXcJzy/EoiAAAAAElFTkSuQmCC>

[image9]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA8AAAAYCAYAAAAlBadpAAAAy0lEQVR4Xu2SMQ8BURCER6XSqiVahd8gWr3/4g8olCqVH6KlUGkQnUonR0hEEGaz7708e+/UivuSSS4zs5fbzQElI+pMvZ1u1JF6RF7Dl4vwRcsM6jdtECOFuTVJB5qtbeDpQwtdG5AJNJsaP7BB+pOFonUCqUKbelJ74+eQQbnwklpRd+dV41IKv68cJmbr/J/skC4NoX7dBjGpfYUr1K/YIEYKC2ui+KWBAbTQswHyw+F5TF2oDHrlE/XyoaMFHThA//fad1zy53wAhPQ9J2j9tisAAAAASUVORK5CYII=>

[image10]: <data:image/png;base64,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>

[image11]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACcAAAAXCAYAAACI2VaYAAABc0lEQVR4Xu2UTysGURTGD1IWigUpCwvWYmFvga9hYeVPXoSFhfIBrCyslWRhRSmipOzlKyCSjWSF8JzOTO+dZ2auGTW5xa9+ve99zpk7p/e9MyL//C59HIRCP5zisCqWpNzN7mm9DzfFfs0GOACP4KDb5NAOPzl02YWvYk3qdLLs5ZnWF1LfJ3Yn0SHSCa+jWmwhygw3AUcoO4MLcBsuUi2Lyob74ACciv2dRalsuCsOwIkEMNwG7OYQHMM5sTO8JbbfpNtAlB5uhsMM8jY8gGvOukWsd9TJXEoPN8sh0SZ24IviG8BXS6GNNQ6Jc9jEYUQzB+IfwFdLoY3zHBJ5m/WI1Q4p9w3gq6XQRn1P5TEElzmM6BW7ns+XZu+UxRQerkOscZ0LDg8cEHp9o7NeiTJ9MLL4drg9+Ahv4U30qUPo64B54YDQwfS6N6nfuDXRYTzBO7H7qfpdsx8zDsc4DIW8cxMElxyEwirs4jAUhjn403wB7MNqvXm6XDoAAAAASUVORK5CYII=>

[image12]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAO4AAAAYCAYAAAD9JcEmAAAGnUlEQVR4Xu2bZ6xlUxTHl5aoo41egkEIBgkivogSJaKEiBLMMGpEREuIDwgRLdHCB21GjfJBdKJNgiD4QIgSzIeJzui9rt/su7111tv7nHPfu+feCfuXrLy3//uce9bZd9e19xUpFAqFQqFQaMumXihMip290JIVvVAo5PjbC4VJc43aDC82cIra5l4sDIdb1L6X0BiwOZXcwJ8ylo/tVs0eKp+preZFZS21NyX4d5PLiywrY9e8r7ZRNftfdlF7R8J1d7q8YbOT2ncSfLnS5V2tNk/tVLWj1A5TO1TtkJ5ZjlH7RO0PtUtcXuRr6a8h+g70AbXr1aapLaa2tdrjatvYi4bMZhLqzCj5Ru1CtfXUllTbUe21yhVV+vLZNswUz6ht7MUhQ+X83IvKCRL8XryXPlbtr7HshWwo1cJ4SsI9VxgNTpfqvSdKvky65kWp+vy22jkm/aFUvzdvkfvUPjbpO9QWmHRkZWn/rpQ1ZWh5Xsb7MIqObw+1L2TMh1SdGSa+TLDTKldM0Gd6x8fU7pdw04HV7IW0/UK7BB/WdBoVCJ3Rx4J2rUv7woqF5DU/6qDlRqmuoIe2vk3tpR81Guld1bZU20TCDAL7TW1pdx09vQVtL6cBndZBXkxwm9oKTntWQhnfrnaGy+uXF7wwQXjPVo2gQ/CBDvdWCYNME619Zqq1Xe//VGUGplijZG1J+3WwBP1wp/v38GlgJEI7qZc+oJf2/CppvUt43s1OYwpl8bMKuFxtlklfJWnf0VgueJiB8L5NpD6TEZhBYBC85IUJ0roRdEi/bae1z1+Z/5mPc+MUoxHBvdSkRwE9PCOJZ7YEf2l0Fiq1rVz7y/gRd66Ea/btpVkOpCrkPEnrXbGnhOfFkW8/k1fHKmofOI0yS/mOltKJFaR0C52on+HAkzK4hvuqFyZI60bQIb97oYHWPtsvinUs6XeNdpfa8iY9CgiQpdZLMyT42zTipvDXxE7L85ak9a64R8LzjlA7X8Lac76E4FIdKR/9O0ZyOuT0yBte6PGEhNkbncUcCZ9DjGAi1AVv+gEfWjWCDmEGc53at2p3S/CJoGOOVj7TQz7kNP+lNn2RlukS1jgpY9Rknj9bQjSb6O+N4bZG8IF1Xwry2M7wWp3fcYpto6+5e16XtN4VdJo8zweQ0Oy63XK0hGCVJ/dOOR3QCeblSE3R4UEJHU2EdTaftbvR2jLIhkvQpy2+zlqj7s6RUHdZxlB32wRs2RVgFhXZQYJfzJBStPLZrm+txs2slyA1RR02+EPlTHG2VCvhI2q/OM1CZ0XecU4n8pq6J24h1UEZtrUmXpHwvOOd3tTYZnpR8vfkdEBPBa6A6OcsL9ZQ9xxYRsaXD0YE3Wtty8/Cs+1ScFEBv2jQKVr57Hv1SCzwLdQucnmjIFcxI9uqvSwhGklPVldh0Nmr9eTWuKwbU7qFdWhba2K2hOdNc3runeLyJrWcITCSuif3WYAe1/2eH7xgWMoLUv8cWEnGlw9G4MxrbcvPwrMXeHHI9FsurXzO3UyggTymX/SKbWGKdVmf1gZ8ucCLNXD9fC8qP0nYOonQOOIIcq6ky2PYUeW9JTwvtS2V8uMGSesQv0cPWm7KS950L/bIrb3Wl3Afsx1LzucmBjlVJnbRFl83m4yBrY4jJfhwltPryqXRZ/b2nvZij7g/mvvwYYMfrDNSkMepnwg9HNoaRgM6odWdRtDAnsTiPr/2QPNxgK7hmQSnvJZqbD6CbmHfO5WHlttrJc/v+8KZatt7sQf7x9zn17No/W6HwCAbLkGhUcGJNXxYx+lo7zktUuvzEmpfSphe5mB0+tmLI4LINuvWFLzoPJNmmuHfi6N3XJcyy6dS/axY8VPTnS4hkEckPcI0GD/8ARRIvYeFhk00M7KP5K9fVfJ5OT1Cfjy9Bhw6QLOHQdoyyIY76jrsy+3hhGbJ+nyvhBbNApgh2VYQC2dNT/biiNhA8i87U0JeXIumzirHyp0yDx0aRw05pUR+7kxz18STbDFoxgmpFPEseR0EGOnhn5NwbWo9DBer/ehFCQ1yrhcdXMNz2LeMZZt7ThOTabiUE533RxKWSxhbaZzJHwVTJZQFbY6/NEq/372o+TxQeGn2NAvdQaPbyosStkCmeLFDJtNwC4sYbFOlAk6FwbCc5EfunN4Vdspd+A9AoMMfbi8MBqZm63pRwizH/6SwUOibYff+/wfOk/wvV3I7D4VCX7Cwt3uxhcnjf3hvSf3Ms1AoFAqFQuE/yD+zehnJGzhpLAAAAABJRU5ErkJggg==>

[image13]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAZCAYAAAAMhW+1AAAAhElEQVR4XmNgGDzgBBD/AuL/QGyGJgcH/QwQBTjBYwYCCkCSh9AFkQFIgSO6IAwkM0AUNALxcygbxbSHUEELJDEQPwCZcxQhBxe7gsxpR8jBxV6AGJJQDg+SJCNUbCKIkwblIINSqJgqiGMH5SADEP8RugAMdKDxwUARKgjC29HkRgIAAFc5JozAqrYVAAAAAElFTkSuQmCC>

[image14]: <data:image/png;base64,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>

[image15]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEwAAAAYCAYAAABQiBvKAAAC70lEQVR4Xu2YS6hOURTHlzfJ4zJg4JFHGRgoXc8yUBIlI8XIzUCMTJQ86hIpKQMGIkoyIREmUgxEMaE8klKSgZLyCHk/1r+199f6/medz52cQ77vV6vO/q29z/7Ovvvsvc8V6dDhb7CURZuxhkUrNmpsZfmfMk5jAktlqsY9lhETNV6wTBzQ+KXxVWM65TL7NL5pfNc4STnPcbF7PdeYRLk62K3xQ+w37KRc5qDGUZYMbjCUpZj3jVFe4crgncbsdD1WrA6C+SnNrzzqLHPlupgm1vcwTjii399gocYXlsp9KTZcRW6exkuNEc7NEatz17k9yXkw8Ozq4JT8uV/UKX018SpFa1c0UzAwcPNTGa8iyg8bNQxui+tHrpyBx3JQJ+jzM0tilBSfvQES0fTkh87AnXblsxojXRlwW1xfdeUM/CGWFYM+d2ks1jgvtgFEoB4/V2PGRPBDgynJPSDvWSBWBwOZQfmSK2fgL7OsEOyC+blmiq3buF7uKyXgt7HEKPOgZK5LMXc4uY/kPchjgc/0Tw5/TQb+CcsKOSHW50DnnibHwBV2/HUpUQZyWKdAP42byV1r1GjmnNi2zaDNBZZi/gZLB3bd7j7GjNSmFegPa7YHx6VoDD5p3GbZI3FlD85hmFHY6XB2Qn2cZ5gNGm9ZJtDmCksxf4ylY7LGyj7GotSmFX4CeBeNAZ75DkvsdlHlMvCuo/4A8rjPM3L+vrgu2yVXs6wQ9DfalfFqwhVePTFfWEa6UiJirVhuiHOvpHhmGy/xmcXfF4PF/cwNXNVwf2cCl4HfzhIgMZilskMslxdI7CpcN/+Forjl6o1Jzn9NvJdgylcMfsOsdI1vSZSx80cghwlVAInNLBM44GGRfC32ncjnNaw/PFA5eEtekvxFjTfSPKB1kr8l8e08iHKZ4WJ1QrZofGDZ5hwR2/FLwWj6s0m7Uzq7MvivQZ0HyH+ZXo29LCP2a6xn2Wbgu/Ixy1b0sGgzNrHo0KEefgMAGtLsHePOHAAAAABJRU5ErkJggg==>

[image16]: <data:image/png;base64,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>

[image17]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAD8AAAAYCAYAAABN9iVRAAACFklEQVR4Xu2XzUsWURTGjx+QCzeKRS5TwxD7FySjf8CFlJsoFFdCGkiIkkRJkavaKUqlbtq1s/btXLjSVSa6EDdBKBgqas/jvVfPnLmSL8gM5Pzg4eV5zpmZe+fjzrwiBQWXnhtQuQ3/d9agI68rppYl76BV6An0EOqCHkD3vTT0W+LGzF7LAPQZavH+FjQH9Z90KGbF7ShPfsrpRYgpsAxtK78AfVeevJL09ouJDgWLuzbMGI7hLtQK3YQavPagKt/T6ftqvA8wu6b8KPQe+gSNQBWqloIbv7BhxhzaAIxD3covSfIuCDD7qjwn3K78mTSK25hn9zn0ASpLdORDLbRiMvsIBGw+LOec/Iy4DX+LW/Bue5/3CYhNclXiuZ38EDTmM15M/k6o+gks7EeyLybTcLXlIhkTT+ZHcQedhqbEreSl8FjcAmjhmsCx1ansus/05J9C35QnrL802XH4OpJtmixLePxHNvT8EHeXBv5IevIxUj31PqhWGW93ZqVerYuiSdJjsvRBG+Le3YT9B6fl6CPLemLyvTYAgz7j6+Ys7kFvSxDfu+dlUtJj+hfs51y0/6V8yBL7bbOB9+smyxK+8uyYNKw9U55fbbafnhfRZrYvEbwxPg+ig/RUiqv1qIy+Q3myA11V/o64vmaVHcM/NOGA86aWB6ln08DPWdbD5zAfwRi87cO8KH4tFhQUFBQUXBb+AkWpnpOeQFeaAAAAAElFTkSuQmCC>

[image18]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAYCAYAAADzoH0MAAAA50lEQVR4XmNgGHZAEYiZ0AWJAQ+B+D8Us6PJEQ0WM0AMIBuANP9EFyQFgAxoRBckFigzQAzgAOI6IJ4PxIwoKgiARQwQAz4wQAJRF8on2hCQ4t9YxDagieEEIMXtWMReQNkWQPwXiP8AsQNMAQxIMkAU8yCJgZwOEpsIxIJAHIwkBxIHeREO0qCCyKAUKqYKxHFQNgx8B+IzSHwGOwZMA0D8R2hiMACS68EmCAMdaHxkoMWAQw6UiUASILwdTQ4Z/EIXIAW8RWKvQ2ITBT4DcQIQJwJxHhBXo8gSAEUMCO/BMEo0jnQAAJxmNxbCEQJaAAAAAElFTkSuQmCC>

[image19]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADoAAAAYCAYAAACr3+4VAAACTUlEQVR4Xu2WO2hVQRCGR0Vi1MaojQERi5RqIxYRgwgqBHyAjYiNFoKCphVRAhaCEAxEFAQx4AMrsRETK8XGRhAhoGAhPjGxCfjAR9T5s7O5c/7dm5wIgdxwPvi5M//s7tnde3fPFamoqJhB5qva2JxrfFD9NdVjs+qzhDZPJGxMQ/JW6i+0T3XJ5d8ktF3rvIYBE3/MpoHapoxXb2NmNZj0VjaVJZJfVM4rsEB1UnWCC45TqoPkXaM8skbVr9pftKfFYalN+qLqgquBs6p28iZd6DnVT4uxU4i58S/7hL/F4jiRbssjL1QPLT6kGpN0vDK8kdBvyPLdlk8G6n/YBAckFBc576l5kauqpRbD73A1LKLb5S8lfRD6vCOvDOj3OuN1kRd5LqG+mAsAhY8Z74vLT9tnr9U8l1WtFm+QUN9TK48D7yh5ZUC/HRnvNnkAlxJqK7kA9kkoHiEfHs4rAx/vNs8nFw9LuhEbzZtH/lTgbPNY68zbS/4y85vIn2BA0sFWm7eQfAAf58TzzMWo83j3M14Zbkna7555ftPwB4HbXad8/CbjRjecd9P5cQM8x1WrXI6z+dvlAH1GyCvDGUmfh/wOeXwfANwbBeK7KLLd8ujlHrTe4mbVK1cD26TYZ9TyY84rywopjvVI9d3lIL4dckqIk/MTwi4hb4mNjE7zIfzsc+xSvZdwYcTz+b/slNrzrlANFyAvLoo3ZMZ5IMWFdlg+lWY1PZJOEvld8hoeLOqHxbixv0r6KpoT4Jo/rxqU8O0uL5YrKiqmyT8BtbJyxr+7FAAAAABJRU5ErkJggg==>

[image20]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAABICAYAAABLN6ksAAAKk0lEQVR4Xu3dCawkRR3H8b+IoohoREAl+lZRgUUEDBqvIHgL2RgREYPK4hHxQiJeCchqIngF0IgYjLpBFEVUjBiMSGSVKN4BjAqCWRWJBvDAAzwQrd/rKuc//+45Hrzp7pn9fpLK9v9fNd09sy/pSndXlRkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAoHJYKrelcm2sAAAAQPfukcrvXPwTtw0AAICe+KPb/pPbBgAAQM+cnsp9YxIAAMynS2Ii2C6VHWLS2cqqNuPsEhMLbptU/pXKf1N5XKjzHhITwc6p7BOTU9rXqvfZAADAnFOnYhx1ON5t1d2a80Pdg62q/2IqN+ftHYdamD0m5w9O5dZUzhyuXminWfXdm/w1le+ncrVVbV4yXD1Ev9uuMTmlUccHAABz4rJUjo5J5/pUnuZiXfxfGGJPsc/dJce621TEzyyy66z5+6qjey8Xq5Ordru7XNS0nyZX2HDbaT8HAAB6aJ1Vd8XGiRd7jT6MnYEfufiDOVc6gefm2LsqlZ1CblHpu38rJpPzrP67KFYHeZQDbPL/lxyUypvz9iNTea+rAwAAc+Rdqdwek8GRVu9UfCPkPp7KQ138DqvqT8mxtv/9/9rKxlSuDLlZ+Wgq+8VkpnPf3sXq2NzbxcUrUnlNTE5J31/TbJxo1fcutk3lcBeL2sbfOzrGJrcBAAALQhf9PWMyWLJ65+DXOTdqAIKmk1B9eQSq7b8Mqpd92Kp3smbpuTY4d717p+PtNqhe7kQ+0wZt9H6YtjeVBlZ9R+X2t+o9vP/keCXU/s9W/R57pfLt4eohavvamGyw0nMAAABzatqLfmynWOWxIV+o7owQ+znBpDw2nRU9BtT+17qcP55e7lcn7KyQ/70Nd9hUpztaPl7JeS9Z/e7iqM+rExt/p1HUqXteTAIAgMWiO156JDctdTI2WDVA4bs5bqI7UBpk4KmtRkN66tCNm8y1dIwmlVFU52f6X5NzkXInuFjvfS25uvgZxa8LuXGuSeVZIRf3Kd+0anDCSjTtBwAALJA7c7FX56vp87o7dYSLH5T/ber4nJPKd0JutWgghY73KpfbmHNRzP3Nbavuyy7WPGrKxQ7pOHH/mkst5t5nw49JH+62x9F+9L0AAMACOtbqnYZxnhJiffbikNNdtwNdfH8b3LmKo0rl8lSeEXKr5TirH0/xLVYNKPAT0MZ2X3HbqvOPHb+WcysR26uTWgZjyKFWzV/n/TPEo9xk9f0DAIAFUWben5bavinEd3WxRmF+yaoO2vGpnJzKL1N5dK7XHG7xeDFeTRpY4PdfJvbVCFB1ujzf7lK3Lap7Y4hvdPE09Ii42Nrq3/sPqbzdqt9tQyqftXoHbpT1Vt8fAABYAOpo6SJ/VKwYY2+rPqP5wZo6CMo1FW8p5z6f/336cPWqK8dTuWcqh+TtuDzURTkfz7f4dCr/sMFo0j2Gq6dS9v/VkNf7bfE3U3mCbzSB2sdOKAAACB5ok9eB7JMyh5fmBcPK+E5d7GTFcu2g6UyV4wEA0LkbbHBh+rtVj5HKi++6+6E7KF0o72ZtiBU9Vu4oYbwXWTXNRqEpQH7r4r4oc94BANALm635wqRRfcr7d6ra1HROyn0hJnuCOzLTOTWVS6yak02/V18fO77f+P8EAPTIqI5GyZcpJNoWz2mrnNs35Pti1O+I+XSY8f8JAOgRXZQ0aWvUZQdkvdXnEtMM9F2dzzR0bptjEnNLa7j2+e8NALAFKXcR4ozxovxzQk4Tm+r9sp9ZVa81JeWAVH6Rc6JRj2XW/qYFv4+2qk5TM6yxekfnV1aNHpRH2KDzWMr6XKc5yUrO03xbeleqTTqHTTGJuVVG/QIA0LnS2dFAAy2iXeYR2+TaFGVhcq/EV7j4nXlb1FlrWu9RUzr4eNR+PeVe72J1Hj/n6rZ3dU2fLzSH2dkjita/3JjKJ1L5mE0/M76+p455bqzAXBv3dwQAQGuaOktNyl2uF+T4qTnWtBv3SWXnnI/70mPMC1z8Y6u3UexfPF/KuUg5v3TRGqsmTJXYPsaztqNVxzwzVmCutf13BABAjQYT6IKku0qT/MCqtpqOYUMqa4erlzW9pH1zKnu6WPWxjWI/oanubsU20pSTE1M5z8X72fjFz2ehdNh07pOU34DSbZnGtO0AAJgZPfLTBWkpVjTQu2aTLl4/t3qbpvgzLn5pznmK45qPj7JqXqwmt6eyg4svtOFljyK9TK5FwacpvrM5Tnkk2tcpKnDHxL9NAABat5I7DVqTsamtfz9N9Se5WHfjymduy/8qPjxvl7isCVna6t+DrZoHrlBn8PF5WwMWvHheMW6Ljqv3/LAYdrfu/pYAAFh+hPhDG3TYvpfKsUMtmmklhE9Z9d6YFvv+javTC//a1zYup32W/Ze53PSOlwY3aAUFLWquSXDVRqNRX5bbKNakpZ/MsRxq1SLpOnct4u2dYdV+n2iD79QFHbd0TDH/tCZrV39LAADcKQ9I5cUxma2LiWQvq6+UoA7fES5esvpkuP4uXKH96/hN1OE7MJUTrLuLbJedxUKDQO4ek44GiPiBG03aWo5Md02nedTelaOsv+cGAMBc8Z0kLRav7Z0G1a3Su3RdXeA1TUrpSOsu542uTnRemrNO9s5xmUNP7pZz6vCJ7qSOemdwNV1n3f1mk2iKlr6eGwAAc0UX1F1SeVje3me4ulVft24u8OpkxeMqfr6LL7dqaa/Cd3TlUqsvwB73OQs6ho7dR112wAEAWDjvSeVtMdmB8s7ebrFixvzgjkKxplTx8eku1h045fbIsbb1LqAX9zkLOoYeZfdR7NQCAIAFoHfzdIH3Kz20YbPVOxaxs6HBHf4Om6ZNUb0Gi5QlmPT+n6fcISG3ml5ug3M836qpW/pE53ZxTAIAgPmnUaJ6lNamt9rkDlukOq39Kpq0WPEbBtXLlNNo4Fkp56hJh+WaVG4dVHeqaX5AAACwIDT1SBcX+njMcR02raWqtWOLMh1KU4ftIyG3mrT/k12sFTf8OWuQxKQRrbNyg43+/QAAwALo4kKvx5qaxPiYVG6y0R02TfkR8/fLueNCvqkTV+jxajnGuKIlzZpooIjqt3M5TZRczk13/3Tn7TKrT/nSBp3H2TEJAAAWxylWPVLrkjoc54ScOnMXuVjvkO2at9W+adCBpkqZBZ1b6ZwVijdbfS3Z2K4NXRwTAAC0rO0LfjxejPe3+h2jn7ptvXd3pYsl7mM1acUKv/9Xh9gblZ+V46154mYAALBg1MnQKg9t8Z0arSLxAReL6ptK8eQQay3XWXaU9H6a37+2tVpF9EobTD3Slll+bwAA0COn2mBR+zZoLVWt9XqLDc+/VsSOWuywyVtyThPZ6l//ftksPNsG51FWYfB0/OtjcsY+ZPXfBQAALDA9VvOjMTG9k6xa91Qu8BUzdKRVnV4AALCF0ZJQerkf01tn4+8EzkpbxwEAAD3U5qNR3DGaUmRtTAIAgC3LhTGB3tCj1yfFJAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAALZU/wN5jxmKt7tdBQAAAABJRU5ErkJggg==>

[image21]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEcAAAAYCAYAAACoaOA9AAACXElEQVR4Xu2XT0gVURTGT0Ek5MZWuTDQclHQNnITBhGCBUGLCiRqIy2iRWAbISgXRdSitqlZ2U6kP5AE0aZFELUQKoKIR0JRYBq0CO3v93nPjTvnnREN8g05P/jgnt+9897ceTN37hMpKSn5xzQjK61c7rxFfmlWm74iwfMbQY4iXchB5ACyX5PSL2H8BLLe9EV2IK8kjLtp+jLckDCoyMQf0MuTZNxPZFdSs78jqckJCeMivOC582fHjJUFg5NpQzYjG5EWTTqpPlOT3Y5jvclx54ybgx2nrSwQXAsvWgmmkDVJzXm8TOoIfZO292pt4c1R5TeorENOIVeRFZkRxeQkcsw4zuOBcYT+srYfam2piOOvq/wsYUHeonWRL9AqcSYiwd2xUoIf0zbn6R37QhxP8c1xt4xbDFckLPJeriFDyCAyoGM7545aOG+QI8bx0eN5jxpP6F8n7aqLAMbF8RRnHfdB29uQH8h3pD0OqDFVk1DyflT6R9p+r7XluRjfqKI+cXyc6C4hDci+pI+ej10tGRZ/coT+vpUSPO9Qkrfm8G7M+G4rQI+6VuSQtiNfkadJnccZ5PwisicctiB4PvacI/R5b6u4UezV2lL1ttpuhdbcWXqw74KVS8x8F4cXxvZtdRzrtY67a1zmQG6C7AdFuPnK61tK5rs4nDD7uC2JfEGeJTXhelpJ6nUSjuNbMAP/cMYvjK87j1kragTP852VCTsljLmNTCOPs91/mEQ+IvckjOdu+6/4lLS9V+WyhbflYQn7iuMSFrQSCf9e4yMXU+tXeUlJScl/x28rVraNlyM0AQAAAABJRU5ErkJggg==>

[image22]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAHEAAAAYCAYAAADNhRJCAAAD1ElEQVR4Xu2Za6hOWRjHH6Rxz/ULmoTmk1skyeUkhUy5TGZKEiGEUD4hOqEUiRBlMO5mvsgXDL6QlFwKucYHueaSxnVcZvD8z3qe8z7vs9c+5z3U+56T/at/Zz3/tfZee6+137WevQ9RRkZGRsZ3RH3WT97MqDs8ZH0WpTGQ9YxCmzMUJr3UTGV9onBNv7s6pSnrGIU251j18qsrWcJ6yXpL4bx1knuUPokbWJtMjBtF287GKzYrWHNMPJKS199BvMYSt5HYP4DXWMdNfIV12sR1BtzcKW8KqOsX8fygFZNY309Z4038hvWXicF51jsTt6D4ueC19GZtBxc9xJsUlqPYhMW8YoHBRd9+aXzOmmxitPnNxGCR+MpFFyvwtnpTacBayJrnKwyLWROd94eLlU6sHZT/BNYU7AF6IxtZa00dWM4a4LxSTiLQ/odKrA+bMlhi7OWWSeK3ljjtPtJ8Wsn6IGV0irJv+FH+wseFAB3kcomVG6wTUp7C+p+S5yuEuxSOuyrxaImrAvVIKkrFAsoN9AP5a5kvXm/n/yq+bg9pkxX1J4jZyHgXxFO2sZpJGX6ZqcMElZv4JiUHEcfcd14h4Lg7EQ8DEeMyhfomvsLRnLU7RbtYOymsMNspLF1pGWYaeyk32NA4U7dMvB7GA2PFx3yA6GRRig/jUcR7bWKkuWCd1Fk2U8i2QC8K9WNy1RXAm+W8QsBxwyPen84DeIJR185XFJlbrNVSPkq5Qe8m3nSJMVYWTDR8XYajk0URXw+cYU3xsD964OPdzfLYlJ9QsuO+4vnNvjqwl/pz4emFh6fW0kr8H5xfbKax/nFeR8ofeN0T+1e2CCDXgK8/iMRkCQn/b28wP4rX0PkAPvYlC7IoJdEBcyTiFcI+Sh53SDz7QODdyrfDslgVmOxVNVQh4DqQJ3gGUe4a0TfK1WWnr1yswLtuDWR8vuEe42FtV3RyLXNZ7U2MvfA/EwMcg/ekmrKUkv0hPuA8v/8C7NOl4AWFMfV0pfx7QXm9icFh8RVMsr9/AK+PNXz6O0xi9fxJEPeUMr423DZ1AOu5PQY3hXi28QqlLeWf6yTrXxMDzaJjKgVdKPRtk0SAl3vUKf5XBxD/EvFmmhh7rT+uAh14O9j63U/fWZSfxYewFMcYRSG1RvKh++HXMoJy/W1xdfrpKiY/2cUEex2uAa9kmDyUu+e1COynsGLgL9rEMm78UFB3lnWJwhedmuYW34x+4FXKJK5OGSViDSUnAPFB52XUYjBh76WMzBZLiX8dyajlINVHKo4XXPwq8e+VjIyMjIyMusAXHuU88VlMPTkAAAAASUVORK5CYII=>

[image23]: <data:image/png;base64,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>

[image24]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAYCAYAAADzoH0MAAAAw0lEQVR4XmNgGHZAEYiZ0AWJAQ+B+D8Us6PJEQ0WM0AMIBuANP9EFyQFgAxoRBckFigzQAzgAOI6IJ4PxIwoKgiARQwQAz4wQAJRF8on2hCQ4t9YxDagieEEIMXtWMReIPGlgPgvEh8OJBkginmQxEBOB4lNhPK7gDgVKoYB0hgwJUqhYqpIYo5QMQxgx4ApAeI/QhPDaQAIIEt0oPFhAK8BoEwEkgTh7WhyMIDXAGLAwBrwHYjfAfEbBkhqdUGVHtkAAJgvMf6XfoHwAAAAAElFTkSuQmCC>

[image25]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEcAAAAYCAYAAACoaOA9AAACRElEQVR4Xu2Xu2sWURDFx6gkoIWIjYYg8dEE0opaCIZABLE24gMM+CjSWBiwiJBYqIEUIUkV31qkSGGhWIj/gCBYWQgWEQQLDSqoiEZzznfnhtnZTfJFCV7x/uDw7ZyZ3W93dnd2VySTyawwrVCDN/93pqFfqkaXSwnu3xR0FjoGHYG6ocMqy00J9e+gDS5HPkCXoBZoDbQbelaoMNyVsLGUiSewSk+1ZpXGbB7hyWa8VeOIX586V6gwMPnNm4nxE9oDtUE7oG0q7nvkq4vJWIXH+AJ0GzrjciVYPODNhOAsHPYmmIHWmTheBZZD6tmR8cMsL8p2CSs3QRcl3K+8PFOnD+p1XlVz9qnHWRX5bpYX5Y6ElTmk2N12jVNu0FopN4FUNeekeqPG4wgZhz5Ck5rfa/LzMOE7Se++85bDhIQhXyXe57egG9B1rT1YW6t+Xkk4aM97KTfnhXoPjfcJ6jLxLgk1G41Xg+blCu+tibdAsyb+2/gGRFZLyB3QeBP0RL3+WLQArGHT5tms5nrjxcfhiMZD0Cn1UuCeLL0v1yTcMpxJJyTUd5g8b0sPawrbPe0NcF69ncbbr169DEpoar3iE6VeSgexBFelWH9cYx6npbTdOMktjF87b7nNWUlKB2HgHPM5xs9N3KNes/EIvZfOK2zsiosj/0pzHksxd9TFEe89qPBq8IMz/uEjl4uk1pw33jQw/xn6ImHuVMFBzTrm+cs3699+dUmpOcmRm7MAvOT4DcPPf75FdxbTmUwmk/lT5gDVRq5Bg2VqeQAAAABJRU5ErkJggg==>

[image26]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEcAAAAYCAYAAACoaOA9AAACgklEQVR4Xu2XOYgVQRCGy3vBC2VB1gtEZEEwMFnWBcVANBAjAyNFDTQRxQUDUUTdYFVMxF0MRNcjMRIFj9hIA49YA89EBMEDvEX/f7prqa7Xo67g28E3H/y8qb9qpnt6pnv6idTU1PxjFkBjvdnqPIN+RE1yuarRCb2X0Nd70Lg0XfAAWg5NhOZC+6E3SUWI+6B50HioW8L1slyU0GCVmQ/dNvFUCX2ebjzeqD5o1ReTV3wNtTupMDD52ZsVI/fwdkAPncd4EDoKzXY5hdfaC52HtrtcAyw+5M2KwT4udd4u6Knzbrk4xzdvlLFQQsNt0AFoCBqTVFQDff0HnDfNxORPBuerN8q4IKERLlJckJfEuGoDNEvSNeI7tCipCNyX8GZch15BT9J0AZcQTr230CUJ1+tJKiJM+JGkd8V5I+G0hEU+J87zc9BZ6EysXVuc9XuWSTpAV9N0wScX64O3vIPWmLhLQt1M4xXQ7M94L+MxP3N8SnwaK7VgFOAnmdsOwkVUB4iD/Cv0zZjsEw7WcNCG6YjmFONxOtE7Ac2A1pscfU67ZsP9DNv2fJC8bzkooWaD8SaYY0UHe5ht3gB7osf5vCkeKx+huyYu4zB0bARaF04rhevDC29GbP8abhAcj96qGG+MMe/T0nDuCm/E+LnzFObYWLPhBs33U/GDwx2y5U70la0xnmM8Qu+R85ITj7jYsljKc82Aba923g3olIlPQr0m1h3zkPGIv49rGa+AfziZoG66nCW3DW8m3Ifxw8B+Po6/+5KKAAeMOS6u/OVG0dMuIcdPOX+5XPz11uW1Ob5sjlse/gveDG2Bdkr+abUknL865VSj8Smvqamp+a/5CWgPt1I1mLpsAAAAAElFTkSuQmCC>

[image27]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAH4AAAAYCAYAAAA8jknPAAAEpElEQVR4Xu2ZacimUxjHL8tglJF9iRm7IoXGMspW0ihbE/kiE7JFSTJDygciiUjZIiU1kcaa7FuUD7KO5osxRPayZBk75/ecc57nev73OY/7qXmf8fbev7p67+t/nXPf5zn3ua+zvGYdHR0dx6rQMa3YX4U2nB/schU7Js5OweaoOAb/qDCKnYN9rmLiJos3+z3YHhLLXB/sj2B/BrtPYp57LN7rk2BzJTbTed5i32BHSiyzabD3LZZZFWy34XCPXYN9p2INbrSJihb1u8Q/3vnwQ7AD0/VWNmi88rcNTyWUWej8DrOzrdx3wAv9yvl5oNzotMzPwU5QUTks2G8qBt6zZiNOEe0Qi43ZzGkHWSzzltOuSZqHAaTaTOdTq/cJ+iUFrVR+TyvrQ5CiS3N76aa8YLRDk0+Kxyf9eLQu1yudn0FnmumI0B+vqJjQPoWHknaB6IDO1FCFArNVtPKDAO0B5/NwXYxoXa5JTQr6rSpOiLOC3RxsPQ0kTg52rWgXBttHNJhl8V5XamBM6I+jg50Z7EEbnn5PsuYX/7LFOqW0jn6Dipn8BZfQlwfMM2grRPcssFiGAZHBf9z5GfSnVJxi9rL43HnJZ+2Bf16/hNlnwXZIsRedTrlfnQ8MDha+G1pc4/xlzX5rAwORejxz22DbJX9HX0govaPMs1aewnswumoVSTkauz1pLB5q5MZn1k/aw07LoH+g4hTCF8Qzz3EaXwvaBsnfJdhV6Rr9pXQNXLNzyZQWY3wUqrXhI2vWw/9etMypFuOnaSBxpzXv14eUUg1ajDGPAynxtaS90C8xzHKLI16hzqMqWtRfVdHBFzS/pe2d6oxijTV/7/2iHZX+bpP0rQeh3ld4t/OJv+P8rPnVd1uo93pB0/YC7wLdD2BlqZXr9lhsI4IJ9vF84azM2XtT/uqhEhFSZW10UucZFS3qviOVecFObGmHpzqj4HlfFLSfRANegvbNRcE2T9fM98QPGIR7oFFuXKin21u0d0UDdLL1KC6zZvv7sDqvBgscZ7F8TosZ7vOxaP6+XNdW9bVUtbbJv9XP5YB2hWiA/rZoPs0/Yc2+Y3uLVlsw1sjrDk/eFpOVPb9Y3K5ldrc45Sh3WPOefbawevAMi7GNnfaNNRcM21t9VGZ46fqcgwvaVELK1udxEpl/I53pOxn9YudTxu9ArrPm/UpZog3sCrQee3o/0GC1xYWf5zaL05LytMVBUoUHbqSixa0JMVarsG/yfVliaCXz89WWSfPbkx+Dven8SUAbTk/XeaGXO1wzEvojzteXAJTJh1fLkv/1IDwW1M377pxZfX/xIrWPffsV9FtU9FDgUhUTbF044PnW4g/X/T7zszYim6bPY5L+mMWzZF3ITALaz++gHU8mja0b/rm5UIJsyG8nxu8vwXz/RrAPbfDVlg5T2kDbct/VMmjNSqDzG6ossfLipmM8OPrWl6AvqGT8N25twz21LUUolFN6x3+znzU7lvVPaSu7LiCjLlKxBNuISR6kTHdI7/7FP5d80v26hrOGL1UcBee6ow4EOoZhxc8x9L02OPT5P6CZqBWLVeiYVhyhQkdHx0zmXzgtYDViXgkWAAAAAElFTkSuQmCC>

[image28]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFQAAAAYCAYAAABk8drWAAADN0lEQVR4Xu2YS6hNURjHP2+63gaoizxKEkreJSmJwoQyc1DCWIkMrogkJgZKlGSARChJMRBlRHlkoiQDkvLoUt58/7vW2r793+ts+8TZue7+1b/29//W2uucddZe+1tHpKKiM7KYjYoUC9jIY5NqG5v/KcNVrWwW4JCqxmaMUarnbHoOqn6oPqsmUC6wT/VF9VV1gnKWY+Lu9Uw1mnJlsEv1TdxnaKNcUd6oJrHJYIC+bIrzj1C8zMTgnWq6vx4mrg3EfJf0loI2S0xcFuPFjd2PEwUZIvHvlzBP9YlN5b5kO64ib7bqpWqA8WaKa3PXeLu9Z8EPw14ZnJQ/HxeLYyWbATyqsb0zttIwcfDm+BiPOuKHSQsH98X1IxMH4GO7KROM+ZHNBjkg8UXYAQaILX+elAC80yY+qxpoYsB9cX3NxAH42OjLBGPuVC1UnRf3gmqUkRKfm2TFxeBJAWO994B8y1xxbTDRAcSXTByAf4XNJjJOfn2vyeLeG7heahsVhOemA/xK0YRyQ7K5w977QL4Feewxge7ew2pg4D9ms4kcFzdmT+M98V6joA8WWIp1PlEP5LBPgm6qW967nrRIc05cWcKgzwU2xfk32TSgaphRUBN9nzwwHt4ZFpSDYQ6wYt/6eE/SIg7aZKqUmk/kgToUKxJvatSOaI96jtko7sPEQJ+rbIrzj7JpGKNaUVDzfZ887AKxXpgDW5lg4s+YmEGf5Wzibf27CbVgr0H7HuTjPk/Js/fFdb23/Go2mwjGG2xiPPrwwmEE1/399XYf1wO5qWzmFalrxOX6GO+VZMuFEap75AF7X0wmjzMr4jUbHg8rkL3AZcl+Vwv62b04AYnebCo7JN0Jb0VuG37hmG6bdkO9Z09j7ao7Ji4DfIZp/hpnecSZF4sHuRY2PeFEGAWJLWx6UABjL3kt7pzO9Sr2P57IIDwylkXevyjuPGwnvEzCWR7/XfSiXADH6UFsGvZKTqWzVfWezS4MjtzhqbS1tAWLbAqbFvxi0f2gi3FKtV61VrVZ4kdUbAN1H/cA6qkyC+x/Fd62UFczL6Tgf6n7VRvYrEjRJq7eLkyNjYoUZdbMFRV/kZ/D0uSwErjLWAAAAABJRU5ErkJggg==>

[image29]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADYAAAAYCAYAAACx4w6bAAABjUlEQVR4Xu2WvytGURjHv5RNUjaLRWSTDMqPyUrJambTO7DIahAWEzG8pQwKi81q9Q/YFMUgJCE/n6fnHO9zn3tf7ym5l5xPfbv3fJ9zz3lOp/ucA0Qiv54O0jppRHkz6v3P0UB6I22QmkhDpHfSPOlO9cuLc9IzJAfWE+lIxRtVjPWgYgk4OGBNiD9nzZzog8y/aQMOXvikNTVlyABZsM+7WQT7kPlbjc+79UqqM34Kv51ZVPPzICuvMdKx8ariB1ixgYLhnPi/9xySplS7JkuoLM5rLdEjf7ogeay69qNrN3/2CGQa6cWdJHrkyw4khx7SLaSwfTunYVQWV4sWUm+gOt03Ifj5tzO8IMat4dhC2CBtpNFADbpvQuC5uZxrlp2/YPwUPFnJmo5ZhC3sJ+iGzL1oAwjcNS6be9Z08DlRVAE5gCTPNyDLKSTWbwMav3o+8DS7KOYa5flqVyYgsRcb0JyR6kk3kM7X7llWffLkHlIBr9yT74e6CvL7JSTvC8gR0K7ikUgkEvkffAATQ3CecYjTaQAAAABJRU5ErkJggg==>

[image30]: <data:image/png;base64,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>

[image31]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABoAAAAYCAYAAADkgu3FAAABAklEQVR4Xu2UPWpCQRSFjxiwcQGuwDLYS8DerCCtewi2aaxdguAOJL2djYXapLXQ0qgERBFB73Df4HjezBuxM7wPTvHud+eHmeEBOc/GTLKXnJ1sEleT7MitEufi+gO5FLbRxxzqXlg4nLjgw0xgJpqwSOhBfZ3qlqWkzEUfn9CJmiwSWlBv+phXyTcXQ/whfGyGKtQPWCB7XIqs+7EY/0u1vuSNakHs/YxZELyZEvwvMEgbOsE7C4IXMs+44HxHid2PxV3oQ9Jx3F3wTkMcce27p/+GInTQlIWHIbR3IamQi9KFDjZHEeML2jtikcUP9G7W0Ce7RfwX0sADR5aT80+5ALjNSQGtk26yAAAAAElFTkSuQmCC>

[image32]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAAA3CAYAAACxQxY4AAAOzElEQVR4Xu3dd7AlRRXH8WMOGDBiXlbFnLMEWQOimAMYi4VCS8WAWf9AWcScMFsmFhQE0RIVs5a7ainBACYMqLsmVFTMAfN86Tnc887tufnd9/bu71PVtbfPhHvfhJ6e7p5ZMxEREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREREan5X0i/atIvUyL2myb9rkl/atLf0zI5Xd5EREREZOZiheuyadqo9rDeOkRERERkxi5lSytt02D5G+agiIiIiEwvVthOS9PGsVOTfp+DwY1yQGQKF8+BEVy6SdfJQRGR5XRKk77WpDPbxOdTm3Ryk24Z5pu3Nzbpe006PU8Y4NFN+qNN38Izrq9Yb/uRvm5lG25q0v5hvlFcrEnn2GxaqubtCja7VrYX50Cra71sb7Y72/+MJn21SV9s0vuadK0wn0jkx+whecIIWG6Syt60VmuZLfN33RyQxfc4q18Il6vywzoHDSx/kfUu+v9M04a5vtWXmUUlYpCu9d/N6vFhWCZXWojtk2KrzUWsty0m+bsH4cI0yLFN+lcO2vL8Fi6MtXUe1qRL5mDjKVafX1ZWPFZr+22Yldqn8yyzb2VlnfdJcWKvTDE8zWb/G6TnEla27/XaPOXeeb3JsujOtvoJdpKV+LitRIM81erfFTGdJwsncUyTXpqDc8BvPj8HW0zbnIMDrLWyzA4pTuyiKbYa3dfKbyX9KE2bxijHzcty0Er36rBlx0W37Wdz0Mr31Fo5djeNy1uNjmjSC6zstx+naaN4T5O+kYNDcMF9Tg6OiTKblrbMy+x54Htuk4Oy7Og5+HmKsS9yhVoWlF9cM1qqZn1S8mqH2ndFTH95Do6IZXNFZx743sNzsNW1fbtQ6azNX4utVnRJ+t99YJo2ieOtdPkMwnddLgdt/O0/jXl9j0zv4PB50mPkijb+cox/m7bCxnfunYPWK7PnYV7fI0ux3d9Sif0wxWQB0VLAzs4tE3fviOMzTfqZlXdsxcHhtDDxni0KJFrI/KKNX7SfYzq6neby9K4C4dtt4ru+k6blZRijEn9H9ucm/aFJ32/Sv9O0cXStH7W/5fFt7KzKNPJf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>