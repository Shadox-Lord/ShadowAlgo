import os
import json
from datetime import datetime
from api.lib.supabase_client import get_supabase

def handler(request):
    supabase = get_supabase()
    enabled_assets = os.getenv("ENABLED_ASSETS", "NQ,XAUUSD,EURUSD,GBPUSD,USJPY,AUDUSD").split(",")
    results = []
    for asset in enabled_assets:
        asset = asset.strip()
        if not asset:
            continue
        module_state = supabase.table("module_states").select("state").eq("module_name", "signal_generator").execute()
        if module_state.data and module_state.data[0]["state"] == "paused":
            continue
        supabase.table("system_logs").insert({
            "level": "info",
            "module": "cron_signal_check",
            "message": f"Checking signals for {asset}",
            "metadata": {"asset": asset, "environment": os.getenv("ENVIRONMENT", "PAPER")}
        }).execute()
        results.append({"asset": asset, "checked": True})
    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "ok",
            "assets_checked": len(results),
            "timestamp": datetime.utcnow().isoformat()
        })
    }