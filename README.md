# IRONBOT

Standalone MNQ engine for Willie. Night Shell HUD, **9/20/50** and **8TCM** as two ENTRY / EXIT master switches. Own NinjaTrader bridge on port **5564**. Not TradeChampion.

NT chart overlay is **lines only** (gold entry, red stop, green target, purple trail, EMA lines). No price / STOP / ENTRY / TARGET words on the chart.

## Willie PC install

```bat
git clone https://github.com/BrentInventions/IRONBOT.git
cd IRONBOT
py -3 -m pip install -r requirements.txt
```

1. Copy `mark2/bridge/ReconSniperBridge.cs` into  
   `Documents\NinjaTrader 8\bin\Custom\Strategies\`
2. NinjaScript Editor → **F5**
3. Add **ReconSniperBridge** to the MNQ chart (Sim101 or live). Leave TradeChampion on **5560** alone
4. Double-click `START-RECON-SNIPER.bat`
5. Optional: `CREATE-RECON-SNIPER-SHORTCUT.bat` puts **IRONBOT** on the Desktop

Default mode is **OBSERVE_ONLY**. Switch to Paper or Live from TRADE. ARM before it can fire.

ENTRY / EXIT has two toggles:

- **9/20/50 MODE** — EMA sniper preset. Off = that method does not enter
- **8TCM MODE** — 8-EMA continuation preset. Off = that method does not enter

Both can be on. Only one trade is open at a time.

## After pulling an update

```bat
git pull
```

1. Copy `mark2/bridge/ReconSniperBridge.cs` into `Documents\NinjaTrader 8\bin\Custom\Strategies\` (overwrite)
2. NinjaScript Editor → **F5**
3. Restart `START-RECON-SNIPER.bat`

## Safety

- Does not import ImpulseRuntime / TradeChampion / port 5560
- Flatten from the HUD cuts the local (and live) position
- Chart stays lines only
