import asyncio
import logging
from urllib.parse import urljoin

import httpx
from playwright.async_api import Error as PlaywrightError, async_playwright

from config import CHROME_EXECUTABLE_PATH, CONCORRENCIA_SCRAPER, URL_NRS

from .utils import (
    extrair_data_atualizacao,
    extrair_texto_html,
    limpar_nome_nr,
    normalizar_chave_nr,
)

log = logging.getLogger(__name__)

TENTATIVAS = 3
TIMEOUT_SEGUNDOS = 60.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/124 Safari/537.36"
)


async def _buscar_html(client: httpx.AsyncClient, url: str) -> str | None:
    """Baixa uma página com retentativas e backoff exponencial."""
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resposta = await client.get(url)
            resposta.raise_for_status()
            return resposta.text
        except Exception as erro:
            if tentativa == TENTATIVAS:
                log.error("Falha ao carregar %s: %s", url, erro)
                return None
            espera = 2**tentativa
            log.warning("[%d/%d] %s falhou (%s). Aguardando %ds...", tentativa, TENTATIVAS, url, erro, espera)
            await asyncio.sleep(espera)
    return None


async def processar_cada_nr(nome_nr: str, link_nr: str, client: httpx.AsyncClient) -> dict | None:
    """Extrai nome, texto e data de atualização da página de uma NR."""
    nome_limpo = limpar_nome_nr(nome_nr)
    log.info("Explorando: %s", nome_limpo)

    html = await _buscar_html(client, link_nr)
    if html is None:
        return None

    texto = extrair_texto_html(html)
    data_atualizacao = extrair_data_atualizacao(html)

    if not texto:
        log.warning("Sem texto extraído para %s; NR ignorada.", nome_limpo)
        return None
    if not data_atualizacao:
        log.warning("Sem data de atualização para %s.", nome_limpo)

    return {
        "nome": nome_limpo,
        "nome_original": nome_nr,
        "texto": texto,
        "data_atualizacao": data_atualizacao,
    }


async def _abrir_navegador(playwright):
    """Usa o Chromium do Playwright e, se não houver, o Chrome instalado na máquina."""
    if CHROME_EXECUTABLE_PATH:
        return await playwright.chromium.launch(
            headless=True, executable_path=CHROME_EXECUTABLE_PATH
        )
    try:
        return await playwright.chromium.launch(headless=True)
    except PlaywrightError:
        log.warning("Chromium do Playwright indisponível; usando o Chrome do sistema.")
        return await playwright.chromium.launch(headless=True, channel="chrome")


async def _listar_links_nrs() -> list[tuple[str, str]]:
    """Abre a página oficial no navegador e devolve os pares (nome, link) das NRs."""
    async with async_playwright() as p:
        browser = await _abrir_navegador(p)
        try:
            page = await browser.new_page()
            log.info("Acessando a lista oficial de NRs...")
            await page.goto(URL_NRS, wait_until="networkidle")

            links: dict[str, tuple[str, str]] = {}
            for elemento in await page.locator("a.internal-link").all():
                texto = (await elemento.inner_text() or "").strip()
                href = await elemento.get_attribute("href")
                if not (texto and href and "NR-" in texto.upper()):
                    continue
                url = urljoin(URL_NRS, href)
                links.setdefault(url, (texto, url))

            return list(links.values())
        finally:
            await browser.close()


async def executar_robo() -> dict:
    """Coleta todas as NRs publicadas, indexadas pelo número da norma."""
    lista_nrs = await _listar_links_nrs()
    log.info("Foram identificadas %d NRs no site. Iniciando colheita...", len(lista_nrs))

    limite = asyncio.Semaphore(CONCORRENCIA_SCRAPER)

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=TIMEOUT_SEGUNDOS,
    ) as client:

        async def coletar(nome: str, link: str):
            async with limite:
                return await processar_cada_nr(nome, link, client)

        coletas = await asyncio.gather(
            *(coletar(nome, link) for nome, link in lista_nrs)
        )

    resultados = {}
    for dados in coletas:
        if not dados:
            continue
        chave = normalizar_chave_nr(dados["nome_original"])
        if chave is None:
            log.warning("Número não identificado para '%s'; NR ignorada.", dados["nome_original"])
            continue
        resultados[chave] = dados

    log.info("Colheita concluída: %d NRs válidas.", len(resultados))
    return resultados


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    resultados = asyncio.run(executar_robo())
    for chave, dados in sorted(resultados.items()):
        print(f"NR-{chave}: data={dados['data_atualizacao']}, texto_len={len(dados['texto'])}")
