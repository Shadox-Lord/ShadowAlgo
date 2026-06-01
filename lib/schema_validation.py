"""
Shadow AI Trading System - Pydantic Schema Validation
======================================================

CRITICAL FIX #3: JSON Schema Validation for LLM Outputs
Enforces strict typing on all agent outputs to prevent hallucination-induced logic breaks.

Without this, a single malformed field (e.g., confidence: "high" instead of 0.82) 
can break downstream logic and cause uncontrolled risk exposure.
"""

from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


class TradeDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = None


class AgentConfidenceLevel(str, Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class MarketStructureSignal(BaseModel):
    """
    PRIMARY OUTPUT SCHEMA: Main LLM analysis output
    All fields are strictly typed with validation rules
    """
    
    # Core decision fields
    structure_valid: bool = Field(
        ..., 
        description="Whether the SMC structure passes all validation checks",
        example=False
    )
    
    direction: Optional[Literal["BUY", "SELL"]] = Field(
        None,
        description="Trade direction if valid, null otherwise",
        example="BUY"
    )
    
    confidence: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Confidence score 0-100",
        example=75.5
    )
    
    # Price levels
    entry: Optional[float] = Field(
        None,
        gt=0,
        description="Entry price level",
        example=1.0850
    )
    
    stop_loss: Optional[float] = Field(
        None,
        gt=0,
        description="Stop loss price level",
        example=1.0800
    )
    
    take_profit: Optional[float] = Field(
        None,
        gt=0,
        description="Take profit price level",
        example=1.0950
    )
    
    # Risk metrics
    rr_ratio: float = Field(
        ...,
        ge=0.0,
        description="Risk-to-reward ratio",
        example=2.0
    )
    
    # Structure confirmation flags
    liquidity_sweep: bool = Field(
        ...,
        description="Confirmed liquidity sweep (stop hunt) detected",
        example=True
    )
    
    bos_confirmed: bool = Field(
        ...,
        description="Break of Structure confirmed",
        example=True
    )
    
    mitigation_present: bool = Field(
        ...,
        description="Mitigation present (FVG fill or OB test)",
        example=True
    )
    
    # Metadata
    reasoning: str = Field(
        ...,
        max_length=200,
        description="Concise reasoning for the decision",
        example="Bullish order block with sweep+BOS, RR=2.5"
    )
    
    risk_factors: List[str] = Field(
        default_factory=list,
        description="List of identified risk factors",
        example=["High impact news in 2h", "Low ADX"]
    )
    
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO timestamp of analysis",
        example="2024-01-15T14:30:00Z"
    )
    
    @model_validator(mode='after')
    def validate_direction_requires_levels(self):
        """If direction is set, entry/SL/TP must be provided"""
        if self.direction is not None:
            if self.entry is None or self.stop_loss is None or self.take_profit is None:
                raise ValueError("Direction requires entry, stop_loss, and take_profit")
        return self
    
    @field_validator('rr_ratio')
    @classmethod
    def validate_minimum_rr(cls, v):
        """Enforce minimum 1:2 RR as per strategy rules"""
        if v < 2.0 and v > 0:
            raise ValueError("RR ratio must be >= 2.0 for valid trades")
        return v
    
    @model_validator(mode='after')
    def validate_confidence_threshold(self):
        """If confidence < 70, structure must be invalid"""
        if self.confidence >= 70 and not self.structure_valid:
            raise ValueError("Confidence >= 70 requires structure_valid=true")
        if self.confidence < 70 and self.structure_valid:
            raise ValueError("Confidence < 70 requires structure_valid=false")
        return self
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return self.dict()
    
    @classmethod
    def from_json(cls, json_str: str) -> 'MarketStructureSignal':
        """Parse from JSON string with validation"""
        import json
        data = json.loads(json_str)
        return cls(**data)


class StructureValidationRequest(BaseModel):
    """
    INPUT SCHEMA: Request for quick structure validation
    Used for conflict resolution between multiple signals
    """
    
    direction: Literal["BUY", "SELL"] = Field(...)
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    current_price: float = Field(..., gt=0)
    asset: str = Field(..., example="EURUSD")


class StructureValidationResponse(BaseModel):
    """
    OUTPUT SCHEMA: Quick validation response
    """
    
    valid: bool = Field(..., description="Whether setup is valid")
    confidence: float = Field(..., ge=0.0, le=100.0)
    issues: List[str] = Field(default_factory=list)
    recommendation: Literal["ACCEPT", "REJECT", "ADJUST"] = Field(...)
    rr_ratio: float = Field(..., ge=0.0)
    
    @model_validator(mode='after')
    def validate_recommendation_logic(self):
        """Ensure recommendation aligns with validity"""
        if self.valid and self.recommendation == "REJECT":
            raise ValueError("Valid setup cannot have REJECT recommendation")
        if not self.valid and self.recommendation == "ACCEPT":
            raise ValueError("Invalid setup cannot have ACCEPT recommendation")
        return self


class RegimeMetricsOutput(BaseModel):
    """
    OUTPUT SCHEMA: Regime filter results
    """
    
    adx: float = Field(..., ge=0.0, le=100.0)
    atr: float = Field(..., gt=0.0)
    atr_percentile: float = Field(..., ge=0.0, le=100.0)
    regime: Literal["trending_bull", "trending_bear", "ranging", "choppy"]
    is_tradeable: bool
    reason: str = Field(..., max_length=150)


class TradeExecutionSignal(BaseModel):
    """
    FINAL OUTPUT SCHEMA: Executable trade signal
    Combines LLM analysis with regime validation
    """
    
    asset: str = Field(..., example="EURUSD")
    direction: Optional[Literal["BUY", "SELL"]]
    entry: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    confidence: float
    rr_ratio: float
    regime_ok: bool
    structure_valid: bool
    timestamp: str
    reasoning: str
    position_size_lots: Optional[float] = Field(None, ge=0.01)
    risk_amount_usd: Optional[float] = None
    
    @model_validator(mode='after')
    def validate_position_size(self):
        """Position size only required if trade is valid"""
        if self.structure_valid and self.regime_ok and self.position_size_lots is None:
            raise ValueError("Position size required for valid trade signal")
        return self


class LLMAuditTrail(BaseModel):
    """
    AUDIT SCHEMA: Complete audit trail for debugging
    Logs every LLM interaction for post-trade analysis
    """
    
    prompt_hash: str = Field(..., description="SHA256 hash of system prompt")
    model_version: str = Field(..., example="qwen-plus-2024-01-15")
    temperature: float = Field(..., ge=0.0, le=2.0)
    tokens_used: int = Field(..., gt=0)
    raw_response: str = Field(..., description="Raw LLM output before parsing")
    parsed_output: dict = Field(..., description="Parsed and validated output")
    validation_errors: List[str] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    fallback_used: bool = Field(default=False)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def log_to_file(self, filepath: str = "./llm_audit_log.jsonl"):
        """Append audit record to JSONL file"""
        import json
        with open(filepath, 'a') as f:
            f.write(self.json() + '\n')


# ============================================================================
# VALIDATION UTILITIES
# ============================================================================

def validate_llm_response(raw_json: str, schema_type: str = "market_structure") -> dict:
    """
    UNIVERSAL VALIDATOR: Parse and validate any LLM response
    
    Args:
        raw_json: Raw JSON string from LLM
        schema_type: Type of schema to validate against
        
    Returns:
        dict: Validated data or error details
        
    Raises:
        ValidationError: If validation fails
    """
    import json
    
    try:
        # First parse raw JSON
        data = json.loads(raw_json)
        
        # Then validate against appropriate schema
        if schema_type == "market_structure":
            validated = MarketStructureSignal(**data)
        elif schema_type == "validation_response":
            validated = StructureValidationResponse(**data)
        elif schema_type == "regime_metrics":
            validated = RegimeMetricsOutput(**data)
        elif schema_type == "trade_signal":
            validated = TradeExecutionSignal(**data)
        else:
            raise ValueError(f"Unknown schema type: {schema_type}")
        
        return {
            "success": True,
            "data": validated.to_dict() if hasattr(validated, 'to_dict') else validated.dict(),
            "validation_errors": []
        }
        
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"Invalid JSON: {str(e)}",
            "raw_response": raw_json[:500]  # Truncate for logging
        }
    
    except ValidationError as e:
        error_messages = [err['msg'] for err in e.errors()]
        return {
            "success": False,
            "error": "Schema validation failed",
            "validation_errors": error_messages,
            "attempted_data": data if 'data' in locals() else {}
        }


def force_no_trade_fallback(reason: str = "Validation failed") -> dict:
    """
    FALLBACK PROTOCOL: Return safe NO_TRADE signal when validation fails
    
    This prevents hallucinated or malformed outputs from triggering trades
    """
    return {
        "structure_valid": False,
        "direction": None,
        "confidence": 0.0,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "rr_ratio": 0.0,
        "liquidity_sweep": False,
        "bos_confirmed": False,
        "mitigation_present": False,
        "reasoning": f"FALLBACK: {reason}",
        "risk_factors": ["LLM output validation failed"],
        "fallback_used": True
    }


# Example usage in QwenEngine:
"""
from .schema_validation import validate_llm_response, force_no_trade_fallback

# In analyze_market method:
response = self.client.chat.completions.create(...)
content = response.choices[0].message.content

# CRITICAL: Validate before using
validation_result = validate_llm_response(content, "market_structure")

if validation_result["success"]:
    return {"success": True, "data": validation_result["data"]}
else:
    # Log validation failure for audit
    audit_trail = LLMAuditTrail(
        prompt_hash=prompt_hash,
        model_version=self.model,
        temperature=0.3,
        tokens_used=response.usage.total_tokens,
        raw_response=content,
        parsed_output={},
        validation_errors=validation_result.get("validation_errors", []),
        fallback_used=True
    )
    audit_trail.log_to_file()
    
    # Return safe fallback
    return {"success": False, "data": force_no_trade_fallback(validation_result["error"])}
"""
