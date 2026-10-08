import test, { type TestContext } from "node:test";
import assert from "node:assert/strict";
import { MongoClient } from "mongodb";
import { Pool } from "pg";
import { NR_EXTRACTOR_PROMPT } from "./prompt.ts";
import { runUpdate } from "./worker.ts";

const updatedAt = "08/10/2026";
const analysis = (usabilidade: unknown) => ({
  descricao: "Requisitos de segurança da atividade.",
  objetivo: "Prevenir acidentes na atividade.",
  aplicabilidade: "Trabalhadores e organizações abrangidos.",
  tempo_reciclagem_meses: 12,
  usabilidade,
});

function setup(t: TestContext, documents: Array<Record<string, unknown>> = [], groqValue: unknown = "Colaborador", geminiValue: unknown = "Colaborador") {
  const calls: Array<{ url: string; body: any }> = [];
  const migrations: unknown[] = [];
  const writes: unknown[] = [];
  const collection = {
    async updateMany(filter: Record<string, unknown>, update: { $set: Record<string, unknown> }) {
      migrations.push(filter);
      for (const document of documents) if (document.usabilidade === filter.usabilidade) Object.assign(document, update.$set);
    },
    async findOne(filter: Record<string, unknown>) {
      return documents.find((doc) => doc._id === filter._id && doc.ultima_atualizacao === filter.ultima_atualizacao) ?? null;
    },
    async updateOne(filter: Record<string, unknown>, update: { $set: Record<string, unknown> }) {
      writes.push(update.$set);
      const document = documents.find((doc) => doc._id === filter._id);
      if (document) Object.assign(document, update.$set);
      else documents.push({ _id: filter._id, ...update.$set });
    },
    find() { return { async toArray() { return documents; } }; },
  };
  t.mock.method(MongoClient.prototype, "connect", async () => {});
  t.mock.method(MongoClient.prototype, "close", async () => {});
  t.mock.method(MongoClient.prototype, "db", () => ({ collection: () => collection }));
  t.mock.method(Pool.prototype, "connect", async () => ({ query: async () => {}, release() {} }));
  t.mock.method(Pool.prototype, "end", async () => {});
  t.mock.method(globalThis, "fetch", async (input: string, init?: RequestInit) => {
    const url = String(input);
    if (url === "https://example.test/nrs") return new Response('<a class="internal-link" href="/nr-1">NR-1 - Segurança</a>');
    if (url === "https://example.test/nr-1") return new Response(`<span>Atualizado em</span><span class="value">${updatedAt}</span><main><p>Treinamento obrigatório dos trabalhadores.</p></main>`);
    const body = JSON.parse(String(init?.body));
    calls.push({ url, body });
    if (url.includes("api.groq.com")) return Response.json({ choices: [{ message: { content: JSON.stringify(analysis(groqValue)) } }] });
    if (url.includes("generativelanguage.googleapis.com")) return Response.json({ candidates: [{ content: { parts: [{ text: JSON.stringify(analysis(geminiValue)) }] } }] });
    throw new Error(`Requisição inesperada no teste: ${url}`);
  });
  const env = {
    MONGO_URI: "mongodb://localhost:27017", MONGO_DATABASE: "test",
    GROQ_API_KEY: "test-key", GEMINI_API_KEY: "test-key",
    URL_NRS: "https://example.test/nrs", HYPERDRIVE: { connectionString: "postgresql://localhost/test" },
  };
  return { documents, calls, migrations, writes, env };
}

for (const category of ["Colaborador", "Empresa"]) {
  test(`modelo retorna ${category} e o Worker grava o mesmo valor no Mongo`, async (t) => {
    const state = setup(t, [], category);
    const result = await runUpdate(state.env);
    assert.equal(result.updated, 1);
    assert.equal(result.failed, 0);
    assert.equal(state.documents[0].usabilidade, category);
    assert.equal(state.calls[0].body.messages[0].content, NR_EXTRACTOR_PROMPT);
    assert.ok(!NR_EXTRACTOR_PROMPT.includes("Funcionario"));
  });
}

test("Funcionario retornado pelo Groq aciona Gemini com prompt atualizado", async (t) => {
  const state = setup(t, [], "Funcionario", "Colaborador");
  const result = await runUpdate(state.env);
  assert.equal(result.updated, 1);
  assert.equal(state.documents[0].usabilidade, "Colaborador");
  assert.equal(state.calls.length, 2);
  assert.equal(state.calls[1].body.systemInstruction.parts[0].text, NR_EXTRACTOR_PROMPT);
});

test("valor antigo vindo dos dois modelos causa falha sem gravar a análise", async (t) => {
  const state = setup(t, [], "Funcionario", "Funcionario");
  const result = await runUpdate(state.env);
  assert.equal(result.status, "partial");
  assert.equal(result.failed, 1);
  assert.equal(result.updated, 0);
  assert.deepEqual(state.writes, []);
});

for (const invalid of ["Mista", ["Colaborador"]]) {
  test(`rejeita usabilidade inválida ${JSON.stringify(invalid)} sem gravar no Mongo`, async (t) => {
    const state = setup(t, [], invalid, invalid);
    const result = await runUpdate(state.env);
    assert.equal(result.failed, 1);
    assert.equal(result.updated, 0);
    assert.deepEqual(state.writes, []);
  });
}

test("migra documento sem mudança na data da NR e preserva Empresa", async (t) => {
  const state = setup(t, [
    { _id: 1, usabilidade: "Funcionario", ultima_atualizacao: updatedAt },
    { _id: 2, usabilidade: "Empresa", ultima_atualizacao: updatedAt },
  ]);
  const result = await runUpdate(state.env);
  assert.equal(result.unchanged, 1);
  assert.equal(state.documents[0].usabilidade, "Colaborador");
  assert.equal(state.documents[1].usabilidade, "Empresa");
  assert.equal(state.documents[0].ultima_atualizacao, updatedAt);
  assert.deepEqual(state.calls, []);
  await runUpdate(state.env);
  assert.equal(state.documents[0].usabilidade, "Colaborador");
});

test("dry_run não migra, não grava e não chama os modelos", async (t) => {
  const state = setup(t, [{ _id: 1, usabilidade: "Funcionario", ultima_atualizacao: updatedAt }]);
  const result = await runUpdate(state.env, true);
  assert.equal(result.status, "dry_run");
  assert.equal(state.documents[0].usabilidade, "Funcionario");
  assert.deepEqual(state.migrations, []);
  assert.deepEqual(state.writes, []);
  assert.deepEqual(state.calls, []);
});
