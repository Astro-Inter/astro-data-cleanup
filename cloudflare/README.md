# astro-data-cleanup no Cloudflare Workers

Implementação nativa do Worker para os três jobs de limpeza, sem Containers. Os
jobs rodam no Durable Object com armazenamento SQLite e se conectam ao PostgreSQL
por Hyperdrive, ao MongoDB por TCP e ao Qdrant pela API HTTPS. Uma única expressão
Cron preserva os três horários UTC de cada hora:

| Job | Cron UTC | Operação |
| --- | --- | --- |
| `firebase-orphan-users` | minuto 05 | Detecta usuários do Firebase sem conta correspondente no PostgreSQL |
| `chatbot-sessions` | minuto 25 | Localiza sessões com mais de um ano e conta os vetores relacionados |
| `old-conversations` | minuto 45 | Localiza mensagens com mais de dois anos |

A configuração usa `5,25,45 * * * *` como um único Cron Trigger da conta. O Worker
identifica cada rotina pelo minuto agendado, preservando a cadência anterior e
liberando dois dos cinco slots gratuitos da conta.

O Worker está configurado com `JOBS_ENABLED=true` e `DRY_RUN=true`. Nesse modo,
ele só consulta e conta candidatos; não apaga usuários, documentos ou vetores.
Os três workflows do GitHub estão desativados; a exclusão real aguarda aprovação.
O endpoint manual também exige `JOBS_TOKEN` e assume simulação quando
`dry_run` não é informado. A API também recusa `dry_run=false` enquanto o
Worker estiver configurado em simulação.

Endpoints publicados:

- `GET /health` verifica se o Worker responde.
- `GET /status` exige `Authorization: Bearer <JOBS_TOKEN>` e retorna estado e cron.
- `POST /jobs/firebase-orphan-users`, `POST /jobs/chatbot-sessions` ou
  `POST /jobs/old-conversations` iniciam uma simulação autenticada. Use
  `?dry_run=true` para deixar esse comportamento explícito.

## Configuração

`wrangler.jsonc` desativa observabilidade e não configura Containers. O
PostgreSQL usa o Hyperdrive `astro-email-db` já existente. MongoDB, Firebase,
Qdrant e o token da API usam Secrets do Worker. As variáveis públicas
`FIREBASE_PROJECT_ID`, `MONGODB_DATABASE` e `QDRANT_URL` são configuração, não
credenciais. Não inclua valores do `.env` no Git.

Instale e valide com `npm ci`, `npm run check` e `npm test`. O deploy protegido
recusa uma conta diferente, cron diferente, modo de exclusão, Containers,
observabilidade ativa ou ausência de Hyperdrive:

```powershell
npm run deploy -- --dry-run
npm run deploy
```

O `--dry-run` valida o bundle sem publicar. O deploy normal publica os valores
de `wrangler.jsonc`, que atualmente mantêm `DRY_RUN=true`. Os workflows de
limpeza já estão desativados no GitHub. O endpoint `/health` é público e não
revela configuração.

## Limites operacionais

As três execuções horárias geram até 72 disparos de Cron e chamadas ao Durable
Object por dia. O Workers Free permite 100.000 requests/dia, e o Durable Object
SQLite tem cotas gratuitas diárias; acima delas, as operações falham sem cobrar
excedentes no plano Free. O Hyperdrive Free inclui 100.000 consultas/dia.

O MongoDB Atlas precisa permitir conexões TCP originadas pelos endereços de
saída do Cloudflare Workers. Não amplie a lista de IPs permitidos para
`0.0.0.0/0`; se o Atlas negar acesso, a validação deve parar e a rede deve ser
configurada de forma apropriada. Execuções com falhas ou timeout devem ser
inspecionadas antes de qualquer repetição.
