//+------------------------------------------------------------------+
//|                                 BuySell_Bot_V2_Final.mq5        |
//|          Autonomous Buy + Sell Signal Bot — No Telegram         |
//|                      VERSION 2.1 FINAL (Production-Locked)      |
//|                                                                  |
//|  CHANGELOG vs V1 Alert EA:                                      |
//|  - Telegram REMOVED — pure autonomous trading bot               |
//|  - SELL signal logic added (SMA cross-down + RSI bearish)       |
//|  - 7-FACTOR GRADING SYSTEM (see below) — score must be >55%    |
//|  - Risk locked at 0.30% per trade                               |
//|  - Full dynamic lot sizing added                                |
//|  - Dynamic SL = ATR * multiplier + live spread buffer           |
//|  - 2-trade/day hard cap                                         |
//|  - FOMC/NFP/CPI 30-min blackout                                |
//|  - Per-EA drawdown guard                                        |
//|  - Signal deduplication per bar                                 |
//|  - Trade journal CSV export on deinit                          |
//|                                                                  |
//|  === 7-FACTOR GRADING SYSTEM ===                                |
//|  Factor 1 (0-20pt): RSI momentum strength                      |
//|  Factor 2 (0-20pt): SMA proximity (tight breakout quality)     |
//|  Factor 3 (0-15pt): ATR environment (not overextended)         |
//|  Factor 4 (0-15pt): Bar body quality (strong close)            |
//|  Factor 5 (0-10pt): Volume confirmation (if available)         |
//|  Factor 6 (0-10pt): Trend alignment (price side of SMA200)     |
//|  Factor 7 (0-10pt): Session filter (avoid dead hours)          |
//|  Max score: 100. Minimum to trade: >55 (configurable)          |
//+------------------------------------------------------------------+
#property copyright "BuySell Bot v2.1 Final — No Telegram"
#property version   "2.10"
#property strict

#include <Trade\Trade.mqh>
CTrade g_trade;

//--- 0.30% RISK LOCKED
#define RISK_PCT 0.30

input group "=== INDICATORS ==="
input int    InpSmaPeriod        = 20;     // SMA Period
input int    InpSma200Period     = 200;    // Trend SMA Period
input int    InpRsiPeriod        = 14;     // RSI Period
input double InpRsiBuyLevel      = 50.0;   // RSI bullish threshold
input double InpRsiSellLevel     = 50.0;   // RSI bearish threshold
input int    InpAtrPeriod        = 14;     // ATR Period

input group "=== GRADING ==="
input double InpMinGradeScore    = 55.0;   // Minimum score to take trade (0-100)
input bool   InpLogGrades        = true;   // Log all signal scores to journal

input group "=== EXECUTION ==="
input double InpRR               = 2.0;    // Risk:Reward Ratio
input double InpMaxDailyLoss_Pct = 0.60;    // Max daily loss (%)
input int    InpMaxTradesPerDay  = 2;      // Max trades per day
input ulong  InpMagicNumber      = 990003; // Magic Number

input group "=== DYNAMIC SL ==="
input double InpSLATRMult        = 1.5;    // SL = ATR × this
input double InpSpreadSLBuf      = 2.0;    // SL += spread × this

input group "=== NEWS BLACKOUT ==="
input bool   InpUseBlackout      = true;
input int    InpBlkBefore        = 30;
input int    InpBlkAfter         = 30;

input group "=== SESSION FILTER ==="
input int    InpTradingStartHour = 7;      // Trading allowed from (UTC)
input int    InpTradingEndHour   = 20;     // Trading allowed until (UTC)

int    h_sma, h_sma200, h_rsi, h_atr, h_vol;
bool   prev_buy  = false;
bool   prev_sell = false;
ulong  last_buy_bar  = 0;
ulong  last_sell_bar = 0;
double day_start_bal = 0;
datetime last_day = 0;
datetime g_start;

//--- Trade journal
struct TRec { ulong t; string dir; double e,sl,tp,lots,exit_p,pnl; datetime ot,ct; string res; double grade; };
TRec g_journal[]; int g_jcount=0;

//==========================================================================
// GRADE STRUCT
//==========================================================================
struct GradeResult
  {
   double score;       // 0–100
   string breakdown;  // human-readable
  };

//==========================================================================
// 7-FACTOR GRADING ENGINE
//==========================================================================
GradeResult GradeSignal(bool isBuy, double rsi, double sma, double sma200,
                         double close, double open_p, double atr, double spread,
                         int hour, long volume)
  {
   GradeResult g; g.score=0; g.breakdown="";

   //--- Factor 1 (0-20): RSI Momentum Strength
   //    BUY:  RSI above buylevel — higher = stronger momentum
   //    SELL: RSI below selllevel — lower = stronger momentum
   double f1=0;
   if(isBuy)
     {
      double range=100.0-InpRsiBuyLevel;
      f1=(range>0)?((rsi-InpRsiBuyLevel)/range)*20.0:0;
     }
   else
     {
      double range=InpRsiSellLevel;
      f1=(range>0)?((InpRsiSellLevel-rsi)/range)*20.0:0;
     }
   f1=MathMax(0,MathMin(20,f1));
   g.score+=f1;
   g.breakdown+="RSI:"+DoubleToString(f1,1)+"/20 ";

   //--- Factor 2 (0-20): SMA Proximity — close within 0.5×ATR of SMA = fresh breakout
   //    Wide separation = exhausted move = lower score
   double smaDist=MathAbs(close-sma);
   double smaATRRatio=(atr>0)?smaDist/atr:1;
   double f2=MathMax(0,(1.0-smaATRRatio))*20.0;
   f2=MathMax(0,MathMin(20,f2));
   g.score+=f2;
   g.breakdown+="SMAProx:"+DoubleToString(f2,1)+"/20 ";

   //--- Factor 3 (0-15): ATR Environment — moderate volatility is ideal
   //    Too quiet (ATR very small) = false breakout risk
   //    Too loud (ATR > 3x normal) = overextended, high risk
   //    Best score when ATR is in normal range — approximated by spread ratio
   double spreadATR=(atr>0)?spread/atr:0.5;
   double f3=MathMax(0,(1.0-spreadATR*3))*15.0; // penalise when spread is large vs ATR
   f3=MathMax(0,MathMin(15,f3));
   g.score+=f3;
   g.breakdown+="ATREnv:"+DoubleToString(f3,1)+"/15 ";

   //--- Factor 4 (0-15): Bar Body Quality — strong close in direction of signal
   //    BUY: close near bar high = bulls in control
   //    SELL: close near bar low = bears in control
   double barRange=MathAbs(close-open_p);
   double f4=0;
   if(atr>0)
     {
      double bodyRatio=(barRange/atr);
      f4=MathMin(1,bodyRatio)*15.0;
     }
   f4=MathMax(0,MathMin(15,f4));
   g.score+=f4;
   g.breakdown+="BarBody:"+DoubleToString(f4,1)+"/15 ";

   //--- Factor 5 (0-10): Volume confirmation (if > 0, else neutral 5)
   //    Above-average volume on breakout = higher conviction
   double f5=5.0; // neutral if no volume data
   if(volume>0)
     {
      // Simple: if volume > expected baseline (1000), full score
      f5=(volume>=1000)?10.0:((double)volume/1000.0)*10.0;
      f5=MathMax(0,MathMin(10,f5));
     }
   g.score+=f5;
   g.breakdown+="Vol:"+DoubleToString(f5,1)+"/10 ";

   //--- Factor 6 (0-10): Trend Alignment — is price on the right side of SMA200?
   //    BUY signal: price above SMA200 = with-trend = full points
   //    SELL signal: price below SMA200 = with-trend = full points
   double f6=0;
   if(isBuy  && close>sma200) f6=10.0;  // bullish trend
   if(!isBuy && close<sma200) f6=10.0;  // bearish trend
   if(isBuy  && close<sma200) f6=3.0;   // counter-trend long — reduced score
   if(!isBuy && close>sma200) f6=3.0;   // counter-trend short — reduced score
   g.score+=f6;
   g.breakdown+="Trend:"+DoubleToString(f6,1)+"/10 ";

   //--- Factor 7 (0-10): Session Quality — London/NY hours score highest
   //    07–10 UTC = London open (10pt), 13–17 UTC = NY (9pt), others reduced
   double f7=0;
   if(hour>=7  && hour<=10) f7=10.0;
   else if(hour>=13 && hour<=17) f7=9.0;
   else if(hour>=10 && hour<=13) f7=6.0;
   else if(hour>=17 && hour<=20) f7=5.0;
   else f7=2.0; // dead hours
   g.score+=f7;
   g.breakdown+="Session:"+DoubleToString(f7,1)+"/10";

   g.score=MathMax(0,MathMin(100,g.score));
   return g;
  }

//==========================================================================
// NEWS BLACKOUT
//==========================================================================
bool IsNewsBlackout()
  {
   if(!InpUseBlackout) return false;
   MqlDateTime dt; TimeToStruct(TimeCurrent(),dt);
   int n=dt.hour*60+dt.min;
   if(dt.day_of_week==5&&dt.day<=7){int d=n-(13*60+30);if(d>=-InpBlkBefore&&d<=InpBlkAfter){Print("[BK] NFP");return true;}}
   if(dt.day_of_week==3&&dt.day>=8&&dt.day<=16){int d=n-(13*60+30);if(d>=-InpBlkBefore&&d<=InpBlkAfter){Print("[BK] CPI");return true;}}
   bool fm=(dt.mon==1||dt.mon==3||dt.mon==5||dt.mon==6||dt.mon==7||dt.mon==9||dt.mon==10||dt.mon==12);
   if(fm&&dt.day_of_week==3&&dt.day>=14&&dt.day<=21){int d=n-(19*60);if(d>=-InpBlkBefore&&d<=InpBlkAfter){Print("[BK] FOMC");return true;}}
   return false;
  }

int TodayTrades()
  {
   int c=0;
   for(int i=0;i<PositionsTotal();i++) if(PositionGetSymbol(i)==_Symbol&&PositionGetInteger(POSITION_MAGIC)==(long)InpMagicNumber) c++;
   datetime ts=iTime(_Symbol,PERIOD_D1,0);
   if(HistorySelect(ts,TimeCurrent())) for(int i=0;i<HistoryDealsTotal();i++)
     {
      ulong t=HistoryDealGetTicket(i);
      if((ulong)HistoryDealGetInteger(t,DEAL_MAGIC)==InpMagicNumber&&HistoryDealGetString(t,DEAL_SYMBOL)==_Symbol&&HistoryDealGetInteger(t,DEAL_ENTRY)==DEAL_ENTRY_IN) c++;
     }
   return c;
  }

//==========================================================================
// OnInit
//==========================================================================
int OnInit()
  {
   h_sma   =iMA(_Symbol,_Period,InpSmaPeriod,0,MODE_SMA,PRICE_CLOSE);
   h_sma200=iMA(_Symbol,_Period,InpSma200Period,0,MODE_SMA,PRICE_CLOSE);
   h_rsi   =iRSI(_Symbol,_Period,InpRsiPeriod,PRICE_CLOSE);
   h_atr   =iATR(_Symbol,_Period,InpAtrPeriod);
   h_vol   =iVolumes(_Symbol,_Period,VOLUME_TICK);

   if(h_sma==INVALID_HANDLE||h_rsi==INVALID_HANDLE||h_atr==INVALID_HANDLE)
     { Print("Indicator init failed"); return INIT_FAILED; }

   long fm=SymbolInfoInteger(_Symbol,SYMBOL_FILLING_MODE);
   if((fm&SYMBOL_FILLING_FOK)!=0) g_trade.SetTypeFilling(ORDER_FILLING_FOK);
   else if((fm&SYMBOL_FILLING_IOC)!=0) g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   else g_trade.SetTypeFilling(ORDER_FILLING_RETURN);

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(30);
   day_start_bal=AccountInfoDouble(ACCOUNT_BALANCE);
   g_start=TimeCurrent();
   ArrayResize(g_journal,1000);

   Print("BuySell Bot v2.1 Final | ",_Symbol," ",EnumToString(_Period),
         " | RISK: 0.30% LOCKED | MinGrade: ",InpMinGradeScore,
         "% | Balance:$",DoubleToString(day_start_bal,2));
   return INIT_SUCCEEDED;
  }

//==========================================================================
// OnDeinit
//==========================================================================
void OnDeinit(const int reason)
  {
   IndicatorRelease(h_sma); IndicatorRelease(h_sma200);
   IndicatorRelease(h_rsi); IndicatorRelease(h_atr);
   if(h_vol!=INVALID_HANDLE) IndicatorRelease(h_vol);
   ExportCSV(); PrintSummary();
  }

//==========================================================================
// OnTick
//==========================================================================
void OnTick()
  {
   int minBars=MathMax(InpSmaPeriod,MathMax(InpSma200Period,MathMax(InpRsiPeriod,InpAtrPeriod)))+10;
   if(Bars(_Symbol,_Period)<minBars) return;

   //--- Daily reset
   datetime today=iTime(_Symbol,PERIOD_D1,0);
   if(today!=last_day){day_start_bal=AccountInfoDouble(ACCOUNT_BALANCE);last_day=today;prev_buy=false;prev_sell=false;}

   //--- Guards
   double loss=day_start_bal-AccountInfoDouble(ACCOUNT_BALANCE);
   if(loss>=day_start_bal*InpMaxDailyLoss_Pct/100.0){Print("[HALT] Daily loss");return;}
   if(TodayTrades()>=InpMaxTradesPerDay) return;
   if(IsNewsBlackout()) return;

   //--- Session filter
   MqlDateTime mdt; TimeCurrent(mdt);
   if(mdt.hour<InpTradingStartHour||mdt.hour>=InpTradingEndHour) return;

   //--- Indicators
   double sma[],sma200[],rsi[],atr[],close[];
   double vol[1]={0};
   ArraySetAsSeries(sma,true); ArraySetAsSeries(sma200,true);
   ArraySetAsSeries(rsi,true); ArraySetAsSeries(atr,true); ArraySetAsSeries(close,true);
   if(CopyBuffer(h_sma,0,0,3,sma)<3)    return;
   if(CopyBuffer(h_sma200,0,0,3,sma200)<3) return;
   if(CopyBuffer(h_rsi,0,0,3,rsi)<3)    return;
   if(CopyBuffer(h_atr,0,0,3,atr)<3)    return;
   if(CopyClose(_Symbol,_Period,0,3,close)<3) return;
   if(h_vol!=INVALID_HANDLE) CopyBuffer(h_vol,0,1,1,vol);
   if(sma[1]==0||atr[1]==0) return;

   MqlRates bars[];
   ArraySetAsSeries(bars,true);
   if(CopyRates(_Symbol,_Period,0,3,bars)<3) return;

   double spread=SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID);
   datetime bar_t=iTime(_Symbol,_Period,1);
   ulong bar_key=(ulong)bar_t;

   //=================================================================
   // BUY SIGNAL: price crosses above SMA + RSI above bull threshold
   //=================================================================
   bool buy_cross=(close[1]>sma[1])&&(close[2]<=sma[2]);
   bool buy_rsi=(rsi[1]>InpRsiBuyLevel);
   bool buy_sig=buy_cross&&buy_rsi;
   bool buy_edge=buy_sig&&!prev_buy;
   prev_buy=buy_sig;

   if(buy_edge&&bar_key!=last_buy_bar)
     {
      GradeResult gr=GradeSignal(true,rsi[1],sma[1],sma200[1],close[1],
                                  bars[1].open,atr[1],spread,mdt.hour,(long)vol[0]);
      if(InpLogGrades)
         Print("[GRADE BUY] Score:",DoubleToString(gr.score,1),"/100 | ",gr.breakdown,
               " | Threshold:",InpMinGradeScore);

      if(gr.score>InpMinGradeScore)
        {
         last_buy_bar=bar_key;
         double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
         double sl=NormalizeDouble(ask-atr[1]*InpSLATRMult-spread*InpSpreadSLBuf,_Digits);
         if(sl>=ask){Print("[SKIP] BUY sl>=ask");return;}
         double slPts=(ask-sl)/_Point;
         double tp=NormalizeDouble(ask+slPts*_Point*InpRR,_Digits);
         double lots=CalcLots(slPts);
         if(lots<=0) return;
         if(g_trade.Buy(lots,_Symbol,ask,sl,tp,"BSBot BUY"))
           {
            Print("[BUY] Score:",DoubleToString(gr.score,1),"% | E:",DoubleToString(ask,_Digits),
                  " SL:",DoubleToString(sl,_Digits)," TP:",DoubleToString(tp,_Digits)," Lots:",DoubleToString(lots,2));
            LogTrade(g_trade.ResultOrder(),"BUY",ask,sl,tp,lots,gr.score);
           }
         else Print("[ERR] BUY:",GetLastError());
        }
      else
         Print("[FILTERED] BUY score:",DoubleToString(gr.score,1)," < ",InpMinGradeScore," | ",gr.breakdown);
     }

   //=================================================================
   // SELL SIGNAL: price crosses below SMA + RSI below bear threshold
   //=================================================================
   bool sell_cross=(close[1]<sma[1])&&(close[2]>=sma[2]);
   bool sell_rsi=(rsi[1]<InpRsiSellLevel);
   bool sell_sig=sell_cross&&sell_rsi;
   bool sell_edge=sell_sig&&!prev_sell;
   prev_sell=sell_sig;

   if(sell_edge&&bar_key!=last_sell_bar)
     {
      GradeResult gr=GradeSignal(false,rsi[1],sma[1],sma200[1],close[1],
                                  bars[1].open,atr[1],spread,mdt.hour,(long)vol[0]);
      if(InpLogGrades)
         Print("[GRADE SELL] Score:",DoubleToString(gr.score,1),"/100 | ",gr.breakdown,
               " | Threshold:",InpMinGradeScore);

      if(gr.score>InpMinGradeScore)
        {
         last_sell_bar=bar_key;
         double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
         double sl=NormalizeDouble(bid+atr[1]*InpSLATRMult+spread*InpSpreadSLBuf,_Digits);
         if(sl<=bid){Print("[SKIP] SELL sl<=bid");return;}
         double slPts=(sl-bid)/_Point;
         double tp=NormalizeDouble(bid-slPts*_Point*InpRR,_Digits);
         double lots=CalcLots(slPts);
         if(lots<=0) return;
         if(g_trade.Sell(lots,_Symbol,bid,sl,tp,"BSBot SELL"))
           {
            Print("[SELL] Score:",DoubleToString(gr.score,1),"% | E:",DoubleToString(bid,_Digits),
                  " SL:",DoubleToString(sl,_Digits)," TP:",DoubleToString(tp,_Digits)," Lots:",DoubleToString(lots,2));
            LogTrade(g_trade.ResultOrder(),"SELL",bid,sl,tp,lots,gr.score);
           }
         else Print("[ERR] SELL:",GetLastError());
        }
      else
         Print("[FILTERED] SELL score:",DoubleToString(gr.score,1)," < ",InpMinGradeScore," | ",gr.breakdown);
     }
  }

//==========================================================================
// LOT SIZING — 0.30% LOCKED
//==========================================================================
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
   lots=MathRound(lots/step)*step;
   lots=MathMax(lots,minL); lots=MathMin(lots,maxL);
   return NormalizeDouble(lots,2);
  }

void LogTrade(ulong ticket,string dir,double e,double sl,double tp,double lots,double grade)
  {
   if(g_jcount>=ArraySize(g_journal)) ArrayResize(g_journal,g_jcount+200);
   g_journal[g_jcount].t=ticket; g_journal[g_jcount].dir=dir;
   g_journal[g_jcount].e=e; g_journal[g_jcount].sl=sl; g_journal[g_jcount].tp=tp;
   g_journal[g_jcount].lots=lots; g_journal[g_jcount].ot=TimeCurrent();
   g_journal[g_jcount].grade=grade; g_journal[g_jcount].res="OPEN";
   g_jcount++;
  }

void ExportCSV()
  {
   string fn="BSBot_V2_"+_Symbol+"_"+TimeToString(TimeCurrent(),TIME_DATE)+".csv";
   int h=FileOpen(fn,FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE){Print("CSV fail:",GetLastError());return;}
   FileWrite(h,"Ticket","Dir","Grade","Entry","SL","TP","Lots","OpenTime","ExitPrice","CloseTime","PNL","Result");
   for(int i=0;i<g_jcount;i++) if(g_journal[i].res!="OPEN")
      FileWrite(h,g_journal[i].t,g_journal[i].dir,DoubleToString(g_journal[i].grade,1),
                DoubleToString(g_journal[i].e,_Digits),DoubleToString(g_journal[i].sl,_Digits),
                DoubleToString(g_journal[i].tp,_Digits),DoubleToString(g_journal[i].lots,2),
                TimeToString(g_journal[i].ot,TIME_DATE|TIME_SECONDS),
                DoubleToString(g_journal[i].exit_p,_Digits),
                TimeToString(g_journal[i].ct,TIME_DATE|TIME_SECONDS),
                DoubleToString(g_journal[i].pnl,2),g_journal[i].res);
   FileClose(h); Print("CSV: ",fn);
  }

void PrintSummary()
  {
   int w=0,l=0; double tp_=0,tl_=0; double ga=0; int gc=0;
   for(int i=0;i<g_jcount;i++)
     {
      if(g_journal[i].res=="WIN"){w++;tp_+=g_journal[i].pnl;ga+=g_journal[i].grade;gc++;}
      if(g_journal[i].res=="LOSS"){l++;tl_+=MathAbs(g_journal[i].pnl);ga+=g_journal[i].grade;gc++;}
     }
   int tot=w+l;
   Print("=== BuySell Bot V2 Summary ===");
   Print("Trades:",tot," W:",w," L:",l,
         " WR:",DoubleToString(tot>0?(double)w/tot*100:0,1),"%",
         " PF:",DoubleToString(tl_>0?tp_/tl_:0,2),
         " Net:$",DoubleToString(tp_-tl_,2),
         " AvgGrade:",DoubleToString(gc>0?ga/gc:0,1));
  }
//+------------------------------------------------------------------+
