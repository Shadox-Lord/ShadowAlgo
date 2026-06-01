# Qwen3.6-Plus Integration Guide

## Overview
This system now uses **Qwen3.6-Plus** (Alibaba's advanced LLM) instead of Claude, accessed via OpenAI-compatible API.

## Why Qwen3.6-Plus?
- **Cost-effective**: ~10x cheaper than Claude-3.5-Sonnet
- **Strong reasoning**: Excellent for financial analysis and structured outputs
- **JSON mode**: Native support for structured JSON responses
- **Low latency**: Fast response times for real-time trading analysis

## Setup Instructions

### Option 1: Alibaba Cloud DashScope (Recommended)

1. **Create Account**: Go to [Alibaba Cloud DashScope](https://dashscope.aliyun.com/)
2. **Get API Key**: Navigate to Console → API Keys
3. **Set Environment Variables in Vercel**:
   ```
   QWEN_API_KEY=your_dashscope_api_key_here
   QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
   QWEN_MODEL=qwen-plus
   ```

### Option 2: OpenRouter (Alternative)

1. **Create Account**: Go to [OpenRouter](https://openrouter.ai/)
2. **Get API Key**: Dashboard → Keys
3. **Set Environment Variables**:
   ```
   QWEN_API_KEY=your_openrouter_api_key
   QWEN_BASE_URL=https://openrouter.ai/api/v1
   QWEN_MODEL=alibaba/qwen-2.5-72b-instruct
   ```

### Option 3: Self-hosted via Ollama/vLLM

For complete control, host Qwen locally:
```bash
ollama run qwen2.5:72b
```
Then set:
```
QWEN_API_KEY=ollama
QWEN_BASE_URL=http://localhost:11434/v1
QWEN_MODEL=qwen2.5:72b
```

## Available Qwen Models

| Model | Context | Best For | Cost (per 1M tokens) |
|-------|---------|----------|---------------------|
| `qwen-plus` | 32K | Balanced performance | ~$0.40 input / $1.20 output |
| `qwen-max` | 32K | Complex reasoning | ~$1.20 input / $4.00 output |
| `qwen-turbo` | 32K | Fast, cheap queries | ~$0.08 input / $0.24 output |

## Testing Your Setup

After deploying to Vercel, test with:
```bash
curl -X POST https://your-vercel-app.vercel.app/api/audit \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","accountBalance":10000,"riskPreference":"moderate"}'
```

Expected response:
```json
{
  "id": "log_xxx",
  "symbol": "BTCUSDT",
  "analysis": {
    "decision": "BUY|SELL|NO_TRADE",
    "confidence": 75,
    "entry_price": 95000,
    "stop_loss": 94000,
    "take_profit": 98000
  }
}
```

## Troubleshooting

### Error: "Missing Qwen API Key"
- Ensure `QWEN_API_KEY` is set in Vercel environment variables
- Redeploy after adding environment variables

### Error: "Invalid API endpoint"
- Check `QWEN_BASE_URL` format (must include `/v1` suffix)
- Verify no trailing slashes

### Error: "Model not found"
- Confirm model name matches provider's catalog
- Try `qwen-plus` as default

## Migration from Claude

Changes made:
1. ✅ Replaced `@anthropic-ai/sdk` with `openai` package
2. ✅ Updated API initialization to use Qwen endpoints
3. ✅ Changed message format (system prompt in messages array)
4. ✅ Enabled JSON response format for structured output
5. ✅ Simplified response parsing (no markdown extraction needed)

No changes needed to frontend code - API route abstraction handles everything.

## Cost Comparison

**Claude-3.5-Sonnet** (previous):
- Input: $3.00 / 1M tokens
- Output: $15.00 / 1M tokens
- Avg cost per analysis: ~$0.15

**Qwen-Plus** (current):
- Input: $0.40 / 1M tokens  
- Output: $1.20 / 1M tokens
- Avg cost per analysis: ~$0.02

**Savings: ~87% reduction in API costs** 🎉
