export interface LLMResponse {
  content: string
  tokensUsed: number
}

// Strip markdown code fences that some LLMs wrap around JSON output, then parse.
export function parseJsonFromLLM(raw: string): any {
  const cleaned = raw
    .replace(/^```(?:json)?\s*/m, '')
    .replace(/\s*```\s*$/m, '')
    .trim()
  return JSON.parse(cleaned)
}

export interface LLMCallInput {
  systemPrompt: string
  userPrompt: string
  model: string
}

// ── Retry helper ──────────────────────────────────────────────────────────────
// Retries on transient upstream errors (429 rate-limit, 5xx service errors).
// Backoff: 1s → 2s → 4s with ±500ms jitter to avoid thundering herd.

const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504])
const MAX_RETRIES = 3

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function fetchWithRetry(
  url: string,
  init: RequestInit,
  provider: string,
): Promise<Response> {
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      const delay = Math.pow(2, attempt - 1) * 1000 + Math.random() * 500
      console.warn(`[LLM] ${provider} transient error — retry ${attempt}/${MAX_RETRIES} in ${Math.round(delay)}ms`)
      await sleep(delay)
    }
    const res = await fetch(url, init)
    if (!RETRYABLE_STATUS.has(res.status) || attempt === MAX_RETRIES) return res
  }
  throw new Error(`${provider} unreachable after ${MAX_RETRIES} retries`)
}

// ── Router — driven by LLM_PROVIDER secret ────────────────────────────────────

export async function callLLM(input: LLMCallInput): Promise<LLMResponse> {
  const provider = (Deno.env.get('LLM_PROVIDER') ?? 'gemini').toLowerCase()
  const { systemPrompt, userPrompt, model } = input

  switch (provider) {
    case 'gemini': {
      const apiKey = Deno.env.get('GEMINI_API_KEY')
      if (!apiKey) throw new Error('GEMINI_API_KEY secret is not set')
      return await callGemini(systemPrompt, userPrompt, model, apiKey)
    }
    case 'openai':
      throw new Error('OpenAI provider is not yet implemented — set LLM_PROVIDER=gemini')
    case 'anthropic':
      throw new Error('Anthropic provider is not yet implemented — set LLM_PROVIDER=gemini')
    default:
      throw new Error(`Unknown LLM_PROVIDER value: "${provider}" — expected gemini`)
  }
}

// ── Gemini ────────────────────────────────────────────────────────────────────
// Docs: https://ai.google.dev/api/generate-content
// responseMimeType: 'application/json' enforces structured JSON output (no fences).

async function callGemini(
  systemPrompt: string,
  userPrompt: string,
  model: string,
  apiKey: string
): Promise<LLMResponse> {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`

  const response = await fetchWithRetry(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      system_instruction: {
        parts: [{ text: systemPrompt }],
      },
      contents: [
        {
          role: 'user',
          parts: [{ text: userPrompt }],
        },
      ],
      generationConfig: {
        temperature: 0.5,
        maxOutputTokens: 16384,
        responseMimeType: 'application/json',
      },
    }),
  }, 'Gemini')

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Gemini API error: ${response.status} - ${error}`)
  }

  const data = await response.json()

  const candidate = data.candidates?.[0]
  if (!candidate) {
    const reason = data.promptFeedback?.blockReason ?? 'unknown'
    throw new Error(`Gemini returned no candidates (blockReason: ${reason})`)
  }
  if (candidate.finishReason === 'SAFETY') {
    throw new Error('Gemini response blocked by safety filters')
  }

  const content    = candidate.content.parts[0].text as string
  const tokensUsed = (data.usageMetadata?.totalTokenCount as number) ?? 0

  return { content, tokensUsed }
}

// ── OpenAI (placeholder) ──────────────────────────────────────────────────────
// Not implemented. To enable: set LLM_PROVIDER=openai and implement callOpenAI.

// ── Anthropic (placeholder) ───────────────────────────────────────────────────
// Not implemented. To enable: set LLM_PROVIDER=anthropic and implement callAnthropic.
