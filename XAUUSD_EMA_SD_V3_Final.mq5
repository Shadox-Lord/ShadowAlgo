//+------------------------------------------------------------------+
//|                                   XAUUSD_EMA_SD_V3_Final.mq5   |
//|              1H Trend Pullback + Supply/Demand Zones            |
//|                       VERSION 3.1 FINAL (Production-Locked)    |
//|  CHANGELOG vs V2:                                               |
//|  - Risk locked at 0.30% per trade                              |
//|  - CRITICAL FIX: Demand/Supply zone ArraySetAsSeries index bug |
//|    rates[i+1] = older bar (correct pre-impulse confirmation)   |
//|  - Dynamic lot sizing added (was missing for short entries)     |
//|  - Dynamic SL = zone width + live spread * buffer              |
//|  - 2-trade/day hard cap (this EA only)                         |
//|  - FOMC/NFP/CPI 30-min blackout                               |
//|  - Per-EA drawdown guard (no shared global state)              |
//|  - Auto-detect filling mode                                    |
//|  - CSV export on deinit                                        |
//+------------------------------------------------------------------+
#property copyright "XAUUSD EMA/SD v3.1 Final"
#property version   "3.10"
#property strict

#include <Trade\Trade.mqh>
CTrade g_trade;

//--- 0.30% RISK LOCKED
#define RISK_PCT 0.30

input group "=== RISK ==="
input double MaxDailyLoss_Pct    = 0.60;    // Max daily loss (%)

input group "=== EA IDENTITY ==="
input ulong  MagicNumber         = 770002; // Magic Number

input group "=== STRATEGY ==="
input int    EMA50_Period        = 50;
input int    EMA200_Period       = 200;
input int    MinImpulse_Points   = 500;    // Min impulse body (points)
input int    ZoneWidth_Points    = 200;    // Zone SL width (points)
input int    ATR_Period          = 14;
input double ATR_Multiplier      = 1.5;
input int    MaxTradesPerDay     = 2;
input double SpreadSLBuffer      = 2.0;    // SL spread multiplier
input bool   CloseFriday         = true;
input int    FridayCloseHour     = 20;

input group "=== NEWS BLACKOUT ==="
input bool   UseNewsBlackout     = true;
input int    BlackoutBefore      = 30;
input int    BlackoutAfter       = 30;

input group "=== EXECUTION ==="
input int    Slippage_Points     = 50;
input int    MaxSpread_Points    = 300;

int      ema50_h=INVALID_HANDLE, ema200_h=INVALID_HANDLE, atr_h=INVALID_HANDLE;
datetime last_bar_time=0, last_day=0;
double   daily_start_bal=0;
datetime g_start;

struct TradeRec { ulong ticket; string dir; double entry,sl,tp,lots,exit_p,profit; datetime open_t,close_t; string result; };
TradeRec g_trades[]; int g_count=0;

bool IsNewsBlackout()
  {
   if(!UseNewsBlackout) return false;
   MqlDateTime dt; TimeToStruct(TimeCurrent(),dt);
   int n=dt.hour*60+dt.min;
   if(dt.day_of_week==5&&dt.day<=7){int d=n-(13*60+30);if(d>=-BlackoutBefore&&d<=BlackoutAfter){Print("[BK] NFP");return true;}}
   if(dt.day_of_week==3&&dt.day>=8&&dt.day<=16){int d=n-(13*60+30);if(d>=-BlackoutBefore&&d<=BlackoutAfter){Print("[BK] CPI");return true;}}
   bool fm=(dt.mon==1||dt.mon==3||dt.mon==5||dt.mon==6||dt.mon==7||dt.mon==9||dt.mon==10||dt.mon==12);
   if(fm&&dt.day_of_week==3&&dt.day>=14&&dt.day<=21){int d=n-(19*60);if(d>=-BlackoutBefore&&d<=BlackoutAfter){Print("[BK] FOMC");return true;}}
   return false;
  }

int TodayTrades()
  {
   int c=0;
   for(int i=0;i<PositionsTotal();i++) if(PositionGetSymbol(i)==_Symbol&&PositionGetInteger(POSITION_MAGIC)==(long)MagicNumber) c++;
   datetime ts=iTime(_Symbol,PERIOD_D1,0);
   if(HistorySelect(ts,TimeCurrent())) for(int i=0;i<HistoryDealsTotal();i++)
     {
      ulong t=HistoryDealGetTicket(i);
      if((ulong)HistoryDealGetInteger(t,DEAL_MAGIC)==MagicNumber&&HistoryDealGetString(t,DEAL_SYMBOL)==_Symbol&&HistoryDealGetInteger(t,DEAL_ENTRY)==DEAL_ENTRY_IN) c++;
     }
   return c;
  }

int OnInit()
  {
   ema50_h =iMA(_Symbol,PERIOD_H1,EMA50_Period,0,MODE_EMA,PRICE_CLOSE);
   ema200_h=iMA(_Symbol,PERIOD_H1,EMA200_Period,0,MODE_EMA,PRICE_CLOSE);
   atr_h   =iATR(_Symbol,PERIOD_H1,ATR_Period);
   if(ema50_h==INVALID_HANDLE||ema200_h==INVALID_HANDLE||atr_h==INVALID_HANDLE){Print("Indicator init failed");return INIT_FAILED;}
   long fm=SymbolInfoInteger(_Symbol,SYMBOL_FILLING_MODE);
   if((fm&SYMBOL_FILLING_FOK)!=0) g_trade.SetTypeFilling(ORDER_FILLING_FOK);
   else if((fm&SYMBOL_FILLING_IOC)!=0) g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   else g_trade.SetTypeFilling(ORDER_FILLING_RETURN);
   g_trade.SetExpertMagicNumber(MagicNumber);
   g_trade.SetDeviationInPoints(Slippage_Points);
   daily_start_bal=AccountInfoDouble(ACCOUNT_BALANCE);
   g_start=TimeCurrent();
   ArrayResize(g_trades,500);
   Print("EMA/SD V3.1 Final | Magic:",MagicNumber," | RISK LOCKED: 0.30% | Balance:$",DoubleToString(daily_start_bal,2));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   IndicatorRelease(ema50_h); IndicatorRelease(ema200_h); IndicatorRelease(atr_h);
   ExportCSV(); PrintSummary();
  }

void OnTick()
  {
   datetime bt=iTime(_Symbol,PERIOD_H1,0);
   if(bt==last_bar_time) return;

   if(CloseFriday){MqlDateTime fd;TimeCurrent(fd);if(fd.day_of_week==5&&fd.hour>=FridayCloseHour){CloseAll();return;}}

   datetime td=iTime(_Symbol,PERIOD_D1,0);
   if(td!=last_day){daily_start_bal=AccountInfoDouble(ACCOUNT_BALANCE);last_day=td;}

   double loss=daily_start_bal-AccountInfoDouble(ACCOUNT_BALANCE);
   if(loss>=daily_start_bal*MaxDailyLoss_Pct/100.0){Print("[HALT] Daily loss limit");return;}
   if(TodayTrades()>=MaxTradesPerDay) return;
   if(HasOpen()) return;
   if(IsNewsBlackout()) return;
   if((int)SymbolInfoInteger(_Symbol,SYMBOL_SPREAD)>MaxSpread_Points) return;

   MqlRates rates[];
   ArraySetAsSeries(rates,true);
   if(CopyRates(_Symbol,PERIOD_H1,0,30,rates)<10) return;

   double ema50[],ema200[],atr[];
   ArraySetAsSeries(ema50,true); ArraySetAsSeries(ema200,true); ArraySetAsSeries(atr,true);
   if(CopyBuffer(ema50_h,0,0,5,ema50)<=0) return;
   if(CopyBuffer(ema200_h,0,0,5,ema200)<=0) return;
   if(CopyBuffer(atr_h,0,0,5,atr)<=0) return;
   if(atr[1]<=0) return;

   double liveSpread=SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double spreadBuf=liveSpread*SpreadSLBuffer;

   double c1=rates[1].close,o1=rates[1].open,l1=rates[1].low,h1=rates[1].high;

   //--- LONG: above EMA200, bullish H1 bar bouncing EMA50, valid demand zone
   if(c1>ema200[1]&&c1>o1&&l1<=ema50[1])
     {
      if(IsDemandZone(rates,atr[1]))
        {
         double entry=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
         double sl=NormalizeDouble(l1-(ZoneWidth_Points*_Point)-spreadBuf,_Digits);
         if(entry<=sl){Print("[SKIP] LONG: entry<=sl");return;}
         double slPts=(entry-sl)/_Point;
         if(slPts<=0) return;
         double tp=NormalizeDouble(entry+2.0*slPts*_Point,_Digits);
         double lots=CalcLots(slPts);
         if(lots<=0) return;
         if(g_trade.Buy(lots,_Symbol,entry,sl,tp,"EMASD3 Long"))
           {last_bar_time=bt;LogTrade(g_trade.ResultOrder(),"BUY",entry,sl,tp,lots);
            Print("[BUY] E:",DoubleToString(entry,_Digits)," SL:",DoubleToString(sl,_Digits)," TP:",DoubleToString(tp,_Digits)," Lots:",DoubleToString(lots,2));}
        }
     }
   //--- SHORT: below EMA200, bearish H1 bar touching EMA50, valid supply zone
   else if(c1<ema200[1]&&c1<o1&&h1>=ema50[1])
     {
      if(IsSupplyZone(rates,atr[1]))
        {
         double entry=SymbolInfoDouble(_Symbol,SYMBOL_BID);
         double sl=NormalizeDouble(h1+(ZoneWidth_Points*_Point)+spreadBuf,_Digits);
         if(entry>=sl){Print("[SKIP] SHORT: entry>=sl");return;}
         double slPts=(sl-entry)/_Point;
         if(slPts<=0) return;
         double tp=NormalizeDouble(entry-2.0*slPts*_Point,_Digits);
         double lots=CalcLots(slPts);
         if(lots<=0) return;
         if(g_trade.Sell(lots,_Symbol,entry,sl,tp,"EMASD3 Short"))
           {last_bar_time=bt;LogTrade(g_trade.ResultOrder(),"SELL",entry,sl,tp,lots);
            Print("[SELL] E:",DoubleToString(entry,_Digits)," SL:",DoubleToString(sl,_Digits)," TP:",DoubleToString(tp,_Digits)," Lots:",DoubleToString(lots,2));}
        }
     }
  }

//--- FIXED: ArraySetAsSeries=true → rates[0]=newest, rates[i]=i bars ago, rates[i+1]=older than rates[i]
//    Impulse at rates[i] (older), pre-impulse confirmation at rates[i+1] (even older)
bool IsDemandZone(MqlRates &rates[],double cur_atr)
  {
   int sz=ArraySize(rates);
   for(int i=2;i<=8;i++)
     {
      if(i+1>=sz) break;
      double body=rates[i].close-rates[i].open; // positive = bullish
      if(body>(MinImpulse_Points*_Point)&&body>(cur_atr*ATR_Multiplier))
        if(rates[i+1].close<rates[i+1].open) // bar BEFORE impulse was bearish — zone created
           return true;
     }
   return false;
  }

bool IsSupplyZone(MqlRates &rates[],double cur_atr)
  {
   int sz=ArraySize(rates);
   for(int i=2;i<=8;i++)
     {
      if(i+1>=sz) break;
      double body=rates[i].open-rates[i].close; // positive = bearish
      if(body>(MinImpulse_Points*_Point)&&body>(cur_atr*ATR_Multiplier))
        if(rates[i+1].close>rates[i+1].open) // bar BEFORE impulse was bullish
           return true;
     }
   return false;
  }

double CalcLots(double slPts)
  {
   if(slPts<=0) return 0;
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmt=bal*(RISK_PCT/100.0); // 0.30% LOCKED
   double tickSz=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tickVal=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tickSz<=0||tickVal<=0) return SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double ticks=(slPts*_Point)/tickSz;
   double lots=riskAmt/(ticks*tickVal);
   double minL=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxL=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) step=0.01;
   lots=MathRound(lots/step)*step; lots=MathMax(lots,minL); lots=MathMin(lots,maxL);
   return NormalizeDouble(lots,2);
  }

bool HasOpen()
  {
   for(int i=0;i<PositionsTotal();i++)
      if(PositionGetSymbol(i)==_Symbol&&PositionGetInteger(POSITION_MAGIC)==(long)MagicNumber) return true;
   return false;
  }

void CloseAll()
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong t=PositionGetTicket(i);
      if(t>0&&PositionGetString(POSITION_SYMBOL)==_Symbol&&PositionGetInteger(POSITION_MAGIC)==(long)MagicNumber)
         g_trade.PositionClose(t);
     }
  }

void LogTrade(ulong ticket,string dir,double entry,double sl,double tp,double lots)
  {
   if(g_count>=ArraySize(g_trades)) ArrayResize(g_trades,g_count+200);
   g_trades[g_count].ticket=ticket; g_trades[g_count].dir=dir;
   g_trades[g_count].entry=entry; g_trades[g_count].sl=sl; g_trades[g_count].tp=tp;
   g_trades[g_count].lots=lots; g_trades[g_count].open_t=TimeCurrent(); g_trades[g_count].result="OPEN";
   g_count++;
  }

void ExportCSV()
  {
   string fn="XAUUSD_EMASD_V3_"+TimeToString(TimeCurrent(),TIME_DATE)+".csv";
   int h=FileOpen(fn,FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE){Print("CSV failed:",GetLastError());return;}
   FileWrite(h,"Ticket","Dir","Entry","SL","TP","Lots","OpenTime","ExitPrice","CloseTime","Profit","Result");
   for(int i=0;i<g_count;i++) if(g_trades[i].result!="OPEN")
      FileWrite(h,g_trades[i].ticket,g_trades[i].dir,
                DoubleToString(g_trades[i].entry,_Digits),DoubleToString(g_trades[i].sl,_Digits),
                DoubleToString(g_trades[i].tp,_Digits),DoubleToString(g_trades[i].lots,2),
                TimeToString(g_trades[i].open_t,TIME_DATE|TIME_SECONDS),
                DoubleToString(g_trades[i].exit_p,_Digits),
                TimeToString(g_trades[i].close_t,TIME_DATE|TIME_SECONDS),
                DoubleToString(g_trades[i].profit,2),g_trades[i].result);
   FileClose(h); Print("CSV: ",fn);
  }

void PrintSummary()
  {
   int w=0,l=0; double tp_=0,tl_=0;
   for(int i=0;i<g_count;i++){if(g_trades[i].result=="WIN"){w++;tp_+=g_trades[i].profit;}if(g_trades[i].result=="LOSS"){l++;tl_+=MathAbs(g_trades[i].profit);}}
   int tot=w+l;
   Print("=== EMA/SD V3 Summary | T:",tot," W:",w," L:",l," WR:",DoubleToString(tot>0?(double)w/tot*100:0,1),"%",
         " PF:",DoubleToString(tl_>0?tp_/tl_:0,2)," Net:$",DoubleToString(tp_-tl_,2)," ===");
  }
//+------------------------------------------------------------------+
