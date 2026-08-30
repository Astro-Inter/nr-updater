import re
from html import unescape
from html.parser import HTMLParser


class ContentCoreTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.div_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and attrs.get("id") == "content-core":
            self.capture = True
            self.div_depth = 0
            self.parts.append("\n")
            return

        if not self.capture:
            return

        if tag == "div":
            self.div_depth += 1
            self.parts.append("\n")
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if not self.capture:
            return

        if tag == "div":
            if self.div_depth == 0:
                self.capture = False
            else:
                self.div_depth -= 1
            self.parts.append("\n")
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def get_text(self) -> str:
        text = unescape("".join(self.parts))
        text = re.sub(r"[ \t\r]+", " ", text)
        text = re.sub(r"\n{2,}", "\n\n", text)
        return text.strip()


def extrair_data_atualizacao(html: str) -> str:
    padroes = [
        r'<span[^>]+class=["\']documentModified["\'][^>]*>.*?Atualizado em</span>.*?<span[^>]+class=["\']value["\'][^>]*>([^<]+)</span>',
        r'Atualizado em</span>\s*<span[^>]*>([^<]+)</span>',
        r'Atualizado em\s*([^<\n]+)',
        r'Atualizado[^0-9]*([0-3]?\d/[01]?\d/\d{4}(?:\s*\d{1,2}h\d{0,2})?)',
    ]
    for padrao in padroes:
        match = re.search(padrao, html, flags=re.DOTALL | re.IGNORECASE)
        if match:
            valor = match.group(1).strip()
            data_match = re.search(r'([0-3]?\d/[01]?\d/\d{4})', valor)
            if data_match:
                return data_match.group(1)
            return valor
    return ""


def extrair_texto_html(html: str) -> str:
    extractor = ContentCoreTextExtractor()
    extractor.feed(html)
    texto = extractor.get_text()
    if texto:
        return texto

    # fallback: extrair o main inteiro
    match = re.search(r'<main[^>]*>(.*?)</main>', html, flags=re.DOTALL | re.IGNORECASE)
    if match:
        texto = re.sub(r'<[^>]+>', ' ', match.group(1))
        texto = unescape(texto)
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto

    return ""


def limpar_nome_nr(nome_nr: str) -> str:
    """Remove o prefixo 'NR-XX' e o marcador de revogação do título da norma."""
    nome = re.sub(r'^\s*NR\s*[-\s]*\d+\s*[-:]?\s*', '', nome_nr, flags=re.IGNORECASE)
    nome = re.sub(r'\(\s*revogada\s*\)', '', nome, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', nome).strip().title()


def normalizar_chave_nr(nome_nr: str) -> int | None:
    """Extrai o número da NR a partir do título; None quando não houver."""
    match = re.search(r'\d+', nome_nr)
    return int(match.group()) if match else None