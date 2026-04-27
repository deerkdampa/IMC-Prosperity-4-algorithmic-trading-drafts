## Round 3: Options Scalping

### Options

In Round 3, the competition introduced a new class of assets: Volcanic Rock Vouchers — effectively call options on a new underlying product, Volcanic Rock (VR).
There were five vouchers available, each with a distinct strike price — 9500, 9750, 10000, 10250, and 10500 — while the underlying Volcanic Rock itself traded around 10,000.
Each voucher granted the right (but not the obligation) to buy Volcanic Rock at the specified strike at expiry.
Importantly, options had limited time to live: starting with seven days until expiry in the first round, decreasing to just two days by the final round.
Without basic familiarity with options theory, particularly concepts like implied volatility and option pricing models, it would have been difficult to design strong strategies for this product.

#### IV Scalping

Our first major insight came from following hints dropped in the competition wiki, suggesting the construction of a volatility smile: plotting implied volatility (IV) against moneyness.
By fitting a parabola to the observed IVs across strikes and then detrending (subtracting the fitted curve from observed values), we could isolate IV deviations that were no longer dependent on moneyness.

<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 6a: Volatility Smile</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/49be51d8-4335-4831-adb0-e811e50ce450"
       alt="Volatility smile scatter plot"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>This scatter plot visualizes implied volatility (<em>v<sub>t</sub></em>) versus moneyness (<em>m<sub>t</sub></em>) across different strikes.  
  A fitted parabola is shown to filter out noise, producing <em>v̂<sub>t</sub></em> — the "fair" implied volatility given <em>m<sub>t</sub></em>.  
  Outliers at the bottom left were disregarded, as they corresponded to historical points where extrinsic value was too low.</em>
</td>
</tr>
</table>

<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 6b: IV Deviations over Time</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/6aa60cbe-029d-49ed-b883-95c9b7e177df"
       alt="IV deviations plot"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>This plot shows the time series of implied volatility deviations (<em>v<sub>t</sub> - v̂<sub>t</sub></em>) derived from Figure 6a, highlighting short-term patterns in relative option mispricing.</em>
</td>
</tr>
</table>


To convert these into actionable trading signals, we input the volatility-smile-implied IV into a Black-Scholes model to calculate a theoretical fair price, then compared it to the actual market price to find price deviations.
Plots of these price deviations — especially for the 10,000 strike call early on — revealed sharp short-term fluctuations, indicating scalping opportunities.



<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 6c: Price Deviations over Time</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/ca6b1614-c6b2-4026-b41e-5af408fae69c"
       alt="Price deviations plot"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>This plot shows the same implied volatility deviations from Figure 6b, but transformed into price space using the Black-Scholes model, providing a more intuitive view of relative mispricings over time.</em>
</td>
</tr>
</table>


We initially focused on the 10,000 strike, but dynamically expanded to include other strikes as the underlying shifted and expiry approached, tracking profitability thresholds in real time to decide when to activate scalping on new options.
Statistical analysis, specifically testing for 1-lag negative autocorrelation in returns, strongly supported the existence of exploitable short-term inefficiencies across several strikes, further validating this approach.



<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 7a: 10k Call Price Fluctuations</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/756d8dab-e76a-4ea6-a986-03d15d5f3bc3"
       alt="10k call price fluctuations"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>This plot shows short-term price fluctuations of the 10,000 strike call option.  
  The orange indicator represents the theoretical call price, calculated using the implied volatility from the fitted parabola (<em>v̂<sub>t</sub></em>) at the option’s current moneyness.</em>
</td>
</tr>
</table>


<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 7b: 10k Call Price Fluctuations (Normalized)</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/da9ae65a-b0a4-49e0-b072-b9abdbffad68"
       alt="Normalized 10k call price fluctuations"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>This plot shows the same 10,000 strike call fluctuations as in Figure 7a,  
  but with prices normalized by the theoretical value (orange indicator) to make deviations more stationary and visually clear.</em>
</td>
</tr>
</table>

#### Gamma Scalping
The expected value from gamma scalping was consistently positive, as the gains from underlying price movements outweighed the losses from time decay. This made buying options and rehedging the resulting deltas from gamma exposure a relatively low-risk way to generate profit. However, while the approach was stable and mostly safe, the absolute returns were limited. It was a reliable source of small gains, but ultimately, we had a higher risk appetite and wanted better returns.

#### Mean Reversion Trading

Simultaneously, analysis of the underlying Volcanic Rock asset suggested potential mean reversion behavior.
Return distributions and price dynamics resembled Squid Ink, which was explicitly designed to mean revert in Round 1.
Autocorrelation analysis of Volcanic Rock returns, compared against randomized normal samples, confirmed significant short-term negative autocorrelation at various horizons, although caution was needed given the presence of large jumps and non-normal return distributions.
Given the limited historical data available (only three days), and uncertainty about future dynamics, fully committing to mean reversion was considered too risky.
Instead, we implemented a lightweight mean reversion model: tracking a fast rolling Exponential Moving Average (EMA) and trading deviations from this EMA using fixed thresholds — without scaling by rolling volatility — to keep the model simple and robust.


<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 8: Autocorrelation Plot for Volcanic Rock</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/ae8f01cf-9cd1-4867-ba26-dfcae781ccff"
       alt="Autocorrelation plot for Volcanic Rock"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>Rolling autocorrelation of Volcanic Rock returns compared to autocorrelations from purely random sequences,  
  suggesting statistically significant mean reversion behavior in the underlying.</em>
</td>
</tr>
</table>

#### Final Strategy

In the end, we deployed a hybrid strategy combining both alpha sources.
Our core focus remained on IV scalping, dynamically expanding across strikes and adjusting thresholds based on evolving conditions, while simultaneously maintaining a moderate mean reversion position — both in the underlying Volcanic Rock and in the deepest in-the-money call (the highest delta option available).
Importantly, this was not a delta hedge in the traditional sense: the delta exposure from scalping was relatively small, and explicit delta hedging would have been prohibitively expensive bid-ask spreads. It was rather a hedge against bad luck. Because this hybrid model was designed to minimize maximum regret across different possible market outcomes: it protected us if strong mean reversion materialized (even if other teams aggressively leveraged mean reversion delta exposure across multiple options and therefore outperforming us in a relative sense), while keeping our core reliance on the more stable, theory-supported scalping opportunities.

Someone could have arrived at a similar strategy without deep prior options expertise by carefully observing the market dynamics.
Even without constructing a full volatility smile, simply watching option prices — particularly the 10,000 strike — would reveal clear short-term mean-reversion patterns and negative autocorrelation in returns.
On the underlying asset side, basic return autocorrelation analysis and exploratory plotting would hint at mean reversion tendencies.
Thus, while a strong theoretical background was helpful, a combination of attentive observation, critical data analysis, and statistical common sense would have led to very similar conclusions.

In terms of results, IV scalping contributed approximately 100,000 - 150,000 SeaShells per round, providing strong and stable profits across all rounds. Mean reversion trading was much more volatile, delivering around 100,000, -50,000, and -10,000 SeaShells across the rounds respectively. Despite the swings, our hybrid approach allowed us to achieve consistently positive net results while keeping downside risks manageable.

Note: After the fourth round, where the mean reversion strategy resulted in a loss of approximately 50,000 SeaShells, we reassessed its validity. Although we no longer found strong empirical evidence to justify continuing with mean reversion purely on standalone expected value grounds, we knew that several top teams were actively only trading mean reversion strategies. So we figured, if they wouldn't find the IV scalping strategy, they might just accept the coinflip and go all in mean reversion because otherwise they would surely get overtaken by everyone. Facing a 200,000 SeaShell lead at that point, we made a calculated decision to maintain some mean reversion exposure — not because we believed it was necessarily positive EV anymore, but to hedge relatively against the teams still pursuing that angle. We estimated the 95% Value at Risk (VaR) of the mean reversion component to be around 50,000 SeaShells — only about 25% of our lead — leaving us with sufficient margin even if the strategy failed again. Under our assumptions, keeping this balanced exposure maximized our likelihood of securing first place by minimizing relative downside risk while preserving our core scalping profits. This turned out to be the right decision. Although, in the last round some random team very unnaturally jumped from 100+ rank to 1st place, we could keep a healthy distance to all teams that were previously close behind us. 