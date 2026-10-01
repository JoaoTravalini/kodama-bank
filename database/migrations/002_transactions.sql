CREATE TABLE transactions (
    id SERIAL PRIMARY KEY,
    transaction_key UUID NOT NULL UNIQUE,
    kind VARCHAR(20) NOT NULL
        CHECK (kind IN ('DEPOSIT', 'TRANSFER')),
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('PENDING', 'COMPLETED', 'REJECTED')),
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    fee NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (fee >= 0),
    source_account_id INTEGER REFERENCES accounts(id),
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id),
    idempotency_key UUID,
    external_reference VARCHAR(100) UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,

    CONSTRAINT transactions_kind_fields_check CHECK (
        (
            kind = 'DEPOSIT'
            AND source_account_id IS NULL
            AND external_reference IS NOT NULL
            AND idempotency_key IS NULL
            AND fee = 0
        )
        OR
        (
            kind = 'TRANSFER'
            AND source_account_id IS NOT NULL
            AND source_account_id <> destination_account_id
            AND external_reference IS NULL
            AND idempotency_key IS NOT NULL
        )
    ),

    CONSTRAINT transactions_completion_check CHECK (
        (status = 'COMPLETED' AND completed_at IS NOT NULL)
        OR
        (status IN ('PENDING', 'REJECTED') AND completed_at IS NULL)
    ),

    CONSTRAINT transactions_source_idempotency_unique
        UNIQUE (source_account_id, idempotency_key)
);

CREATE TABLE account_entries (
    id SERIAL PRIMARY KEY,
    entry_key UUID NOT NULL UNIQUE,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    kind VARCHAR(20) NOT NULL
        CHECK (kind IN ('CREDIT', 'DEBIT', 'FEE')),
    amount NUMERIC(18, 2) NOT NULL,
    balance_after NUMERIC(18, 2) NOT NULL CHECK (balance_after >= 0),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT account_entries_amount_check CHECK (
        (kind = 'CREDIT' AND amount > 0)
        OR
        (kind IN ('DEBIT', 'FEE') AND amount < 0)
    ),

    CONSTRAINT account_entries_operation_unique
        UNIQUE (transaction_id, account_id, kind)
);

CREATE INDEX account_entries_account_history_idx
    ON account_entries (account_id, id DESC);