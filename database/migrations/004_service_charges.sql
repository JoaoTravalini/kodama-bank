CREATE TABLE service_charges (
    id SERIAL PRIMARY KEY,
    charge_key UUID NOT NULL UNIQUE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    description VARCHAR(255) NOT NULL
        CHECK (length(btrim(description)) > 0),
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'PAID')),
    paid_transaction_id INTEGER UNIQUE REFERENCES transactions(id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMP,

    CONSTRAINT service_charges_payment_state_check CHECK (
        (status = 'OPEN'
            AND paid_transaction_id IS NULL
            AND paid_at IS NULL)
        OR
        (status = 'PAID'
            AND paid_transaction_id IS NOT NULL
            AND paid_at IS NOT NULL)
    )
);

CREATE INDEX service_charges_account_history_idx
    ON service_charges (account_id, id DESC);