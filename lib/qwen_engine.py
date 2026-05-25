"""
Shadow AI Trading System - Qwen Engine Integration
Connects to Alibaba DashScope API with compressed failure signatures
"""

import os
import json
from typing import Dict, List, Optional, Any
from openai import OpenAI

from .trading_core import FEW_SHOT_FAILURE_SIGNATURES, MarketRegime


class QwenEngine:
    """
    Core LLM engine using Qwen-Plus via Alibaba DashScope
    Implements compressed few-shot autopsy injection (Patch 3)
    """
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("QWEN_API_KEY")
        self.base_url = base_url or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = os.getenv("QWEN_MODEL", "qwen-plus")
        
        if not self.api_key:
            raise ValueError("QWEN_API_KEY environment variable is required")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def _build_system_prompt(self, asset: str) -> str:
        """
        Build system prompt with compressed failure signatures (Patch 3)
        Uses concise rules instead of raw OHLCV arrays to avoid timeout
        """
        return f"""You are an institutional quantitative analyst specializing in Smart Money Concepts (SMC) for {asset}.

CORE MANDATE:
- Identify high-probability AMD (Accumulation-Manipulation-Distribution) setups
- ONLY validate structures with confirmed liquidity sweep + BOS + mitigation
- Enforce minimum 1:2.0 Risk-to-Reward ratio
- Default to NO_TRADE when uncertain

{FEW_SHOT_FAILURE_SIGNATURES}

RESPONSE FORMAT:
You MUST return a valid JSON object with this exact structure:
{{
  "structure_valid": boolean,
  "direction": "BUY" | "SELL" | null,
  "confidence": number (0-100),
  "entry": number,
  "stop_loss": number,
  "take_profit": number,
  "rr_ratio": number,
  "liquidity_sweep": boolean,
  "bos_confirmed": boolean,
  "mitigation_present": boolean,
  "reasoning": "string (max 200 chars)",
  "risk_factors": ["string"]
}}

CRITICAL RULES:
1. If ANY checklist item from FAILURE PATTERNS is violated → structure_valid: false
2. Confidence < 70 → structure_valid: false
3. RR < 2.0 → structure_valid: false
4. No clear sweep+BOS → structure_valid: false
5. When in doubt → NO_TRADE (structure_valid: false, direction: null)

Think step-by-step, then output ONLY the JSON."""

    def analyze_market(self, 
                       asset: str,
                       h4_data: List[Dict],
                       h1_data: List[Dict],
                       macro_context: str = "",
                       regime_status: str = "") -> Dict[str, Any]:
        """
        Analyze market structure using Qwen-Plus
        Returns parsed JSON response or error dict
        """
        # Format OHLCV data concisely (last 20 candles only)
        h4_summary = self._format_ohlcv_summary(h4_data[-20:])
        h1_summary = self._format_ohlcv_summary(h1_data[-20:])
        
        user_prompt = f"""ASSET: {asset}
REGIME STATUS: {regime_status or "Not provided"}

H4 STRUCTURE (Last 20 candles):
{h4_summary}

H1 STRUCTURE (Last 20 candles):
{h1_summary}

MACRO CONTEXT:
{macro_context or "No significant news events"}

Analyze this market structure according to your SMC framework. Remember: precision over frequency. If conditions are not perfect, return NO_TRADE."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._build_system_prompt(asset)},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,  # Low temperature for consistency
                max_tokens=800,
                timeout=8.0  # Keep under Vercel 10s limit
            )
            
            content = response.choices[0].message.content
            parsed = json.loads(content)
            
            # Validate required fields
            required_fields = ["structure_valid", "confidence", "reasoning"]
            for field in required_fields:
                if field not in parsed:
                    parsed[field] = None if field in ["structure_valid"] else 0
            
            return {
                "success": True,
                "data": parsed,
                "model": self.model,
                "tokens_used": response.usage.total_tokens if hasattr(response, 'usage') else 0
            }
            
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON response: {str(e)}",
                "raw_response": content if 'content' in locals() else None
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _format_ohlcv_summary(self, candles: List[Dict]) -> str:
        """Format OHLCV data concisely to save tokens"""
        if not candles:
            return "No data available"
        
        lines = []
        for i, candle in enumerate(candles):
            # Format: [Time] O:price H:price L:price C:price V:vol
            time_str = candle.get('time', '').split('T')[0] if 'T' in str(candle.get('time', '')) else str(candle.get('time', ''))
            line = f"{i+1}. O:{candle.get('open', 0):.5f} H:{candle.get('high', 0):.5f} L:{candle.get('low', 0):.5f} C:{candle.get('close', 0):.5f}"
            lines.append(line)
        
        return "\n".join(lines)
    
    def validate_structure(self, 
                          direction: str,
                          entry: float,
                          sl: float,
                          tp: float,
                          current_price: float) -> Dict[str, Any]:
        """
        Quick validation of a specific trade setup
        Used for conflict resolution (lower RR priority)
        """
        rr_ratio = abs(tp - entry) / abs(sl - entry) if abs(sl - entry) > 0 else 0
        
        prompt = f"""Quick validation check:

Direction: {direction}
Entry: {entry:.5f}
Stop Loss: {sl:.5f}
Take Profit: {tp:.5f}
Current Price: {current_price:.5f}
RR Ratio: {rr_ratio:.2f}

Is this a valid SMC setup? Return JSON:
{{
  "valid": boolean,
  "confidence": number (0-100),
  "issues": ["string"],
  "recommendation": "ACCEPT" | "REJECT" | "ADJUST"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="qwen-turbo",  # Use faster model for simple validation
                messages=[
                    {"role": "system", "content": "You are a risk validation assistant. Be concise and critical."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=300,
                timeout=5.0
            )
            
            content = response.choices[0].message.content
            parsed = json.loads(content)
            
            return {
                "success": True,
                "data": parsed,
                "rr_ratio": rr_ratio
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "rr_ratio": rr_ratio
            }


# Singleton instance for reuse
_engine_instance: Optional[QwenEngine] = None


def get_qwen_engine() -> QwenEngine:
    """Get or create Qwen engine singleton"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = QwenEngine()
    return _engine_instance
