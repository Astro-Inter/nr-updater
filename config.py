import os

import dotenv

dotenv.load_dotenv()

# Execução: false => o robô não roda.
RODAR_CRON = os.getenv("RODAR_CRON", "true").strip().lower() in ("true", "1", "sim", "yes")

# API keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Modelos
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
