
## Round 5: Trader IDs
  
In Round 5, no new products were introduced.
The main change was that historical trader IDs were made public, allowing teams to directly identify which trades were executed by specific bots.
For us, this did not fundamentally alter our strategies, as we had already identified Olivia’s behavior early in the competition.
However, we took this opportunity to update our detection logic: instead of inferring Olivia’s trades indirectly by tracking running minimums and maximums, we now simply checked the trader ID directly.
This adjustment helped eliminate false positives, reduced the risk of missing genuine Olivia trades, and saved a few hundred SeaShells over the course of the round.
As with every previous round, we also re-optimized all relevant parameters based on the latest available data to ensure robustness going into the final evaluation.
This was the last round, and we had a sizeable lead to place 2 (~190k), so we decided to play it save, incase ETF spreads don't converge, by half-hedging the baskets. We also limited our mean reversion strategy to minimze risk.
