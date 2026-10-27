import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from pydantic import ValidationError

from agents.prompt import NR_EXTRACTOR_PROMPT
from schemas.nr_schema import NrAnalise, NrSchema


def dados_analise(usabilidade):
    return {
        "descricao": "Requisitos de segurança para a atividade.",
        "objetivo": "Prevenir acidentes durante a atividade.",
        "aplicabilidade": "Trabalhadores e organizações abrangidos pela atividade.",
        "tempo_reciclagem_meses": 12,
        "usabilidade": usabilidade,
    }


def resposta_luna(usabilidade):
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(dados_analise(usabilidade)),
    }}]})


class UsabilidadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Chaves fictícias e banco simulado impedem acesso aos serviços reais.
        config = types.ModuleType("config")
        config.OPENROUTER_API_KEY = "test-key"
        mongodb = types.ModuleType("database.mongodb")
        mongodb.db = {"nrs": MagicMock(), "nrs_pendentes": MagicMock()}
        with patch.dict(sys.modules, {"config": config, "database.mongodb": mongodb}):
            cls.agent = importlib.import_module("agents.agent")
            cls.database = importlib.import_module("database.nr")

    def test_luna_uses_json_contract_and_saves_both_categories(self):
        for categoria in ("Colaborador", "Empresa"):
            with self.subTest(categoria=categoria), patch("httpx.Client.post", return_value=resposta_luna(categoria)) as request:
                analise = self.agent.processar_nr("Texto de uma NR para análise.")
                self.assertIsInstance(analise, NrAnalise)
                self.assertEqual(analise.usabilidade, categoria)
                self.assertEqual(request.call_args.args[0], "https://openrouter.ai/api/v1/chat/completions")
                body = request.call_args.kwargs["json"]
                self.assertEqual(body["model"], "openai/gpt-6-luna")
                self.assertEqual(body["response_format"], {"type": "json_object"})
                self.assertTrue(body["messages"][0]["content"].startswith(NR_EXTRACTOR_PROMPT))
                self.assertNotIn("tools", body)
                self.assertNotIn("temperature", body)
                nr = NrSchema(id=1, nome="NR", texto="Texto", ultima_atualizacao="08/10/2026")
                nr.aplicar_analise(analise)
                with patch.object(self.database, "pending_collection") as collection:
                    self.database.salvar_nr(nr)
                    self.assertEqual(collection.update_one.call_args.args[1]["$set"]["usabilidade"], categoria)

    def test_invalid_category_retries_same_luna_without_another_provider(self):
        with patch("httpx.Client.post", side_effect=[resposta_luna("Funcionario"), resposta_luna("Colaborador")]) as request:
            self.assertEqual(self.agent.processar_nr("Texto da NR").usabilidade, "Colaborador")
            self.assertEqual(request.call_count, 2)
            self.assertTrue(all(c.kwargs["json"]["model"] == "openai/gpt-6-luna" for c in request.call_args_list))

    def test_python_and_worker_prompts_match_and_exclude_old_category(self):
        source = (Path(__file__).resolve().parents[1] / "cloudflare" / "prompt.ts").read_text(encoding="utf-8")
        worker_prompt = json.loads(source.split("=", 1)[1].strip().removesuffix(";"))
        self.assertEqual(worker_prompt, NR_EXTRACTOR_PROMPT)
        self.assertIn('"Colaborador" ou "Empresa"', NR_EXTRACTOR_PROMPT)
        self.assertNotIn("Funcionario", NR_EXTRACTOR_PROMPT)

    def test_two_invalid_responses_fail_before_writing(self):
        with patch("httpx.Client.post", side_effect=[resposta_luna("Funcionario"), resposta_luna("Funcionario")]) as request:
            with self.assertRaises(ValueError):
                self.agent.processar_nr("Texto da NR.")
            self.assertEqual(request.call_count, 2)

    def test_schema_rejects_old_and_unknown_categories(self):
        for categoria in ("Funcionario", "Mista", "colaborador", "Colaborador e Empresa", ["Colaborador"]):
            with self.subTest(categoria=categoria), self.assertRaises(ValidationError):
                NrAnalise(**dados_analise(categoria))

    def test_migration_is_idempotent_and_preserves_company_and_update_date(self):
        documents = [
            {"usabilidade": "Funcionario", "ultima_atualizacao": "01/01/2026"},
            {"usabilidade": "Empresa", "ultima_atualizacao": "01/01/2026"},
            {"usabilidade": "Colaborador", "ultima_atualizacao": "01/01/2026"},
        ]

        def update_many(query, update):
            changed = 0
            for document in documents:
                if document["usabilidade"] == query["usabilidade"]:
                    document.update(update["$set"])
                    changed += 1
            return types.SimpleNamespace(modified_count=changed)

        with patch.object(self.database, "pending_collection") as collection:
            collection.update_many.side_effect = update_many
            self.assertEqual(self.database.migrar_usabilidade_funcionario(), 1)
            self.assertEqual(self.database.migrar_usabilidade_funcionario(), 0)
        self.assertEqual([doc["usabilidade"] for doc in documents], ["Colaborador", "Empresa", "Colaborador"])
        self.assertTrue(all(doc["ultima_atualizacao"] == "01/01/2026" for doc in documents))

    def test_update_checks_both_approved_and_pending_versions(self):
        for approved, pending, expected in ((None, None, True), ({"_id": 1}, None, False), (None, {"_id": 1}, False)):
            with self.subTest(approved=approved, pending=pending), patch.object(
                self.database, "collection"
            ) as collection, patch.object(self.database, "pending_collection") as candidates:
                collection.find_one.return_value = approved
                candidates.find_one.return_value = pending
                self.assertEqual(self.database.precisa_atualizar(1, "08/10/2026"), expected)
                collection.update_one.assert_not_called()

    def test_candidate_write_preserves_approved_collection_and_schema(self):
        nr = NrSchema(id=1, nome="NR", texto="Texto fonte", ultima_atualizacao="08/10/2026")
        nr.aplicar_analise(NrAnalise(**dados_analise("Colaborador")))
        with patch.object(self.database, "collection") as approved, patch.object(
            self.database, "pending_collection"
        ) as pending:
            self.database.salvar_nr(nr)
            approved.update_one.assert_not_called()
            payload = pending.update_one.call_args.args[1]
            self.assertEqual(set(payload["$set"]), set(self.database.CAMPOS_PERSISTIDOS))
            self.assertIn("data_criacao", payload["$setOnInsert"])
            self.assertNotIn("texto", payload["$set"])


if __name__ == "__main__":
    unittest.main()
