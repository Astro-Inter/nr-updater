from typing import Literal, Optional

from pydantic import BaseModel, Field

Usabilidade = Literal["Funcionario", "Empresa"]


class NrAnalise(BaseModel):
    """Resultado da análise do texto de uma Norma Regulamentadora."""

    descricao: str = Field(
        description="2 a 5 frases sobre O QUE a norma estabelece e quais temas de SST regula."
    )
    objetivo: str = Field(
        description="2 a 5 frases sobre PARA QUE a norma existe: a finalidade de segurança e saúde que busca alcançar."
    )
    aplicabilidade: str = Field(
        description="2 a 5 frases sobre ONDE, PARA QUEM e EM QUE SITUAÇÕES a norma se aplica."
    )
    tempo_reciclagem_meses: int = Field(
        default=12,
        ge=1,
        description="Intervalo em meses da reciclagem do treinamento principal. Use 12 quando a norma não definir periodicidade.",
    )
    usabilidade: Usabilidade = Field(
        description="'Funcionario' se a norma exige capacitação obrigatória do trabalhador; caso contrário 'Empresa'."
    )


class NrSchema(BaseModel):
    id: int
    nome: str
    texto: str
    ultima_atualizacao: str
    revogada: bool = False
    descricao: Optional[str] = None
    objetivo: Optional[str] = None
    aplicabilidade: Optional[str] = None
    tempo_reciclagem_meses: Optional[int] = None
    usabilidade: Optional[Usabilidade] = None

    def aplicar_analise(self, analise: NrAnalise) -> "NrSchema":
        for campo, valor in analise.model_dump().items():
            setattr(self, campo, valor)
        return self
