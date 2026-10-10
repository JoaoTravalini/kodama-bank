# Imagem oficial e publica do PostgreSQL.
FROM postgres:16

# Todo arquivo .sql colocado aqui roda sozinho quando o banco nasce.
# E assim que as tabelas do projeto sao criadas.
COPY database.sql /docker-entrypoint-initdb.d/01.sql
COPY migrations/002_transactions.sql /docker-entrypoint-initdb.d/02.sql
COPY migrations/003_transfer_rejection_reason.sql /docker-entrypoint-initdb.d/03.sql
COPY migrations/004_service_charges.sql /docker-entrypoint-initdb.d/04.sql
COPY migrations/005_charge_due_date.sql /docker-entrypoint-initdb.d/05.sql
COPY migrations/006_charge_payments.sql /docker-entrypoint-initdb.d/06.sql
COPY migrations/007_charge_cancellation.sql /docker-entrypoint-initdb.d/07.sql