import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
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


def resposta_groq(usabilidade):
    message = AIMessage(content="", tool_calls=[{
        "name": "NrAnalise", "args": dados_analise(usabilidade), "id": "test-call",
    }])
    return ChatResult(generations=[ChatGeneration(message=message)])


def resposta_gemini(usabilidade):
    message = AIMessage(content=json.dumps(dados_analise(usabilidade)))
    return ChatResult(generations=[ChatGeneration(message=message)])


class UsabilidadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Chaves fictícias e banco simulado impedem acesso aos serviços reais.
        config = types.ModuleType("config")
        config.GROQ_API_KEY = config.GEMINI_API_KEY = "test-key"
        config.GROQ_MODEL = "llama-3.3-70b-versatile"
        config.GEMINI_MODEL = "gemini-2.5-flash"
        mongodb = types.ModuleType("database.mongodb")
        mongodb.db = {"nrs": MagicMock()}
        with patch.dict(sys.modules, {"config": config, "database.mongodb": mongodb}):
            cls.agent = importlib.import_module("agents.agent")
            cls.database = importlib.import_module("database.nr")

    def test_agent_passes_new_enum_to_groq_and_saves_both_categories(self):
        for categoria in ("Colaborador", "Empresa"):
            with self.subTest(categoria=categoria), patch.object(
                ChatGroq, "_generate", return_value=resposta_groq(categoria)
            ) as groq, patch.object(ChatGoogleGenerativeAI, "_generate") as gemini:
                analise = self.agent.processar_nr("Texto de uma NR para análise.")
                self.assertIsInstance(analise, NrAnalise)
                self.assertEqual(analise.usabilidade, categoria)
                gemini.assert_not_called()
                args, kwargs = groq.call_args
                self.assertEqual(args[0][0].content, NR_EXTRACTOR_PROMPT)
                schema = kwargs["tools"][0]["function"]["parameters"]
                self.assertEqual(schema["properties"]["usabilidade"]["enum"], ["Colaborador", "Empresa"])
                nr = NrSchema(id=1, nome="NR", texto="Texto", ultima_atualizacao="08/10/2026")
                nr.aplicar_analise(analise)
                with patch.object(self.database, "collection") as collection:
                    self.database.salvar_nr(nr)
                    payload = collection.update_one.call_args.args[1]["$set"]
                    self.assertEqual(payload["usabilidade"], categoria)

    def test_old_groq_value_activates_gemini_with_updated_prompt_and_schema(self):
        for categoria in ("Colaborador", "Empresa"):
            with self.subTest(categoria=categoria), patch.object(
                ChatGroq, "_generate", return_value=resposta_groq("Funcionario")
            ), patch.object(
                ChatGoogleGenerativeAI, "_generate", return_value=resposta_gemini(categoria)
            ) as gemini:
                analise = self.agent.processar_nr("Texto da NR.")
                self.assertEqual(analise.usabilidade, categoria)
                args, kwargs = gemini.call_args
                self.assertEqual(args[0][0].content, NR_EXTRACTOR_PROMPT)
                self.assertEqual(kwargs["response_json_schema"]["properties"]["usabilidade"]["enum"], ["Colaborador", "Empresa"])

    def test_python_and_worker_prompts_match_and_exclude_old_category(self):
        source = (Path(__file__).resolve().parents[1] / "cloudflare" / "prompt.ts").read_text(encoding="utf-8")
        worker_prompt = json.loads(source.split("=", 1)[1].strip().removesuffix(";"))
        self.assertEqual(worker_prompt, NR_EXTRACTOR_PROMPT)
        self.assertIn('"Colaborador" ou "Empresa"', NR_EXTRACTOR_PROMPT)
        self.assertNotIn("Funcionario", NR_EXTRACTOR_PROMPT)

    def test_both_providers_returning_old_value_raise_instead_of_saving_it(self):
        with patch.object(ChatGroq, "_generate", return_value=resposta_groq("Funcionario")), patch.object(
            ChatGoogleGenerativeAI, "_generate", return_value=resposta_gemini("Funcionario")
        ) as gemini:
            with self.assertRaises(ValueError):
                self.agent.processar_nr("Texto da NR.")
            gemini.assert_called_once()

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

        with patch.object(self.database, "collection") as collection:
            collection.update_many.side_effect = update_many
            self.assertEqual(self.database.migrar_usabilidade_funcionario(), 1)
            self.assertEqual(self.database.migrar_usabilidade_funcionario(), 0)
        self.assertEqual([doc["usabilidade"] for doc in documents], ["Colaborador", "Empresa", "Colaborador"])
        self.assertTrue(all(doc["ultima_atualizacao"] == "01/01/2026" for doc in documents))


if __name__ == "__main__":
    unittest.main()
