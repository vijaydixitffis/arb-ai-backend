export interface LLMResponse {
  content: string
  tokensUsed: number
}

// Strip markdown code fences that some LLMs wrap around JSON output, then parse.
// With Gemini's responseMimeType: 'application/json' the output is already clean,
// but this guard handles any provider that adds fences.
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

export async function callLLM(input: LLMCallInput): Promise<LLMResponse> {
  const { systemPrompt, userPrompt, model } = input

  if (model.startsWith('gemini')) {
    const apiKey = Deno.env.get('GEMINI_API_KEY')
    if (!apiKey) throw new Error('GEMINI_API_KEY is not set')
    return await callGemini(systemPrompt, userPrompt, model, apiKey)
  } else if (model.startsWith('gpt')) {
    const apiKey = Deno.env.get('OPENAI_API_KEY')
    if (!apiKey) throw new Error('OPENAI_API_KEY is not set')
    return await callOpenAI(systemPrompt, userPrompt, model, apiKey)
  } else if (model.startsWith('claude')) {
    const apiKey = Deno.env.get('ANTHROPIC_API_KEY')
    if (!apiKey) throw new Error('ANTHROPIC_API_KEY is not set')
    return await callAnthropic(systemPrompt, userPrompt, model, apiKey)
  } else {
    throw new Error(`Unsupported model: ${model}`)
  }
}

// ── Gemini ────────────────────────────────────────────────────────────────────
// Docs: https://ai.google.dev/api/generate-content
// responseMimeType: 'application/json' enforces structured JSON output (no fences).
// Free tier: gemini-2.5-flash-lite → 15 RPM / 1000 RPD.

async function callGemini(
  systemPrompt: string,
  userPrompt: string,
  model: string,
  apiKey: string
): Promise<LLMResponse> {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`

  const response = await fetch(url, {
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
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Gemini API error: ${response.status} - ${error}`)
  }

  const data = await response.json()

  // Guard against safety blocks or empty candidates
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

// ── OpenAI ────────────────────────────────────────────────────────────────────

async function callOpenAI(
  systemPrompt: string,
  userPrompt: string,
  model: string,
  apiKey: string
): Promise<LLMResponse> {
  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user',   content: userPrompt   },
      ],
      temperature:     0.5,
      max_tokens:      16384,
      response_format: { type: 'json_object' },
    }),
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`OpenAI API error: ${response.status} - ${error}`)
  }

  const data      = await response.json()
  const content   = data.choices[0].message.content as string
  const tokensUsed = data.usage.total_tokens as number

  return { content, tokensUsed }
}

// ── Anthropic ─────────────────────────────────────────────────────────────────

async function callAnthropic(
  systemPrompt: string,
  userPrompt: string,
  model: string,
  apiKey: string
): Promise<LLMResponse> {
  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key':         apiKey,
      'Content-Type':      'application/json',
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      max_tokens: 16384,
      system:     systemPrompt,
      messages: [
        { role: 'user', content: userPrompt },
      ],
    }),
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Anthropic API error: ${response.status} - ${error}`)
  }

  const data       = await response.json()
  const content    = data.content[0].text as string
  const tokensUsed = (data.usage.input_tokens + data.usage.output_tokens) as number

  return { content, tokensUsed }
}
