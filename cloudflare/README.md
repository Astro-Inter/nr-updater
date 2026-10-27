# nr-updater no Cloudflare Workers

O Worker substitui o Chromium/Playwright do projeto por coleta HTTP da página oficial, usando `openai/gpt-6-luna` exclusivamente pelo OpenRouter. As análises são gravadas em `nrs_pendentes` para revisão no web; a collection `nrs` permanece como fonte aprovada e exclusiva da sincronização PostgreSQL. A publicação usa Worker comum, Cron Trigger e o Hyperdrive `astro-email-db` já existente; não usa Containers nem cria banco.

Cada NR possui um candidato pendente com os mesmos campos de `nrs`. Datas já
aprovadas ou pendentes não são reanalisadas; uma nova data substitui somente o
candidato. A aprovação e a remoção do pendente serão realizadas pelo web. O Worker
não altera documentos aprovados, inclusive na normalização de usabilidade, que
agora afeta apenas pendentes. Consulte o README principal para o contrato de revisão.

## Execução

O cron executa diariamente com a expressão `0 3 * * *` (03:00 UTC, meia-noite no horário de Brasília). `JOBS_ENABLED` e `RODAR_CRON` mantêm o controle funcional do projeto.

Cada execução começa sincronizando a collection aprovada `nrs` com PostgreSQL
pela procedure `ler_json_nr`, antes de coletar e gerar análises pendentes. Assim,
uma falha posterior na coleta ou nos modelos não impede a sincronização diária.
O modo `dry_run` continua sem chamar a procedure nem gravar dados.

Os segredos exigidos são `OPENROUTER_API_KEY`, `MONGO_URI`, `MONGO_DATABASE` e `JOBS_TOKEN`. O PostgreSQL usa o binding Hyperdrive definido em `wrangler.jsonc`, que aponta para o banco `astro_2` já configurado na conta. Não registre valores em arquivos do repositório.

Para instalar e validar localmente:

```sh
npm ci
npm test
npm run check
npm run build
```

`GET /health` retorna apenas a saúde do serviço. A rota `POST /run?dry_run=true` exige `Authorization: Bearer <JOBS_TOKEN>` e sempre executa sem gravar nem chamar modelos de IA; também valida uma consulta `SELECT 1` pelo Hyperdrive. Só o Cron pode executar atualizações e sincronizar a procedure PostgreSQL `ler_json_nr`.

Caso exista outro agendador para a mesma rotina, desative-o depois da validação para evitar execuções duplicadas.

## Limites gratuitos

Não usa Workers Paid nem Cloudflare Containers. A rotina usa conexões HTTP para o site e modelos e conexões de banco via driver MongoDB e Hyperdrive. Confirme limites gratuitos dos provedores MongoDB, OpenRouter e Aiven separadamente; este repositório não muda seus planos.

## Exportação Grafana

O Worker envia resultados resumidos do Cron e da validação manual em OTLP/HTTP para GRAFANA_OTLP_ENDPOINT; GRAFANA_OTLP_HEADERS é um Secret. A exportação omite texto de NRs e credenciais e não interrompe a atualização quando falha.

A sincronização chama `ler_json_nr(text)` com JSON serializado. O parâmetro
é enviado como `text`, conforme a assinatura documentada no banco.

## Preparar o segredo sem publicar

Use `wrangler versions secret put OPENROUTER_API_KEY` a partir desta pasta,
informando a chave pelo prompt seguro. Esse comando cria versão não publicada;
revise a versão e autorize a publicação do código separadamente. Não use
`wrangler secret put` durante a preparação, pois ele altera a versão ativa.
Preserve os secrets de banco, JOBS_TOKEN, Hyperdrive e agendamentos existentes.
Após a publicação e validação, as chaves antigas podem ser removidas em uma
mudança separada, preservando a possibilidade de retorno à versão anterior.
