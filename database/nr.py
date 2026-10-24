from datetime import datetime, timezone

from schemas.nr_schema import NrSchema

from .mongodb import db

collection = db["nrs"]
pending_collection = db["nrs_pendentes"]

# Campos gravados no Mongo (o restante do schema é auxiliar).
CAMPOS_PERSISTIDOS = (
    "nome",
    "revogada",
    "descricao",
    "objetivo",
    "aplicabilidade",
    "tempo_reciclagem_meses",
    "usabilidade",
    "ultima_atualizacao",
)


def precisa_atualizar(id: int, data_atualizacao: str) -> bool:
    """Analisa apenas versões que não estão aprovadas nem aguardando revisão."""
    query = {"_id": id, "ultima_atualizacao": data_atualizacao}
    return (
        collection.find_one(query, {"_id": 1}) is None
        and pending_collection.find_one(query, {"_id": 1}) is None
    )


def salvar_nr(nr_data: NrSchema) -> None:
    """Salva o candidato para revisão, sem publicar na collection nrs."""
    pending_collection.update_one(
        {"_id": nr_data.id},
        {
            "$set": nr_data.model_dump(include=set(CAMPOS_PERSISTIDOS)),
            "$setOnInsert": {"data_criacao": datetime.now(timezone.utc)},
        },
        upsert=True,
    )


def migrar_usabilidade_funcionario() -> int:
    """Normaliza apenas candidatos; documentos aprovados não são modificados."""
    resultado = pending_collection.update_many(
        {"usabilidade": "Funcionario"},
        {"$set": {"usabilidade": "Colaborador"}},
    )
    return resultado.modified_count


def listar_nrs_para_postgres() -> list[dict]:
    campos = ("nome", "revogada", "tempo_reciclagem_meses")
    return [
        {
            "id": str(nr["_id"]),
            "nome": nr.get("nome"),
            "revogada": nr.get("revogada"),
            "tempo_reciclagem_mes": nr.get("tempo_reciclagem_meses"),
        }
        for nr in collection.find({}, {campo: 1 for campo in campos})
    ]
