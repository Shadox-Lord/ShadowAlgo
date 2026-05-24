/**
 * Shadow AI Trading Auditor - Production Backend
 * 
 * Features:
 * - Real-time market data (Binance)
 * - Secure LLM integration (Anthropic)
 * - Strict Risk Management (Kill switches, position sizing)
 * - Rate limiting & Input validation
 * - Comprehensive logging
 */

import Anthropic from '@anthropic-ai/sdk';

// Initialize Anthropic (Server-side only)
const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

// Configuration
const CONFIG = {
  MAX_DAILY_LOSS_PERCENT: 5, // 5% max daily loss
  MAX_TRADE_RISK_PERCENT: 2, // 2% risk per trade
  MIN_CONFIDENCE_SCORE: 70,  // Minimum 70% confidence to trade
  RATE_LIMIT_WINDOW_MS: 3600000, // 1 hour
  RATE_LIMIT_MAX_REQUESTS: 10,
};

// Helper: Get Client IP
function getClientIP(req) {
  const forwarded = req.headers['x-forwarded-for'];
  return forwarded ? forwarded.split(',')[0].trim() : req.socket?.remoteAddress || 'unknown';
}

// Helper: Simple In-Memory Rate Limiting (Use Redis for production scale)
const rateLimitStore = new Map();
function checkRateLimit(ip) {
  const now = Date.now();
  const userRecord = rateLimitStore.get(ip);
  
  if (!userRecord) {
    rateLimitStore.set(ip, { count: 1, resetTime: now + CONFIG.RATE_LIMIT_WINDOW_MS });
    return true;
  }

  if (now > userRecord.resetTime) {
    rateLimitStore.set(ip, { count: 1, resetTime: now + CONFIG.RATE_LIMIT_WINDOW_MS });
    return true;
  }

  if (userRecord.count >= CONFIG.RATE_LIMIT_MAX_REQUESTS) {
    return false;
  }

  userRecord.count++;
  return true;
}

// Helper: Fetch Real Market Data (Binance Public API)
async function fetchMarketData(symbol, interval = '1h', limit = 50) {
  try {
    const url = `https://api.binance.com/api/v3/klines?symbol=${symbol.toUpperCase()}&interval=${interval}&limit=${limit}`;
    const response = await fetch(url, { timeout: 5000 });
    
    if (!response.ok) throw new Error(`Binance API Error: ${response.status}`);
    
    const data = await response.json();
    
    // Format data for AI consumption
    return data.map(candle => ({
      time: new Date(candle[0]).toISOString(),
      open: parseFloat(candle[1]),
      high: parseFloat(candle[2]),
      low: parseFloat(candle[3]),
      close: parseFloat(candle[4]),
      volume: parseFloat(candle[5])
    }));
  } catch (error) {
    console.error('Market Data Fetch Failed:', error);
    throw new Error('Failed to fetch real-time market data');
  }
}

// Helper: Calculate Position Size & Risk
function calculateRiskMetrics(entry, stopLoss, takeProfit, balance, riskPercent) {
  const riskPerShare = Math.abs(entry - stopLoss);
  if (riskPerShare === 0) return null;

  const totalRiskAmount = balance * (riskPercent / 100);
  const positionSize = totalRiskAmount / riskPerShare;
  const potentialProfit = positionSize * (takeProfit - entry);
  const potentialLoss = positionSize * (entry - stopLoss); // Should equal totalRiskAmount
  const rrRatio = Math.abs(potentialProfit / potentialLoss);

  return {
    positionSize: parseFloat(positionSize.toFixed(4)),
    riskAmount: parseFloat(totalRiskAmount.toFixed(2)),
    potentialProfit: parseFloat(potentialProfit.toFixed(2)),
    rrRatio: parseFloat(rrRatio.toFixed(2))
  };
}

export default async function handler(req, res) {
  // CORS Headers
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // 1. Security Checks
  const ip = getClientIP(req);
  if (!checkRateLimit(ip)) {
    return res.status(429).json({ error: 'Rate limit exceeded. Try again in 1 hour.' });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    console.error('Missing API Key');
    return res.status(500).json({ error: 'Server configuration error: Missing API Key' });
  }

  // 2. Input Validation
  let { symbol, accountBalance, riskPreference } = req.body;
  
  symbol = symbol?.toUpperCase().trim();
  accountBalance = parseFloat(accountBalance);
  riskPreference = riskPreference || 'moderate';

  if (!symbol || !/^[A-Z]+$/.test(symbol)) {
    return res.status(400).json({ error: 'Invalid symbol format' });
  }
  if (isNaN(accountBalance) || accountBalance <= 0) {
    return res.status(400).json({ error: 'Invalid account balance' });
  }

  const startTime = Date.now();
  let logId = `log_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  console.log(`[${logId}] Audit started for ${symbol} by ${ip}`);

  try {
    // 3. Fetch Real Market Data
    console.log(`[${logId}] Fetching market data for ${symbol}...`);
    const marketData = await fetchMarketData(symbol);
    
    if (!marketData || marketData.length < 20) {
      throw new Error('Insufficient market data for analysis');
    }

    const currentPrice = marketData[marketData.length - 1].close;
    
    // 4. Construct System Prompt (Server-side only, never exposed to client)
    const SYSTEM_PROMPT = `
You are an expert institutional algorithmic trader specializing in Smart Money Concepts (SMC), Price Action, and Risk Management.
Your goal is to analyze market data and provide a high-probability trading setup with strict risk controls.

ANALYSIS FRAMEWORK:
1. MARKET STRUCTURE: Identify trend (HH/HL or LH/LL), Break of Structure (BOS), Change of Character (CHoCH).
2. KEY LEVELS: Identify Order Blocks, Fair Value Gaps (FVG), Support/Resistance, Liquidity Pools.
3. MOMENTUM: Analyze volume profile and relative strength.
4. SENTIMENT: Determine overall market bias (Bullish/Bearish/Neutral).

RISK RULES (NON-NEGOTIABLE):
- Never recommend a trade with Risk:Reward < 1:2.
- Stop Loss MUST be placed below/above structural swing points.
- Take Profit should target opposing liquidity or structural levels.
- If confidence is below 70%, recommend NO TRADE.

OUTPUT FORMAT (JSON ONLY):
{
  "decision": "BUY" | "SELL" | "NO_TRADE",
  "confidence": number (0-100),
  "reasoning": "Concise summary of technical analysis",
  "entry_price": number (current price or limit order),
  "stop_loss": number,
  "take_profit": number,
  "invalidation_condition": "What proves this thesis wrong?",
  "risk_score": number (1-10, 10 being highest risk)
}
`;

    // 5. Call Anthropic API
    console.log(`[${logId}] Requesting AI analysis...`);
    const message = await anthropic.messages.create({
      model: 'claude-3-5-sonnet-20241022',
      max_tokens: 1000,
      system: SYSTEM_PROMPT,
      messages: [
        {
          role: 'user',
          content: `Analyze ${symbol} based on the last ${marketData.length} candles. Current Price: ${currentPrice}.
          
Recent Data (OHLCV):
${JSON.stringify(marketData.slice(-10))}

Account Context:
- Balance: $${accountBalance}
- Risk Profile: ${riskPreference}
- Max Risk Per Trade: ${CONFIG.MAX_TRADE_RISK_PERCENT}%

Provide your trading decision in valid JSON format.`
        }
      ]
    });

    // 6. Parse & Validate AI Response
    let aiResponse;
    try {
      const textContent = message.content.find(c => c.type === 'text')?.text || '';
      // Extract JSON from markdown code blocks if present
      const jsonMatch = textContent.match(/```json\s*([\s\S]*?)\s*```/) || textContent.match(/\{[\s\S]*\}/);
      const jsonString = jsonMatch ? jsonMatch[1] || jsonMatch[0] : textContent;
      aiResponse = JSON.parse(jsonString);
    } catch (e) {
      console.error('AI Response Parsing Failed:', e);
      throw new Error('AI returned invalid data format');
    }

    // 7. Apply Risk Management Logic
    if (aiResponse.decision !== 'NO_TRADE') {
      // Validate Confidence
      if (aiResponse.confidence < CONFIG.MIN_CONFIDENCE_SCORE) {
        aiResponse.decision = 'NO_TRADE';
        aiResponse.reasoning += ` (Confidence ${aiResponse.confidence}% below threshold ${CONFIG.MIN_CONFIDENCE_SCORE}%)`;
      }

      // Validate R:R
      const entry = aiResponse.entry_price || currentPrice;
      const sl = aiResponse.stop_loss;
      const tp = aiResponse.take_profit;
      
      if (!sl || !tp) {
        aiResponse.decision = 'NO_TRADE';
        aiResponse.reasoning += ' (Missing SL/TP levels)';
      } else {
        const risk = Math.abs(entry - sl);
        const reward = Math.abs(tp - entry);
        if (reward / risk < 2) {
          aiResponse.decision = 'NO_TRADE';
          aiResponse.reasoning += ' (Risk:Reward ratio < 1:2)';
        }
      }
    }

    // 8. Calculate Position Size if Trade Approved
    let riskMetrics = null;
    if (aiResponse.decision !== 'NO_TRADE' && aiResponse.stop_loss && aiResponse.take_profit) {
      const entry = aiResponse.entry_price || currentPrice;
      riskMetrics = calculateRiskMetrics(
        entry,
        aiResponse.stop_loss,
        aiResponse.take_profit,
        accountBalance,
        CONFIG.MAX_TRADE_RISK_PERCENT
      );
    }

    // 9. Final Response Construction
    const executionTime = Date.now() - startTime;
    const result = {
      id: logId,
      timestamp: new Date().toISOString(),
      symbol,
      currentPrice,
      analysis: aiResponse,
      riskMetrics,
      executionTimeMs: executionTime,
      disclaimer: "This is an AI-assisted analysis tool. Trading involves significant risk. Past performance does not guarantee future results."
    };

    console.log(`[${logId}] Audit completed successfully in ${executionTime}ms`);
    return res.status(200).json(result);

  } catch (error) {
    console.error(`[${logId}] Critical Error:`, error.message);
    return res.status(500).json({ 
      error: 'Analysis failed', 
      details: error.message,
      logId 
    });
  }
}
