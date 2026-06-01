//+------------------------------------------------------------------+
//|                                           Shadow_Portfolio_Hub.mq5 |
//|                        Elite MQL5 Enterprise Architect & Developer |
//|                                   Unified Multi-Strategy Master EA |
//+------------------------------------------------------------------+
#property copyright "Shadow AI Trading Auditor v2.0"
#property link      "https://shadow-audit.com"
#property version   "1.00"
#property strict
#property description "Unified Portfolio Hub: NQ ORB, London Killzone, Gold Pullback, Grading Bot"
#property description "Architecture: Modular State Machine with Global Risk Guardrails"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\Position.mqh>

//+------------------------------------------------------------------+
//| 1. GLOBAL CONSTANTS & MAGIC NUMBER MATRIX                        |
//+------------------------------------------------------------------+
#define MAGIC_NQ_ORB        550000
#define MAGIC_SHADOW        660000
#define MAGIC_GOLD_PULL     770000
#define MAGIC_GRADING_BOT   880000

#define MAX_TRADES_PER_MOD  2
#define GLOBAL_DAILY_DD_PCT 0.60 // 0.60% Hard Stop
#define NEWS_BLACKOUT_MIN   30   // Minutes before/after news
#define FRIDAY_CLOSE_HOUR   20   // UTC

// Strategy Identifiers
enum ENUM_STRATEGY_ID {
   STRAT_NONE = 0,
   STRAT_NQ_ORB,
   STRAT_SHADOW,
   STRAT_GOLD_PULL,
   STRAT_GRADING_BOT
};

// News Event Types
enum ENUM_NEWS_EVENT {
   NEWS_NONE = 0,
   NEWS_NFP,
   NEWS_CPI,
   NEWS_FOMC
};

//+------------------------------------------------------------------+
//| 2. UNIFIED INPUTS (GROUPED BY STRATEGY)                          |
//+------------------------------------------------------------------+
input group "--- GLOBAL RISK SETTINGS ---"
input double Inp_GlobalRiskPct       = 0.30;   // Risk % Per Trade (Base)
input bool   Inp_EnableNewsFilter    = true;   // Enable NFP/CPI/FOMC Blackout
input bool   Inp_EnableFridayClose   = true;   // Close all @ Friday 20:00 UTC

input group "--- STRATEGY 1: NQ ORB (Nasdaq) ---"
input bool   Inp_NQ_Enabled          = true;
input double Inp_NQ_RiskMult         = 1.5;    // Multiplier for NQ volatility
input int    Inp_NQ_ORB_Minutes      = 15;    // Opening Range Duration
input double Inp_NQ_BufferPts        = 1.5;    // Points buffer for entry

input group "--- STRATEGY 2: SHADOW (London Killzone) ---"
input bool   Inp_Shadow_Enabled      = true;
input string Inp_Shadow_Symbols      = "EURUSD,GBPUSD"; // Comma separated
input int    Inp_Shadow_AsianStart   = 0;     // UTC Hour
input int    Inp_Shadow_AsianEnd     = 8;     // UTC Hour
input int    Inp_Shadow_LondonStart  = 8;     // UTC Hour
input int    Inp_Shadow_LondonEnd    = 10;    // UTC Hour

input group "--- STRATEGY 3: GOLD PULLBACK (XAUUSD) ---"
input bool   Inp_Gold_Enabled        = true;
input int    Inp_Gold_EMA_Period     = 50;
input int    Inp_Gold_SD_ZonePts     = 200;   // Points for S/D Zone

input group "--- STRATEGY 4: GRADING BOT (Multi-Asset) ---"
input bool   Inp_Grading_Enabled     = true;
input int    Inp_Grading_MinScore    = 55;    // Min Grade (0-100) to trade
input int    Inp_Grading_SMA_Period  = 20;

//+------------------------------------------------------------------+
//| 3. FORWARD CLASS DECLARATIONS                                    |
//+------------------------------------------------------------------+
class CPortfolioRiskManager;
class CStrategyNQORB;
class CStrategyShadow;
class CStrategyGoldPullback;
class CStrategyGradingBot;

//+------------------------------------------------------------------+
//| 4. CENTRALIZED RISK ENGINE (GLOBAL GUARDRAILS)                   |
//+------------------------------------------------------------------+
class CPortfolioRiskManager
{
private:
   CAccountInfo     m_account;
   CPositionInfo    m_position;
   CTrade           m_tradeRef; // Reference only, not used for execution here
   datetime         m_lastBarTime;
   double           m_dailyStartBalance;
   double           m_maxDailyLossAmount;
   int              m_tradesToday[4]; // Index matches ENUM_STRATEGY_ID
   bool             m_isEStopActive;
   bool             m_emergencyCloseExecuted;
   
   // News Calendar (Hardcoded 2024-2025 Key Dates)
   struct NewsEvent {
      datetime time;
      ENUM_NEWS_EVENT type;
   };
   NewsEvent m_newsCalendar[];

public:
   CPortfolioRiskManager() {
      ZeroMemory(m_tradesToday);
      m_isEStopActive = false;
      m_emergencyCloseExecuted = false;
      m_dailyStartBalance = 0;
      InitializeNewsCalendar();
   }

   void InitializeNewsCalendar() {
      // Hardcoded Critical Events (Sample for 2024-2025)
      // Format: YYYY.MM.DD HH:MM
      AddNewsEvent("2024.05.03 12:30", NEWS_NFP);
      AddNewsEvent("2024.05.15 12:30", NEWS_CPI);
      AddNewsEvent("2024.05.01 18:00", NEWS_FOMC);
      AddNewsEvent("2024.06.07 12:30", NEWS_NFP);
      AddNewsEvent("2024.06.12 12:30", NEWS_CPI);
      AddNewsEvent("2024.06.12 18:00", NEWS_FOMC);
      // Add more dates as needed or load from CSV
      Print("[RISK] News Calendar initialized with ", ArraySize(m_newsCalendar), " events.");
   }

   void AddNewsEvent(string dateStr, ENUM_NEWS_EVENT type) {
      int idx = ArraySize(m_newsCalendar);
      ArrayResize(m_newsCalendar, idx + 1);
      datetime dt = StringToTime(dateStr);
      m_newsCalendar[idx].time = dt;
      m_newsCalendar[idx].type = type;
   }

   bool OnInit() {
      m_dailyStartBalance = m_account.Balance();
      m_maxDailyLossAmount = m_dailyStartBalance * (GLOBAL_DAILY_DD_PCT / 100.0);
      ArrayFill(m_tradesToday, 0, ArraySize(m_tradesToday), 0);
      m_isEStopActive = false;
      m_emergencyCloseExecuted = false;
      Print("[RISK] Daily Start Balance: ", m_dailyStartBalance, " | Max Loss Limit: ", m_maxDailyLossAmount);
      return true;
   }

   void OnNewDay() {
      m_dailyStartBalance = m_account.Balance();
      m_maxDailyLossAmount = m_dailyStartBalance * (GLOBAL_DAILY_DD_PCT / 100.0);
      ArrayFill(m_tradesToday, 0, ArraySize(m_tradesToday), 0);
      m_isEStopActive = false;
      m_emergencyCloseExecuted = false;
      Print("[RISK] New Day Reset. Balance: ", m_dailyStartBalance);
   }

   // Returns true if trading is allowed
   bool CheckGlobalGuardrails(CTrade &trade) {
      if(m_isEStopActive) {
         if(!m_emergencyCloseExecuted) {
            ExecuteEmergencyClose(trade);
            m_emergencyCloseExecuted = true;
         }
         return false;
      }

      // 1. Check Daily Drawdown (Realized + Unrealized)
      double currentEquity = m_account.Equity();
      double dailyDD = m_dailyStartBalance - currentEquity;
      
      if(dailyDD >= m_maxDailyLossAmount) {
         TriggerEStop("Global Daily DD Hit (" + DoubleToString(dailyDD, 2) + ")");
         ExecuteEmergencyClose(trade);
         m_emergencyCloseExecuted = true;
         return false;
      }

      // 2. Check News Blackout
      if(Inp_EnableNewsFilter && IsNewsBlackout()) {
         return false;
      }

      // 3. Check Friday Close
      if(Inp_EnableFridayClose && IsFridayCloseTime()) {
         TriggerEStop("Friday Close Protection");
         ExecuteEmergencyClose(trade);
         m_emergencyCloseExecuted = true;
         return false;
      }

      return true;
   }

   void ExecuteEmergencyClose(CTrade &trade) {
      Print("!!! EXECUTING EMERGENCY CLOSE FOR ALL SHADOW POSITIONS !!!");
      CPositionInfo pos;
      int total = PositionsTotal();
      for(int i = total - 1; i >= 0; i--) {
         if(pos.SelectByIndex(i)) {
            long magic = pos.Magic();
            // Check if position belongs to any of our strategies
            if(magic == MAGIC_NQ_ORB || magic == MAGIC_SHADOW || 
               magic == MAGIC_GOLD_PULL || magic == MAGIC_GRADING_BOT) {
               trade.PositionClose(pos.Ticket());
               Print("Closed Position: ", pos.Symbol(), " Magic: ", magic);
            }
         }
      }
      // Also delete pending orders
      int orders = OrdersTotal();
      for(int i = orders - 1; i >= 0; i--) {
         if(OrderSelect(i, SELECT_BY_POS, ORDERS_HISTORY)) continue; // Skip history
         // Need to select from market orders
         ulong ticket = OrderGetTicket(i); 
         if(ticket > 0) {
            if(OrderGetString(ORDER_MAGIC) == MAGIC_NQ_ORB || 
               OrderGetString(ORDER_MAGIC) == MAGIC_SHADOW ||
               OrderGetString(ORDER_MAGIC) == MAGIC_GOLD_PULL ||
               OrderGetString(ORDER_MAGIC) == MAGIC_GRADING_BOT) {
               trade.OrderDelete(ticket);
            }
         }
      }
      PrintAlert("!!! E-STOP EXECUTED: ALL POSITIONS CLOSED !!!");
   }

   bool CheckModuleCap(ENUM_STRATEGY_ID id) {
      if(id <= STRAT_NONE || id > STRAT_GRADING_BOT) return false;
      return (m_tradesToday[id] < MAX_TRADES_PER_MOD);
   }

   void IncrementTradeCount(ENUM_STRATEGY_ID id) {
      if(id > STRAT_NONE && id <= STRAT_GRADING_BOT) {
         m_tradesToday[id]++;
         Print("[RISK] Module ", id, " trade count: ", m_tradesToday[id]);
      }
   }

   void TriggerEStop(string reason) {
      if(m_isEStopActive) return;
      m_isEStopActive = true;
      PrintAlert("!!! E-STOP TRIGGERED: " + reason + " !!!");
   }

   bool IsEStopActive() const { return m_isEStopActive; }

   // Dynamic Lot Calculation
   double CalculateLots(double stopLossPoints, string symbol) {
      if(stopLossPoints <= 0) return 0;
      
      CSymbolInfo symInfo;
      if(!symInfo.Name(symbol)) return 0;
      
      double riskAmount = m_dailyStartBalance * (Inp_GlobalRiskPct / 100.0);
      double tickValue = symInfo.TickValue();
      double tickSize = symInfo.TickSize();
      
      // Calculate value per point for 1 lot
      double pointValue = (tickValue / tickSize) * symInfo.Point();
      
      double lots = riskAmount / (stopLossPoints * pointValue);
      
      // Normalize lots
      double minLot = symInfo.LotsMin();
      double maxLot = symInfo.LotsMax();
      double stepLot = symInfo.LotsStep();
      
      lots = MathFloor(lots / stepLot) * stepLot;
      lots = MathMax(minLot, MathMin(maxLot, lots));
      
      return lots;
   }

private:
   bool IsNewsBlackout() {
      datetime now = TimeCurrent();
      int size = ArraySize(m_newsCalendar);
      for(int i = 0; i < size; i++) {
         datetime eventTime = m_newsCalendar[i].time;
         datetime startBlock = eventTime - (NEWS_BLACKOUT_MIN * 60);
         datetime endBlock = eventTime + (NEWS_BLACKOUT_MIN * 60);
         
         if(now >= startBlock && now <= endBlock) {
            Print("[NEWS] Blackout Active: ", EnumToString(m_newsCalendar[i].type), " until ", TimeToString(endBlock));
            return true;
         }
      }
      return false;
   }

   bool IsFridayCloseTime() {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      if(dt.day_of_week == 5 && dt.hour >= FRIDAY_CLOSE_HOUR) return true;
      return false;
   }
};

//+------------------------------------------------------------------+
//| 5. STRATEGY MODULE: NQ ORB                                       |
//+------------------------------------------------------------------+
class CStrategyNQORB
{
private:
   int m_handleVWAP, m_handleEMA20, m_handleEMA50;
   bool m_initialized;
   double m_orbHigh, m_orbLow;
   datetime m_orbStartTime;
   bool m_orbCalculated;
   int m_ticketsToday[2]; // Track tickets to avoid re-entry
   
public:
   CStrategyNQORB() : m_initialized(false), m_orbCalculated(false) {
      ZeroMemory(m_ticketsToday);
   }
   
   bool Init() {
      if(!Inp_NQ_Enabled) return false;
      // Initialize indicators
      m_handleVWAP = iCustom(_Symbol, PERIOD_M15, "Examples\\VWAP"); // Placeholder path
      m_handleEMA20 = iMA(_Symbol, PERIOD_M15, 20, 0, MODE_EMA, PRICE_CLOSE);
      m_handleEMA50 = iMA(_Symbol, PERIOD_M15, 50, 0, MODE_EMA, PRICE_CLOSE);
      
      if(m_handleEMA20 == INVALID_HANDLE || m_handleEMA50 == INVALID_HANDLE) {
         Print("NQ: Failed to create EMA handles");
         return false;
      }
      m_initialized = true;
      m_orbStartTime = 0;
      return true;
   }

   void OnTick(CTrade &trade, CPortfolioRiskManager &risk) {
      if(!Inp_NQ_Enabled || !m_initialized) return;
      if(StringFind(_Symbol, "NQ") == -1 && StringFind(_Symbol, "US100") == -1) return; 
      
      if(!risk.CheckModuleCap(STRAT_NQ_ORB)) return;

      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      
      // 1. Define Session Start (NY Open 9:30 AM EST -> 13:30/14:30 UTC depending on DST)
      // Simplified: Assume 13:30 UTC for Winter, 12:30 UTC for Summer. 
      // Using a fixed 13:30 UTC for this example.
      int sessionHour = 13;
      int sessionMin = 30;
      
      // Reset ORB at start of session
      if(dt.hour == sessionHour && dt.min == sessionMin && !m_orbCalculated) {
         m_orbCalculated = true;
         m_orbStartTime = TimeCurrent();
         // Calculate initial range (will expand in loop below)
         m_orbHigh = High[1];
         m_orbLow = Low[1];
      }
      
      // Expand ORB during the first N minutes
      if(m_orbCalculated && (TimeCurrent() - m_orbStartTime) < (Inp_NQ_ORB_Minutes * 60)) {
         m_orbHigh = MathMax(m_orbHigh, High[1]);
         m_orbLow = MathMin(m_orbLow, Low[1]);
         return; // Wait for ORB period to finish
      }
      
      if(!m_orbCalculated) return;

      // 2. Entry Logic
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double orbBuffer = Inp_NQ_BufferPts * _Point;
      
      double ema20[], ema50[], vwap[];
      ArraySetAsSeries(ema20, true); ArraySetAsSeries(ema50, true); ArraySetAsSeries(vwap, true);
      
      if(CopyBuffer(m_handleEMA20, 0, 0, 3, ema20) <= 0) return;
      if(CopyBuffer(m_handleEMA50, 0, 0, 3, ema50) <= 0) return;
      // VWAP copy omitted for brevity, assume trend filter
      
      bool trendBullish = (Close[1] > ema20[1] && ema20[1] > ema50[1]);
      bool trendBearish = (Close[1] < ema20[1] && ema20[1] < ema50[1]);
      
      // LONG: Break above ORB High + Buffer
      if(trendBullish && ask > (m_orbHigh + orbBuffer)) {
         double sl = m_orbLow - (10 * _Point); // Below ORB Low
         double tp = ask + ((ask - sl) * 2.2); // 1:2.2 RR
         double lots = risk.CalculateLots((ask - sl) / _Point, _Symbol);
         
         if(lots > 0) {
            trade.SetExpertMagicNumber(MAGIC_NQ_ORB);
            if(trade.Buy(lots, _Symbol, ask, sl, tp, "NQ_ORB_Long")) {
               risk.IncrementTradeCount(STRAT_NQ_ORB);
               Print("NQ ORB Long Executed @ ", ask);
            }
         }
      }
      
      // SHORT: Break below ORB Low - Buffer
      if(trendBearish && bid < (m_orbLow - orbBuffer)) {
         double sl = m_orbHigh + (10 * _Point);
         double tp = bid - ((sl - bid) * 2.2);
         double lots = risk.CalculateLots((sl - bid) / _Point, _Symbol);
         
         if(lots > 0) {
            trade.SetExpertMagicNumber(MAGIC_NQ_ORB);
            if(trade.Sell(lots, _Symbol, bid, sl, tp, "NQ_ORB_Short")) {
               risk.IncrementTradeCount(STRAT_NQ_ORB);
               Print("NQ ORB Short Executed @ ", bid);
            }
         }
      }
   }

   void OnDeinit() {
      if(m_handleVWAP != INVALID_HANDLE) IndicatorRelease(m_handleVWAP);
      if(m_handleEMA20 != INVALID_HANDLE) IndicatorRelease(m_handleEMA20);
      if(m_handleEMA50 != INVALID_HANDLE) IndicatorRelease(m_handleEMA50);
   }
};

//+------------------------------------------------------------------+
//| 6. STRATEGY MODULE: SHADOW (London Killzone)                     |
//+------------------------------------------------------------------+
class CStrategyShadow
{
private:
   int m_handleATR;
   bool m_initialized;
   double m_asianHigh, m_asianLow;
   datetime m_asianStartDay;
   
public:
   CStrategyShadow() : m_initialized(false), m_asianStartDay(0) {}
   
   bool Init() {
      if(!Inp_Shadow_Enabled) return false;
      m_handleATR = iATR(_Symbol, PERIOD_M15, 14);
      m_initialized = (m_handleATR != INVALID_HANDLE);
      return m_initialized;
   }

   void OnTick(CTrade &trade, CPortfolioRiskManager &risk) {
      if(!Inp_Shadow_Enabled || !m_initialized) return;
      if(StringFind(Inp_Shadow_Symbols, _Symbol) == -1) return;
      if(!risk.CheckModuleCap(STRAT_SHADOW)) return;

      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      
      // 1. Define Asian Session (00:00 - 08:00 UTC)
      if(dt.hour >= Inp_Shadow_AsianStart && dt.hour < Inp_Shadow_AsianEnd) {
         if(m_asianStartDay != dt.day) {
            m_asianStartDay = dt.day;
            m_asianHigh = High[1];
            m_asianLow = Low[1];
         } else {
            m_asianHigh = MathMax(m_asianHigh, High[1]);
            m_asianLow = MathMin(m_asianLow, Low[1]);
         }
         return;
      }
      
      // 2. London Killzone (08:00 - 10:00 UTC)
      if(dt.hour >= Inp_Shadow_LondonStart && dt.hour < Inp_Shadow_LondonEnd) {
         if(m_asianStartDay == 0) return; // No Asian data
         
         double atrVal[];
         ArraySetAsSeries(atrVal, true);
         if(CopyBuffer(m_handleATR, 0, 0, 1, atrVal) <= 0) return;
         double atr = atrVal[0];
         
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double spreadBuffer = 1.5 * _Point; // 1.5 points buffer
         
         // Sweep Logic: Price sweeps Asian Low then reverses up
         if(Low[1] < (m_asianLow - spreadBuffer) && Close[1] > m_asianLow) {
            // MSS Confirmation: Close above previous high
            if(Close[1] > High[2]) {
               double sl = Low[1] - (atr * 0.5);
               double tp = ask + ((ask - sl) * 2.0);
               double lots = risk.CalculateLots((ask - sl) / _Point, _Symbol);
               
               if(lots > 0) {
                  trade.SetExpertMagicNumber(MAGIC_SHADOW);
                  if(trade.Buy(lots, _Symbol, ask, sl, tp, "Shadow_Sweep_Long")) {
                     risk.IncrementTradeCount(STRAT_SHADOW);
                     m_asianStartDay = 0; // Reset for next day
                  }
               }
            }
         }
         
         // Sweep Logic: Price sweeps Asian High then reverses down
         if(High[1] > (m_asianHigh + spreadBuffer) && Close[1] < m_asianHigh) {
            if(Close[1] < Low[2]) {
               double sl = High[1] + (atr * 0.5);
               double tp = bid - ((sl - bid) * 2.0);
               double lots = risk.CalculateLots((sl - bid) / _Point, _Symbol);
               
               if(lots > 0) {
                  trade.SetExpertMagicNumber(MAGIC_SHADOW);
                  if(trade.Sell(lots, _Symbol, bid, sl, tp, "Shadow_Sweep_Short")) {
                     risk.IncrementTradeCount(STRAT_SHADOW);
                     m_asianStartDay = 0;
                  }
               }
            }
         }
      } else if (dt.hour >= 10) {
         m_asianStartDay = 0; // Reset after session
      }
   }

   void OnDeinit() {
      if(m_handleATR != INVALID_HANDLE) IndicatorRelease(m_handleATR);
   }
};

//+------------------------------------------------------------------+
//| 7. STRATEGY MODULE: GOLD PULLBACK                                |
//+------------------------------------------------------------------+
class CStrategyGoldPullback
{
private:
   int m_handleEMA50, m_handleEMA200;
   bool m_initialized;
   bool m_zoneDetected;
   double m_zoneHigh, m_zoneLow;
   datetime m_zoneTime;
   
public:
   CStrategyGoldPullback() : m_initialized(false), m_zoneDetected(false) {}
   
   bool Init() {
      if(!Inp_Gold_Enabled) return false;
      m_handleEMA50 = iMA(_Symbol, PERIOD_H1, Inp_Gold_EMA_Period, 0, MODE_EMA, PRICE_CLOSE);
      m_handleEMA200 = iMA(_Symbol, PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
      m_initialized = (m_handleEMA50 != INVALID_HANDLE && m_handleEMA200 != INVALID_HANDLE);
      return m_initialized;
   }

   void OnTick(CTrade &trade, CPortfolioRiskManager &risk) {
      if(!Inp_Gold_Enabled || !m_initialized) return;
      if(StringFind(_Symbol, "XAU") == -1 && StringFind(_Symbol, "GOLD") == -1) return;
      if(!risk.CheckModuleCap(STRAT_GOLD_PULL)) return;

      double ema50[], ema200[];
      ArraySetAsSeries(ema50, true); ArraySetAsSeries(ema200, true);
      if(CopyBuffer(m_handleEMA50, 0, 0, 3, ema50) <= 0) return;
      if(CopyBuffer(m_handleEMA200, 0, 0, 3, ema200) <= 0) return;

      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      
      // Detect Supply/Demand Zones (Simplified: Large impulse bar)
      double barBody = MathAbs(Open[1] - Close[1]);
      double avgBody = (MathAbs(Open[2]-Close[2]) + MathAbs(Open[3]-Close[3])) / 2;
      
      if(barBody > (avgBody * 2.0) && !m_zoneDetected) {
         m_zoneDetected = true;
         m_zoneTime = Time[1];
         if(Close[1] > Open[1]) { // Bullish Impulse -> Demand
            m_zoneLow = Low[1];
            m_zoneHigh = High[1];
         } else { // Bearish Impulse -> Supply
            m_zoneHigh = High[1];
            m_zoneLow = Low[1];
         }
      }
      
      // Expire zone after 4 hours
      if(m_zoneDetected && (TimeCurrent() - m_zoneTime) > (4 * 3600)) {
         m_zoneDetected = false;
      }

      if(!m_zoneDetected) return;

      // LONG: Trend Up + Pullback to Demand
      if(Close[1] > ema200[1] && Close[1] > ema50[1]) {
         if(bid <= (m_zoneHigh + (Inp_Gold_SD_ZonePts * _Point)) && bid >= m_zoneLow) {
            double sl = m_zoneLow - (20 * _Point);
            double tp = ask + ((ask - sl) * 2.0);
            double lots = risk.CalculateLots((ask - sl) / _Point, _Symbol);
            
            if(lots > 0) {
               trade.SetExpertMagicNumber(MAGIC_GOLD_PULL);
               if(trade.Buy(lots, _Symbol, ask, sl, tp, "Gold_Pullback_Long")) {
                  risk.IncrementTradeCount(STRAT_GOLD_PULL);
                  m_zoneDetected = false;
               }
            }
         }
      }
      
      // SHORT: Trend Down + Pullback to Supply
      if(Close[1] < ema200[1] && Close[1] < ema50[1]) {
         if(ask >= (m_zoneLow - (Inp_Gold_SD_ZonePts * _Point)) && ask <= m_zoneHigh) {
            double sl = m_zoneHigh + (20 * _Point);
            double tp = bid - ((sl - bid) * 2.0);
            double lots = risk.CalculateLots((sl - bid) / _Point, _Symbol);
            
            if(lots > 0) {
               trade.SetExpertMagicNumber(MAGIC_GOLD_PULL);
               if(trade.Sell(lots, _Symbol, bid, sl, tp, "Gold_Pullback_Short")) {
                  risk.IncrementTradeCount(STRAT_GOLD_PULL);
                  m_zoneDetected = false;
               }
            }
         }
      }
   }

   void OnDeinit() {
      if(m_handleEMA50 != INVALID_HANDLE) IndicatorRelease(m_handleEMA50);
      if(m_handleEMA200 != INVALID_HANDLE) IndicatorRelease(m_handleEMA200);
   }
};

//+------------------------------------------------------------------+
//| 8. STRATEGY MODULE: GRADING BOT                                  |
//+------------------------------------------------------------------+
class CStrategyGradingBot
{
private:
   int m_handleSMA, m_handleRSI, m_handleATR, m_handleVol;
   bool m_initialized;
   
public:
   CStrategyGradingBot() : m_initialized(false) {}
   
   bool Init() {
      if(!Inp_Grading_Enabled) return false;
      m_handleSMA = iMA(_Symbol, _Period, Inp_Grading_SMA_Period, 0, MODE_SMA, PRICE_CLOSE);
      m_handleRSI = iRSI(_Symbol, _Period, 14, PRICE_CLOSE);
      m_handleATR = iATR(_Symbol, _Period, 14);
      m_handleVol = iVolumes(_Symbol, _Period, VOLUME_TICK);
      m_initialized = (m_handleSMA != INVALID_HANDLE && m_handleRSI != INVALID_HANDLE);
      return m_initialized;
   }

   void OnTick(CTrade &trade, CPortfolioRiskManager &risk) {
      if(!Inp_Grading_Enabled || !m_initialized) return;
      if(!risk.CheckModuleCap(STRAT_GRADING_BOT)) return;

      // 7-Factor Grading System
      int grade = 0;
      
      double sma[], rsi[], atr[], vol[];
      ArraySetAsSeries(sma, true); ArraySetAsSeries(rsi, true); 
      ArraySetAsSeries(atr, true); ArraySetAsSeries(vol, true);
      
      if(CopyBuffer(m_handleSMA, 0, 0, 3, sma) <= 0) return;
      if(CopyBuffer(m_handleRSI, 0, 0, 1, rsi) <= 0) return;
      if(CopyBuffer(m_handleATR, 0, 0, 1, atr) <= 0) return;
      if(CopyBuffer(m_handleVol, 0, 0, 1, vol) <= 0) return;

      double currentRSI = rsi[0];
      double currentSMA = sma[0];
      double currentPrice = Close[0];
      double currentVol = vol[0];
      double currentATR = atr[0];
      
      // Factor 1: RSI Momentum (0-20)
      if(currentRSI > 50 && currentRSI < 70) grade += 10;
      if(currentRSI > 40 && currentRSI < 50) grade += 10; // Reversal potential
      
      // Factor 2: SMA Proximity (0-20)
      double distSMA = MathAbs(currentPrice - currentSMA) / _Point;
      if(distSMA < 10) grade += 20; // Tight breakout
      
      // Factor 3: ATR Environment (0-15)
      if(currentATR > (Average(true, 10) * 1.2)) grade += 15; // High vol
      
      // Factor 4: Bar Body Quality (0-15)
      double body = MathAbs(Open[0] - Close[0]);
      double range = High[0] - Low[0];
      if(range > 0 && (body / range) > 0.7) grade += 15;
      
      // Factor 5: Volume (0-10)
      if(currentVol > 1000) grade += 10;
      
      // Factor 6: Trend Alignment (0-10)
      if(currentPrice > sma[0]) grade += 10;
      
      // Factor 7: Session Quality (0-10)
      MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
      if(dt.hour >= 7 && dt.hour <= 20) grade += 10; // London/NY overlap

      // Execution
      if(grade >= Inp_Grading_MinScore) {
         double slDist = currentATR * 1.5;
         double sl, tp, lots;
         
         if(currentRSI > 50 && currentPrice > currentSMA) {
            // BUY
            sl = currentPrice - slDist;
            tp = currentPrice + (slDist * 2.0);
            lots = risk.CalculateLots(slDist / _Point, _Symbol);
            if(lots > 0) {
               trade.SetExpertMagicNumber(MAGIC_GRADING_BOT);
               if(trade.Buy(lots, _Symbol, 0, sl, tp, "Grading_Bot_Long")) {
                  risk.IncrementTradeCount(STRAT_GRADING_BOT);
                  Print("Grading Bot Long: Grade=", grade);
               }
            }
         } else if (currentRSI < 50 && currentPrice < currentSMA) {
            // SELL
            sl = currentPrice + slDist;
            tp = currentPrice - (slDist * 2.0);
            lots = risk.CalculateLots(slDist / _Point, _Symbol);
            if(lots > 0) {
               trade.SetExpertMagicNumber(MAGIC_GRADING_BOT);
               if(trade.Sell(lots, _Symbol, 0, sl, tp, "Grading_Bot_Short")) {
                  risk.IncrementTradeCount(STRAT_GRADING_BOT);
                  Print("Grading Bot Short: Grade=", grade);
               }
            }
         }
      }
   }
   
   double Average(bool useClose, int period) {
      double sum = 0;
      for(int i=0; i<period; i++) sum += MathAbs(Open[i]-Close[i]);
      return sum/period;
   }

   void OnDeinit() {
      if(m_handleSMA != INVALID_HANDLE) IndicatorRelease(m_handleSMA);
      if(m_handleRSI != INVALID_HANDLE) IndicatorRelease(m_handleRSI);
      if(m_handleATR != INVALID_HANDLE) IndicatorRelease(m_handleATR);
      if(m_handleVol != INVALID_HANDLE) IndicatorRelease(m_handleVol);
   }
};

//+------------------------------------------------------------------+
//| 9. GLOBAL INSTANCES                                              |
//+------------------------------------------------------------------+
CPortfolioRiskManager   g_RiskManager;
CStrategyNQORB          g_StratNQ;
CStrategyShadow         g_StratShadow;
CStrategyGoldPullback   g_StratGold;
CStrategyGradingBot     g_StratGrading;

CTrade                  g_Trade;
CPositionInfo           g_Position;
COrderInfo              g_Order;
CSymbolInfo             g_SymbolInfo;

datetime                g_LastBarTime = 0;

//+------------------------------------------------------------------+
//| 10. MASTER EVENT ROUTING: OnInit                                 |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== Shadow Portfolio Hub Initializing ===");
   
   g_Trade.SetDeviationInPoints(10);
   
   if(!g_SymbolInfo.Name(_Symbol)) {
      Print("Error: Symbol ", _Symbol, " not found");
      return INIT_FAILED;
   }
   
   ENUM_ORDER_TYPE_FILLING filling = (ENUM_ORDER_TYPE_FILLING)g_SymbolInfo.TradeFillFlags();
   if((filling & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      g_Trade.SetTypeFilling(ORDER_FILLING_FOK);
   else if((filling & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      g_Trade.SetTypeFilling(ORDER_FILLING_IOC);
   else
      g_Trade.SetTypeFilling(ORDER_FILLING_RETURN);
      
   Print("[EXEC] Broker Filling Mode Detected: ", g_Trade.TypeFilling());

   if(!g_RiskManager.OnInit()) return INIT_FAILED;

   bool initStatus = true;
   initStatus &= g_StratNQ.Init();
   initStatus &= g_StratShadow.Init();
   initStatus &= g_StratGold.Init();
   initStatus &= g_StratGrading.Init();

   if(!initStatus) Print("Warning: One or more strategies failed to initialize.");

   Print("=== Initialization Complete ===");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| 11. MASTER EVENT ROUTING: OnTick                                 |
//+------------------------------------------------------------------+
void OnTick()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.hour == 0 && dt.min == 0) {
      static datetime lastReset = 0;
      if(TimeCurrent() - lastReset > 3600) {
         g_RiskManager.OnNewDay();
         lastReset = TimeCurrent();
      }
   }

   if(!g_RiskManager.CheckGlobalGuardrails(g_Trade)) {
      return; 
   }

   g_StratNQ.OnTick(g_Trade, g_RiskManager);
   g_StratShadow.OnTick(g_Trade, g_RiskManager);
   g_StratGold.OnTick(g_Trade, g_RiskManager);
   g_StratGrading.OnTick(g_Trade, g_RiskManager);
}

//+------------------------------------------------------------------+
//| 12. MASTER EVENT ROUTING: OnDeinit                               |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("=== Shadow Portfolio Hub Shutting Down ===");
   
   g_StratNQ.OnDeinit();
   g_StratShadow.OnDeinit();
   g_StratGold.OnDeinit();
   g_StratGrading.OnDeinit();
   
   ExportPerformanceCSV(reason);
   Comment("");
}

void ExportPerformanceCSV(int reason) {
   string filename = "Shadow_Hub_Performance_" + TimeToString(TimeCurrent(), TIME_DATE) + ".csv";
   int handle = FileOpen(filename, FILE_CSV | FILE_WRITE | FILE_ANSI, ';');
   if(handle != INVALID_HANDLE) {
      FileWrite(handle, "Timestamp", "StrategyID", "MagicNumber", "Type", "Lots", "Price", "SL", "TP", "Result");
      FileClose(handle);
      Print("Performance log exported to: ", filename);
   }
}
//+------------------------------------------------------------------+
