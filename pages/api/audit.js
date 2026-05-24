// Vercel Serverless Function - Secure API Gateway for Anthropic
// Store ANTHROPIC_API_KEY in Vercel Environment Variables (Settings → Environment Variables)

export const config = {
  runtime: 'edge',
};

// Rate limiting store (in production, use Redis or Vercel KV)
const rateLimitStore = new Map();

const RATE_LIMIT_WINDOW_MS = 3600000; // 1 hour
const RATE_LIMIT_MAX_REQUESTS = 10; // 10 requests per hour per IP

function checkRateLimit(ip) {
  const now = Date.now();
  const userRecord = rateLimitStore.get(ip);
  
  if (!userRecord) {
    rateLimitStore.set(ip, { count: 1, windowStart: now });
    return { allowed: true, remaining: RATE_LIMIT_MAX_REQUESTS - 1 };
  }
  
  // Reset window if expired
  if (now - userRecord.windowStart > RATE_LIMIT_WINDOW_MS) {
    rateLimitStore.set(ip, { count: 1, windowStart: now });
    return { allowed: true, remaining: RATE_LIMIT_MAX_REQUESTS - 1 };
  }
  
  // Check if limit exceeded
  if (userRecord.count >= RATE_LIMIT_MAX_REQUESTS) {
    const resetTime = Math.ceil((userRecord.windowStart + RATE_LIMIT_WINDOW_MS - now) / 60000);
    return { 
      allowed: false, 
      remaining: 0,
      resetMinutes: resetTime
    };
  }
  
  // Increment counter
  userRecord.count++;
  rateLimitStore.set(ip, userRecord);
  return { allowed: true, remaining: RATE_LIMIT_MAX_REQUESTS - userRecord.count };
}

export default async function handler(request) {
  // CORS headers
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  };

  // Handle preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 200, headers: corsHeaders });
  }

  // Only allow POST
  if (request.method !== 'POST') {
    return new Response(
      JSON.stringify({ error: 'Method not allowed' }),
      { status: 405, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }

  // Get client IP for rate limiting
  const ip = request.headers.get('x-forwarded-for')?.split(',')[0] || 
             request.headers.get('x-real-ip') || 
             'unknown';

  // Check rate limit
  const rateLimit = checkRateLimit(ip);
  if (!rateLimit.allowed) {
    return new Response(
      JSON.stringify({ 
        error: 'Rate limit exceeded',
        message: `Maximum ${RATE_LIMIT_MAX_REQUESTS} requests per hour. Try again in ${rateLimit.resetMinutes} minutes.`
      }),
      { 
        status: 429, 
        headers: { 
          ...corsHeaders, 
          'Content-Type': 'application/json',
          'X-RateLimit-Reset': rateLimit.resetMinutes.toString()
        } 
      }
    );
  }

  // Verify API key exists in environment
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.error('ANTHROPIC_API_KEY not configured in environment variables');
    return new Response(
      JSON.stringify({ error: 'Server configuration error' }),
      { 
        status: 500, 
        headers: { ...corsHeaders, 'Content-Type': 'application/json' } 
      }
    );
  }

  try {
    // Parse request body
    const body = await request.json();
    
    // Validate required fields
    if (!body.messages || !Array.isArray(body.messages)) {
      return new Response(
        JSON.stringify({ error: 'Invalid request: messages array required' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Prepare Anthropic API request
    const anthropicRequest = {
      model: body.model || 'claude-sonnet-4-20250514',
      max_tokens: body.max_tokens || 1000,
      system: body.system,
      messages: body.messages,
    };

    // Call Anthropic API from server-side (API key never exposed to client)
    const anthropicResponse = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'false',
      },
      body: JSON.stringify(anthropicRequest),
    });

    // Add rate limit headers to response
    const responseHeaders = {
      ...corsHeaders,
      'Content-Type': 'application/json',
      'X-RateLimit-Remaining': rateLimit.remaining.toString(),
    };

    if (!anthropicResponse.ok) {
      const errorData = await anthropicResponse.text();
      console.error(`Anthropic API error: ${anthropicResponse.status}`, errorData);
      
      let errorMessage = 'API request failed';
      if (anthropicResponse.status === 401) {
        errorMessage = 'Invalid API key configuration';
      } else if (anthropicResponse.status === 429) {
        errorMessage = 'Anthropic rate limit exceeded';
      } else if (anthropicResponse.status >= 500) {
        errorMessage = 'Anthropic service temporarily unavailable';
      }

      return new Response(
        JSON.stringify({ error: errorMessage }),
        { 
          status: anthropicResponse.status, 
          headers: responseHeaders 
        }
      );
    }

    const data = await anthropicResponse.json();
    
    // Return successful response
    return new Response(
      JSON.stringify(data),
      { status: 200, headers: responseHeaders }
    );

  } catch (error) {
    console.error('Server error:', error);
    return new Response(
      JSON.stringify({ error: 'Internal server error' }),
      { 
        status: 500, 
        headers: { ...corsHeaders, 'Content-Type': 'application/json' } 
      }
    );
  }
}
