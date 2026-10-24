# nr-updater no Cloudflare Workers

O Worker substitui o Chromium/Playwright do projeto por coleta HTTP da página oficial, mantendo a análise Groq com fallback Gemini e as gravações em MongoDB e PostgreSQL. A publicação usa Worker comum, Cron Trigger e o Hyperdrive `astro-email-db` já existente; não usa Containers nem cria banco.

## Execução

O cron executa diariamente com a expressão `0 3 * * *` (03:00 UTC, meia-noite no horário de Brasília). `JOBS_ENABLED` e `RODAR_CRON` mantêm o controle funcional do projeto.

Os segredos exigidos são `GROQ_API_KEY`, `GEMINI_API_KEY`, `MONGO_URI`, `MONGO_DATABASE` e `JOBS_TOKEN`. O PostgreSQL usa o binding Hyperdrive definido em `wrangler.jsonc`, que aponta para o banco `astro_2` já configurado na conta. Não registre valores em arquivos do repositório.

Para instalar e validar localmente:

```sh
npm ci
npm test
npm run check
```

`GET /health` retorna apenas a saúde do serviço. A rota `POST /run?dry_run=true` exige `Authorization: Bearer <JOBS_TOKEN>` e sempre executa sem gravar nem chamar modelos de IA; também valida uma consulta `SELECT 1` pelo Hyperdrive. Só o Cron pode executar atualizações e sincronizar a procedure PostgreSQL `ler_json_nr`.

Caso exista outro agendador para a mesma rotina, desative-o depois da validação para evitar execuções duplicadas.

## Limites gratuitos

Não usa Workers Paid nem Cloudflare Containers. A rotina usa conexões HTTP para o site e modelos e conexões de banco via driver MongoDB e Hyperdrive. Confirme limites gratuitos dos provedores MongoDB, Groq, Gemini e Aiven separadamente; este repositório não muda seus planos.

## Exportação Grafana

O Worker envia resultados resumidos do Cron e da validação manual em OTLP/HTTP para GRAFANA_OTLP_ENDPOINT; GRAFANA_OTLP_HEADERS é um Secret. A exportação omite texto de NRs e credenciais e não interrompe a atualização quando falha.

A sincronização chama `ler_json_nr(text)` com JSON serializado. O parâmetro
é enviado como `text`, conforme a assinatura documentada no banco.
