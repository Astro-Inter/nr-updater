from config import OPENROUTER_API_KEY
from infrastructure.openrouter import analyze_nr
from schemas.nr_schema import NrAnalise
from .prompt import NR_EXTRACTOR_PROMPT


def processar_nr(texto_nr: str) -> NrAnalise:
    """Preserva o contrato de análise; nenhuma ferramenta é oferecida ao modelo."""
    return analyze_nr(texto_nr, NR_EXTRACTOR_PROMPT, OPENROUTER_API_KEY)
