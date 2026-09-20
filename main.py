import asyncio
import logging
import re
from time import monotonic

from agents.agent import processar_nr
from config import RODAR_CRON
from database.nr import listar_nrs_para_postgres, precisa_atualizar, salvar_nr
from database.postgres import executar_procedure
from observability import configure_observability
from schemas.nr_schema import NrSchema
from scraper.scraper import executar_robo

log = logging.getLogger("nr-updater")

MARCADOR_REVOGADA = re.compile(r"\(\s*revogada\s*\)", re.IGNORECASE)


def montar_nr(nr_id: int, dados: dict) -> NrSchema:
    texto = str(dados["texto"])
    titulo = dados.get("nome_original", "")
    return NrSchema(
        id=nr_id,
        nome=dados["nome"],
        texto=MARCADOR_REVOGADA.sub("", texto).strip(),
        ultima_atualizacao=dados["data_atualizacao"],
        revogada=bool(MARCADOR_REVOGADA.search(titulo) or MARCADOR_REVOGADA.search(texto)),
    )


def main():
    observability = configure_observability()
    inicio = monotonic()

    try:
        if not RODAR_CRON:
            log.info(
                "RODAR=false; execução interrompida.",
                extra={"operation": "update_nrs", "status": "skipped"},
            )
            return

        resultados = asyncio.run(executar_robo())
        if not resultados:
            log.error(
                "Nenhuma NR coletada; nada a sincronizar.",
                extra={"operation": "update_nrs", "status": "error"},
            )
            raise SystemExit(1)

        atualizadas = falhas = 0
        for nr_id, dados in sorted(resultados.items()):
            nr = montar_nr(nr_id, dados)

            if not precisa_atualizar(nr.id, nr.ultima_atualizacao):
                log.info("NR-%s já está atualizada.", nr.id)
                continue

            try:
                nr.aplicar_analise(processar_nr(nr.texto))
            except Exception:
                falhas += 1
                log.exception(
                    "Erro ao processar NR-%s.",
                    nr.id,
                    extra={"operation": "process_nr", "status": "error"},
                )
                continue

            salvar_nr(nr)
            atualizadas += 1
            log.info(
                "NR-%s salva (%s, reciclagem %s meses).",
                nr.id,
                nr.usabilidade,
                nr.tempo_reciclagem_meses,
            )

        log.info(
            "Resumo: %d atualizadas, %d falhas, %d coletadas.",
            atualizadas,
            falhas,
            len(resultados),
            extra={
                "operation": "update_nrs",
                "duration_ms": round((monotonic() - inicio) * 1000),
                "status": "partial" if falhas else "success",
            },
        )

        executar_procedure("ler_json_nr", listar_nrs_para_postgres())
        log.info(
            "Sincronização com o PostgreSQL concluída.",
            extra={"operation": "sync_postgres", "status": "success"},
        )
    except Exception:
        log.exception(
            "Falha não tratada na atualização das NRs.",
            extra={
                "operation": "update_nrs",
                "duration_ms": round((monotonic() - inicio) * 1000),
                "status": "error",
            },
        )
        raise
    finally:
        observability.shutdown()


if __name__ == "__main__":
    main()
