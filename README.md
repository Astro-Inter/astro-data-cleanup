# Astro Data Cleanup

Serviço Python do ecossistema Astro para executar rotinas automatizadas de
manutenção e expurgo de dados. O projeto concentra a regra de negócio em
workers independentes; o GitHub Actions será responsável apenas por preparar o
ambiente e disparar cada worker.

> Estado atual: fundação criada pela SCRUM-230 e worker de usuários órfãos
> implementado pela SCRUM-231. Os demais workers e workflows serão adicionados
> nas subtarefas seguintes.

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
│   └── workflows/                 # SCRUM-234
├── src/
│   ├── config/
│   │   ├── logging_config.py
│   │   └── settings.py
│   ├── database/
│   │   └── postgres.py
│   ├── integrations/
│   │   └── firebase.py
│   ├── workers/
│   │   ├── firebase_orphan_users/ # Worker implementado na SCRUM-231
│   │   ├── chatbot_sessions/      # SCRUM-232
│   │   ├── old_conversations/     # SCRUM-233
│   │   ├── base.py
│   │   └── registry.py
│   └── main.py
├── tests/
├── .env.example
└── pyproject.toml
```

Diretórios reservados que ainda não possuem implementação contêm um
`.gitkeep` para serem versionados.

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

As variáveis de PostgreSQL, MongoDB, Qdrant e Firebase estão documentadas no
`.env.example`. O PostgreSQL é configurado por uma URL completa em
`POSTGRES_URL`. Para o Firebase Admin SDK, o projeto usa `FIREBASE_PROJECT_ID` e
o JSON completo da conta de serviço codificado em Base64 em
`FIREBASE_CREDENTIALS_BASE64`.

O worker valida que o `project_id` dentro das credenciais corresponde a
`FIREBASE_PROJECT_ID` antes de acessar o Authentication. Essa proteção evita
executar o expurgo acidentalmente em outro projeto Firebase.

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

O worker disponível nesta etapa é `firebase-orphan-users`.

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
7. Na SCRUM-234, crie um workflow dedicado que invoque o nome registrado.

## Relação com as subtarefas

| Jira | Responsabilidade |
| --- | --- |
| SCRUM-230 | Fundação, configuração, logging, contrato, registro, CLI e testes-base |
| SCRUM-231 | Worker de usuários órfãos no Firebase |
| SCRUM-232 | Worker de sessões antigas no MongoDB e Qdrant |
| SCRUM-233 | Worker de conversas antigas |
| SCRUM-234 | Workflows agendados e execução manual no GitHub Actions |
