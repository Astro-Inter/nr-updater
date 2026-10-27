import os

import dotenv

dotenv.load_dotenv()

# Execução: false => o robô não roda.
RODAR_CRON = os.getenv("RODAR_CRON", "true").strip().lower() in ("true", "1", "sim", "yes")

# Provedor unico de IA; o modelo e fixado na camada de infraestrutura.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# MongoDB
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DATABASE = os.getenv("MONGO_DATABASE")

# PostgreSQL
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

# Scraper
URL_NRS = os.getenv(
    "URL_NRS",
    "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho"
    "/seguranca-e-saude-no-trabalho/ctpp-nrs/normas-regulamentadoras-nrs",
)
# Vazio => usa o Chromium que vem com o Playwright (necessário no CI/Linux).
CHROME_EXECUTABLE_PATH = os.getenv("CHROME_EXECUTABLE_PATH") or None
CONCORRENCIA_SCRAPER = int(os.getenv("CONCORRENCIA_SCRAPER", "4"))
