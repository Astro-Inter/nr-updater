# nr-updater no Cloudflare Workers

O Worker substitui o Chromium/Playwright do projeto por coleta HTTP da página oficial, mantendo a análise Groq com fallback Gemini e as gravações em MongoDB e PostgreSQL. A publicação usa Worker comum, Cron Trigger e o Hyperdrive `astro-email-db` já existente; não usa Containers nem cria banco.

## Execução

O cron preserva a agenda atual do GitHub Actions: `0 3 1 */3 *` (03:00 UTC no primeiro dia de janeiro, abril, julho e outubro). `JOBS_ENABLED` permanece `false` até configurar os Secrets e validar a execução de leitura. `RODAR_CRON` mantém o controle funcional do projeto.

Os segredos exigidos são `GROQ_API_KEY`, `GEMINI_API_KEY`, `MONGO_URI`, `MONGO_DATABASE` e `JOBS_TOKEN`. O PostgreSQL usa o binding Hyperdrive definido em `wrangler.jsonc`, que aponta para o banco `astro_2` já configurado na conta. Não registre valores em arquivos do repositório.

Para instalar e validar localmente:

```sh
npm ci
npm test
npm run check
```

`GET /health` retorna apenas a saúde do serviço. A rota `POST /run?dry_run=true` exige `Authorization: Bearer <JOBS_TOKEN>` e sempre executa sem gravar nem chamar modelos de IA; também valida uma consulta `SELECT 1` pelo Hyperdrive. Só o Cron pode executar atualizações e sincronizar a procedure PostgreSQL `ler_json_nr`.

O workflow GitHub Actions permanece ativo até validar o cron no Worker e uma execução equivalente. Desative-o depois da validação para evitar agendadores duplicados. O cron é trimestral, portanto a primeira execução futura ocorrerá na próxima data correspondente.

## Limites gratuitos

Não usa Workers Paid nem Cloudflare Containers. A rotina usa conexões HTTP para o site e modelos e conexões de banco via driver MongoDB e Hyperdrive. Confirme limites gratuitos dos provedores MongoDB, Groq, Gemini e Aiven separadamente; este repositório não muda seus planos.

## Exportação Grafana

O Worker envia resultados resumidos do Cron e da validação manual em OTLP/HTTP para GRAFANA_OTLP_ENDPOINT; GRAFANA_OTLP_HEADERS é um Secret. A exportação omite texto de NRs e credenciais e não interrompe a atualização quando falha.
