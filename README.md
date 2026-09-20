# nr-updater
Cron para rodar um RPA que altera ou inclui todas as NRs do site do governo em nosso MongoDB e PostgreSQL.

## Observabilidade

O projeto utiliza o SDK do OpenTelemetry para enviar logs ao Grafana Cloud por
OTLP/HTTP. Os logs continuam sendo escritos no console em JSON. O envio remoto é
opcional e só é ativado quando as duas variáveis abaixo estão preenchidas:

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-<regiao>.grafana.net/otlp
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<credencial>
```

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
