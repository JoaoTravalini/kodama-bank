# Imagem oficial e publica do PostgreSQL.
FROM postgres:16

# Todo arquivo .sql colocado aqui roda sozinho quando o banco nasce.
# E assim que as tabelas do projeto sao criadas.
COPY database.sql /docker-entrypoint-initdb.d/01.sql
COPY migrations/002_transactions.sql /docker-entrypoint-initdb.d/02.sql
COPY migrations/003_transfer_rejection_reason.sql /docker-entrypoint-initdb.d/03.sql