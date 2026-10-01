CREATE TABLE clients (
    id SERIAL PRIMARY KEY,
    client_key UUID NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    document_number CHAR(11) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE accounts (
    id SERIAL PRIMARY KEY,
    account_key UUID NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    type VARCHAR(20) NOT NULL CHECK (type IN ('personal', 'professional')),
    balance NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, type)
);