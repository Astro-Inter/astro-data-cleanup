# Astro Data Cleanup

Serviço Python do ecossistema Astro para executar rotinas automatizadas de
manutenção e expurgo de dados. O projeto concentra a regra de negócio em
workers independentes; o GitHub Actions será responsável apenas por preparar o
ambiente e disparar cada worker.

> Estado atual: fundação criada pela SCRUM-230, worker de usuários órfãos
> implementado pela SCRUM-231 e worker de sessões antigas implementado pela
> SCRUM-232. O expurgo de conversas antigas foi implementado pela SCRUM-233 e
> as execuções automatizadas pela SCRUM-234.

## Princípios da arquitetura

- um ponto central de execução (`python -m src.main`);
- workers isolados, registrados por nome;
- conexões externas concentradas em `src/database` e `src/integrations`;
- configuração por variáveis de ambiente;
- logging padronizado, sem `print` na lógica de negócio;
- `DRY_RUN=true` como padrão seguro;
- dependências externas injetáveis para permitir testes com mocks.

## Estrutura

```text
astro-data-cleanup/
├── .github/
│   └── workflows/                 # Automações implementadas na SCRUM-234
├── src/
│   ├── config/
│   │   ├── logging_config.py
│   │   └── settings.py
│   ├── database/
│   │   ├── mongodb.py
│   │   ├── postgres.py
│   │   └── qdrant.py
│   ├── integrations/
│   │   └── firebase.py
│   ├── workers/
│   │   ├── firebase_orphan_users/ # Worker implementado na SCRUM-231
│   │   ├── chatbot_sessions/      # Worker implementado na SCRUM-232
│   │   ├── old_conversations/     # Worker implementado na SCRUM-233
│   │   ├── base.py
│   │   └── registry.py
│   └── main.py
├── tests/
├── .env.example
└── pyproject.toml
```

## Requisitos

- Python 3.11 ou superior.

Para instalar o projeto e as ferramentas de desenvolvimento:

```bash
python -m pip install -e ".[dev]"
```

## Configuração

Copie `.env.example` para `.env` apenas como referência local e exporte as
variáveis no ambiente. O serviço não carrega arquivos `.env` automaticamente,
o que evita comportamento implícito entre a máquina local e o GitHub Actions.

Variáveis disponíveis na fundação:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `APP_ENV` | `development` | Ambiente da aplicação |
| `DRY_RUN` | `true` | Impede exclusões reais quando habilitado |
| `LOG_LEVEL` | `INFO` | Nível global de logging |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | vazio | URL base OTLP/HTTP do Grafana Cloud |
| `OTEL_EXPORTER_OTLP_HEADERS` | vazio | Header de autenticação OTLP |

As variáveis de PostgreSQL, MongoDB, Qdrant e Firebase estão documentadas no
`.env.example`. O PostgreSQL é configurado por uma URL completa em
`POSTGRES_URL`. Para o Firebase Admin SDK, o projeto usa `FIREBASE_PROJECT_ID` e
o JSON completo da conta de serviço codificado em Base64 em
`FIREBASE_CREDENTIALS_BASE64`.

O worker valida que o `project_id` dentro das credenciais corresponde a
`FIREBASE_PROJECT_ID` antes de acessar o Authentication. Essa proteção evita
executar o expurgo acidentalmente em outro projeto Firebase.

O MongoDB usa `MONGODB_URI` e `MONGODB_DATABASE`. As coleções configuráveis
`MONGODB_SESSIONS_COLLECTION` e `MONGODB_MESSAGES_COLLECTION` têm como padrão
`sessoes` e `mensagens`, respectivamente. O `QDRANT_URL` deve ser a URL base da
instância, sem o caminho `/dashboard`, e usa `QDRANT_API_KEY`. A coleção
`QDRANT_SUMMARIES_COLLECTION` tem como padrão `memoria_resumos`.

## Execução local

Listar workers registrados:

```bash
python -m src.main --list
```

Executar um worker:

```bash
python -m src.main firebase-orphan-users
```

Executar todos os workers registrados:

```bash
python -m src.main all
```

Os workers disponíveis nesta etapa são `firebase-orphan-users`,
`chatbot-sessions` e `old-conversations`.

### DRY RUN

`DRY_RUN` é habilitado por padrão. Para tornar a intenção explícita no
PowerShell:

```powershell
$env:DRY_RUN = "true"
python -m src.main all
```

Uma exclusão real só poderá ocorrer com `DRY_RUN=false` e com o worker concreto
implementado. Cada worker é responsável por consultar e registrar os dados que
seriam removidos antes de efetuar qualquer exclusão.

## Worker de usuários órfãos no Firebase

O worker `firebase-orphan-users`:

1. lista os UIDs existentes em `conta.firebase_uid` no PostgreSQL;
2. lista todas as contas do Firebase Authentication por páginas;
3. identifica contas do Firebase ausentes no PostgreSQL;
4. revalida cada UID no PostgreSQL imediatamente antes da possível exclusão;
5. em `DRY_RUN`, apenas registra o que seria removido;
6. fora de `DRY_RUN`, exclui cada conta individualmente e registra o resultado.

A consulta à tabela `conta` inclui suas tabelas herdadas `usuario` e `admin`.
Assim, uma conta administrativa existente também é preservada. Se uma consulta
de validação falhar, o worker interrompe a execução em vez de assumir que a
conta é órfã. Falhas individuais de exclusão são registradas e fazem o processo
terminar com código diferente de zero.

Execução segura inicial:

```bash
DRY_RUN=true python -m src.main firebase-orphan-users
```

Depois de revisar os logs, a exclusão real pode ser habilitada explicitamente:

```bash
DRY_RUN=false python -m src.main firebase-orphan-users
```

## Worker de sessões antigas do chatbot

O worker `chatbot-sessions` considera expirada uma sessão de `sessoes` quando
`iniciada_em` é anterior a um ano-calendário contado em UTC. O `_id` textual do
documento identifica o payload `session_id` dos pontos na coleção
`memoria_resumos`.

Para cada sessão elegível, o worker:

1. revalida no MongoDB se a sessão ainda está expirada;
2. conta ou remove todos os pontos cujo payload `session_id` corresponde ao
   `_id` da sessão;
3. aguarda o Qdrant concluir a operação;
4. remove o documento do MongoDB usando `_id`, `iniciada_em` original e data
   limite como condições de segurança.

O Qdrant é processado antes do MongoDB. Se o Qdrant falhar, o documento do
MongoDB é preservado. Se o MongoDB falhar depois da remoção vetorial, a sessão
continua disponível para uma nova execução, e a remoção por filtro no Qdrant é
idempotente.

Execução inicial em modo seguro:

```bash
DRY_RUN=true python -m src.main chatbot-sessions
```

## Worker de conversas antigas

O worker `old-conversations` considera expirada cada mensagem da coleção
`mensagens` cujo campo BSON Date `data` seja estritamente anterior a dois
anos-calendário contados em UTC.

Antes de excluir cada documento, o worker revalida seu `_id` e a data limite.
A exclusão também exige que o campo `data` ainda seja exatamente igual ao valor
lido inicialmente, evitando remover uma mensagem modificada durante a execução.
Falhas individuais são registradas, as demais mensagens continuam sendo
processadas e o worker termina com código diferente de zero.

Execução inicial em modo seguro:

```bash
DRY_RUN=true python -m src.main old-conversations
```

## Execução automatizada

Cada worker possui um workflow dedicado no GitHub Actions. Os agendamentos
usam UTC e são escalonados para impedir que as rotinas iniciem simultaneamente:

| Workflow | Worker | Agendamento semanal |
| --- | --- | --- |
| `firebase-orphan-users.yml` | `firebase-orphan-users` | Domingo, 03:10 UTC |
| `chatbot-sessions.yml` | `chatbot-sessions` | Domingo, 03:30 UTC |
| `old-conversations.yml` | `old-conversations` | Domingo, 03:50 UTC |

Execuções agendadas usam `DRY_RUN=false` para realizar o expurgo. Ao iniciar
um workflow manualmente pela aba Actions, o campo `dry_run` começa em `true` e
precisa ser alterado explicitamente para permitir exclusões.

Configure estes GitHub Actions Secrets antes de habilitar os workflows:

| Secret | Workflows que utilizam |
| --- | --- |
| `POSTGRES_URL` | Usuários órfãos |
| `FIREBASE_PROJECT_ID` | Usuários órfãos |
| `FIREBASE_CREDENTIALS_BASE64` | Usuários órfãos |
| `MONGODB_URI` | Sessões e conversas antigas |
| `MONGODB_DATABASE` | Sessões e conversas antigas |
| `QDRANT_URL` | Sessões antigas |
| `QDRANT_API_KEY` | Sessões antigas |
| `GRAFANA_OTLP_ENDPOINT` | Todos os workers |
| `GRAFANA_OTLP_HEADERS` | Todos os workers |

Os workflows solicitam somente permissão de leitura do conteúdo do
repositório, não persistem credenciais Git no checkout e bloqueiam execuções
simultâneas do mesmo worker. Agendamentos do GitHub Actions passam a funcionar
quando os arquivos estão na branch padrão do repositório.

## Observabilidade

O projeto usa OpenTelemetry para enviar logs ao Grafana Cloud pelo protocolo
OTLP/HTTP. O console continua recebendo cada evento em JSON, com `timestamp`,
`level`, `service.name`, `service.version`, ambiente e mensagem. Durante a
execução também são incluídos, quando aplicáveis, `job.name`, `worker.name`,
`duration` e `status`. O identificador do serviço é
`service.name=astro-data-cleanup`.

A exportação é opcional. Ela só é ativada quando as duas variáveis abaixo têm
valor; sem elas, inclusive no desenvolvimento local, o projeto mantém apenas o
logging no console:

```text
OTEL_EXPORTER_OTLP_ENDPOINT
OTEL_EXPORTER_OTLP_HEADERS
```

Use em `OTEL_EXPORTER_OTLP_ENDPOINT` a URL base exibida no bloco OpenTelemetry
da sua stack Grafana Cloud. Por ser a variável OTLP genérica, não acrescente
`/v1/logs`: o exporter HTTP monta o caminho específico do sinal. O header tem
o formato fornecido pelo Grafana, por exemplo
`Authorization=Basic <credencial-codificada>`. Nunca grave esse valor em
arquivos versionados.

Nos GitHub Actions, crie secrets do repositório ou da organização com estes
nomes:

- `GRAFANA_OTLP_ENDPOINT`: URL base OTLP da stack;
- `GRAFANA_OTLP_HEADERS`: header completo de autenticação.

Os workflows convertem esses secrets nas variáveis `OTEL_EXPORTER_OTLP_*` para
o processo Python. Agenda, execução manual e demais credenciais não são
alteradas.

Para testar localmente sem Grafana, deixe as duas variáveis vazias e execute
`python -m src.main --list` ou um worker em `DRY_RUN=true`. Para validar o envio
real, defina ambas no ambiente, execute um worker seguro e confirme em Grafana
Cloud > Explore > Logs com uma consulta pelo label
`{service_name="astro-data-cleanup"}`. Filtre também por `job_name` ou
`deployment_environment_name` para isolar a execução. A chegada dos eventos
`Worker iniciado` e `Worker finalizado` confirma o pipeline; em caso de falha
de conexão, o processo preserva os logs JSON no console.

## Testes

Os testes não acessam infraestrutura externa. Execute:

```bash
python -m pytest
python -m ruff check .
```

Os workers futuros devem receber seus clientes de dados por injeção e usar
mocks nos testes.

## Como adicionar um worker

1. Crie o módulo em `src/workers/<nome_do_worker>/worker.py`.
2. Herde de `BaseWorker` e defina o atributo `name`.
3. Implemente `run`, respeitando `self.settings.dry_run`.
4. Registre a classe com `@register_worker`.
5. Importe o módulo em `src/workers/__init__.py` para ativar o registro.
6. Adicione testes com clientes externos simulados.
7. Crie um workflow dedicado que invoque o nome registrado.

## Relação com as subtarefas

| Jira | Responsabilidade |
| --- | --- |
| SCRUM-230 | Fundação, configuração, logging, contrato, registro, CLI e testes-base |
| SCRUM-231 | Worker de usuários órfãos no Firebase |
| SCRUM-232 | Worker de sessões antigas no MongoDB e Qdrant |
| SCRUM-233 | Worker de conversas antigas |
| SCRUM-234 | Workflows agendados e execução manual no GitHub Actions |
