# Recon Sniper (Mark II) — current trading spec for revision

**Paste this first:** You are revising **Recon Sniper**, also called **Mark II**. It is a tick-driven MNQ event engine that sits out chop, enters on classified tape events, and manages winners as **bank-then-runner**: print **$25/contract**, **do not flatten**, move the stop to that floor, then trail **4.5 points** behind the extreme so the bank is never given back. Default path is **LIVE NinjaTrader orders** (Sim101 or funded, whichever account the strategy is on). DISARM only blocks new entries. Observe/Paper are **not** the product trading path. Chart overlay is **horizontal lines only** (gold entry, red stop, green bank floor) — no `Draw.Text`. Below is production behavior as of the code. Propose revisions. Do not invent a hard take-profit at the bank. Do not treat STOP 20pt as a $20 profit target.

---

## 1. What this is

1. **Recon Sniper** = the **Mark II event engine** (`mark2/`). Standalone product. Own Night Shell HUD. Own NinjaTrader strategy **ReconSniperBridge** on TCP port **5564**.
2. It is **not** ImpulseRuntime Dual / TradeChampion. Dual is a different product on **TradeChampionBridge :5560**.
3. It is **not** the Mark I HUD. Mark I (Neuro / Stark HUD) can **host the same Mark II engine** and send orders through **TradeChampionBridge :5560**. Same entry/exit math; different window, port, and product name (`MARK I` / `MarkI`).
4. Standalone Recon Sniper: `PRODUCT_NAME=RECON SNIPER`, `PRODUCT_ENGINE=ReconSniper`, kickers `RECON LONG` / `RECON SHORT`, `BRIDGE_NAME=ReconSniperBridge`, port **5564**.
5. Engine does not import ImpulseRuntime, TradeChampion, or port 5560.

---

## 2. Market / contract

1. Instrument: **MNQ** (Micro Nasdaq).
2. Point value: **$2 per point** (`POINT_VALUE = 2.0`).
3. Tick size: **0.25** (`TICK_SIZE = 0.25`).
4. Qty: `CONTRACTS` default **1**, clamped to `[1, MAX_CONTRACTS]`. `MAX_CONTRACTS` engine default **10**.
5. NinjaTrader bridge property `MaxContracts` defaults to **1**. Live fill qty is `min(engine qty, bridge MaxContracts)`. If the HUD is at 2 and NT MaxContracts is 1, NT sends 1.
6. Bank dollars scale with qty: 1 contract banks **$25**, 2 banks **$50**. Bank **points** stay **12.5** (`$25 / $2`).
7. Stop dollars scale with qty: 20 pt × $2 × 1 = **$40**; × 2 = **$80**.
8. Recorded PnL subtracts round-turn fees **$2.48 per contract**. The **$25 bank is gross** (12.5 pts × $2), not net of fees.
9. Daily risk cap: `MAX_LOSS_DOLLARS = 600`. Blocks a new entry if that trade’s stop risk in dollars (`stop_points × $2 × qty`) exceeds $600, or if session `daily_pnl <= -$600`.
10. Anti-spam: **4 orders in 20 seconds** trips an internal kill; further entries `REJECT_RISK` until process restart.

---

## 3. Execution model

1. **Tick-driven.** Entries and exits evaluate on each incoming tick. Candle close is **not** an entry event.
2. Completed 1-minute bars update **slow context only** (trend, ATR, EMA, VWAP, structure, regime). Context refresh throttle: **5.0 s** (`CONTEXT_REFRESH_SEC`).
3. On connect, the engine requests **200 seed bars**. Trading is suppressed until **15 completed bars** exist (`IDLE` until then). Trend classifier needs **8** bars (5m groups if ≥8 five-minute bars exist, else 1m).
4. Bridge: `Calculate = OnEachTick`, `StreamTicks = true`, tick throttle **50 ms**, heartbeat **1 s** (account cash/equity/position).
5. **LIVE** (`MODE = LIVE`, the default): engine sends JSON-line TCP to ReconSniperBridge:
   - `"type":"order","action":"BUY"|"SELL"` with `quantity` and `stop_loss` (price)
   - `"type":"order","action":"CLOSE"` to flatten
   - `"type":"set_stop","stop":<price>` on every stop ratchet (reason `"trail"`)
   - `"type":"levels"` for chart lines
6. NT: `EnterLong` / `EnterShort` with signal names `ReconLong` / `ReconShort`. Flatten via `ExitLong`/`ExitShort` (`ReconFlat`). `SetStopLoss(..., CalculationMode.Price, stopPx)`. Duplicate entries blocked if already in a position, `entriesLocked`, or `closePending`.
7. **Chart — lines only.** Gold `ReconEntry`, orange-red `ReconStop`, lime-green `ReconTarget` (the **bank floor price**, not a take-profit). **No `Draw.Text` / `Draw.TextFixed`.** Willie chart stays lines-only. Do not add price, bias, STOP/ENTRY/TARGET labels, or “when it trades” text.
8. Green line is `paper.target` = lock price, set at entry and **not moved**. Red line is `paper.stop`, which moves: initial stop → bank floor → 4.5 pt trail.
9. HUD ARM/DISARM is `MARK2_ENABLED`, **not** a mode switch. Flatten from HUD is `HUD_FLAT` (local + LIVE CLOSE).
10. Code still contains `OBSERVE_ONLY` and `PAPER_TRADE` in the execution enum. The Night Shell HUD **removed** Observe/Paper. Chip reads **NT LIVE** or **PAUSED**. Do not treat those leftover modes as the shipping path.

---

## 4. When it sits out

`REQUIRE_TRENDING = true`. An event is rejected `REJECT_REGIME` unless **all** of:

- `trend_regime` is **`TRENDING` or `HIGH_VOL`**
- side LONG ⇒ `longs_allowed`; side SHORT ⇒ `shorts_allowed`

`longs_allowed` / `shorts_allowed` require that same tradeable regime **and** bias **BULLISH** / **BEARISH**. **NEUTRAL bias sits out** even if the regime is TRENDING.

### Regime classifier (`classify_trend`)

Uses 5-minute bars when ≥8 complete 5m groups exist, else 1m. ATR and efficiency on that series:

| Condition (first match) | Regime | Trades? |
|---|---|---|
| ATR < **2.0** | `QUIET` | No |
| ATR ≥ **40.0** | `CHAOTIC` | No |
| directional efficiency < **0.22** | `CHOPPY` | No |
| ATR > **18.0** | `HIGH_VOL` | Yes, if bias matches |
| else | `TRENDING` | Yes, if bias matches |

Bias: price vs EMA(20) **and** EMA slope. Efficiency = `|net close change| / path` over ~8 bars.

Sit-out regimes: **CHOPPY, QUIET, CHAOTIC**. HUD shows `NO TRADE` / wait for TRENDING.

Session labels (`NY_OPEN`, `NY_MID`, `NY_POWER`, `PREMARKET`, `ASIA_OVERNIGHT`, `AFTER_HOURS`) are **display/context only**. They are **not** entry gates.

### Other hard gates (before ARM)

Evaluated on the event’s side. Failures do not enter.

| Gate | Rule | Reject |
|---|---|---|
| Volume | `relative_volume >= 0.45` **or** `volume <= 0` (zero volume **bypasses**) | `REJECT_LOW_VOLUME` |
| Structure | LONG blocked if structure `LH_LL`; SHORT blocked if `HH_HL`. `MIXED` / `HH` / `LL` allowed | `REJECT_STRUCTURE` |
| Extension | side extension risk ≥ **72** (`MAX_EXTENSION_RISK`) | `REJECT_EXTENSION` |
| Confidence | side confidence ≥ **58** (`LONG/SHORT_CONFIDENCE_THRESHOLD`) | `REJECT_LOW_CONFIDENCE` |
| Confidence velocity | side conf-velocity ≥ **0.25**; if velocity < 0 → fading | `REJECT_LOW_VELOCITY` or `REJECT_CONFIDENCE_FADING` |
| Opportunity | side opportunity ≥ **52** | `REJECT_LOW_OPPORTUNITY` |
| Direction conflict | both long and short confidence > 50 **and** `|L−S| < 8` | `REJECT_DIRECTION_CONFLICT` |
| Duplicate | event already taken/logged, or weaker replacement | `REJECT_DUPLICATE_EVENT` |
| Cooldown | **2.0 s** after an exit (`begin_cooldown(..., 2.0)`) | `REJECT_COOLDOWN` |
| Disarm / disabled | `MARK2_ENABLED = false` | no new entries (`DISABLED` / `REJECT_MODE`) |
| Risk | kill, disconnected, pending/open, qty > max, $600 cap, 4/20s | `REJECT_RISK` |

Need **15 completed bars** or the tick path returns without evaluating.

---

## 5. Entry

### 5.1 Event types (all enabled)

Detector picks **one** type: highest-scoring candidate that fires. Side = whichever side has **higher opportunity** (not confidence). If both confidence < **40** and opportunity < **45**, no event.

| Type | Fire condition |
|---|---|
| `VOLUME_EXPANSION` | `relative_volume >= 1.15` |
| `MOMENTUM_EXPANSION` | signed velocity > **0.4** |
| `IMPULSE` | `impulse_score >= 55` (`IMPULSE_MIN`) |
| `VOLATILITY_EXPANSION` | `volatility_state == "expanding"` |
| `BREAKOUT` | LONG: price > swing high; SHORT: price < swing low |
| `PULLBACK_CONTINUATION` | LONG: bias BULLISH/BULL, price ≥ forming open, `ema_distance_atr <= 0.35`; SHORT: BEARISH/BEAR, price ≤ forming open, `ema_distance_atr >= -0.35` |

Same event continues if same direction and (same forming-bar time **or** same type within **45 s**). Event **ends** (`CONFIDENCE_RESET`) after **4** consecutive ticks with confidence < **42** (`EVENT_RESET_THRESHOLD`) **or** `|velocity| < 0.18`. A stronger independent event can supersede a weak untraded one; a taken/logged event blocks duplicates.

### 5.2 Scores

**Confidence (0–100), EMA-smoothed** (`CONFIDENCE_SMOOTH_ALPHA = 0.35`). Velocity/accel over last **6** smoothed values. Weighted parts (then normalized):

| Weight key | Default |
|---|---|
| trend_alignment | 0.18 |
| momentum | 0.14 |
| impulse | 0.12 |
| velocity | 0.10 |
| trend_strength | 0.08 |
| relative_volume | 0.08 |
| volume_acceleration | 0.08 |
| acceleration | 0.08 |
| breakout_quality | 0.06 |
| structure | 0.04 |
| volatility_state | 0.02 |
| vwap_relationship | 0.02 |

Regime contribution inside confidence: TRENDING **88**, HIGH_VOL **70**, CHOPPY **18**, else **15**.

**Opportunity (0–100)** is separate: z-scores of velocity, relative volume, volume acceleration, impulse, and confidence-velocity vs a rolling baseline (`OPPORTUNITY_BASELINE_BARS = 20`, hist length ×4). Unusual activity **against** the side is multiplied by **0.35**. Persistent bullish tape is not supposed to keep firing.

**Extension risk (0–100)** measures **this impulse’s** displacement from event start (else forming open), not session distance from VWAP. Blocks at **≥ 72**.

**Fast features (tick):** velocity = price change over **2.0 s**; acceleration over **1.0 s**; relative volume = forming-bar volume / completed average (`VOLUME_LOOKBACK = 20`); impulse from forming range/body/velocity/volume (never unfinished-candle final H/L). Tick buffer **80**.

**Trade health (0–100)** is computed in-trade and shown on the HUD. **`manage_paper` currently ignores health, ATR, and hold time.** Health does not exit.

### 5.3 State machine

`IDLE → WATCHING → EVENT_DETECTED → MOMENTUM_BUILDING → TRADE_ARMED → EXECUTE → TRADE_INITIAL`

Then in trade: `TRADE_PROFITABLE` (bank tagged) → `RUNNER_MANAGEMENT` (MFE past bank) → `EXIT` → `COOLDOWN` (2 s) → `WATCHING`.

Arm requires **two consecutive ticks** that pass every gate (`_building_ticks < 2` stays in `MOMENTUM_BUILDING`). First passing tick does **not** fire.

Fill: marketable BUY/SELL at the tick price; initial stop = entry ± `INITIAL_STOP_POINTS`; target field = **bank lock price** (not a flatten price).

---

## 6. Risk / stop

**Do not confuse STOP 20 pt with bank $25.**

1. `INITIAL_STOP_POINTS` is the **initial protective stop in points**.
2. HUD control is labeled STOP in points. Placeholder and code default: **20 pt**.
   - 20 pt × $2/pt = **$40 per contract** of stop risk (qty 1).
   - This is **not** a $20 profit target.
3. `initial_stop()` **ignores ATR**. Distance is the configured point gap only. Clamp on HUD set: **[1.0, 80.0]** in 0.25 increments.
4. Live: that price is sent as `stop_loss` on the entry order, then updated with `set_stop` as the stop ratchets.
5. **File discrepancy:** `mark2/config.py` dataclass default is **20.0**. Night Shell HTML placeholder is **20 / $40**. Mark I persist (`jarvis_bot/mark_i_defaults.json`) is **20.0**. **`mark2/mark2_defaults.json` currently stores `INITIAL_STOP_POINTS: 25.0`.** Standalone `load_config()` reads that JSON, so a fresh Recon Sniper process may start at **25 pt ($50)** until the HUD STOP control is changed. Treat **20 pt as the intended HUD default**; call out 25 if you rely on the JSON file as shipped.
6. While in trade and **before** the bank is tagged, changing HUD STOP can widen/tighten the live stop (engine will not move the stop through the market).

---

## 7. Bank then runner (critical)

This is the whole exit design. Getting it wrong produces a hard-TP bot.

### Bank

1. `BANK_DOLLARS_PER_CONTRACT = 25.0`.
2. `bank_points = 25 / 2 = 12.5` points.
3. `lock_price`: LONG `entry + 12.5`; SHORT `entry - 12.5`.
4. `initial_target()` returns **that lock price**. The green chart line **is the bank floor**, not a take-profit.
5. When price **tags** the lock (`price >= target` long / `<= target` short):
   - `target_touched = True`
   - stop is moved to **lock**
   - engine returns **`done=False`** — **no CLOSE, no flatten**
   - state → `TRADE_PROFITABLE`
6. **Sitting on $25 does not flatten.** Tests hold the lock price for many ticks; exit stays false; stop stays at lock.
7. A floor break requires price **one full tick through** the lock (`lock ± 0.25`), not equality with the lock.

### Trail

1. `RUNNER_TRAIL_POINTS = 4.5`.
2. Runner flag: `mfe >= bank_points + tick` → MFE ≥ **12.75** pts.
3. After bank: `stop = max(lock, peak − 4.5)` (long) or `min(lock, peak + 4.5)` (short). The stop **never goes back through the bank**.
4. The 4.5-pt trail only **leaves** the floor once the extreme is **4.5 pts beyond the lock** (about **+17.0 pts / ~$34** from entry on a long before the red line leaves the green line). Until then the stop sits on the bank even if `runner` is already true.
5. `TARGET_MODE`, `TRAIL_MODE`, `VOLATILITY_TRAIL_MULTIPLIER`, `INITIAL_TARGET_ATR_MULT`, `RUNNER_THRESHOLD`, `SCRATCH_*` are **config leftovers**. `manage_paper` does **not** read them. Changing `TARGET_MODE` to `HARD` in JSON **does not** flatten at the bank.

### Exit reasons (engine)

| Reason | Meaning |
|---|---|
| `STOP` | Hit the **initial** protective stop before the bank |
| `FLOOR` | After bank, broke the bank floor (and runner flag still false) |
| `TRAIL` | After bank, hit the trailed stop (or floor break after runner flag is true) |
| `HUD_FLAT` | Operator flatten |
| `SHUTDOWN` | Host stop (Mark I) |

A fill around **~$20.02** is a **hard take-profit flatten from a different product** (Impulse/TradeChampion-style). **This engine does not flatten at $20 or $25.** If you see that fill on Recon Sniper, it is a bug or the wrong strategy — not the 4.5-pt trail.

### Worked numbers (1 MNQ, long, entry 20000)

- Initial stop: **19980** if STOP=20 pt ($40 risk).
- Green bank: **20012.50** ($25 / 12.5 pts). Tag it → stay in, stop → 20012.50.
- Sit at 20012.50 → **still in**.
- Peak 20020: trail candidate 20015.5, still `max(lock, trail)` = **20012.50**.
- Peak 20017+: stop starts following `peak − 4.5`, always ≥ 20012.50.
- Exit on stop/floor/trail only.

---

## 8. What ChatGPT must not break

1. **Willie chart: no text.** ReconSniperBridge draws three horizontal lines only. Do not add `Draw.Text` / `Draw.TextFixed`. Do not turn on TradeChampion `DrawChartTextLabels` (must stay `false` on Willie’s install). Horizontal level lines are fine.
2. **Do not flatten at the bank.** $25 is a floor. “Take profit at $25” is a regression.
3. **LIVE = real NT orders** on whatever account the chart strategy is running (Sim101 or funded). `MODE=LIVE` is the default. DISARM (`MARK2_ENABLED=false`) = **no new entries**, still LIVE, still manages/exits an open trade, still `set_stop` / CLOSE.
4. **Do not reintroduce Observe as the default trading path.** Observe/Paper were removed from the HUD. Leftover enum values must not become the shipping default.
5. **Do not mix STOP 20 pt with bank $25.** Stop is loss distance. Bank is the runner floor.
6. **Do not make candle-close the entry clock.** Seed bars are context; ticks are the trigger.
7. **Do not point Recon Sniper at port 5560** or import ImpulseRuntime. Standalone product is **5564**.
8. **Do not treat unused knobs as live.** `TARGET_MODE=CHECKPOINT`, `TRAIL_MODE=ATR_ADAPTIVE`, scratch, ATR target/trail multipliers, `MOMENTUM_Z` / `VOLUME_Z` / `VELOCITY_Z` are **not wired** into `manage_paper` or event classify. Tuning them changes JSON only unless you also wire them.
9. Keep Explorer/NT recovery and Dual/Impulse out of this product. This brief is Recon Sniper / Mark II only.

---

## 9. Knobs (real keys + current defaults)

From `mark2/config.py` + `mark2/mark2_defaults.json`. JSON overrides the dataclass when the process loads defaults.

### Live (wired)

| Key | JSON / dataclass | What it actually does |
|---|---|---|
| `MODE` | `LIVE` | LIVE sends NT orders. Invalid → LIVE |
| `MARK2_ENABLED` | `true` | ARM/DISARM. False = no new entries |
| `CONTRACTS` | `1` | Qty, clamped to max |
| `MAX_CONTRACTS` | `10` | Engine cap (NT bridge cap is separate, default 1) |
| `BANK_DOLLARS_PER_CONTRACT` | `25.0` | Floor dollars/contract → 12.5 pts |
| `RUNNER_TRAIL_POINTS` | `4.5` | Trail distance after bank; never through floor |
| `INITIAL_STOP_POINTS` | JSON **25.0** / code+HUD **20.0** | Initial stop **points** (see §6) |
| `LONG_CONFIDENCE_THRESHOLD` | `58.0` | Min long confidence |
| `SHORT_CONFIDENCE_THRESHOLD` | `58.0` | Min short confidence |
| `MIN_CONFIDENCE_VELOCITY` | `0.25` | Min confidence slope to arm |
| `LONG_OPPORTUNITY_THRESHOLD` | `52.0` | Min long opportunity |
| `SHORT_OPPORTUNITY_THRESHOLD` | `52.0` | Min short opportunity |
| `MAX_EXTENSION_RISK` | `72.0` | Block chase |
| `EVENT_RESET_THRESHOLD` | `42.0` | Event fade if conf below this |
| `EVENT_END_STREAK` | `4` | Fade ticks to end event |
| `REQUIRE_TRENDING` | `true` | Enforce TRENDING/HIGH_VOL + bias |
| `IMPULSE_MIN` | `55.0` | Impulse event fire |
| `VELOCITY_WINDOW_SEC` | `2.0` | Price velocity window |
| `ACCEL_WINDOW_SEC` | `1.0` | Accel window |
| `CONFIDENCE_SMOOTH_ALPHA` | `0.35` | Confidence EMA |
| `CONFIDENCE_DERIV_WINDOW` | `6` | Conf velocity lookback |
| `OPPORTUNITY_BASELINE_BARS` | `20` | Opportunity z-score baseline |
| `TICK_BUFFER` | `80` | Fast tick deque |
| `CONTEXT_REFRESH_SEC` | `5.0` | Slow context throttle |
| `ATR_PERIOD` | `14` | ATR / vol-state |
| `EMA_PERIOD` | `20` | Trend EMA |
| `VWAP_LOOKBACK` | `80` | VWAP window |
| `VOLUME_LOOKBACK` | `20` | Rel-volume average |
| `MAX_LOSS_DOLLARS` | `600.0` | Per-trade stop $ and session floor |
| `POINT_VALUE` | `2.0` | MNQ $ / pt |
| `TICK_SIZE` | `0.25` | MNQ tick |
| `BRIDGE_PORT` | `5564` | ReconSniperBridge (Mark I persist uses 5560) |
| `events.*` | all `true` | Per-type detector toggles |
| `weights.*` | see §5.2 | Confidence mix (normalized) |

Hardcoded (not config keys): volume gate **0.45**; event volume **1.15**; momentum vel **0.4**; event fade `|vel|<0.18`; duplicate window **45 s**; arm **2 ticks**; post-exit cooldown **2.0 s**; direction-conflict gap **8**; order-spam **4 / 20 s**; fees **$2.48**; regime ATR **2 / 18 / 40**; efficiency **0.22**; pullback EMA distance **0.35**; classify floor conf **40** / opp **45**; floor break **1 tick**.

### Present in JSON but **not used** by current exit/entry classify

| Key | Value | Status |
|---|---|---|
| `TARGET_MODE` | `CHECKPOINT` | Ignored by `manage_paper` |
| `TRAIL_MODE` | `ATR_ADAPTIVE` | Ignored; trail is fixed 4.5 pt |
| `VOLATILITY_TRAIL_MULTIPLIER` | `1.6` | Ignored |
| `INITIAL_TARGET_ATR_MULT` | `1.1` | Ignored; target = bank lock |
| `RUNNER_THRESHOLD` | `70.0` | Ignored; runner = MFE vs bank |
| `SCRATCH_THRESHOLD` | `28.0` | Ignored |
| `SCRATCH_MAX_SECONDS` | `8.0` | Ignored |
| `MOMENTUM_Z` | `1.4` | Unused |
| `VOLUME_Z` | `1.3` | Unused |
| `VELOCITY_Z` | `1.4` | Unused |

If you propose using these, say so explicitly as **new wiring**, not a numeric tweak.

---

## 10. Open questions for revision

- **Bank $25 vs $20.** Floor is $25 / 12.5 pts today. A ~$20 flatten is a different (wrong) behavior. If the goal is a smaller bank, change `BANK_DOLLARS_PER_CONTRACT` and keep floor-then-trail — do not add a hard TP.
- **Trail 4.5.** Stop does not leave the floor until ~4.5 pts **past** the bank (~17 pts MFE). Is 4.5 too wide, too tight, or should trail start immediately at the floor?
- **Stop 20 vs JSON 25.** Intended HUD default 20 pt ($40). JSON file currently 25 pt. Which should ship? ATR-based stop vs fixed points?
- **Regime sit-out.** CHOPPY/QUIET/CHAOTIC + NEUTRAL are blocked. ATR cuts 2 / 18 / 40 and efficiency 0.22 — too strict (misses) or too loose (chop entries)? Should HIGH_VOL trade?
- **Two-tick arm delay** and **58 / 52 / 0.25 / 72** gates — too conservative vs too spammy?
- **Volume 0.45** with **volume==0 bypass** — accidental hole?
- **Health / scratch unused.** In-trade health is displayed but never exits. Wire a failed-event scratch, or delete the knobs?
- **Qty vs NT MaxContracts=1.** HUD can show 2–10 while the bridge still caps at 1 unless the operator raises it.
- **Fees.** Bank is gross $25; ledger nets $2.48. Should the floor be net?
- **Event taxonomy.** Six types, winner-take-all. Drop pullback? Require volume on momentum? One-shot per event is already enforced.

---

### Revision rules for the other model

Propose concrete numeric and/or logic changes. For each change: what breaks if we keep today’s behavior, what the new rule is, and how it interacts with **bank-as-floor**. Do not replace the runner with a hard target unless you explicitly argue for abandoning this product’s exit design. Keep chart lines-only. Keep LIVE as the order path. Keep DISARM ≠ flatten.
