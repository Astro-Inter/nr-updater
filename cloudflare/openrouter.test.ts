import test from "node:test";
import assert from "node:assert/strict";
import { analyzeWithLuna } from "./openrouter.ts";
const validate = (content: unknown) => {
  if (typeof content !== "string") throw new Error();
  const data = JSON.parse(content);
  if (data.ok !== true) throw new Error();
  return data;
};
function response(content = '{"ok":true}', finish = "stop", extras = {}) {
  return Response.json({ choices: [{ finish_reason: finish, message: { content, ...extras } }] });
}
for (const status of [400, 401, 402, 403, 404, 429, 503]) test(`HTTP ${status} limitado e sanitizado`, async t => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => { calls++; return new Response("private-key", { status, headers: { "retry-after": "0" } }); });
  await assert.rejects(analyzeWithLuna("Fonte", "Prompt", "private-key", validate), (error: Error) => {
    assert.ok(!error.message.includes("private-key")); return true;
  });
  assert.equal(calls, [429, 503].includes(status) ? 2 : 1);
});
test("truncamento aumenta orçamento uma vez e preserva a fonte", async t => {
  const payloads: any[] = [];
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    payloads.push(JSON.parse(String(init?.body)));
    return payloads.length === 1 ? response("", "length") : response();
  });
  assert.equal((await analyzeWithLuna("Fonte", "Prompt", "key", validate)).ok, true);
  assert.deepEqual(payloads.map(p => p.max_tokens), [4096, 8192]);
  assert.equal(payloads[0].messages[1].content, payloads[1].messages[1].content);
});
test("ferramentas, vazio, bloqueio e JSON invalido nao viram candidatos", async t => {
  for (const make of [() => response(""), () => response("not-json"), () => response("{}"),
    () => response("x", "content_filter"), () => response("x", "tool_calls", { tool_calls: [{}] }),
    () => Response.json({ error: { code: 402, message: "private-key" } })]) {
    const stub = t.mock.method(globalThis, "fetch", async () => make());
    await assert.rejects(analyzeWithLuna("Fonte", "Prompt", "key", validate)); stub.mock.restore();
  }
});
test("chave ausente e entrada excessiva sao rejeitadas sem inferencia", async t => {
  let calls = 0; t.mock.method(globalThis, "fetch", async () => { calls++; return response(); });
  await assert.rejects(analyzeWithLuna("Fonte", "Prompt", "", validate));
  await assert.rejects(analyzeWithLuna("x".repeat(120001), "Prompt", "key", validate));
  assert.equal(calls, 0);
});
test("retry-after longo nao repete a chamada", async t => {
  let calls = 0; t.mock.method(globalThis, "fetch", async () => { calls++; return new Response(null, { status: 429, headers: { "retry-after": "30" } }); });
  await assert.rejects(analyzeWithLuna("Fonte", "Prompt", "key", validate)); assert.equal(calls, 1);
});
