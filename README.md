# Kodama Bank

API bancária desenvolvida para o desafio do bootcamp QI Tech. O projeto está em desenvolvimento.

## Tecnologias

Python 3.11, FastAPI, PostgreSQL, SQLAlchemy, Docker Compose e pytest.

## Executar

Na raiz do repositório:

```bash
docker compose up --build -d
docker compose ps
```

A API fica disponível em `http://localhost:3000`. Verifique se está ativa:

```bash
curl -i http://localhost:3000/health_check
```

A resposta esperada é `204 No Content`. O Docker executa `database/database.sql` quando cria um banco novo. Se você já tiver um banco local criado antes da adição das tabelas `clients` e `accounts`, será necessário criá-las nesse banco; editar o arquivo SQL não altera uma instalação existente.

## Autenticação

`POST /auth/login` recebe `email` e `password` e devolve um JWT de acesso válido por 15 minutos (`access_token`, `token_type` e `expires_in`). Credenciais incorretas retornam `401`.

`GET /clients/me` exige `Authorization: Bearer <access_token>`. Retorna os dados do cliente identificado pelo token. Token ausente, inválido ou expirado retorna `401`.

A chave `JWT_SECRET` é configuração local e não deve ser versionada. O token deve ser enviado no cabeçalho Authorization, nunca na URL.

## Cadastro de clientes

`POST /clients` recebe:

```json
{
  "name": "Maria Silva",
  "email": "maria@example.com",
  "document_number": "529.982.247-25",
  "password": "SenhaDeTeste123!"
}
```

Exemplo no Git Bash:

```bash
curl -i -X POST http://localhost:3000/clients \
  -H "Content-Type: application/json" \
  -d '{"name":"Maria Silva","email":"maria@example.com","document_number":"529.982.247-25","password":"SenhaDeTeste123!"}'
```

O cadastro cria uma conta `personal` e uma `professional`, ambas com saldo inicial zero. A resposta `201 Created` contém `client_key` e as chaves das contas. IDs internos e senha não são retornados.

| Caso | Status | Código |
|---|---:|---|
| Cadastro criado | 201 | — |
| JSON fora do contrato | 400 | `QIT000001` |
| CPF inválido | 422 | `KOD001001` |
| CPF já cadastrado | 409 | `KOD001002` |
| E-mail já cadastrado | 409 | `KOD001003` |

O CPF pode ser enviado com ou sem pontuação e é armazenado com 11 dígitos. O e-mail é normalizado para minúsculas. A senha é armazenada como hash com salt aleatório; o login com JWT ainda será implementado.

## Organização

- `database/`: criação das tabelas no PostgreSQL.
- `src/schemas/`: formato aceito nas requisições.
- `src/resources/`: entrada e saída HTTP.
- `src/controllers/`: regras de negócio.
- `src/repositories/`: consultas e gravações no banco.
- `src/models/`: representação das tabelas em Python.
- `src/errors/`: erros padronizados.
- `src/middlewares/`: processamento comum às requisições.
- `src/utils/`: funções auxiliares.
- `tests/`: testes da API.

## Testes

Com os containers ativos, instale as dependências de desenvolvimento em um ambiente virtual Python 3.11 e execute no Git Bash:

```bash
SERVER_LOCALHOST=127.0.0.1 python -m pytest -v tests/integration
```

Os testes de cadastro enviam requisições HTTP à API e verificam os dados no PostgreSQL. Eles inserem clientes fictícios no banco local.