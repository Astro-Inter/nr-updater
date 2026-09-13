from datetime import datetime, timezone

from schemas.nr_schema import NrSchema

from .mongodb import db

collection = db["nrs"]

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
    """True quando a NR ainda não existe ou mudou de data de atualização."""
    return collection.find_one(
        {"_id": id, "ultima_atualizacao": data_atualizacao}, {"_id": 1}
    ) is None


def salvar_nr(nr_data: NrSchema) -> None:
    collection.update_one(
        {"_id": nr_data.id},
        {
            "$set": nr_data.model_dump(include=set(CAMPOS_PERSISTIDOS)),
            "$setOnInsert": {"data_criacao": datetime.now(timezone.utc)},
        },
        upsert=True,
    )


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
