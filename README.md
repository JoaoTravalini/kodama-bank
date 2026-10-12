# Kodama Bank

API bancária demonstrativa para profissionais autônomos, desenvolvida para o desafio do Bootcamp QI Tech 2026.

O sistema separa contas pessoal e profissional e permite acompanhar serviços a receber, receber pagamentos, movimentar saldos, cancelar cobranças abertas e devolver pagamentos concluídos. Extratos, comprovantes e conciliação interna permitem consultar e verificar o histórico financeiro.

Os depósitos e pagamentos são simulados. O projeto não realiza Pix, não emite boletos e não movimenta dinheiro real.

## Tecnologias

- Python 3.11 e FastAPI.
- PostgreSQL 16 e SQLAlchemy.
- PyJWT para autenticação.
- Docker Compose para executar API, banco e worker.
- pytest para testes de unidade, integração e ponta a ponta.

## Funcionalidades

- Cadastro com validação de CPF, unicidade de CPF/e-mail e criação automática das contas pessoal e profissional.
- Armazenamento de senhas como hash com salt aleatório.
- Login com JWT e consulta ao perfil autenticado.
- Consulta de contas, saldos e extratos restrita ao proprietário.
- Depósitos internos simulados, protegidos contra crédito duplicado.
- Transferências com idempotência e processamento assíncrono.
- Registro de créditos, débitos e tarifas no extrato.
- Cobranças por serviços prestados na conta profissional.
- Vencimento opcional, identificação de atraso e resumo de recebíveis.
- Pagamento de cobrança por outro cliente Kodama.
- Quitação de cobrança por depósito interno simulado.
- Cancelamento de cobranças abertas, preservando o histórico.
- Estorno integral de cobranças pagas por transferência entre clientes.
- Comprovantes de pagamento e de estorno em JSON.
- Conciliação interna de saldos, lançamentos, pagamentos e estornos.
- Retomada de operações pendentes após indisponibilidade do worker.

## Arquitetura

A aplicação possui três serviços:

| Serviço | Responsabilidade |
| --- | --- |
| `api` | Recebe requisições, autentica clientes, aplica regras e registra solicitações |
| `db` | Persiste clientes, contas, transações, lançamentos e cobranças |
| `worker` | Busca transferências e estornos pendentes e executa a movimentação financeira |

Os pendentes ficam no PostgreSQL. Não há um broker de mensagens externo.

A API registra transferências e estornos como `PENDING`. O worker consulta esses registros e confirma ou rejeita cada operação.

Durante o processamento, o worker bloqueia a transação, as contas em ordem crescente de ID e, quando aplicável, a cobrança. As regras financeiras são verificadas sob esses bloqueios.

Saldos, lançamentos e estados são confirmados na mesma transação de banco. Uma falha técnica anterior ao commit provoca rollback e mantém a operação pendente para nova tentativa.

## Regras financeiras

### Valores e tarifas

Os valores recebidos pela API usam strings decimais com duas casas, como `"100.00"`. O código utiliza `Decimal`, e o banco utiliza `NUMERIC(18,2)`.

- Transferências entre contas do mesmo cliente são gratuitas.
- Entre clientes diferentes, a tarifa é de 0,5% do valor, arredondada para centavos com `ROUND_HALF_UP` e limitada a R$ 2,00.
- A origem precisa ter saldo para valor mais tarifa.
- O destino recebe o valor integral.
- A tarifa só é debitada quando a operação é concluída.
- Uma tarifa de valor zero não gera lançamento `FEE`.
- Operações rejeitadas não alteram saldos nem geram lançamentos.
- O saldo máximo considerado pelo processamento é `9999999999999999.99`.

### Idempotência

| Operação | Proteção contra repetição |
| --- | --- |
| Depósito | `external_reference` única |
| Transferência comum | Conta de origem e `idempotency_key` |
| Pagamento de cobrança | Conta de origem e `idempotency_key` |
| Estorno | Conta de origem e `idempotency_key` |
| Cancelamento | Estado da cobrança e preservação da data original |

Transferências, pagamentos de cobrança e estornos compartilham o espaço de chaves da mesma conta de origem. Uma chave usada em uma dessas operações não pode identificar outra operação diferente nessa conta.

O consumidor da API gera uma UUID para cada intenção de operação e reutiliza essa chave ao repetir o mesmo pedido. A API recebe a chave e aplica a proteção contra duplicação.

Repetir uma operação com a mesma chave e os mesmos dados recupera seu resultado existente. Reutilizar a chave com outros dados gera conflito.

Uma operação rejeitada continua rejeitada quando sua chave é repetida. Para uma nova tentativa, use outra chave.

Criar uma cobrança não usa chave de idempotência: cada chamada válida cria uma nova cobrança. No cadastro, CPF e e-mail únicos impedem duplicatas.

### Estados

| Registro | Estados |
| --- | --- |
| Transação | `PENDING`, `COMPLETED`, `REJECTED` |
| Cobrança | `OPEN`, `PAID`, `CANCELED`, `REFUNDED` |

Uma cobrança começa como `OPEN`, sem movimentar dinheiro. O pagamento concluído a torna `PAID`; o cancelamento de uma cobrança aberta a torna `CANCELED`; a devolução concluída a torna `REFUNDED`.

O atraso não é um estado separado no banco. Uma cobrança `OPEN` com vencimento anterior à data atual em São Paulo recebe `overdue: true`. Vencimento no dia atual ainda não é atraso.

## Executar localmente

É necessário ter Docker com Docker Compose. Python 3.11 é necessário para executar os testes na máquina local.

Na raiz do repositório:

```bash
docker compose up -d --build --wait
docker compose ps
```

O Compose inicia API, PostgreSQL e worker. API e banco devem aparecer como `healthy`; o worker deve estar em execução.

A API utiliza `http://127.0.0.1:3000`.

```bash
curl -i http://127.0.0.1:3000/health_check
```

Resposta esperada: `204 No Content`.

### Configuração

O `.env` é opcional para a demonstração local. O Compose fornece valores padrão para iniciar o projeto.

Para usar configurações próprias, crie um `.env` na raiz:

```dotenv
JWT_SECRET=SUBSTITUA_POR_UM_SEGREDO_ALEATORIO_LONGO
INTERNAL_TOKEN=SUBSTITUA_POR_UM_TOKEN_LOCAL
```

Uma chave pode ser gerada com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Não versione o `.env`. Os valores padrão são destinados à demonstração local.

Se uma porta estiver ocupada, configure `API_PORT` ou `DB_PORT` no `.env`, por exemplo:

```dotenv
API_PORT=3001
DB_PORT=5433
```

Nesse caso, ajuste a porta nos comandos HTTP. Os testes carregam as configurações locais pelo `.env`.

### Banco e migrações

Em uma instalação nova, o Docker inicializa o banco com `database/database.sql` e as migrações copiadas pelo `database/Dockerfile`.

| Migração | Alteração |
| --- | --- |
| `002_transactions.sql` | Transações e lançamentos financeiros |
| `003_transfer_rejection_reason.sql` | Motivos de rejeição |
| `004_service_charges.sql` | Cobranças por serviços |
| `005_charge_due_date.sql` | Vencimento das cobranças |
| `006_charge_payments.sql` | Vínculo entre transferências e cobranças |
| `007_charge_cancellation.sql` | Cancelamento de cobranças |
| `008_charge_refunds.sql` | Estornos e estado `REFUNDED` |

Os scripts de inicialização são executados somente quando um banco novo é criado. Reconstruir a imagem não reaplica migrações a uma base existente.

Em uma base existente, aplique apenas as migrações ainda não executadas, na ordem. Por exemplo, para uma base que já possui as anteriores e ainda não recebeu a migração de estornos:

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U bootcamp -d bootcamp < database/migrations/008_charge_refunds.sql
```

Não reaplique indiscriminadamente todos os scripts a uma base já atualizada.

## Autenticação e acesso

As rotas do cliente exigem:

```http
Authorization: Bearer SEU_JWT
```

O JWT é obtido pelo login. Contas e cobranças de outro cliente recebem `404`, assim como registros inexistentes.

Depósitos simulados e conciliação exigem:

```http
INTERNAL-TOKEN: SEU_TOKEN_INTERNO
```

JWT não autoriza essas operações internas. O token interno também não substitui o JWT nas rotas do cliente.

## Rotas

| Método | Caminho | Autorização | Função |
| --- | --- | --- | --- |
| `GET` | `/` | Nenhuma | Identificação do serviço |
| `GET` | `/health_check` | Nenhuma | Verificação de resposta da API |
| `POST` | `/clients` | Nenhuma | Cadastro e criação das duas contas |
| `POST` | `/auth/login` | Nenhuma | Emissão de JWT |
| `GET` | `/clients/me` | JWT | Perfil autenticado |
| `GET` | `/accounts` | JWT | Contas do cliente |
| `GET` | `/accounts/{account_key}` | JWT | Conta e saldo |
| `GET` | `/accounts/{account_key}/entries` | JWT | Extrato paginado |
| `POST` | `/accounts/{account_key}/deposits` | Token interno | Depósito simulado |
| `POST` | `/accounts/{source_account_key}/transfers` | JWT | Solicitação de transferência |
| `GET` | `/accounts/{source_account_key}/transfers/{transaction_key}` | JWT | Resultado da transferência |
| `POST` | `/accounts/{account_key}/charges` | JWT | Criação de cobrança |
| `GET` | `/accounts/{account_key}/charges` | JWT | Listagem de cobranças |
| `GET` | `/accounts/{account_key}/charges/summary` | JWT | Resumo de recebíveis |
| `GET` | `/accounts/{account_key}/charges/{charge_key}` | JWT | Consulta de cobrança |
| `GET` | `/accounts/{account_key}/charges/{charge_key}/receipt` | JWT | Comprovante do pagamento original |
| `POST` | `/accounts/{account_key}/charges/{charge_key}/cancel` | JWT | Cancelamento de cobrança aberta |
| `POST` | `/accounts/{source_account_key}/charge-payments` | JWT | Pagamento de cobrança |
| `POST` | `/accounts/{account_key}/charges/{charge_key}/refunds` | JWT | Solicitação de estorno |
| `GET` | `/accounts/{account_key}/charges/{charge_key}/refunds/{transaction_key}` | JWT | Resultado do estorno |
| `GET` | `/accounts/{account_key}/charges/{charge_key}/refunds/{transaction_key}/receipt` | JWT | Comprovante do estorno |
| `GET` | `/internal/accounts/{account_key}/reconciliation` | Token interno | Conciliação interna |

## Exemplos de requisição

Os exemplos abaixo usam a notação HTTP. Substitua os identificadores e tokens pelos valores retornados pela aplicação.

### Cadastro e login

```http
POST /clients
Content-Type: application/json

{
  "name": "Maria Silva",
  "email": "maria@example.com",
  "document_number": "52998224725",
  "password": "SenhaDeTeste123"
}
```

O CPF de exemplo é destinado a testes. CPF e e-mail devem ser diferentes em novos cadastros.

```http
POST /auth/login
Content-Type: application/json

{
  "email": "maria@example.com",
  "password": "SenhaDeTeste123"
}
```

Use o `access_token` retornado nas rotas do cliente.

### Depósito simulado

```http
POST /accounts/ACCOUNT_KEY/deposits
INTERNAL-TOKEN: SEU_TOKEN_INTERNO
Content-Type: application/json

{
  "amount": "100.50",
  "external_reference": "deposito-demo-001"
}
```

Repetir conta, valor e referência recupera o depósito sem novo crédito. Usar a referência com outros dados retorna `409`.

Referências iniciadas por `charge:` são reservadas para quitação de cobranças.

### Transferência comum

```http
POST /accounts/SOURCE_ACCOUNT_KEY/transfers
Authorization: Bearer SEU_JWT
Content-Type: application/json

{
  "destination_account_key": "DESTINATION_ACCOUNT_KEY",
  "amount": "40.00",
  "idempotency_key": "2b137445-6846-4381-b3ab-59042970f4f0"
}
```

A resposta `202` informa uma operação `PENDING`, sem movimentação imediata. Consulte o resultado:

```http
GET /accounts/SOURCE_ACCOUNT_KEY/transfers/TRANSACTION_KEY
Authorization: Bearer SEU_JWT
```

O resultado pode ser `COMPLETED` ou `REJECTED`. Uma rejeição informa `rejection_reason`, como `INSUFFICIENT_FUNDS` ou `DESTINATION_LIMIT_EXCEEDED`.

Repetições legítimas de operações finalizadas recebem `200` com o resultado existente.

### Criação de cobrança

Somente a conta profissional pode criar cobranças:

```http
POST /accounts/PROFESSIONAL_ACCOUNT_KEY/charges
Authorization: Bearer JWT_DO_PROFISSIONAL
Content-Type: application/json

{
  "description": "Criação de site",
  "amount": "100.00",
  "due_date": "2026-10-15"
}
```

A cobrança começa como `OPEN` e não altera o saldo. A resposta contém `charge_key` e `payment_reference`, no formato `charge:UUID`.

`due_date` é opcional e deve ser uma data válida no formato `AAAA-MM-DD`. Datas anteriores são aceitas para registrar serviços já vencidos.

### Pagamento de cobrança por outro cliente

O pagador informa uma conta própria, a chave da cobrança e uma chave nova de idempotência:

```http
POST /accounts/PAYER_ACCOUNT_KEY/charge-payments
Authorization: Bearer JWT_DO_PAGADOR
Content-Type: application/json

{
  "charge_key": "CHARGE_KEY",
  "idempotency_key": "fc59c4fb-2062-4cba-ae86-c02574eec14d"
}
```

Valor e destino são obtidos da cobrança; o pagador não pode escolhê-los no corpo.

O pagamento é registrado como transferência `PENDING`. Consulte o resultado pela rota de transferências da conta do pagador.

Ao concluir, o worker confirma juntos:

- Débito do valor e da tarifa na origem.
- Crédito integral na conta profissional.
- Lançamentos no extrato.
- Transação `COMPLETED`.
- Cobrança `PAID` e identificação do pagamento.

O titular não pode pagar a própria cobrança. Tentativas concorrentes não podem quitá-la duas vezes.

Uma rejeição por falta de saldo mantém a cobrança aberta. Uma nova tentativa exige outra chave de idempotência.

### Quitação por depósito interno

Uma operação interna pode simular um recebimento externo:

```http
POST /accounts/PROFESSIONAL_ACCOUNT_KEY/deposits
INTERNAL-TOKEN: SEU_TOKEN_INTERNO
Content-Type: application/json

{
  "amount": "100.00",
  "external_reference": "charge:CHARGE_KEY"
}
```

Conta, valor e referência precisam corresponder à cobrança aberta. O crédito e a quitação são confirmados juntos.

Se esse depósito quitar a cobrança antes de uma transferência pendente, o worker rejeita a transferência sem debitar o pagador.

Esse fluxo não consulta nem comprova liquidação por uma instituição externa.

### Cancelamento de cobrança

```http
POST /accounts/PROFESSIONAL_ACCOUNT_KEY/charges/CHARGE_KEY/cancel
Authorization: Bearer JWT_DO_PROFISSIONAL
```

Somente cobranças `OPEN` podem ser canceladas. A resposta `200` informa `CANCELED` e `canceled_at`.

Repetir o cancelamento mantém a data original. Cobranças `PAID` ou `REFUNDED` retornam `409`.

Se o cancelamento vencer a disputa com um pagamento pendente, o worker rejeita esse pagamento com `CHARGE_CANCELED`, sem movimentação financeira.

Cancelar não devolve dinheiro e não apaga registros.

### Estorno de pagamento

O profissional pode solicitar a devolução integral de uma cobrança paga por transferência de outro cliente Kodama:

```http
POST /accounts/PROFESSIONAL_ACCOUNT_KEY/charges/CHARGE_KEY/refunds
Authorization: Bearer JWT_DO_PROFISSIONAL
Content-Type: application/json

{
  "idempotency_key": "acec1fb7-3568-4db0-94e0-6e136b8072af"
}
```

O corpo aceita somente `idempotency_key`. Valor, pagamento original e destino são obtidos dos registros existentes.

A resposta `202` informa uma transação `REFUND` no estado `PENDING`. Consulte:

```http
GET /accounts/PROFESSIONAL_ACCOUNT_KEY/charges/CHARGE_KEY/refunds/TRANSACTION_KEY
Authorization: Bearer JWT_DO_PROFISSIONAL
```

Regras do estorno:

- É integral e limitado a uma devolução concluída por pagamento original.
- Devolve o valor à conta que originalmente pagou a cobrança.
- Não cobra nova tarifa.
- Não devolve a tarifa do pagamento original.
- Exige saldo suficiente na conta profissional e respeita o limite da conta de destino.
- Preserva a transação original, seus lançamentos e seu comprovante.
- Cria uma nova transação e novos lançamentos de débito e crédito.
- A cobrança permanece `PAID` enquanto o estorno estiver pendente ou rejeitado.
- Somente a conclusão a torna `REFUNDED`, com identificação e data do estorno.
- Estornos concorrentes não podem devolver o valor duas vezes.

Uma rejeição não movimenta dinheiro. Após resolver sua causa, outra tentativa pode ser solicitada com uma nova chave.

Após a conclusão, repetir a chave original recupera o estorno; uma chave nova recebe `409`. A repetição de uma tentativa anteriormente rejeitada continua recuperando aquela rejeição.

Cobranças quitadas por depósito interno não são elegíveis: esse fluxo não identifica uma conta pagadora Kodama para receber a devolução. Estornos parciais também não fazem parte desta versão.

Exemplo: um pagamento de R$ 100,00 exige R$ 100,50 do pagador. Após a quitação, o profissional recebe R$ 100,00. Se o estorno concluir, R$ 100,00 voltam ao pagador; a tarifa original de R$ 0,50 permanece registrada.

### Comprovantes

Comprovante do pagamento original:

```http
GET /accounts/PROFESSIONAL_ACCOUNT_KEY/charges/CHARGE_KEY/receipt
Authorization: Bearer JWT_DO_PROFISSIONAL
```

O JSON identifica cobrança, transação e lançamento de crédito, além de valor recebido, saldo após o crédito, data e método de pagamento.

Esse comprovante permanece disponível após um estorno e continua descrevendo o pagamento original. Ele não expõe a conta do pagador.

Comprovante do estorno:

```http
GET /accounts/PROFESSIONAL_ACCOUNT_KEY/charges/CHARGE_KEY/refunds/TRANSACTION_KEY/receipt
Authorization: Bearer JWT_DO_PROFISSIONAL
```

O JSON identifica:

- Cobrança e transação de estorno.
- Transação original.
- Contas de origem e destino da devolução.
- Valor devolvido e tarifa original mantida.
- Lançamentos de débito e crédito.
- Saldos após esses lançamentos e data da conclusão.

O comprovante de estorno só está disponível quando a devolução foi concluída. Operações pendentes ou rejeitadas recebem `409`; inconsistências nos registros impedem sua emissão.

Os comprovantes exigem o JWT do titular da conta profissional e utilizam `Cache-Control: no-store`. Descrevem operações simuladas dentro do Kodama.

### Extrato

```http
GET /accounts/ACCOUNT_KEY/entries?page=1&limit=20
Authorization: Bearer SEU_JWT
```

| Parâmetro | Valores | Padrão |
| --- | --- | --- |
| `page` | Inteiro de 1 a 999999 | `1` |
| `limit` | Inteiro de 1 a 100 | `20` |
| `kind` | `CREDIT`, `DEBIT` ou `FEE` | Todos |

Os lançamentos incluem `entry_key`, `transaction_key`, `transaction_kind`, `kind`, `amount`, `balance_after` e `created_at`.

`transaction_kind` distingue depósitos, transferências e estornos: `DEPOSIT`, `TRANSFER` ou `REFUND`. Ele é um campo da resposta, não um filtro de consulta.

Créditos são positivos; débitos e tarifas são negativos. `balance_after` representa o saldo após aquele lançamento, não necessariamente o saldo atual.

Operações pendentes ou rejeitadas não aparecem no extrato porque não geram lançamentos.

### Cobranças e resumo de recebíveis

```http
GET /accounts/PROFESSIONAL_ACCOUNT_KEY/charges?page=1&limit=20
Authorization: Bearer JWT_DO_PROFISSIONAL
```

A listagem utiliza os mesmos limites de paginação do extrato e informa `has_more`.

Para consultar os totais:

```http
GET /accounts/PROFESSIONAL_ACCOUNT_KEY/charges/summary
Authorization: Bearer JWT_DO_PROFISSIONAL
```

Exemplo:

```json
{
  "account_key": "UUID_DA_CONTA_PROFISSIONAL",
  "as_of_date": "2026-10-12",
  "open": {"count": 3, "amount": "190.00"},
  "overdue": {"count": 1, "amount": "50.00"},
  "paid": {"count": 2, "amount": "150.00"},
  "refunded": {"count": 1, "amount": "100.00"}
}
```

- `open`: cobranças atualmente abertas.
- `overdue`: subconjunto das abertas com vencimento anterior à data de referência.
- `paid`: cobranças atualmente pagas, sem estorno concluído.
- `refunded`: cobranças cujo pagamento foi devolvido.
- `as_of_date`: data em São Paulo usada para avaliar os vencimentos.

Não some `open` com `overdue`, pois os atrasados já estão incluídos nos abertos.

Os totais abrangem todas as cobranças da conta, independentemente da paginação. Cobranças canceladas não participam desses grupos.

`paid` e `refunded` representam valores de cobranças, não o saldo disponível da conta.

### Conciliação interna

```http
GET /internal/accounts/ACCOUNT_KEY/reconciliation
INTERNAL-TOKEN: SEU_TOKEN_INTERNO
```

Exemplo após uma cobrança de R$ 100,00 ser paga e estornada, sem outras movimentações na conta profissional:

```json
{
  "account_key": "UUID_DA_CONTA",
  "balance": "0.00",
  "ledger_balance": "0.00",
  "paid_charges_checked": 1,
  "refunded_charges_checked": 1,
  "consistent": true,
  "issues": []
}
```

A conciliação verifica:

- Saldo armazenado contra a soma dos lançamentos da conta.
- Pagamentos originais de cobranças `PAID` e `REFUNDED`.
- Transação e crédito associados ao pagamento.
- Ligação entre estorno, cobrança e pagamento original.
- Direção, valor, tarifa zero e data do estorno concluído.
- Existência dos dois lançamentos esperados para a devolução.

Os estornos são conferidos tanto na consulta da conta profissional quanto na da conta pagadora envolvida.

`paid_charges_checked` inclui pagamentos originais preservados após estorno. `refunded_charges_checked` informa as cobranças estornadas verificadas para a conta.

Possíveis divergências:

- `BALANCE_MISMATCH`
- `CHARGE_TRANSACTION_MISMATCH`
- `CHARGE_CREDIT_MISMATCH`
- `CHARGE_REFUND_TRANSACTION_MISMATCH`
- `CHARGE_REFUND_ENTRIES_MISMATCH`

A consulta utiliza isolamento `REPEATABLE READ` e uma transação somente de leitura. Isso evita comparar registros de momentos diferentes enquanto outra operação é confirmada.

Divergências retornam `200` com `consistent: false` e detalhes em `issues`. A conciliação não modifica registros, não corrige valores automaticamente e não consulta instituições externas.

## Erros

Os erros seguem um formato comum:

```json
{
  "title": "Refund receipt unavailable",
  "description": "A receipt is available only after the refund is completed.",
  "translation": "O comprovante fica disponível somente após a conclusão do estorno.",
  "code": "KOD008004"
}
```

Os códigos distinguem situações de negócio dentro do mesmo status HTTP.

Respostas frequentes:

| Status | Situação |
| --- | --- |
| `400` | Corpo, parâmetro, data ou UUID inválido |
| `401` | JWT ausente, inválido ou expirado; credenciais incorretas |
| `403` | Token interno ausente ou incorreto |
| `404` | Registro inexistente ou inacessível ao cliente |
| `409` | Conflito de idempotência ou estado incompatível |
| `422` | Regra de negócio inválida, como CPF inválido ou valor zero |
| `500` | Falha técnica ou inconsistência que impede a operação |

Saldo insuficiente durante o processamento assíncrono gera uma transação `REJECTED`; sua consulta retorna `200` com o resultado e o motivo.

## Logs

A API registra entrada e saída das requisições, método, rota, status, duração e identificador da requisição. O corpo da requisição não é registrado pelo middleware de logs.

O identificador é devolvido no cabeçalho `x-request-id`.

O worker registra identificadores das operações processadas, resultados e falhas técnicas. Após uma falha técnica, utiliza espera progressiva entre tentativas, limitada a 60 segundos.

Para consultar:

```bash
docker compose logs --tail=100 api worker
```

## Testes

Na validação local desta versão:

- 103 testes de integração e unidade aprovados.
- 6 testes de ponta a ponta aprovados.

### Preparar o ambiente

No Git Bash do Windows, usando Python 3.11:

```bash
py -3.11 -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
```

Se o ambiente já existe, basta ativá-lo.

Em Linux/macOS, crie o ambiente com `python3.11 -m venv .venv` e ative com `source .venv/bin/activate`.

### Executar a suíte

Integração e unidade precisam do worker parado: alguns testes observam `PENDING` e chamam o processador de forma controlada.

```bash
docker compose up -d --build --wait db api
docker compose stop worker

PYTHONPATH=src SERVER_LOCALHOST=127.0.0.1 python -m pytest -q tests/integration tests/unit
```

Para os testes de ponta a ponta, ligue o worker:

```bash
docker compose up -d --build --wait worker

PYTHONPATH=src SERVER_LOCALHOST=127.0.0.1 python -m pytest -q tests/e2e
```

Os E2E exercitam a API e o worker real. Os testes de recuperação param e reiniciam o serviço `worker`; execute a suíte sem outras operações concorrentes que dependam desse serviço.

### Cobertura de cenários

Os testes verificam:

- Cadastro, duplicidades, validação de CPF e autenticação.
- JWT inválido, adulterado ou expirado e isolamento entre clientes.
- Depósitos repetidos e conflitos de referência.
- Tarifas, falta de saldo e limite da conta de destino.
- Extrato, paginação, vencimentos e resumo de recebíveis.
- Pagamento e cancelamento de cobranças.
- Concorrência entre pagamentos e entre estornos.
- Solicitações HTTP simultâneas com a mesma chave de idempotência.
- Conflitos de chave entre transferências, pagamentos e estornos.
- Rejeição de pedidos que tentam alterar valor ou destino da devolução.
- Rollback após falha técnica e nova tentativa.
- Preservação do pagamento original, da tarifa e dos comprovantes.
- Detecção de divergências reais introduzidas temporariamente no banco.
- Retomada de transferências e estornos pendentes após indisponibilidade do worker.
- Repetição após reinicialização sem duplicação financeira.

A CI executa integração e unidade antes de iniciar o worker e executa os E2E depois. O banco é inicializado do zero no ambiente da CI.

Não utilize `DbUtils.rollback()` para recriar o banco das funcionalidades novas: essa rotina representa o esquema inicial e pode remover tabelas acrescentadas por migrações.

## Organização do código

| Pasta | Responsabilidade |
| --- | --- |
| `src/resources` | Recebe requisições HTTP e monta respostas |
| `src/controllers` | Aplica regras de negócio e coordena operações |
| `src/repositories` | Consulta e persiste dados no PostgreSQL |
| `src/models` | Representa as tabelas no código |
| `src/schemas` | Valida corpos e parâmetros |
| `src/errors` | Define erros e respostas de negócio |
| `src/middlewares` | Cuida de contexto, logs, sessão e token interno |
| `src/utils` | Reúne funções compartilhadas de validação, autenticação e valores |
| `src/workers` | Busca e processa transferências e estornos pendentes |
| `database` | Contém o esquema inicial e as migrações SQL |
| `tests/unit` | Verifica regras isoladas |
| `tests/integration` | Verifica API, banco e processamento controlado |
| `tests/e2e` | Verifica jornadas por HTTP com o worker real |

## Escopo desta versão

O projeto implementa operações bancárias simuladas e o ciclo de cobranças para profissionais autônomos: registrar, acompanhar, receber, cancelar cobranças abertas e devolver pagamentos elegíveis, preservando o histórico.

Pix, boletos, integrações financeiras reais, documentos fiscais, estornos parciais e devoluções de depósitos externos simulados ficam fora do escopo.