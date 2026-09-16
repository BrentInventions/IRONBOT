#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
using NinjaTrader.NinjaScript.Indicators;
#endregion

// Recon Sniper own bridge — do NOT use TradeChampionBridge / port 5560.
// Copy to Documents\NinjaTrader 8\bin\Custom\Strategies\ then F5.

namespace NinjaTrader.NinjaScript.Strategies
{
	public class ReconSniperBridge : Strategy
	{
		private const string BridgeVersion = "RS-0.2.18";
		private const string LongSignal = "ReconLong";
		private const string ShortSignal = "ReconShort";
		private const string FlatSignal = "ReconFlat";

		private TcpListener listener;
		private TcpClient client;
		private NetworkStream stream;
		private Thread listenerThread;
		private volatile bool running;
		private readonly object streamLock = new object();
		private readonly ConcurrentQueue<string> outbound = new ConcurrentQueue<string>();
		private readonly ConcurrentQueue<Action> mainActions = new ConcurrentQueue<Action>();
		private DateTime lastBarSent = DateTime.MinValue;
		private DateTime lastHtf60Sent = DateTime.MinValue;
		private DateTime lastHtf240Sent = DateTime.MinValue;
		private bool seedSent;
		private DateTime lastTickSentUtc = DateTime.MinValue;
		private double lastTickPriceSent;
		private System.Threading.Timer heartbeatTimer;
		private bool entriesLocked;
		private bool closePending;
		private string cachedAccountName = "";
		private double cachedCash;
		private double cachedNetLiq;
		private double cachedSodCash;
		private double cachedUnrealized;
		private double cachedRealized;
		private double cachedBuyingPower;
		private DateTime lastAccountCacheUtc = DateTime.MinValue;
		private volatile bool emaOverlayOn;
		private EMA ema9Ind;
		private EMA ema20Ind;
		private EMA ema50Ind;
		private EMA ema8M1;
		private EMA ema8H1;
		private EMA ema8H4;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = "Recon Sniper event-driven engine bridge. Port 5564. Independent of TradeChampion.";
				Name = "ReconSniperBridge";
				Calculate = Calculate.OnEachTick;
				IsExitOnSessionCloseStrategy = false;
				EntriesPerDirection = 1;
				EntryHandling = EntryHandling.UniqueEntries;
				RealtimeErrorHandling = RealtimeErrorHandling.IgnoreAllErrors;
				StopTargetHandling = StopTargetHandling.PerEntryExecution;
				BarsRequiredToTrade = 20;
				StartBehavior = StartBehavior.ImmediatelySubmit;
				TimeInForce = TimeInForce.Gtc;
				TraceOrders = true;
				IsOverlay = true;
				Port = 5564;
				// Must match HUD MAX_CONTRACTS (prop size). Existing chart instances
				// keep their saved value — set MaxContracts on the strategy properties.
				MaxContracts = 50;
				SeedBars = 400;
				TickThrottleMs = 50;
				StreamTicks = true;
				AddPlot(new Stroke(Brushes.Red, 4), PlotStyle.Line, "EMA9");
				AddPlot(new Stroke(Brushes.White, 4), PlotStyle.Line, "EMA20");
				AddPlot(new Stroke(Brushes.DodgerBlue, 4), PlotStyle.Line, "EMA50");
				AddPlot(new Stroke(Brushes.Orange, 4), PlotStyle.Line, "EMA8 1m");
				AddPlot(new Stroke(Brushes.Gold, 4), PlotStyle.Line, "EMA8 1H");
			}
			else if (State == State.Configure)
			{
				AddDataSeries(BarsPeriodType.Minute, 60);
				AddDataSeries(BarsPeriodType.Minute, 240);
			}
			else if (State == State.DataLoaded)
			{
				ema9Ind = EMA(Close, 9);
				ema20Ind = EMA(Close, 20);
				ema50Ind = EMA(Close, 50);
				ema8M1 = EMA(Close, 8);
				if (BarsArray != null && BarsArray.Length > 1)
					ema8H1 = EMA(BarsArray[1], 8);
				if (BarsArray != null && BarsArray.Length > 2)
					ema8H4 = EMA(BarsArray[2], 8);
				StartBridge();
				heartbeatTimer = new System.Threading.Timer(_ =>
				{
					if (!running) return;
					try
					{
						TriggerCustomEvent(o =>
						{
							DrainMain();
							SendHeartbeat();
						}, null);
					}
					catch { }
				}, null, 1000, 1000);
			}
			else if (State == State.Terminated)
			{
				running = false;
				try { heartbeatTimer?.Dispose(); } catch { }
				StopBridge();
			}
		}

		protected override void OnBarUpdate()
		{
			try { DrainMain(); } catch { }
			if (BarsInProgress != 0)
			{
				bool htfRt = State == State.Realtime;
				if (!htfRt && !seedSent)
					return;
				if (CurrentBar < 1)
					return;
				if (IsFirstTickOfBar)
				{
					DateTime closedHtf = Time[1];
					if (BarsInProgress == 1)
					{
						if (closedHtf != lastHtf60Sent)
						{
							lastHtf60Sent = closedHtf;
							SendHtfBar(1, 1, htfRt, false);
						}
					}
					else if (BarsInProgress == 2)
					{
						if (closedHtf != lastHtf240Sent)
						{
							lastHtf240Sent = closedHtf;
							SendHtfBar(2, 1, htfRt, false);
						}
					}
				}
				return;
			}
			try { PaintEmaPlots(); } catch { }
			if (CurrentBar < BarsRequiredToTrade)
				return;
			// Playback / rewind is Historical. After seed, still send bars so Python can trade.
			bool rt = State == State.Realtime;
			if (!rt && !seedSent)
				return;
			if (IsFirstTickOfBar && CurrentBar > 0)
			{
				DateTime closed = Time[1];
				if (closed != lastBarSent)
				{
					lastBarSent = closed;
					SendCompletedBar(1, rt);
					SendHeartbeat();
				}
			}
			if (StreamTicks)
				MaybeSendTick();
		}

		protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity,
			MarketPosition marketPosition, string orderId, DateTime time)
		{
			if (State != State.Realtime || execution == null || execution.Order == null)
				return;
			string name = execution.Order.Name ?? "";
			if (execution.Order.OrderState != OrderState.Filled)
				return;
			RefreshAccountCache();
			int pos = Position == null ? 0 : (int)Position.Quantity * (Position.MarketPosition == MarketPosition.Long ? 1 : Position.MarketPosition == MarketPosition.Short ? -1 : 0);
			Enqueue(string.Format(CultureInfo.InvariantCulture,
				"{{\"type\":\"fill\",\"price\":{0},\"quantity\":{1},\"position\":{2},\"order_name\":\"{3}\",\"time\":\"{4:O}\",\"realized_pnl\":{5},\"unrealized_pnl\":{6}}}\n",
				price, quantity, pos, name.Replace("\"", ""), time, cachedRealized, cachedUnrealized));
			if (name == FlatSignal || name.IndexOf("Stop loss", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				closePending = false;
				entriesLocked = false;
			}
		}

		private void MaybeSendTick()
		{
			try
			{
				double last = Close[0];
				if (last <= 0) return;
				DateTime now = DateTime.UtcNow;
				double tick = TickSize > 0 ? TickSize : 0.25;
				if (lastTickPriceSent > 0 && Math.Abs(last - lastTickPriceSent) < tick * 0.5
					&& (now - lastTickSentUtc).TotalMilliseconds < TickThrottleMs)
					return;
				lastTickSentUtc = now;
				lastTickPriceSent = last;
				Enqueue(string.Format(CultureInfo.InvariantCulture,
					"{{\"type\":\"tick\",\"realtime\":true,\"time\":\"{0:O}\",\"bar_time\":\"{1:O}\",\"last\":{2},\"open\":{3},\"high\":{4},\"low\":{5},\"volume\":{6}}}\n",
					now, Time[0], last, Open[0], High[0], Low[0], (long)Volume[0]));
			}
			catch { }
		}

		private void SendCompletedBar(int barsAgo, bool realtime)
		{
			Enqueue(string.Format(CultureInfo.InvariantCulture,
				"{{\"type\":\"bar\",\"realtime\":{0},\"time\":\"{1:O}\",\"open\":{2},\"high\":{3},\"low\":{4},\"close\":{5},\"volume\":{6}}}\n",
				realtime ? "true" : "false", Time[barsAgo], Open[barsAgo], High[barsAgo], Low[barsAgo], Close[barsAgo], Volume[barsAgo]));
		}

		private void SendHtfBar(int bip, int barsAgo, bool realtime, bool seed)
		{
			if (bip <= 0 || BarsArray == null || bip >= BarsArray.Length)
				return;
			if (CurrentBars == null || CurrentBars[bip] < barsAgo)
				return;
			int minutes = 60;
			try { minutes = BarsPeriods[bip].Value; } catch { minutes = bip == 2 ? 240 : 60; }
			Enqueue(string.Format(CultureInfo.InvariantCulture,
				"{{\"type\":\"{0}\",\"timeframe\":{1},\"realtime\":{2},\"seed\":{3},\"time\":\"{4:O}\",\"open\":{5},\"high\":{6},\"low\":{7},\"close\":{8},\"volume\":{9}}}\n",
				seed ? "seed_bar_htf" : "bar_htf",
				minutes,
				realtime ? "true" : "false",
				seed ? "true" : "false",
				Times[bip][barsAgo], Opens[bip][barsAgo], Highs[bip][barsAgo], Lows[bip][barsAgo], Closes[bip][barsAgo], Volumes[bip][barsAgo]));
		}

		private static double FiniteOrZero(double v)
		{
			return double.IsNaN(v) || double.IsInfinity(v) ? 0.0 : v;
		}

		private double ReadAccountValue(AccountItem item)
		{
			try
			{
				if (Account == null)
					return 0;
				return Account.Get(item, Currency.UsDollar);
			}
			catch
			{
				return 0;
			}
		}

		private static string EscapeJson(string s)
		{
			if (string.IsNullOrEmpty(s)) return "";
			return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
		}

		private void RefreshAccountCache()
		{
			if ((DateTime.UtcNow - lastAccountCacheUtc).TotalMilliseconds < 750)
				return;
			lastAccountCacheUtc = DateTime.UtcNow;
			try
			{
				double refPx = 0;
				try { if (CurrentBar >= 0) refPx = Close[0]; } catch { }
				cachedUnrealized = 0;
				if (Position != null && Position.MarketPosition != MarketPosition.Flat && refPx > 0)
					cachedUnrealized = Position.GetUnrealizedProfitLoss(PerformanceUnit.Currency, refPx);
			}
			catch { cachedUnrealized = 0; }
			cachedRealized = FiniteOrZero(ReadAccountValue(AccountItem.RealizedProfitLoss));
			cachedCash = FiniteOrZero(ReadAccountValue(AccountItem.CashValue));
			cachedNetLiq = FiniteOrZero(ReadAccountValue(AccountItem.NetLiquidation));
			cachedSodCash = FiniteOrZero(ReadAccountValue(AccountItem.SodCashValue));
			if (cachedCash == 0 && cachedSodCash > 0) cachedCash = cachedSodCash;
			if (cachedNetLiq == 0 && cachedCash > 0) cachedNetLiq = cachedCash + cachedUnrealized;
			try { cachedAccountName = Account != null ? Account.Name : ""; } catch { cachedAccountName = ""; }
			cachedBuyingPower = FiniteOrZero(ReadAccountValue(AccountItem.BuyingPower));
			cachedUnrealized = FiniteOrZero(cachedUnrealized);
		}

		private void SendHeartbeat()
		{
			RefreshAccountCache();
			int pos = 0;
			if (Position != null)
			{
				if (Position.MarketPosition == MarketPosition.Long) pos = (int)Position.Quantity;
				else if (Position.MarketPosition == MarketPosition.Short) pos = -(int)Position.Quantity;
			}
			double last = 0;
			try { if (CurrentBar >= 0) last = Close[0]; } catch { }
			double pointValue = 2.0;
			string instrument = "";
			string symbol = "";
			try
			{
				if (Instrument != null)
				{
					instrument = Instrument.FullName ?? "";
					if (Instrument.MasterInstrument != null)
					{
						pointValue = Instrument.MasterInstrument.PointValue;
						symbol = Instrument.MasterInstrument.Name ?? "";
					}
				}
			}
			catch { }
			string acct = string.IsNullOrEmpty(cachedAccountName) ? "unknown" : cachedAccountName;
			Enqueue(string.Format(CultureInfo.InvariantCulture,
				"{{\"type\":\"heartbeat\",\"bridge_version\":\"{0}\",\"account\":\"{1}\",\"instrument\":\"{2}\",\"symbol\":\"{3}\",\"position\":{4},\"unrealized_pnl\":{5},\"realized_pnl\":{6},\"cash_value\":{7},\"net_liquidation\":{8},\"sod_cash\":{9},\"buying_power\":{10},\"point_value\":{11},\"tick_size\":{12},\"last\":{13}}}\n",
				BridgeVersion, EscapeJson(acct), EscapeJson(instrument), EscapeJson(symbol),
				pos, cachedUnrealized, cachedRealized, cachedCash, cachedNetLiq, cachedSodCash,
				cachedBuyingPower, pointValue, TickSize, last));
		}

		private void SendSeed()
		{
			int n = Math.Min(SeedBars, CurrentBar);
			for (int i = n; i >= 1; i--)
			{
				Enqueue(string.Format(CultureInfo.InvariantCulture,
					"{{\"type\":\"bar\",\"seed\":true,\"realtime\":false,\"time\":\"{0:O}\",\"open\":{1},\"high\":{2},\"low\":{3},\"close\":{4},\"volume\":{5}}}\n",
					Time[i], Open[i], High[i], Low[i], Close[i], Volume[i]));
			}
			try
			{
				if (BarsArray != null)
				{
					for (int bip = 1; bip < BarsArray.Length; bip++)
					{
						int hn = Math.Min(400, CurrentBars[bip]);
						for (int i = hn; i >= 1; i--)
							SendHtfBar(bip, i, false, true);
					}
				}
			}
			catch { }
			Enqueue(string.Format(CultureInfo.InvariantCulture, "{{\"type\":\"seed_done\",\"count\":{0}}}\n", n));
			seedSent = true;
		}

		private void StartBridge()
		{
			running = true;
			listenerThread = new Thread(ListenLoop) { IsBackground = true, Name = "ReconSniper" };
			listenerThread.Start();
		}

		private void StopBridge()
		{
			running = false;
			try { listener?.Stop(); } catch { }
			lock (streamLock)
			{
				try { stream?.Close(); } catch { }
				try { client?.Close(); } catch { }
				stream = null;
				client = null;
			}
		}

		private void ListenLoop()
		{
			try
			{
				listener = new TcpListener(IPAddress.Loopback, Port);
				listener.Start();
				Print("ReconSniper listening on " + Port);
				while (running)
				{
					TcpClient incoming = listener.AcceptTcpClient();
					lock (streamLock)
					{
						try { client?.Close(); } catch { }
						client = incoming;
						stream = incoming.GetStream();
					}
					mainActions.Enqueue(SendSeed);
					Thread reader = new Thread(ReadLoop) { IsBackground = true };
					reader.Start();
					while (running)
					{
						string msg;
						while (outbound.TryDequeue(out msg))
						{
							try
							{
								byte[] bytes = Encoding.UTF8.GetBytes(msg);
								lock (streamLock)
								{
									if (stream != null) stream.Write(bytes, 0, bytes.Length);
								}
							}
							catch { break; }
						}
						Thread.Sleep(10);
					}
				}
			}
			catch (Exception ex)
			{
				Print("ReconSniper listen: " + ex.Message);
			}
		}

		private void ReadLoop()
		{
			NetworkStream myStream;
			lock (streamLock) { myStream = stream; }
			if (myStream == null) return;
			var buf = new byte[4096];
			var sb = new StringBuilder();
			try
			{
				while (running)
				{
					int n = myStream.Read(buf, 0, buf.Length);
					if (n <= 0) break;
					sb.Append(Encoding.UTF8.GetString(buf, 0, n));
					string all = sb.ToString();
					int idx;
					while ((idx = all.IndexOf('\n')) >= 0)
					{
						string line = all.Substring(0, idx).Trim();
						all = all.Substring(idx + 1);
						if (line.Length > 0)
							mainActions.Enqueue(() => HandleLine(line));
					}
					sb.Clear();
					sb.Append(all);
				}
			}
			catch { }
		}

		private void DrainMain()
		{
			Action act;
			while (mainActions.TryDequeue(out act))
			{
				try { act(); } catch (Exception ex) { Print("ReconSniper action: " + ex.Message); }
			}
		}

		private void HandleLine(string line)
		{
			if (line.IndexOf("\"type\":\"config\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				int want = GetInt(line, "seed_bars", 0);
				if (want > 0)
					SeedBars = Math.Min(Math.Max(want, 50), 2000);
				return;
			}
			if (line.IndexOf("\"type\":\"request_seed\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				int want = GetInt(line, "seed_bars", 0);
				if (want > 0)
					SeedBars = Math.Min(Math.Max(want, 50), 2000);
				mainActions.Enqueue(SendSeed);
				return;
			}
			if (line.IndexOf("\"type\":\"ping\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				Enqueue("{\"type\":\"pong\"}\n");
				return;
			}
			if (line.IndexOf("\"type\":\"ema_overlay\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				string onRaw = GetString(line, "enabled").ToLowerInvariant();
				emaOverlayOn = onRaw == "true" || onRaw == "1";
				return;
			}
			if (line.IndexOf("\"type\":\"tcm8_overlay\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				ApplyTcm8Overlay(line);
				return;
			}
			if (line.IndexOf("\"type\":\"barriers\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				ApplyBarriers(line);
				return;
			}
			if (line.IndexOf("\"type\":\"levels\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				ApplyLevels(line);
				return;
			}
			if (line.IndexOf("\"type\":\"set_stop\"", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				double stopPx = GetDouble(line, "stop", 0);
				if (stopPx <= 0)
					stopPx = GetDouble(line, "stop_loss", 0);
				if (stopPx > 0 && Position != null && Position.MarketPosition != MarketPosition.Flat)
				{
					double mkt = Close[0];
					double tickSz = Instrument != null && Instrument.MasterInstrument != null
						? Instrument.MasterInstrument.TickSize
						: TickSize;
					if (tickSz <= 0) tickSz = 0.25;
					// Require a clear tick through the stop before market-exiting.
					// Sitting on the bank floor must not flatten — Python owns FLOOR/TRAIL.
					if (Position.MarketPosition == MarketPosition.Long)
					{
						if (mkt <= stopPx - tickSz)
						{
							int q = Math.Max(1, (int)Position.Quantity);
							ExitLong(q, FlatSignal, LongSignal);
						}
						else if (stopPx < mkt - tickSz)
							SetStopLoss(LongSignal, CalculationMode.Price, stopPx, false);
					}
					else if (Position.MarketPosition == MarketPosition.Short)
					{
						if (mkt >= stopPx + tickSz)
						{
							int q = Math.Max(1, (int)Math.Abs(Position.Quantity));
							ExitShort(q, FlatSignal, ShortSignal);
						}
						else if (stopPx > mkt + tickSz)
							SetStopLoss(ShortSignal, CalculationMode.Price, stopPx, false);
					}
				}
				Enqueue("{\"type\":\"ack\",\"message\":\"stop updated\"}\n");
				return;
			}
			if (line.IndexOf("\"type\":\"order\"", StringComparison.OrdinalIgnoreCase) < 0)
				return;
			string action = GetString(line, "action").ToUpperInvariant();
			int qty = Math.Max(1, GetInt(line, "quantity", 1));
			if (qty > MaxContracts) qty = MaxContracts;
			int pos = Position == null ? 0 : (int)Position.Quantity;
			if (action == "CLOSE" || action == "FLAT")
			{
				if (Position == null || Position.MarketPosition == MarketPosition.Flat)
				{
					closePending = false;
					entriesLocked = false;
					Enqueue("{\"type\":\"ack\",\"message\":\"already flat\"}\n");
					return;
				}
				closePending = true;
				if (Position.MarketPosition == MarketPosition.Long)
					ExitLong(pos, FlatSignal, LongSignal);
				else if (Position.MarketPosition == MarketPosition.Short)
					ExitShort(pos, FlatSignal, ShortSignal);
				Enqueue("{\"type\":\"ack\",\"message\":\"flat submitted\"}\n");
				return;
			}
			if (Position == null || Position.MarketPosition == MarketPosition.Flat)
			{
				closePending = false;
				entriesLocked = false;
			}
			if (entriesLocked || closePending || (Position != null && Position.MarketPosition != MarketPosition.Flat))
			{
				Enqueue("{\"type\":\"ack\",\"message\":\"duplicate blocked\"}\n");
				return;
			}
			double stop = GetDouble(line, "stop_loss", 0);
			double target = GetDouble(line, "take_profit", 0);
			try
			{
				if (action == "BUY" || action == "LONG")
				{
					EnterLong(qty, LongSignal);
					if (stop > 0) SetStopLoss(LongSignal, CalculationMode.Price, stop, false);
					if (target > 0) SetProfitTarget(LongSignal, CalculationMode.Price, target);
					Enqueue("{\"type\":\"ack\",\"message\":\"order submitted\",\"action\":\"BUY\",\"quantity\":" + qty.ToString(CultureInfo.InvariantCulture) + "}\n");
				}
				else if (action == "SELL" || action == "SHORT")
				{
					EnterShort(qty, ShortSignal);
					if (stop > 0) SetStopLoss(ShortSignal, CalculationMode.Price, stop, false);
					if (target > 0) SetProfitTarget(ShortSignal, CalculationMode.Price, target);
					Enqueue("{\"type\":\"ack\",\"message\":\"order submitted\",\"action\":\"SELL\",\"quantity\":" + qty.ToString(CultureInfo.InvariantCulture) + "}\n");
				}
			}
			catch (Exception ex)
			{
				// Never let an order fault disable the strategy / kill the TCP bridge.
				Enqueue("{\"type\":\"ack\",\"message\":\"order error\",\"error\":\"" + EscapeJson(ex.Message) + "\"}\n");
			}
		}

		private void PaintEmaPlots()
		{
			if (CurrentBar < 0 || Values == null || Values.Length < 3)
				return;
			// Always draw the three lines. Do not flip Plot.Brush — that greys
			// the strategy plot checkboxes in NT and hides the lines.
			try
			{
				if (Plots != null)
				{
					int n = Math.Min(Plots.Length, 5);
					for (int i = 0; i < n; i++)
						Plots[i].Width = 4;
				}
			}
			catch { }
			if (CurrentBar >= 8 && ema9Ind != null)
				Values[0][0] = ema9Ind[0];
			if (CurrentBar >= 19 && ema20Ind != null)
				Values[1][0] = ema20Ind[0];
			if (CurrentBar >= 49 && ema50Ind != null)
				Values[2][0] = ema50Ind[0];
			if (Values.Length >= 5)
			{
				if (CurrentBar >= 7 && ema8M1 != null)
					Values[3][0] = ema8M1[0];
				if (ema8H1 != null && CurrentBars != null && CurrentBars.Length > 1 && CurrentBars[1] >= 7)
					Values[4][0] = ema8H1[0];
			}
		}

		private void ApplyTcm8Overlay(string line)
		{
			// Lines only. No Draw.Text / price labels on Willie's chart.
			string onRaw = GetString(line, "enabled").ToLowerInvariant();
			bool on = onRaw == "true" || onRaw == "1";
			RemoveDrawObject("ReconTcm8_4h");
			RemoveDrawObject("ReconTcm8_4hTxt");
			RemoveDrawObject("ReconTcm8_1hTxt");
			if (!on)
			{
				RemoveDrawObject("ReconTcm8_1m");
				RemoveDrawObject("ReconTcm8_1h");
				return;
			}
			DrawBarrierLine("ReconTcm8_1m", GetDouble(line, "ema1m", 0), Brushes.Orange);
			DrawBarrierLine("ReconTcm8_1h", GetDouble(line, "ema1h", 0), Brushes.Gold);
		}

		private void ApplyLevels(string line)
		{
			string clearRaw = GetString(line, "clear").ToLowerInvariant();
			bool clear = clearRaw == "true" || clearRaw == "1";
			double entry = GetDouble(line, "entry", 0);
			if (clear || entry <= 0)
			{
				RemoveDrawObject("ReconEntry");
				RemoveDrawObject("ReconStop");
				RemoveDrawObject("ReconTarget");
				RemoveDrawObject("ReconTrail");
				return;
			}
			double stop = GetDouble(line, "stop", 0);
			double target = GetDouble(line, "target", 0);
			double trail = GetDouble(line, "trail", 0);
			string trailRaw = GetString(line, "trail_active").ToLowerInvariant();
			bool trailActive = trailRaw == "true" || trailRaw == "1" || trail > 0;
			// Up to 4 lines: gold entry · green arm · red hard stop · purple tip trail.
			Draw.HorizontalLine(this, "ReconEntry", entry, Brushes.Gold);
			if (target > 0)
				Draw.HorizontalLine(this, "ReconTarget", target, Brushes.LimeGreen);
			else
				RemoveDrawObject("ReconTarget");
			if (stop > 0)
				Draw.HorizontalLine(this, "ReconStop", stop, Brushes.OrangeRed);
			else
				RemoveDrawObject("ReconStop");
			if (trailActive && trail > 0)
				Draw.HorizontalLine(this, "ReconTrail", trail, Brushes.MediumPurple);
			else
				RemoveDrawObject("ReconTrail");
		}

		private void DrawBarrierLine(string tag, double px, System.Windows.Media.Brush brush)
		{
			if (px <= 0)
			{
				RemoveDrawObject(tag);
				return;
			}
			Draw.HorizontalLine(this, tag, px, brush);
		}

		private void ApplyBarriers(string line)
		{
			// Lines only. No Draw.Text / price labels.
			string onRaw = GetString(line, "enabled").ToLowerInvariant();
			bool on = onRaw == "true" || onRaw == "1";
			if (!on)
			{
				RemoveDrawObject("ReconPdh");
				RemoveDrawObject("ReconPdl");
				RemoveDrawObject("ReconNextLong");
				RemoveDrawObject("ReconNextShort");
				return;
			}
			DrawBarrierLine("ReconPdh", GetDouble(line, "pdh", 0), Brushes.DeepSkyBlue);
			DrawBarrierLine("ReconPdl", GetDouble(line, "pdl", 0), Brushes.DodgerBlue);
			DrawBarrierLine("ReconNextLong", GetDouble(line, "next_long", 0), Brushes.Cyan);
			DrawBarrierLine("ReconNextShort", GetDouble(line, "next_short", 0), Brushes.MediumTurquoise);
		}

		private void Enqueue(string s) { outbound.Enqueue(s); }

		private static string GetString(string json, string key)
		{
			string needle = "\"" + key + "\":";
			int i = json.IndexOf(needle, StringComparison.OrdinalIgnoreCase);
			if (i < 0) return "";
			i += needle.Length;
			while (i < json.Length && (json[i] == ' ' || json[i] == '"'))
			{
				if (json[i] == '"')
				{
					int end = json.IndexOf('"', i + 1);
					return end > i ? json.Substring(i + 1, end - i - 1) : "";
				}
				i++;
			}
			int j = i;
			while (j < json.Length && json[j] != ',' && json[j] != '}' && json[j] != ' ') j++;
			return json.Substring(i, j - i).Trim('"');
		}

		private static int GetInt(string json, string key, int fallback)
		{
			double v = GetDouble(json, key, fallback);
			return (int)v;
		}

		private static double GetDouble(string json, string key, double fallback)
		{
			string s = GetString(json, key);
			double v;
			if (double.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out v))
				return v;
			return fallback;
		}

		[NinjaScriptProperty]
		public int Port { get; set; }

		[NinjaScriptProperty]
		public int MaxContracts { get; set; }

		[NinjaScriptProperty]
		public int SeedBars { get; set; }

		[NinjaScriptProperty]
		public int TickThrottleMs { get; set; }

		[NinjaScriptProperty]
		public bool StreamTicks { get; set; }
	}
}
