/** Única saída de inferência do Worker; preserva schema, sem ferramentas nativas. */
export const TEXT_MODEL = "openai/gpt-6-luna";
export class OpenRouterError extends Error {
  readonly code: string;
  readonly retryAfter: number;
  constructor(code: string, retryAfter = 1) { super(code); this.code = code; this.retryAfter = retryAfter; }
}
const transient = new Set([408, 429, 500, 502, 503, 504, 524, 529]);
async function readJson(response: Response): Promise<any> {
  const reader = response.body?.getReader();
  if (!reader) throw new OpenRouterError("openrouter_invalid_response");
  const parts: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const next = await reader.read(); if (next.done) break;
      size += next.value.length; if (size > 512000) throw new OpenRouterError("openrouter_response_too_large");
      parts.push(next.value);
    }
  } finally { await reader.cancel().catch(() => {}); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  return JSON.parse(new TextDecoder().decode(bytes));
}

export async function analyzeWithLuna<T>(text: string, prompt: string, key: string,
  validate: (content: unknown) => T): Promise<T> {
  if (!key?.trim()) throw new OpenRouterError("missing_openrouter_api_key");
  if (!text?.trim()) throw new OpenRouterError("empty_nr_text");
  if (text.length > 120000) throw new OpenRouterError("nr_text_too_large");
  let maxTokens = 4096;
  for (let attempt = 0; attempt < 2; attempt++) {
    const started = Date.now();
    try {
      let response: Response;
      try {
        response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
          method: "POST", redirect: "manual", signal: AbortSignal.timeout(30000),
          headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
          body: JSON.stringify({ model: TEXT_MODEL, reasoning: { effort: "none" }, max_tokens: maxTokens,
            response_format: { type: "json_object" }, provider: { require_parameters: true, data_collection: "deny" },
            messages: [{ role: "system", content: prompt + (attempt ? " Retorne somente JSON valido conforme o contrato." : "") },
              { role: "user", content: text }] }),
        });
      } catch { throw new OpenRouterError("openrouter_unavailable"); }
      if (!response.ok) {
        await response.body?.cancel();
        const raw = Number(response.headers.get("retry-after") ?? "1");
        const delay = Number.isFinite(raw) ? Math.min(60, Math.max(1, Math.ceil(raw))) : 1;
        throw new OpenRouterError(`openrouter_http_${response.status}`, delay);
      }
      let data: any;
      try { data = await readJson(response); }
      catch { throw new OpenRouterError("openrouter_invalid_response"); }
      if (data?.error) {
        const code = Number(data.error.code);
        throw new OpenRouterError(Number.isInteger(code) && code >= 400 && code <= 599 ? `openrouter_http_${code}` : "openrouter_invalid_response");
      }
      const choice = data?.choices?.[0];
      if (data?.choices?.length !== 1 || choice?.finish_reason !== "stop" || choice?.message?.tool_calls?.length) {
        if (choice?.finish_reason === "length") maxTokens = 8192;
        throw new OpenRouterError("openrouter_invalid_response");
      }
      let result: T;
      try { result = validate(choice.message?.content); }
      catch { throw new OpenRouterError("openrouter_invalid_response"); }
      const usage = Object.fromEntries(Object.entries(data.usage ?? {}).filter(([k, v]) =>
        ["prompt_tokens", "completion_tokens", "total_tokens", "cost"].includes(k) && typeof v === "number" && Number.isFinite(v)));
      console.log(JSON.stringify({ event: "openrouter_usage", model: TEXT_MODEL, durationMs: Date.now() - started, usage }));
      return result;
    } catch (error) {
      const safe = error instanceof OpenRouterError ? error : new OpenRouterError("openrouter_invalid_response");
      const status = Number(safe.code.match(/^openrouter_http_(\d+)$/)?.[1]);
      const retry = safe.code === "openrouter_invalid_response" || safe.code === "openrouter_unavailable" || transient.has(status);
      if (attempt || !retry || safe.retryAfter > 2) throw safe;
      if (safe.code !== "openrouter_invalid_response") await new Promise(resolve => setTimeout(resolve, safe.retryAfter * 1000));
    }
  }
  throw new OpenRouterError("openrouter_unavailable");
}
