import { MongoClient, type Document, type MongoClientOptions } from "mongodb";
import { Pool } from "pg";
import { NR_EXTRACTOR_PROMPT } from "./prompt.ts";
import { queueGrafanaLog, type GrafanaEnv } from "./grafana-logs.ts";

const JOB = "update-nrs";
const CRON = "0 3 1 */3 *";
const DEFAULT_URL = "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/seguranca-e-saude-no-trabalho/ctpp-nrs/normas-regulamentadoras-nrs";

interface Env extends GrafanaEnv {
  MONGO_URI: string;
  MONGO_DATABASE: string;
  GEMINI_API_KEY: string;
  GROQ_API_KEY: string;
  GEMINI_MODEL?: string;
  GROQ_MODEL?: string;
  URL_NRS?: string;
  RODAR_CRON?: string;
  JOBS_ENABLED?: string;
  JOBS_TOKEN?: string;
  HYPERDRIVE: Hyperdrive;
}
interface Hyperdrive { connectionString: string }
interface Norm { id: number; name: string; title: string; url: string; text: string; updatedAt: string; revoked: boolean }
interface Analysis { descricao: string; objetivo: string; aplicabilidade: string; tempo_reciclagem_meses: number; usabilidade: "Funcionario" | "Empresa" }
interface NrDocument extends Document { _id: number; ultima_atualizacao?: string; nome?: string; revogada?: boolean; tempo_reciclagem_meses?: number }

function decode(value: string): string {
  return value.replace(/&#(\d+);/g, (_, n: string) => String.fromCodePoint(Number(n)))
    .replace(/&#x([\da-f]+);/gi, (_, n: string) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'").replace(/&lt;/gi, "<").replace(/&gt;/gi, ">");
}

function attr(attrs: string, name: string): string | null {
  const match = attrs.match(new RegExp(`(?:^|\\s)${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, "i"));
  return match ? decode(match[1] ?? match[2] ?? match[3] ?? "") : null;
}

export function listNormLinks(html: string, baseUrl: string): Array<{ title: string; url: string }> {
  const result = new Map<string, { title: string; url: string }>();
  for (const match of html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a\s*>/gi)) {
    const attrs = match[1] ?? "";
    if (!(attr(attrs, "class") ?? "").split(/\s+/).includes("internal-link")) continue;
    const rawTitle = decode((match[2] ?? "").replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();
    const href = attr(attrs, "href");
    if (!rawTitle || !/NR-/i.test(rawTitle) || !href) continue;
    const url = new URL(href, baseUrl).toString();
    result.set(url, { title: rawTitle, url });
  }
  return [...result.values()];
}

function contentCore(html: string): string | null {
  const start = /<div\b(?=[^>]*\bid\s*=\s*["']content-core["'])[^>]*>/i.exec(html);
  if (!start || start.index === undefined) return null;
  const bodyStart = start.index + start[0].length;
  const tags = /<\/?div\b[^>]*>/gi;
  tags.lastIndex = bodyStart;
  let depth = 1;
  let tag: RegExpExecArray | null;
  while ((tag = tags.exec(html))) {
    if (/^<\s*\//.test(tag[0])) depth--;
    else if (!/\/\s*>$/.test(tag[0])) depth++;
    if (depth === 0) return html.slice(bodyStart, tag.index);
  }
  return html.slice(bodyStart);
}

export function extractText(html: string): string {
  const core = contentCore(html) ?? html.match(/<main\b[^>]*>([\s\S]*?)<\/main\s*>/i)?.[1] ?? "";
  return decode(core.replace(/<(script|style|noscript)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, " ")
    .replace(/<\/(?:p|li|h[1-6]|section|article|div)\s*>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]*>/g, " "))
    .replace(/[ \t\r]+/g, " ").replace(/\n{2,}/g, "\n\n").trim();
}

export function updatedDate(html: string): string {
  const patterns = [
    /class=["'][^"']*documentModified[^"']*["'][^>]*>[\s\S]*?Atualizado em<\/span>[\s\S]*?<span[^>]*class=["'][^"']*value[^"']*["'][^>]*>([^<]+)/i,
    /Atualizado em<\/span>\s*<span[^>]*>([^<]+)/i,
    /Atualizado[^\d]*([0-3]?\d\/[01]?\d\/\d{4}(?:\s*\d{1,2}h\d{0,2})?)/i,
  ];
  for (const pattern of patterns) {
    const value = html.match(pattern)?.[1]?.trim();
    if (value) return value.match(/[0-3]?\d\/[01]?\d\/\d{4}/)?.[0] ?? value;
  }
  return "";
}

function normId(title: string): number | null {
  const match = title.match(/\d+/);
  return match ? Number(match[0]) : null;
}

export function cleanName(title: string): string {
  return title.replace(/^\s*NR\s*[-\s]*\d+\s*[-:]?\s*/i, "")
    .replace(/\(\s*revogada\s*\)/gi, "").replace(/\s+/g, " ").trim()
    .toLocaleLowerCase("pt-BR")
    .replace(/(^|[\s-])(\p{L})/gu, (_match, prefix: string, letter: string) => prefix + letter.toLocaleUpperCase("pt-BR"));
}

async function getHtml(url: string): Promise<string> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const response = await fetch(url, { headers: { "User-Agent": "Astro NR updater/1.0" }, redirect: "follow", signal: AbortSignal.timeout(60_000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.text();
    } catch (error) {
      lastError = error;
      if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 2 ** attempt * 1000));
    }
  }
  throw new Error(`Não foi possível carregar ${new URL(url).hostname}: ${String(lastError)}`);
}

async function scrape(env: Env): Promise<Norm[]> {
  const listingUrl = env.URL_NRS || DEFAULT_URL;
  const links = listNormLinks(await getHtml(listingUrl), listingUrl);
  if (!links.length) throw new Error("Nenhuma NR localizada na página oficial; sincronização abortada.");
  const seen = new Set<number>();
  const norms: Norm[] = [];
  // Sequential fetch keeps the free-tier socket and subrequest usage predictable.
  for (const link of links) {
    const id = normId(link.title);
    if (id === null || seen.has(id)) continue;
    seen.add(id);
    const html = await getHtml(link.url);
    const text = extractText(html);
    const updatedAt = updatedDate(html);
    if (!text || !updatedAt) {
      console.warn(JSON.stringify({ event: "norm_skipped", id, reason: !text ? "empty_text" : "missing_update_date" }));
      continue;
    }
    norms.push({ id, name: cleanName(link.title), title: link.title, url: link.url, text, updatedAt, revoked: /\(\s*revogada\s*\)/i.test(link.title) || /\(\s*revogada\s*\)/i.test(text) });
  }
  if (!norms.length) throw new Error("Nenhum texto de NR válido; sincronização abortada.");
  return norms;
}

function parseAnalysis(value: unknown): Analysis {
  const item = typeof value === "string" ? JSON.parse(value) : value;
  if (!item || typeof item !== "object") throw new Error("Resposta de análise inválida");
  const a = item as Record<string, unknown>;
  const result = {
    descricao: String(a.descricao ?? "").trim(),
    objetivo: String(a.objetivo ?? "").trim(),
    aplicabilidade: String(a.aplicabilidade ?? "").trim(),
    tempo_reciclagem_meses: Number(a.tempo_reciclagem_meses ?? 12),
    usabilidade: a.usabilidade,
  };
  if (!result.descricao || !result.objetivo || !result.aplicabilidade || !Number.isInteger(result.tempo_reciclagem_meses) || result.tempo_reciclagem_meses < 1 || !["Funcionario", "Empresa"].includes(String(result.usabilidade))) throw new Error("Modelo retornou análise fora do schema");
  return result as Analysis;
}

async function analyze(text: string, env: Env): Promise<Analysis> {
  const content = text.slice(0, 120_000);
  try {
    const response = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST", headers: { Authorization: `Bearer ${env.GROQ_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: env.GROQ_MODEL || "llama-3.3-70b-versatile", temperature: 0, response_format: { type: "json_object" }, messages: [{ role: "system", content: NR_EXTRACTOR_PROMPT }, { role: "user", content }] }),
    });
    if (!response.ok) throw new Error(`Groq HTTP ${response.status}`);
    const data = await response.json() as { choices?: Array<{ message?: { content?: string } }> };
    return parseAnalysis(data.choices?.[0]?.message?.content);
  } catch (groqError) {
    console.warn(JSON.stringify({ event: "analysis_fallback", provider: "gemini", reason: String(groqError).slice(0, 160) }));
    const model = env.GEMINI_MODEL || "gemini-2.5-flash";
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(env.GEMINI_API_KEY)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ systemInstruction: { parts: [{ text: NR_EXTRACTOR_PROMPT }] }, contents: [{ role: "user", parts: [{ text: content }] }], generationConfig: { temperature: 0, responseMimeType: "application/json" } }),
    });
    if (!response.ok) throw new Error(`Groq falhou e Gemini retornou HTTP ${response.status}`);
    const data = await response.json() as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }> };
    return parseAnalysis(data.candidates?.[0]?.content?.parts?.map((part) => part.text ?? "").join(""));
  }
}

function mustHave(env: Env): void {
  for (const key of ["MONGO_URI", "MONGO_DATABASE", "GROQ_API_KEY", "GEMINI_API_KEY"] as const) {
    if (!env[key]) throw new Error(`Secret obrigatório ausente: ${key}`);
  }
  if (!env.HYPERDRIVE?.connectionString) throw new Error("Binding Hyperdrive ausente");
}

export async function runUpdate(env: Env, dryRun = false): Promise<Record<string, number | string>> {
  mustHave(env);
  const mongoOptions = { maxPoolSize: 2, minPoolSize: 0, serverSelectionTimeoutMS: 15_000, appName: "nr-updater-worker" } as MongoClientOptions;
  const mongo = new MongoClient(env.MONGO_URI, mongoOptions);
  const pg = new Pool({ connectionString: env.HYPERDRIVE.connectionString, max: 1, connectionTimeoutMillis: 15_000 });
  let updated = 0, failed = 0, unchanged = 0;
  try {
    await mongo.connect();
    const collection = mongo.db(env.MONGO_DATABASE).collection<NrDocument>("nrs");
    const norms = await scrape(env);
    for (const norm of norms) {
      const current = await collection.findOne({ _id: norm.id, ultima_atualizacao: norm.updatedAt }, { projection: { _id: 1 } });
      if (current) { unchanged++; continue; }
      if (dryRun) { updated++; continue; }
      try {
        const analysis = await analyze(norm.text, env);
        await collection.updateOne({ _id: norm.id }, {
          $set: { nome: norm.name, revogada: norm.revoked, ...analysis, ultima_atualizacao: norm.updatedAt },
          $setOnInsert: { data_criacao: new Date() },
        }, { upsert: true });
        updated++;
      } catch (error) {
        failed++;
        console.error(JSON.stringify({ event: "norm_update_failed", id: norm.id, error: String(error).slice(0, 300) }));
      }
    }
    if (!dryRun) {
      const postgresRows = await collection.find({}, { projection: { nome: 1, revogada: 1, tempo_reciclagem_meses: 1 } }).toArray();
      const payload = postgresRows.map((row) => ({ id: String(row._id), nome: row.nome ?? null, revogada: row.revogada ?? null, tempo_reciclagem_mes: row.tempo_reciclagem_meses ?? null }));
      const client = await pg.connect();
      try { await client.query("CALL ler_json_nr($1::json)", [JSON.stringify(payload)]); }
      finally { client.release(); }
    } else {
      const client = await pg.connect();
      try { await client.query("SELECT 1"); }
      finally { client.release(); }
    }
    return { status: failed ? "partial" : dryRun ? "dry_run" : "success", found: norms.length, updated, unchanged, failed };
  } finally {
    await Promise.allSettled([mongo.close(), pg.end()]);
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method === "GET" && new URL(request.url).pathname === "/health") return Response.json({ service: "nr-updater", status: "ok" });
    if (!env.JOBS_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.JOBS_TOKEN}`) return Response.json({ error: "unauthorized" }, { status: 401 });
    if (request.method !== "POST" || new URL(request.url).pathname !== "/run") return Response.json({ error: "not_found" }, { status: 404 });
    const dryRun = new URL(request.url).searchParams.get("dry_run");
    if (dryRun !== "true") return Response.json({ error: "manual_runs_must_be_dry_run" }, { status: 400 });
    try {
      const result = await runUpdate(env, true);
      queueGrafanaLog(ctx, env, "nr-updater", "nr_update_validated", "INFO",
        { status: "dry_run", found: result.found, updated: result.updated, failed: result.failed });
      return Response.json(result);
    } catch (error) {
      console.error(JSON.stringify({ event: "update_failed", error: String(error).slice(0, 500) }));
      queueGrafanaLog(ctx, env, "nr-updater", "nr_update_failed", "ERROR", { operation: "manual_dry_run" });
      return Response.json({ error: "update_failed" }, { status: 500 });
    }
  },
  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (event.cron !== CRON || env.JOBS_ENABLED !== "true" || env.RODAR_CRON === "false") {
      console.log(JSON.stringify({ event: "cron_skipped", cron: event.cron }));
      return;
    }
    let result: Record<string, number | string>;
    try {
      result = await runUpdate(env, false);
    } catch (error) {
      queueGrafanaLog(ctx, env, "nr-updater", "nr_update_failed", "ERROR", { operation: "scheduled" });
      throw error;
    }
    queueGrafanaLog(ctx, env, "nr-updater", "nr_update_finished",
      result.status === "success" ? "INFO" : "ERROR", {
        status: result.status, found: result.found, updated: result.updated, unchanged: result.unchanged,
        failed: result.failed, scheduled_time: new Date(event.scheduledTime).toISOString(),
      });
    console.log(JSON.stringify({ event: "update_finished", ...result, scheduledTime: event.scheduledTime }));
  },
} satisfies ExportedHandler<Env>;
