# Kodama Bank

API bancária em desenvolvimento para o projeto Kodama Bank, voltado a profissionais autônomos. Esta versão implementa cadastro, autenticação, contas, depósitos simulados, transferências com processamento assíncrono e extrato por conta.

> Os depósitos são operações simuladas para testar os fluxos financeiros. Esta versão não movimenta dinheiro real.

## Funcionalidades implementadas

- Cadastro de cliente com validação de CPF e criação de contas pessoal e profissional.
- Login com JWT e consulta ao perfil do cliente.
- Consulta de contas restrita ao proprietário.
- Depósito simulado autorizado por `INTERNAL-TOKEN`, com proteção contra crédito duplicado pela referência externa.
- Solicitação de transferência com chave de idempotência.
- Tarifa de transferência: gratuita entre contas do mesmo cliente; entre clientes diferentes, 0,5% do valor, limitada a R$ 2,00.
- Processamento de transferências por um worker separado da API.
- Rejeição de transferências sem saldo suficiente ou que ultrapassem o limite da conta de destino.
- Lançamentos financeiros de crédito, débito e tarifa, gravados junto com a atualização dos saldos.
- Extrato paginado por conta, protegido por JWT.

## Como funciona uma transferência

1. O cliente solicita a transferência pela API. A operação é registrada como `PENDING`.
2. O worker procura operações pendentes no PostgreSQL.
3. Ele verifica saldo e limite da conta de destino.
4. Se a transferência puder ser feita, atualiza os saldos, registra os lançamentos e marca a operação como `COMPLETED`.
5. Se alguma regra impedir a transferência, marca a operação como `REJECTED` e registra o motivo. Nesse caso, não movimenta saldos nem cobra tarifa.

O processamento usa transação no banco e bloqueio das linhas envolvidas. Assim, uma falha técnica desfaz a operação incompleta, e transferências concorrentes não podem gastar o mesmo saldo duas vezes.

## Requisitos

- Docker com Docker Compose.
- Python 3.11 para executar os testes na máquina local.

## Executar localmente

Para testar localmente, o `.env` é opcional: o Docker Compose usa uma chave JWT de demonstração. Para usar seus próprios segredos, crie um arquivo `.env` na raiz do projeto com:

```dotenv
JWT_SECRET=SUBSTITUA_POR_UM_SEGREDO_ALEATORIO_LONGO
INTERNAL_TOKEN=SUBSTITUA_POR_UM_TOKEN_LOCAL
```

Você pode gerar o valor de `JWT_SECRET` com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copie o resultado para o `.env`. Não versionе esse arquivo.

Suba os serviços:

```bash
docker compose up -d --build
docker compose ps
```

Aguarde `api` e `db` aparecerem como `healthy`. A API fica em `http://127.0.0.1:3000`. Para conferir:

```bash
curl -i http://127.0.0.1:3000/health_check
```

A resposta esperada é `204 No Content`.

O Docker Compose inicia três serviços: `api`, `db` (PostgreSQL) e `worker`. Os scripts SQL de inicialização executam automaticamente quando um banco **novo** é criado. Em um banco que já existe, novos scripts de migração precisam ser aplicados conforme a etapa correspondente; reconstruir a imagem não reaplica scripts ao volume existente.

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

Nas rotas de conta protegidas por JWT, o cliente só pode acessar suas próprias contas. Uma conta de outro cliente recebe `404`, assim como uma conta inexistente.

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

O CPF de exemplo é apenas para testes locais. Use outro CPF válido ao repetir o cadastro, pois o sistema impede duplicatas.

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

`external_reference` identifica o depósito. Repetir a mesma referência com os mesmos dados não credita a conta novamente; reutilizá-la com dados diferentes gera conflito.

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

Exemplo de estrutura da resposta:

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

`CREDIT` aumenta o saldo; `DEBIT` e `FEE` aparecem com valor negativo. `balance_after` é o saldo da conta após aquele lançamento. Transferências pendentes ou rejeitadas não aparecem no extrato porque não geraram lançamentos.

## Testes

Com a API e o banco saudáveis, ative seu ambiente Python 3.11. No Git Bash do Windows:

```bash
source .venv/Scripts/activate
```

Os testes de integração enviam requisições para a API local e usam o PostgreSQL. Pare o worker antes deles para que ele não processe uma transferência enquanto um teste verifica o estado `PENDING`:

```bash
docker compose stop worker
PYTHONPATH=src SERVER_LOCALHOST=127.0.0.1 python -m pytest -q tests/integration
PYTHONPATH=src python -m pytest -q tests/unit/test_transfer_fee.py
docker compose start worker
PYTHONPATH=src SERVER_LOCALHOST=127.0.0.1 python -m pytest -q tests/e2e/test_transfer_worker.py
```
Na CI, os testes de integração e de unidade rodam antes de iniciar o worker; o teste de ponta a ponta roda depois, com os três serviços ligados.

Não execute `DbUtils.rollback()` nos testes das funcionalidades novas: essa rotina recria apenas o esquema inicial e pode remover tabelas acrescentadas pelas migrações.

## Organização do código

| Pasta | Responsabilidade |
| --- | --- |
| `src/resources` | Recebe as requisições HTTP e monta as respostas |
| `src/controllers` | Aplica regras de negócio e coordena as operações |
| `src/repositories` | Faz consultas e persistência no PostgreSQL |
| `src/models` | Representa as tabelas no código |
| `src/schemas` | Valida corpos de requisição e parâmetros da URL |
| `src/middlewares` | Cuida de contexto, logs, sessão e token interno |
| `src/workers` | Processa transferências pendentes fora da requisição HTTP |
| `database` | Define o esquema inicial e as migrações SQL |
| `tests` | Testa regras isoladas e fluxos de integração |

## Estado do projeto

O núcleo bancário descrito acima está implementado e testado. O produto para profissionais autônomos ainda está em desenvolvimento; este README descreve somente as funcionalidades disponíveis nesta versão.