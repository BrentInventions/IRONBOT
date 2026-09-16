# Recon Sniper

Standalone event-driven MNQ engine for Willie. **Not TradeChampion.** Own HUD, own NinjaTrader bridge on port **5564**.

Chart overlay is **lines only** (gold entry, red stop, green target). No price/bias text on the chart.

## What it does

- Watches live ticks, not candle-close entries
- Trades only when the tape is **TRENDING** (or high-vol trend). Chop sits out
- Observe / Paper / Live from the Night Shell HUD
- HUD size control: **MNQ contracts** — 1 banks **$25**, 2 banks **$50**
- HUD **STOP** in points (default 20). Dollars scale with contract size
- After the bank is tagged it is a **floor**, not an exit. A **4.5-point trail** sits behind the tip and never gives the bank back
- Large **PNL** (session net, including open) and **BALANCE** (NinjaTrader equity) on the HUD. Balance shows **WAITING** until ReconSniperBridge heartbeats include cash/equity
- PNL LOG lists closed trades plus the live open row. Chart stays **lines only** (no Draw.Text)

## Willie PC install

1. Clone this repo
2. `py -3 -m pip install -r requirements.txt`
3. Copy `mark2/bridge/ReconSniperBridge.cs` into  
   `Documents\NinjaTrader 8\bin\Custom\Strategies\`
4. NinjaScript Editor → **F5**
5. Add **ReconSniperBridge** to the MNQ chart (Sim101 or live). Leave TradeChampion on **5560** alone
6. Double-click `START-RECON-SNIPER.bat`
7. Optional: double-click `CREATE-DESKTOP-SHORTCUT.bat` to put **Recon Sniper** on the Desktop

Default mode is **OBSERVE_ONLY** (simulated runner on the HUD, no NT orders). Switch to Paper or Live from Control.

## After pulling an update

1. Copy `mark2/bridge/ReconSniperBridge.cs` into `Documents\NinjaTrader 8\bin\Custom\Strategies\` (overwrite)
2. NinjaScript Editor → **F5** (needed for NT balance to flow)
3. Restart `START-RECON-SNIPER.bat`

## Safety

- Does not import ImpulseRuntime / TradeChampion / port 5560
- Flatten from the HUD cuts the local (and live) position
