//+------------------------------------------------------------------+
//|                                          Shadow_V5_Final.mq5    |
//|              London Kill Zone — Asian Range Liquidity Sweep      |
//|                        VERSION 5.1 FINAL (Production-Locked)    |
//|  CHANGELOG vs V4:                                               |
//|  - Risk locked at 0.30% per trade (hardcoded in lot calc)      |
//|  - Removed cross-EA GlobalVariable portfolio lock               |
//|  - 2-trade/day hard cap (this EA only, independent)            |
//|  - Dynamic SL = SwingPoint + ATR + live spread * buffer        |
//|  - FOMC / NFP / CPI 30-min blackout only                      |
//|  - Per-EA daily drawdown guard                                  |
//|  - Auto-detect broker filling mode                              |
//|  - Friday close protection                                      |
//+------------------------------------------------------------------+
#property copyright "Shadow EA v5.1 Final"
#property version   "5.10"
#property strict

#include <Trade\Trade.mqh>

input group "=== RISK ==="
input double InpMaxDailyDrawdown    = 0.60;    // Max Daily Drawdown (%)

input group "=== EA IDENTITY ==="
input int    InpMagicNumber         = 550001; // Magic Number

input group "=== SESSION TIMES (UTC) ==="
input int    InpAsianStartHour      = 0;
input int    InpAsianEndHour        = 8;
input int    InpLondonStartHour     = 8;
input int    InpLondonKillZoneHrs   = 2;

input group "=== STRATEGY ==="
input double InpRiskRewardRatio     = 2.0;
input int    InpMSSLookback         = 10;
input int    InpMaxTradesPerDay     = 2;
input bool   InpCloseFriday         = true;
input int    InpFridayCloseHour     = 20;

input group "=== DYNAMIC SL ==="
input int    InpATRPeriod           = 14;
input double InpSpreadBufferMult    = 1.5;

input group "=== NEWS BLACKOUT ==="
input bool   InpUseNewsBlackout     = true;
input int    InpBlackoutMinsBefore  = 30;
input int    InpBlackoutMinsAfter   = 30;

CTrade   g_trade;
int      g_ATRHandle        = INVALID_HANDLE;
double   g_DayStartBalance  = 0;
bool     g_TradingAllowed   = true;
double   g_AsianHigh        = 0;
double   g_AsianLow         = 0;
bool     g_AsianCalculated  = false;
datetime g_LastDayTime      = 0;

//--- 0.30% RISK — LOCKED CONSTANT
#define RISK_PCT 0.30

bool IsHighImpactBlackout()
  {
   if(!InpUseNewsBlackout) return false;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   int nowMins = dt.hour * 60 + dt.min;
   // NFP: First Friday, 13:30 UTC
   if(dt.day_of_week==5 && dt.day<=7)
     { int d=nowMins-(13*60+30); if(d>=-InpBlackoutMinsBefore&&d<=InpBlackoutMinsAfter){Print("[BLACKOUT] NFP");return true;} }
   // CPI: 2nd/3rd Wednesday, 13:30 UTC
   if(dt.day_of_week==3 && dt.day>=8 && dt.day<=16)
     { int d=nowMins-(13*60+30); if(d>=-InpBlackoutMinsBefore&&d<=InpBlackoutMinsAfter){Print("[BLACKOUT] CPI");return true;} }
   // FOMC: 3rd Wednesday FOMC months, 19:00 UTC
   bool fm=(dt.mon==1||dt.mon==3||dt.mon==5||dt.mon==6||dt.mon==7||dt.mon==9||dt.mon==10||dt.mon==12);
   if(fm&&dt.day_of_week==3&&dt.day>=14&&dt.day<=21)
     { int d=nowMins-(19*60); if(d>=-InpBlackoutMinsBefore&&d<=InpBlackoutMinsAfter){Print("[BLACKOUT] FOMC");return true;} }
   return false;
  }

int CountTodayTrades()
  {
   int count=0;
   for(int i=0;i<PositionsTotal();i++)
      if(PositionGetSymbol(i)==_Symbol&&PositionGetInteger(POSITION_MAGIC)==InpMagicNumber) count++;
   datetime ts=iTime(_Symbol,PERIOD_D1,0);
   if(HistorySelect(ts,TimeCurrent()))
      for(int i=0;i<HistoryDealsTotal();i++)
        {
         ulong t=HistoryDealGetTicket(i);
         if((long)HistoryDealGetInteger(t,DEAL_MAGIC)==InpMagicNumber&&
            HistoryDealGetString(t,DEAL_SYMBOL)==_Symbol&&
            HistoryDealGetInteger(t,DEAL_ENTRY)==DEAL_ENTRY_IN) count++;
        }
   return count;
  }

int OnInit()
  {
   g_ATRHandle=iATR(_Symbol,PERIOD_M15,InpATRPeriod);
   if(g_ATRHandle==INVALID_HANDLE){Print("ATR failed:",GetLastError());return INIT_FAILED;}
   long fm=SymbolInfoInteger(_Symbol,SYMBOL_FILLING_MODE);
   if((fm&SYMBOL_FILLING_FOK)!=0)       g_trade.SetTypeFilling(ORDER_FILLING_FOK);
   else if((fm&SYMBOL_FILLING_IOC)!=0)  g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   else                                  g_trade.SetTypeFilling(ORDER_FILLING_RETURN);
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(20);
   g_DayStartBalance=AccountInfoDouble(ACCOUNT_BALANCE);
   Print("Shadow V5.1 Final | Magic:",InpMagicNumber," | RISK LOCKED: 0.30% | Balance:$",DoubleToString(g_DayStartBalance,2));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  { if(g_ATRHandle!=INVALID_HANDLE) IndicatorRelease(g_ATRHandle); }

void OnTick()
  {
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED)||!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) return;
   datetime curDay=iTime(_Symbol,PERIOD_D1,0);
   if(curDay!=g_LastDayTime)
     {
      g_LastDayTime=curDay; g_DayStartBalance=AccountInfoDouble(ACCOUNT_BALANCE);
      g_TradingAllowed=true; g_AsianCalculated=false; g_AsianHigh=0; g_AsianLow=0;
      Print("[RESET] Balance:$",DoubleToString(g_DayStartBalance,2));
     }
   if(g_TradingAllowed)
     {
      double dd=(g_DayStartBalance>0)?((g_DayStartBalance-AccountInfoDouble(ACCOUNT_EQUITY))/g_DayStartBalance*100.0):0;
      if(dd>=InpMaxDailyDrawdown){Print("[HALT] DD:",DoubleToString(dd,2),"%");g_TradingAllowed=false;CloseAll();}
     }
   if(!g_TradingAllowed) return;
   if(InpCloseFriday){MqlDateTime fd;TimeCurrent(fd);if(fd.day_of_week==5&&fd.hour>=InpFridayCloseHour){CloseAll();return;}}
   if(CountTodayTrades()>=InpMaxTradesPerDay) return;
   if(IsHighImpactBlackout()) return;
   MqlDateTime mdt; TimeCurrent(mdt);
   if(!g_AsianCalculated&&mdt.hour>=InpAsianEndHour) CalcAsian();
   if(mdt.hour>=InpLondonStartHour&&mdt.hour<(InpLondonStartHour+InpLondonKillZoneHrs))
     {
      if(g_AsianHigh<=g_AsianLow||g_AsianHigh==0) return;
      if(HasOpen()) return;
      Execute();
     }
  }

void CalcAsian()
  {
   MqlDateTime dt; TimeToStruct(TimeCurrent(),dt);
   dt.hour=InpAsianStartHour;dt.min=0;dt.sec=0; datetime sA=StructToTime(dt);
   dt.hour=InpAsianEndHour;                       datetime eA=StructToTime(dt);
   int sb=iBarShift(_Symbol,PERIOD_M15,sA,false);
   int eb=iBarShift(_Symbol,PERIOD_M15,eA,false);
   if(sb<0||eb<0||sb<=eb) return;
   int cnt=sb-eb;
   int hi=iHighest(_Symbol,PERIOD_M15,MODE_HIGH,cnt,eb);
   int lo=iLowest(_Symbol,PERIOD_M15,MODE_LOW,cnt,eb);
   if(hi<0||lo<0) return;
   g_AsianHigh=iHigh(_Symbol,PERIOD_M15,hi);
   g_AsianLow=iLow(_Symbol,PERIOD_M15,lo);
   g_AsianCalculated=true;
   Print("[ASIAN] H:",DoubleToString(g_AsianHigh,_Digits)," L:",DoubleToString(g_AsianLow,_Digits));
  }

void Execute()
  {
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(ask<=0||bid<=0||bid>=ask) return;
   double spread=ask-bid; double spreadBuf=spread*InpSpreadBufferMult;
   double atr[1];
   if(CopyBuffer(g_ATRHandle,0,1,1,atr)<1||atr[0]<=0) return;
   double pH=iHigh(_Symbol,PERIOD_M1,1);
   double pL=iLow(_Symbol,PERIOD_M1,1);
   if(pH<=0||pL<=0) return;

   if(pH>g_AsianHigh&&iClose(_Symbol,PERIOD_M1,0)<iOpen(_Symbol,PERIOD_M1,1))
     {
      double entry=bid;
      int si=iHighest(_Symbol,PERIOD_M1,MODE_HIGH,InpMSSLookback,1);
      double swH=iHigh(_Symbol,PERIOD_M1,si);
      if(swH<=entry) return;
      double sl=NormalizeDouble(swH+atr[0]+spreadBuf,_Digits);
      double tp=NormalizeDouble(entry-(sl-entry)*InpRiskRewardRatio,_Digits);
      if(tp>=entry) return;
      double lots=CalcLots(entry,sl);
      if(lots<=0) return;
      if(g_trade.Sell(lots,_Symbol,entry,sl,tp,"Shadow5 SELL"))
         Print("[SELL] E:",DoubleToString(entry,_Digits)," SL:",DoubleToString(sl,_Digits)," TP:",DoubleToString(tp,_Digits)," Lots:",DoubleToString(lots,2));
      else Print("[ERR] SELL:",GetLastError());
     }
   else if(pL<g_AsianLow&&iClose(_Symbol,PERIOD_M1,0)>iOpen(_Symbol,PERIOD_M1,1))
     {
      double entry=ask;
      int si=iLowest(_Symbol,PERIOD_M1,MODE_LOW,InpMSSLookback,1);
      double swL=iLow(_Symbol,PERIOD_M1,si);
      if(swL>=entry) return;
      double sl=NormalizeDouble(swL-atr[0]-spreadBuf,_Digits);
      double tp=NormalizeDouble(entry+(entry-sl)*InpRiskRewardRatio,_Digits);
      if(tp<=entry) return;
      double lots=CalcLots(entry,sl);
      if(lots<=0) return;
      if(g_trade.Buy(lots,_Symbol,entry,sl,tp,"Shadow5 BUY"))
         Print("[BUY] E:",DoubleToString(entry,_Digits)," SL:",DoubleToString(sl,_Digits)," TP:",DoubleToString(tp,_Digits)," Lots:",DoubleToString(lots,2));
      else Print("[ERR] BUY:",GetLastError());
     }
  }

bool HasOpen()
  {
   for(int i=0;i<PositionsTotal();i++)
      if(PositionGetSymbol(i)==_Symbol&&PositionGetInteger(POSITION_MAGIC)==InpMagicNumber) return true;
   return false;
  }

void CloseAll()
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong t=PositionGetTicket(i);
      if(t>0&&PositionGetString(POSITION_SYMBOL)==_Symbol&&PositionGetInteger(POSITION_MAGIC)==InpMagicNumber)
         g_trade.PositionClose(t);
     }
  }

double CalcLots(double entry,double sl)
  {
   double balance=AccountInfoDouble(ACCOUNT_BALANCE);
   if(balance<=0) return 0;
   double riskAmt=balance*(RISK_PCT/100.0); // 0.30% LOCKED
   double tickSz=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tickVal=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tickSz<=0||tickVal<=0) return 0;
   double slDist=MathAbs(entry-sl);
   if(slDist<=0) return 0;
   double slTicks=slDist/tickSz;
   double lots=riskAmt/(slTicks*tickVal);
   double minL=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxL=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) step=0.01;
   lots=MathFloor(lots/step)*step;
   lots=MathMax(lots,minL); lots=MathMin(lots,maxL);
   double actual=slTicks*tickVal*lots;
   if(actual>riskAmt*1.05){lots=MathFloor((riskAmt/(slTicks*tickVal))/step)*step;lots=MathMax(lots,minL);}
   return lots;
  }
//+------------------------------------------------------------------+
