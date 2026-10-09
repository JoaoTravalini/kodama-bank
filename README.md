# Kodama Bank

API bancária para profissionais autônomos. O projeto implementa cadastro, autenticação, contas pessoal e profissional, depósitos simulados, transferências, extrato e acompanhamento de cobranças por serviços prestados.

> Este é um projeto demonstrativo. Depósitos e pagamentos de cobranças são simulados: a aplicação não emite boletos, não realiza Pix e não movimenta dinheiro real.

## Funcionalidades

- Cadastro de cliente com validação de CPF e criação das contas pessoal e profissional.
- Login com JWT e consulta ao perfil do cliente.
- Consulta de contas restrita ao proprietário.
- Depósito simulado autorizado por `INTERNAL-TOKEN`, com proteção contra crédito duplicado.
- Solicitação de transferência com chave de idempotência.
- Transferências gratuitas entre contas do mesmo cliente. Entre clientes diferentes, tarifa de 0,5% do valor, limitada a R$ 2,00.
- Processamento de transferências por um worker separado da API.
- Rejeição de transferências sem saldo suficiente ou que ultrapassem o limite da conta de destino.
- Lançamentos de crédito, débito e tarifa registrados junto com a atualização dos saldos.
- Extrato paginado por conta, protegido por JWT.
- Registro e consulta de cobranças por serviços na conta profissional.
- Quitação simulada de cobranças, vinculando cobrança, depósito, saldo e extrato.
- Agenda de recebíveis com vencimento opcional, identificação de atrasos e resumo de valores abertos, atrasados e pagos.

## Fluxos principais

### Transferência

1. O cliente solicita a transferência pela API. Ela é registrada como `PENDING`.
2. O worker procura transferências pendentes no PostgreSQL.
3. Ele verifica saldo e limite da conta de destino.
4. Se a transferência puder ser feita, atualiza os saldos, registra os lançamentos e marca a operação como `COMPLETED`.
5. Se alguma regra impedir a transferência, marca a operação como `REJECTED` e registra o motivo. Nesse caso, não movimenta saldos nem cobra tarifa.

O processamento usa uma transação de banco e bloqueia as linhas envolvidas. Uma falha técnica desfaz uma operação incompleta, e transferências concorrentes não podem gastar o mesmo saldo duas vezes.

### Cobrança por serviço

1. O autônomo registra na conta profissional um serviço prestado, o valor a receber e, opcionalmente, a data de vencimento. A cobrança começa como `OPEN` e não altera o saldo.
2. A API devolve uma referência de pagamento no formato `charge:UUID`.
3. Para demonstrar o recebimento, uma operação interna envia um depósito simulado à conta profissional com essa referência e o valor exato.
4. O depósito registra o crédito no extrato, atualiza o saldo e altera a cobrança para `PAID` na mesma transação de banco.
5. Repetir o mesmo depósito recupera a operação existente, sem creditar a conta novamente.

Uma referência de cobrança desconhecida, uma conta diferente ou um valor divergente são recusados sem movimentar o saldo. O cliente pode consultar suas cobranças com JWT, mas quitar uma cobrança exige `INTERNAL-TOKEN`.

Uma cobrança `OPEN` com vencimento anterior à data atual em São Paulo aparece com `overdue: true`; ela continua `OPEN` no banco. Vencimento no dia atual ainda não é atraso. Depois do pagamento, `overdue` passa a `false`. O resumo de recebíveis soma todas as cobranças da conta profissional, independentemente da paginação da listagem; `overdue` é um subconjunto de `open`.

## Requisitos

- Docker com Docker Compose.
- Python 3.11 para executar os testes na máquina local.

## Executar localmente

O arquivo `.env` é opcional para testes locais: o Docker Compose possui valores de demonstração. Para definir seus próprios segredos, crie um `.env` na raiz:

```dotenv
JWT_SECRET=SUBSTITUA_POR_UM_SEGREDO_ALEATORIO_LONGO
INTERNAL_TOKEN=SUBSTITUA_POR_UM_TOKEN_LOCAL
```

Para gerar uma chave JWT:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Não versione o arquivo `.env`.

Suba os serviços:

```bash
docker compose up -d --build
docker compose ps
```

O Compose inicia `api`, `db` (PostgreSQL) e `worker`. Aguarde a API e o banco aparecerem como `healthy`. A API responde em `http://127.0.0.1:3000`.

Verifique:

```bash
curl -i http://127.0.0.1:3000/health_check
```

A resposta esperada é `204 No Content`.

Os scripts SQL em `database/` são aplicados automaticamente **somente quando um banco novo é inicializado**. Reconstruir a imagem não reaplica migrações a um volume existente. Para um banco local existente, execute apenas as migrações que ainda faltam, na ordem. Se o banco ainda não possui a tabela de cobranças, aplique primeiro:

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U bootcamp -d bootcamp < database/migrations/004_service_charges.sql
```

Em seguida, se ainda não possui a coluna `due_date`, aplique:

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U bootcamp -d bootcamp < database/migrations/005_charge_due_date.sql
```

A migração `005` também pode ser executada novamente sem duplicar a coluna.

## Rotas

| Método | Rota | Autorização | Descrição |
| --- | --- | --- | --- |
| `GET` | `/health_check` | Nenhuma | Verifica se a API está respondendo |
| `POST` | `/clients` | Nenhuma | Cadastra cliente e cria suas duas contas |
| `POST` | `/auth/login` | Nenhuma | Retorna um JWT |
| `GET` | `/clients/me` | JWT | Consulta o perfil autenticado |
| `GET` | `/accounts` | JWT | Lista as contas do cliente |
| `GET` | `/accounts/{account_key}` | JWT | Consulta uma conta do cliente |
| `POST` | `/accounts/{account_key}/deposits` | `INTERNAL-TOKEN` | Registra um depósito simulado |
| `POST` | `/accounts/{account_key}/transfers` | JWT | Solicita uma transferência |
| `GET` | `/accounts/{account_key}/transfers/{transaction_key}` | JWT | Consulta o estado de uma transferência |
| `GET` | `/accounts/{account_key}/entries` | JWT | Consulta o extrato da conta |
| `POST` | `/accounts/{account_key}/charges` | JWT | Registra uma cobrança na conta profissional |
| `GET` | `/accounts/{account_key}/charges` | JWT | Lista as cobranças da conta |
| `GET` | `/accounts/{account_key}/charges/summary` | JWT | Resume os recebíveis da conta profissional |
| `GET` | `/accounts/{account_key}/charges/{charge_key}` | JWT | Consulta uma cobrança |

Nas rotas do cliente, uma conta de outro cliente recebe `404`, assim como uma conta inexistente.

### Cadastro

```http
POST /clients
Content-Type: application/json

{
  "name": "Maria Silva",
  "email": "maria@example.com",
  "document_number": "52998224725",
  "password": "SenhaDeTeste123!"
}
```

O CPF de exemplo serve apenas para testes locais. Use outro CPF válido ao repetir o cadastro, pois o sistema impede duplicatas.

### Login

```http
POST /auth/login
Content-Type: application/json

{
  "email": "maria@example.com",
  "password": "SenhaDeTeste123!"
}
```

Nas rotas do cliente, envie o token recebido no cabeçalho:

```http
Authorization: Bearer SEU_JWT
```

### Depósito simulado

```http
POST /accounts/SUA_CHAVE_DE_CONTA/deposits
INTERNAL-TOKEN: SEU_TOKEN_LOCAL
Content-Type: application/json

{
  "amount": "100.00",
  "external_reference": "pagamento-teste-001"
}
```

`external_reference` identifica o depósito. Repetir a referência com os mesmos dados não credita a conta novamente; reutilizá-la com dados diferentes gera conflito.

Referências que começam com `charge:` são reservadas para pagamentos simulados de cobranças e seguem as regras descritas abaixo.

### Cobrança por serviço

O cliente registra um valor a receber em sua **conta profissional**:

```http
POST /accounts/CHAVE_DA_CONTA_PROFISSIONAL/charges
Authorization: Bearer SEU_JWT
Content-Type: application/json

{
  "description": "Criação de site",
  "amount": "120.00",
  "due_date": "2026-10-15"
}
```

`due_date` é opcional, usa `AAAA-MM-DD` e precisa ser uma data válida. Pode ser anterior à data atual para registrar um serviço já vencido. Sem vencimento, a resposta traz `due_date: null`. A resposta também inclui `charge_key`, estado `OPEN`, `overdue` e `payment_reference` no formato `charge:UUID`. Criar a cobrança não deposita dinheiro.

Para listar cobranças:

```http
GET /accounts/CHAVE_DA_CONTA_PROFISSIONAL/charges?page=1&limit=20
Authorization: Bearer SEU_JWT
```

`page` aceita valores de 1 a 999999 e `limit` aceita valores de 1 a 100. Os padrões são `page=1` e `limit=20`.

Para consultar os totais da conta profissional:

```http
GET /accounts/CHAVE_DA_CONTA_PROFISSIONAL/charges/summary
Authorization: Bearer SEU_JWT
```

Exemplo de resposta:

```json
{
  "account_key": "UUID_DA_CONTA_PROFISSIONAL",
  "as_of_date": "2026-10-09",
  "open": {"count": 3, "amount": "190.00"},
  "overdue": {"count": 1, "amount": "50.00"},
  "paid": {"count": 2, "amount": "150.00"}
}
```

`as_of_date` é a data em São Paulo usada para avaliar os vencimentos. `open` inclui as cobranças atrasadas; não some `open` e `overdue`. `paid` é o histórico de cobranças pagas, e não o saldo atual da conta. Esses totais cobrem todas as cobranças da conta, mesmo quando a listagem é paginada.

Para consultar uma cobrança:

```http
GET /accounts/CHAVE_DA_CONTA_PROFISSIONAL/charges/CHARGE_KEY
Authorization: Bearer SEU_JWT
```

Para simular seu pagamento, use **a referência devolvida na criação** e envie o valor exato pelo endpoint interno:

```http
POST /accounts/CHAVE_DA_CONTA_PROFISSIONAL/deposits
INTERNAL-TOKEN: SEU_TOKEN_LOCAL
Content-Type: application/json

{
  "amount": "120.00",
  "external_reference": "charge:UUID_DA_COBRANCA"
}
```

Após esse depósito, a consulta da cobrança retorna `PAID`, `paid_at` e `overdue: false`; o crédito pode ser visto no extrato. O JWT do cliente não autoriza depósitos. Cada chamada de criação de cobrança registra **uma nova cobrança**; a proteção contra repetição se aplica ao depósito com a mesma referência.

### Solicitação de transferência

```http
POST /accounts/CHAVE_DA_CONTA_DE_ORIGEM/transfers
Authorization: Bearer SEU_JWT
Content-Type: application/json

{
  "amount": "40.00",
  "destination_account_key": "CHAVE_DA_CONTA_DE_DESTINO",
  "idempotency_key": "2b137445-6846-4381-b3ab-59042970f4f0"
}
```

O valor é uma string decimal com duas casas. A API retorna a transferência inicialmente como `PENDING`. Repetir a solicitação com a mesma chave e os mesmos dados recupera a mesma operação; alterar os dados mantendo a chave gera conflito.

A tarifa é calculada na solicitação, mas **só é debitada quando a transferência é concluída**.

### Extrato

```http
GET /accounts/SUA_CHAVE_DE_CONTA/entries?page=1&limit=20&kind=FEE
Authorization: Bearer SEU_JWT
```

Todos os parâmetros são opcionais:

| Parâmetro | Valores | Padrão |
| --- | --- | --- |
| `page` | Inteiro de 1 a 999999 | `1` |
| `limit` | Inteiro de 1 a 100 | `20` |
| `kind` | `CREDIT`, `DEBIT` ou `FEE` | Todos |

Exemplo de resposta:

```json
{
  "account_key": "UUID_DA_CONTA",
  "page": 1,
  "limit": 20,
  "has_more": false,
  "entries": [
    {
      "entry_key": "UUID_DO_LANCAMENTO",
      "transaction_key": "UUID_DA_TRANSACAO",
      "transaction_kind": "TRANSFER",
      "kind": "FEE",
      "amount": "-0.20",
      "balance_after": "59.80",
      "created_at": "2026-10-02T03:00:00"
    }
  ]
}
```

`CREDIT` aumenta o saldo; `DEBIT` e `FEE` aparecem com valor negativo. `balance_after` é o saldo após aquele lançamento. Transferências pendentes ou rejeitadas não aparecem no extrato porque não geraram lançamentos.

## Testes

Com a API e o banco saudáveis, ative o ambiente Python 3.11. No Git Bash do Windows:

```bash
source .venv/Scripts/activate
```

Pare o worker antes dos testes de integração: alguns testes precisam observar uma transferência no estado `PENDING`, antes do processamento.

```bash
docker compose stop worker
PYTHONPATH=src SERVER_LOCALHOST=127.0.0.1 python -m pytest -q tests/integration tests/unit
docker compose start worker
PYTHONPATH=src SERVER_LOCALHOST=127.0.0.1 python -m pytest -q tests/e2e
```

Os testes das cobranças verificam criação sem movimentação financeira, autenticação, isolamento entre clientes, validação, paginação, vencimento, totais de recebíveis, pagamento correto, rejeição de pagamentos incompatíveis e proteção contra créditos duplicados, inclusive com requisições simultâneas.

Na CI, os testes de integração e unidade rodam antes de iniciar o worker; os testes de ponta a ponta rodam depois, com os três serviços ligados.

Não execute `DbUtils.rollback()` nos testes das funcionalidades novas: essa rotina recria apenas o esquema inicial e pode remover tabelas acrescentadas pelas migrações.

## Organização do código

| Pasta | Responsabilidade |
| --- | --- |
| `src/resources` | Recebe requisições HTTP e monta respostas |
| `src/controllers` | Aplica regras de negócio e coordena operações |
| `src/repositories` | Faz consultas e persistência no PostgreSQL |
| `src/models` | Representa as tabelas no código |
| `src/schemas` | Valida corpos de requisição e parâmetros |
| `src/errors` | Define erros de negócio e suas respostas HTTP |
| `src/middlewares` | Cuida de contexto, logs, sessão e token interno |
| `src/workers` | Processa transferências pendentes fora da requisição HTTP |
| `database` | Define o esquema inicial e as migrações SQL |
| `tests` | Verifica regras isoladas e fluxos por HTTP |

## Estado do projeto

O núcleo bancário e o fluxo simulado de valores a receber para profissionais autônomos estão implementados e testados. O produto permite registrar um serviço, acompanhar o vencimento e os totais a receber, simular o recebimento na conta profissional e consultar o crédito no extrato.

Pagamentos externos reais, emissão de boletos, Pix e documentos fiscais estão fora do escopo desta versão.