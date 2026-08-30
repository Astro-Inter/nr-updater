import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL
from schemas.nr_schema import NrAnalise

from .prompt import NR_EXTRACTOR_PROMPT

log = logging.getLogger(__name__)

# Margem de segurança para a janela de contexto dos modelos.
MAX_CARACTERES = 120_000


def _cadeia(llm):
    """Modelo com saída obrigatoriamente no formato de NrAnalise."""
    return llm.with_structured_output(NrAnalise)


# temperature=0 já torna a saída determinística; top_p seria redundante.
_analisador = _cadeia(
    ChatGroq(model=GROQ_MODEL, temperature=0.0, api_key=GROQ_API_KEY)
).with_fallbacks(
    [
        _cadeia(
            ChatGoogleGenerativeAI(
                model=GEMINI_MODEL, temperature=0.0, google_api_key=GEMINI_API_KEY
            )
        )
    ]
)


def processar_nr(texto_nr: str) -> NrAnalise:
    """Analisa o texto de uma NR e devolve os campos estruturados."""
    if len(texto_nr) > MAX_CARACTERES:
        log.warning(
            "Texto truncado de %d para %d caracteres.", len(texto_nr), MAX_CARACTERES
        )
        texto_nr = texto_nr[:MAX_CARACTERES]

    return _analisador.invoke(
        [SystemMessage(NR_EXTRACTOR_PROMPT), HumanMessage(texto_nr)]
    )
