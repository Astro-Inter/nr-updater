import test from "node:test";
import assert from "node:assert/strict";
import { cleanName, extractText, listNormLinks, updatedDate } from "./worker.ts";

test("only NR links from the official list are returned and duplicate URLs collapse", () => {
  const html = `<a class="internal-link" href="/nr-1">NR-1 - Disposições Gerais</a>
    <a class="internal-link" href="/nr-1">NR-1 - Disposições Gerais</a>
    <a class="external-link" href="/skip">NR-2 - Revogada</a>`;
  assert.deepEqual(listNormLinks(html, "https://gov.br/nrs"), [
    { title: "NR-1 - Disposições Gerais", url: "https://gov.br/nr-1" },
  ]);
});

test("extracts the content area, decodes entities and keeps paragraph boundaries", () => {
  const html = `<main><div id="content-core"><h1>Segurança &amp; saúde</h1><p>Texto&nbsp;da norma.</p></div></main>`;
  assert.match(extractText(html), /Segurança & saúde/);
  assert.match(extractText(html), /Texto da norma\./);
});

test("reads the publication's updated date and normalizes the NR title", () => {
  assert.equal(updatedDate('<span>Atualizado em</span><span class="value">12/03/2025 10h</span>'), "12/03/2025");
  assert.equal(cleanName("NR-18 - Segurança e Saúde no Trabalho na Indústria da Construção"), "Segurança E Saúde No Trabalho Na Indústria Da Construção");
});
