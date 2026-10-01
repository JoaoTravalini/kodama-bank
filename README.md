# Kodama Bank

API bancária desenvolvida para o desafio do bootcamp QI Tech. O projeto está em desenvolvimento.

## Tecnologias

Python 3.11, FastAPI, PostgreSQL, SQLAlchemy, Docker Compose, PyJWT e pytest.

## Executar

Na raiz do repositório, crie o arquivo local de configuração:

```bash
cp .env.example .env
```

Defina um valor aleatório para `JWT_SECRET` no `.env`. Você pode gerar um valor com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

O `.env` contém configurações locais e não deve ser enviado ao GitHub.

Suba a API e o PostgreSQL:

```bash
docker compose up -d --build
docker compose ps
```

A API fica disponível em `http://localhost:3000`. Para conferir se está ativa:

```bash
curl -i http://localhost:3000/health_check
```

A resposta esperada é `204 No Content`.

O Docker executa `database/database.sql` somente ao inicializar um banco novo. Alterar esse arquivo não modifica automaticamente um banco já criado.

## Cadastro de clientes

`POST /clients` cadastra um cliente e cria duas contas: `personal` e `professional`, ambas com saldo inicial zero.

Exemplo no Git Bash:

```bash
curl -i -X POST http://localhost:3000/clients \
  -H "Content-Type: application/json" \
  -d '{"name":"Maria Silva","email":"maria@example.com","document_number":"529.982.247-25","password":"SenhaDeTeste123!"}'
```

Uma resposta `201 Created` contém o `client_key` e o `account_key` de cada conta. IDs internos e senha não são retornados.

| Caso | Status | Código |
|---|---:|---|
| Cadastro criado | 201 | — |
| JSON fora do contrato | 400 | `QIT000001` |
| CPF inválido | 422 | `KOD001001` |
| CPF já cadastrado | 409 | `KOD001002` |
| E-mail já cadastrado | 409 | `KOD001003` |

O CPF pode ser enviado com ou sem pontuação e é armazenado com 11 dígitos. O e-mail é normalizado para minúsculas. A senha é armazenada como hash com salt aleatório.

## Autenticação

`POST /auth/login` recebe o e-mail e a senha cadastrados:

```bash
curl -i -X POST http://localhost:3000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"maria@example.com","password":"SenhaDeTeste123!"}'
```

A resposta contém `access_token`, `token_type` e `expires_in`. O token é um JWT válido por 15 minutos. E-mail inexistente e senha incorreta recebem a mesma resposta `401`.

As rotas do cliente autenticado exigem o cabeçalho:

```text
Authorization: Bearer <access_token>
```

`GET /clients/me` retorna os dados do cliente identificado pelo token, incluindo as chaves e os tipos de suas contas. Token ausente, inválido ou expirado retorna `401` com o código `KOD002002`.

`JWT_SECRET` é uma configuração local e não deve ser versionada. Envie o token no cabeçalho `Authorization`, nunca na URL.

## Consulta de contas

`GET /accounts` lista as contas do cliente autenticado e seus saldos:

```bash
curl -i http://localhost:3000/accounts \
  -H "Authorization: Bearer SEU_ACCESS_TOKEN"
```

Exemplo de resposta:

```json
{
  "accounts": [
    {
      "account_key": "11111111-1111-4111-8111-111111111111",
      "type": "personal",
      "balance": "0.00"
    },
    {
      "account_key": "22222222-2222-4222-8222-222222222222",
      "type": "professional",
      "balance": "0.00"
    }
  ]
}
```

`GET /accounts/{account_key}` consulta uma conta específica:

```bash
curl -i http://localhost:3000/accounts/11111111-1111-4111-8111-111111111111 \
  -H "Authorization: Bearer SEU_ACCESS_TOKEN"
```

O saldo é devolvido como **string decimal**, com duas casas, para preservar a representação monetária. A API consulta somente contas pertencentes ao cliente identificado pelo JWT.

| Caso | Status | Código |
|---|---:|---|
| Consulta realizada | 200 | — |
| Token ausente ou inválido | 401 | `KOD002002` |
| Conta inexistente ou pertencente a outro cliente | 404 | `KOD003001` |
| `account_key` fora do formato UUID | 400 | `QIT000010` |

Uma conta de outro cliente recebe a mesma resposta de uma conta inexistente; a API não revela sua existência.

## Organização

- `database/`: criação das tabelas no PostgreSQL.
- `src/schemas/`: formatos aceitos nas requisições com corpo JSON.
- `src/resources/`: entrada HTTP e montagem das respostas.
- `src/controllers/`: autenticação e regras de negócio.
- `src/repositories/`: consultas e gravações no banco.
- `src/models/`: representação das tabelas em Python.
- `src/errors/`: erros padronizados.
- `src/middlewares/`: processamento comum às requisições.
- `src/utils/`: funções auxiliares, incluindo hash de senha e JWT.
- `tests/`: testes de integração da API.

## Testes

Com os containers ativos e o ambiente virtual Python 3.11 ativado, execute no Git Bash:

```bash
source .venv/Scripts/activate
SERVER_LOCALHOST=127.0.0.1 python -m pytest -v tests/integration
```

Os testes enviam requisições HTTP para a API em execução. Eles verificam cadastro, autenticação, consulta das próprias contas, bloqueio de acesso a contas de outros clientes e comportamento dos erros. Os testes criam clientes fictícios no banco local.