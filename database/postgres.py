import json

import psycopg

from config import (
    POSTGRES_DATABASE,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)


def conectar():
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DATABASE,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )


def executar_procedure(procedure: str, dados) -> None:
    """Chama uma procedure que recebe um único parâmetro JSON."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            f"CALL {procedure}(%s)",
            (json.dumps(dados, ensure_ascii=False),),
        )
