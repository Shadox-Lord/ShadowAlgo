import os
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from api.lib.supabase_client import get_supabase
from api.lib.telegram_notifier import send_telegram_alert

app = FastAPI(title="ShadowAlgo Trading API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SignalRequest(BaseModel):
    asset: str
    direction: str
    confidence: float
    timeframe: str = "15m"
    strategy: Optional[str] = "manual"

class EstopRequest(BaseModel):
    reason: Optional[str] = "Manual emergency stop triggered via API"

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        "environment": os.getenv("ENVIRONMENT", "unknown")
    }

@app.get("/api/status")
async def system_status():
    supabase = get_supabase()
    open_trades_resp = supabase.table("trades").select("count", count="exact").eq("status", "open").execute()
    open_trades = open_trades_resp.count if hasattr(open_trades_resp, 'count') else 0
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_trades = supabase.table("trades").select("pnl").gte("exit_time", today_start.isoformat()).execute()
    today_pnl = sum(float(t.get("pnl", 0) or 0) for t in today_trades.data) if today_trades.data else 0
    modules_resp = supabase.table("module_states").select("*").execute()
    modules = {m["module_name"]: m["state"] for m in (modules_resp.data or [])}
    signals_resp = supabase.table("signals").select("*").order("created_at", desc=True).limit(5).execute()
    return {
        "environment": os.getenv("ENVIRONMENT", "unknown"),
        "enabled_assets": os.getenv("ENABLED_ASSETS", "").split(","),
        "open_trades": open_trades,
        "today_pnl": round(today_pnl, 2),
        "module_states": modules,
        "recent_signals": signals_resp.data or [],
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/trades")
async def list_trades(limit: int = 20, status: Optional[str] = None, asset: Optional[str] = None):
    supabase = get_supabase()
    query = supabase.table("trades").select("*").order("entry_time", desc=True).limit(limit)
    if status:
        query = query.eq("status", status)
    if asset:
        query = query.eq("asset", asset.upper())
    resp = query.execute()
    return {"trades": resp.data or []}}

@app.get("/api/signals")
async def list_signals(limit: int = 20, triggered: Optional[bool] = None):
    supabase = get_supabase()
    query = supabase.table("signals").select("*").order("created_at", desc=True).limit(limit)
    if triggered is not None:
        query = query.eq("triggered", triggered)
    resp = query.execute()
    return {"signals": resp.data or []}}

@app.get("/api/performance")
async def get_performance(days: int = 30, asset: Optional[str] = None):
    supabase = get_supabase()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    query = supabase.table("trades").select("*").gte("exit_time", since).eq("status", "closed")
    if asset:
        query = query.eq("asset", asset.upper())
    resp = query.execute()
    trades = resp.data or []
    if not trades:
        return {"period_days": days, "total_trades": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0, "max_drawdown": 0, "profit_factor": 0}
    winning = [t for t in trades if float(t.get("pnl", 0) or 0) > 0]
    losing = [t for t in trades if float(t.get("pnl", 0) or 0) <= 0]
    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
    gross_profit = sum(float(t.get("pnl", 0) or 0) for t in winning)
    gross_loss = abs(sum(float(t.get("pnl", 0) or 0) for t in losing))
    return {
        "period_days": days,
        "total_trades": len(trades),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": round(len(winning) / len(trades) * 100, 2) if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(trades), 2) if trades else 0,
        "max_drawdown": 0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else float('inf'),
        "asset": asset or "all"
    }

@app.post("/api/estop")
async def emergency_stop(req: EstopRequest):
    supabase = get_supabase()
    supabase.table("system_logs").insert({
        "level": "error",
        "module": "api_estop",
        "message": req.reason,
        "metadata": {"source": "api", "timestamp": datetime.utcnow().isoformat()}
    }).execute()
    try:
        send_telegram_alert(f"EMERGENCY STOP TRIGGERED\nReason: {req.reason}\nAll positions should be liquidated.")
    except Exception:
        pass
    return {
        "status": "estop_executed",
        "message": "Emergency stop triggered. All modules should halt.",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/signal")
async def create_signal(signal: SignalRequest):
    supabase = get_supabase()
    data = {
        "asset": signal.asset.upper(),
        "direction": signal.direction,
        "confidence": signal.confidence,
        "timeframe": signal.timeframe,
        "strategy": signal.strategy,
        "kronos_approved": False,
        "qwen_approved": False,
        "triggered": False,
        "metadata": {"source": "api_manual"}
    }
    resp = supabase.table("signals").insert(data).execute()
    if resp.data:
        return {"signal": resp.data[0], "message": "Signal created successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to create signal")

@app.get("/api/logs")
async def get_logs(limit: int = 50, level: Optional[str] = None, module: Optional[str] = None):
    supabase = get_supabase()
    query = supabase.table("system_logs").select("*").order("created_at", desc=True).limit(limit)
    if level:
        query = query.eq("level", level)
    if module:
        query = query.eq("module", module)
    resp = query.execute()
    return {"logs": resp.data or []}