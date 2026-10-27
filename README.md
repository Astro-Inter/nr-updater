# nr-updater
Cron para coletar NRs do site do governo e gerar análises para revisão no MongoDB.

## Revisão das análises

As análises geradas pela IA são gravadas em `nrs_pendentes`, com os mesmos campos
de `nrs`: `_id` (número da NR), `nome`, `revogada`, `descricao`, `objetivo`,
`aplicabilidade`, `tempo_reciclagem_meses`, `usabilidade`, `ultima_atualizacao`
e `data_criacao`. Não há publicação automática: `nrs` contém os dados aprovados.

Há um candidato por NR. Se a data coletada já estiver aprovada ou pendente, a IA
não é chamada novamente. Uma nova data substitui o candidato anterior da mesma
NR, preservando sua `data_criacao`, sem modificar a versão aprovada. Dados já
existentes em `nrs` não são movidos nem apagados.

A futura aprovação no web deve copiar o candidato revisado para `nrs` e remover
somente a versão pendente aprovada (conferindo também `ultima_atualizacao` para
não apagar uma atualização mais recente). Essa ação e a tela de revisão não são
implementadas neste serviço. Enquanto o web não aprovar, os candidatos não entram
no PostgreSQL: a sincronização periódica lê exclusivamente `nrs`. Após a aprovação,
a próxima execução diária sincroniza os dados aprovados.

A sincronização chama `ler_json_nr` diariamente às 03:00 UTC (00:00 de Brasília),
no início da execução, antes da coleta e da IA. Ela envia exclusivamente os dados
de `nrs` no formato já esperado pela procedure: `id`, `nome`, `revogada` e
`tempo_reciclagem_mes`. Uma falha posterior na coleta ou na IA não desfaz essa
sincronização; registros em `nrs_pendentes` nunca entram nesse payload.

O usuário MongoDB do serviço precisa de leitura em `nrs` e leitura/escrita em
`nrs_pendentes`. A collection pendente é criada automaticamente na primeira
gravação; o cron não promove nem remove candidatos automaticamente.

## Observabilidade

O projeto utiliza o SDK do OpenTelemetry para enviar logs ao Grafana Cloud por
OTLP/HTTP. Os logs continuam sendo escritos no console em JSON. O envio remoto é
opcional e só é ativado quando as duas variáveis abaixo estão preenchidas:

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-<regiao>.grafana.net/otlp
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<credencial>
```

O endpoint recomendado é o gateway-base copiado do portal do Grafana Cloud,
terminado em `/otlp`. A URL completa terminada em `/otlp/v1/logs` também é
aceita. Não use o endpoint de push do Loki (`/loki/api/v1/push`), pois ele não é
um endpoint OTLP.

Não salve valores reais no repositório. Em desenvolvimento, copie
`.env.example` para `.env`; sem as credenciais, a aplicação funciona normalmente
usando apenas o console. Os recursos enviados têm `service.name=nr-updater`, além
de ambiente, versão, job e worker. O ambiente é identificado automaticamente e,
no GitHub Actions, a versão do serviço usa o SHA da execução.

No GitHub, crie em **Settings > Secrets and variables > Actions** os secrets
`GRAFANA_OTLP_ENDPOINT` e `GRAFANA_OTLP_HEADERS`. O workflow os disponibiliza
para a aplicação como `OTEL_EXPORTER_OTLP_ENDPOINT` e
`OTEL_EXPORTER_OTLP_HEADERS`; a credencial não aparece no YAML.

Para validar a integração, execute `python main.py` com as variáveis configuradas.
No Grafana Cloud, abra **Drilldown > Logs** (ou **Explore > Logs**) e filtre por
`service_name = nr-updater`. A conversão OTLP do Loki troca os pontos dos nomes
de atributos por sublinhados, por isso `service.name` aparece como
`service_name`.

## Diagnóstico operacional

Consulte [os campos e limites dos novos diagnósticos](docs/observability-diagnostics.md) para investigar falhas por requisição ou execução no Grafana.
