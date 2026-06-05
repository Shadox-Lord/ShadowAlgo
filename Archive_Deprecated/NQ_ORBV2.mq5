//+------------------------------------------------------------------+
//|                                         NQ_ORB_Strategy_v2.mq5   |
//|                                  MQL5 Compliant | Handle-Based   |
//+------------------------------------------------------------------+
#property copyright "Investment Analyst"
#property version   "2.0"
#property description "15-min ORB for NQ100/USD. MQL5 Compliant v2.0"
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//--- INPUTS ---
input int    GMT_OFFSET_HOURS   = -5;      // NY Standard Time offset
input int    ORB_MINUTES        = 15;       // Opening range window
input double RISK_PERCENT       = 0.5;      // Account risk per trade (%)
input int    MAX_DAILY_TRADES   = 2;        // Hard daily trade cap
input double MAX_DAILY_LOSS_R   = 2.0;      // Max daily loss in R
input double TP1_R              = 1.0;      // First partial target
input double TP2_R              = 2.2;      // Final target
input double ATR_MULT_SL        = 1.5;      // SL = ATR * multiplier
input double RVOL_THRESHOLD     = 1.4;      // Relative volume filter
input double PREMAX_RANGE_PTS   = 40.0;     // Pre-market max range (points)
input double BUFFER_PTS         = 1.5;      // Limit order buffer from OR extreme

//--- GLOBALS ---
double   orb_high = 0, orb_low = 0, atr_val = 0, rvol_val = 1.0;
bool     orb_defined = false;
int      daily_trades = 0;
double   daily_start_equity = 0;
bool     daily_limit_hit = false;
int      last_day = 0;

// Indicator Handles
int atr_handle = INVALID_HANDLE, ema20_handle = INVALID_HANDLE, ema50_handle = INVALID_HANDLE;
double atr_buf[], ema20_buf[], ema50_buf[];

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetDeviationInPoints(10);
   trade.SetMarginMode();
   trade.SetAsyncMode(false);
   
   // Set filling mode dynamically per broker
   ENUM_ORDER_TYPE_FILLING filling = (ENUM_ORDER_TYPE_FILLING)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   trade.SetTypeFilling(filling);
   
   // Create indicator handles (MQL5 requires handles + CopyBuffer)
   atr_handle   = iATR(_Symbol, PERIOD_M5, 14);
   ema20_handle = iMA(_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   ema50_handle = iMA(_Symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   
   if(atr_handle==INVALID_HANDLE || ema20_handle==INVALID_HANDLE || ema50_handle==INVALID_HANDLE)
   {
      Print("[ERROR] Failed to create indicator handles.");
      return(INIT_FAILED);
   }
   
   ArraySetAsSeries(atr_buf, true);
   ArraySetAsSeries(ema20_buf, true);
   ArraySetAsSeries(ema50_buf, true);
   
   MqlDateTime dt;
   TimeCurrent(dt);
   last_day = dt.day;
   daily_start_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   
   Print("[ORB v2.0] MQL5 Compliant. Initialized.");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   MqlDateTime dt;
   TimeCurrent(dt);
   
   // Reset daily metrics at new day
   if(dt.day != last_day)
   {
      daily_trades = 0;
      daily_limit_hit = false;
      daily_start_equity = AccountInfoDouble(ACCOUNT_EQUITY);
      last_day = dt.day;
      orb_defined = false;
      orb_high = 0; orb_low = 0;
   }
   
   if(daily_limit_hit) return;
   
   // Copy indicator buffers
   if(CopyBuffer(atr_handle, 0, 0, 1, atr_buf) < 1 ||
      CopyBuffer(ema20_handle, 0, 0, 1, ema20_buf) < 1 ||
      CopyBuffer(ema50_handle, 0, 0, 1, ema50_buf) < 1) return;
      
   atr_val = atr_buf[0];
   
   CheckSessionAndORB(dt);
   if(!orb_defined) return;
   
   if(!CheckFilters()) return;
   
   ManageOpenPositions();
   CheckEntrySignals();
}

//+------------------------------------------------------------------+
//| Session & ORB Logic                                              |
//+------------------------------------------------------------------+
void CheckSessionAndORB(MqlDateTime &dt)
{
   int ny_h = (dt.hour + GMT_OFFSET_HOURS + 24) % 24;
   int ny_m = dt.min;
   int current_min = ny_h * 60 + ny_m;
   
   int session_start = 9*60 + 30;
   int orb_end       = session_start + ORB_MINUTES;
   
   if(current_min >= session_start && current_min < orb_end)
   {
      double h = iHigh(_Symbol, PERIOD_M15, 0);
      double l = iLow(_Symbol, PERIOD_M15, 0);
      if(orb_high == 0 || h > orb_high) orb_high = h;
      if(orb_low == 0 || l < orb_low) orb_low = l;
   }
   else if(current_min >= orb_end && !orb_defined)
   {
      orb_defined = true;
      Print("[ORB] Defined. High: ", orb_high, " Low: ", orb_low, " ATR: ", atr_val);
   }
}

//+------------------------------------------------------------------+
//| Confluence Filters                                               |
//+------------------------------------------------------------------+
bool CheckFilters()
{
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double vwap = CalculateSessionVWAP();
   
   // 1. VWAP & Trend Alignment
   bool vwap_ok = (price > vwap && price > (orb_high+orb_low)/2) || 
                  (price < vwap && price < (orb_high+orb_low)/2);
   bool trend_ok = (price > vwap && ema20_buf[0] > ema50_buf[0]) || 
                   (price < vwap && ema20_buf[0] < ema50_buf[0]);
   
   // 2. RVOL
   rvol_val = GetRVOL();
   bool rvol_ok = rvol_val >= RVOL_THRESHOLD;
   
   // 3. Pre-market Range (approx)
   bool prem_ok = (orb_high - orb_low) <= PREMAX_RANGE_PTS * _Point;
   
   return vwap_ok && trend_ok && rvol_ok && prem_ok;
}

//+------------------------------------------------------------------+
//| Entry & Order Management                                         |
//+------------------------------------------------------------------+
void CheckEntrySignals()
{
   if(PositionsTotal() > 0 || daily_trades >= MAX_DAILY_TRADES) return;
   
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl_pts = ATR_MULT_SL * atr_val / _Point;
   double lot = CalculateLotSize(sl_pts);
   if(lot <= 0) return;
   
   double sl_long = orb_low - 5*_Point;
   double tp1_long = price + (price - sl_long) * TP1_R;
   double tp2_long = price + (price - sl_long) * TP2_R;
   
   double sl_short = orb_high + 5*_Point;
   double tp1_short = price - (sl_short - price) * TP1_R;
   double tp2_short = price - (sl_short - price) * TP2_R;
   
   // Long Limit
   if(price <= orb_high + BUFFER_PTS*_Point && price > orb_high - 2*BUFFER_PTS*_Point)
   {
      if(trade.BuyLimit(lot, price, _Symbol, sl_long, tp2_long, ORDER_TIME_GTC, 0, "ORB_Long_Retest"))
      {
         daily_trades++;
         Print("[ENTRY] Long Limit @ ", price);
      }
   }
   
   // Short Limit
   if(price >= orb_low - BUFFER_PTS*_Point && price < orb_low + 2*BUFFER_PTS*_Point)
   {
      if(trade.SellLimit(lot, price, _Symbol, sl_short, tp2_short, ORDER_TIME_GTC, 0, "ORB_Short_Retest"))
      {
         daily_trades++;
         Print("[ENTRY] Short Limit @ ", price);
      }
   }
}

//+------------------------------------------------------------------+
//| Trade Management (Partials, Trailing, Daily Limits)              |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      
      double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double current_price = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 
                             SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double tp = PositionGetDouble(POSITION_TP);
      double volume = PositionGetDouble(POSITION_VOLUME);
      
      double profit_pts = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 
                          (current_price - open_price)/_Point : (open_price - current_price)/_Point;
      double entry_sl_pts = MathAbs((PositionGetDouble(POSITION_SL) - open_price)/_Point);
      if(entry_sl_pts == 0) continue;
      
      double current_r = profit_pts / entry_sl_pts;
      
      // TP1: Close 50%, move SL to BE, set TP2
      if(current_r >= TP1_R && volume > 0.02)
      {
         double half_vol = NormalizeDouble(volume * 0.5, 2);
         if(trade.PositionClose(ticket, half_vol))
         {
            double new_sl = open_price; // Breakeven
            double new_tp = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 
                            open_price + (TP2_R - TP1_R) * entry_sl_pts * _Point : 
                            open_price - (TP2_R - TP1_R) * entry_sl_pts * _Point;
            trade.PositionModify(ticket, new_sl, new_tp);
            Print("[TP1] 50% closed, SL->BE, TP2 set");
         }
      }
      
      // Daily Loss Check
      double daily_pl = AccountInfoDouble(ACCOUNT_EQUITY) - daily_start_equity;
      double risk_usd = daily_start_equity * (RISK_PERCENT/100.0);
      if(daily_pl <= -MAX_DAILY_LOSS_R * risk_usd)
      {
         daily_limit_hit = true;
         CloseAllPositions();
         Print("[DAILY LIMIT] -2R hit. Trading halted.");
      }
   }
}

//+------------------------------------------------------------------+
//| Helper Functions                                                 |
//+------------------------------------------------------------------+
double CalculateSessionVWAP()
{
   double cum_pv = 0, cum_vol = 0;
   for(int i=0; i<100; i++)
   {
      datetime t = iTime(_Symbol, PERIOD_M5, i);
      MqlDateTime dt; TimeToStruct(t, dt);
      int ny_h = (dt.hour + GMT_OFFSET_HOURS + 24) % 24;
      if(ny_h < 9 || (ny_h == 9 && dt.min < 30)) break;
      
      double p = (iHigh(_Symbol, PERIOD_M5, i) + iLow(_Symbol, PERIOD_M5, i) + iClose(_Symbol, PERIOD_M5, i))/3.0;
      double v = (double)iVolume(_Symbol, PERIOD_M5, i);
      cum_pv += p*v; 
      cum_vol += v;
   }
   return (cum_vol > 0) ? cum_pv/cum_vol : SymbolInfoDouble(_Symbol, SYMBOL_BID);
}

double GetRVOL()
{
   double cur_vol = (double)iVolume(_Symbol, PERIOD_M5, 0);
   double avg_vol = 0;
   for(int i=1; i<=20; i++) avg_vol += (double)iVolume(_Symbol, PERIOD_M5, i);
   avg_vol /= 20.0;
   return (avg_vol > 0) ? cur_vol/avg_vol : 1.0;
}

double CalculateLotSize(double sl_pts)
{
   double risk_usd = AccountInfoDouble(ACCOUNT_EQUITY) * (RISK_PERCENT/100.0);
   double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double sl_usd = sl_pts * (tick_val / tick_size);
   if(sl_usd <= 0) return 0.01;
   return NormalizeDouble(risk_usd / sl_usd, 2);
}

void CloseAllPositions()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL) == _Symbol)
         trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(atr_handle!=INVALID_HANDLE) IndicatorRelease(atr_handle);
   if(ema20_handle!=INVALID_HANDLE) IndicatorRelease(ema20_handle);
   if(ema50_handle!=INVALID_HANDLE) IndicatorRelease(ema50_handle);
   Print("[ORB v2.0] Deinitialized & handles released.");
}