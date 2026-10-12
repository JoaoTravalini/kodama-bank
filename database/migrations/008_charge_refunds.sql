BEGIN;

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS refund_of_transaction_id INTEGER
    REFERENCES transactions(id);

ALTER TABLE service_charges
    ADD COLUMN IF NOT EXISTS refunded_transaction_id INTEGER
    UNIQUE REFERENCES transactions(id),
    ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMP;

ALTER TABLE transactions
    DROP CONSTRAINT IF EXISTS transactions_kind_check;

ALTER TABLE transactions
    ADD CONSTRAINT transactions_kind_check
    CHECK (kind IN ('DEPOSIT', 'TRANSFER', 'REFUND'));

ALTER TABLE transactions
    DROP CONSTRAINT IF EXISTS transactions_kind_fields_check;

ALTER TABLE transactions
    ADD CONSTRAINT transactions_kind_fields_check CHECK (
        (
            kind = 'DEPOSIT'
            AND source_account_id IS NULL
            AND external_reference IS NOT NULL
            AND idempotency_key IS NULL
            AND fee = 0
            AND refund_of_transaction_id IS NULL
        )
        OR
        (
            kind = 'TRANSFER'
            AND source_account_id IS NOT NULL
            AND source_account_id <> destination_account_id
            AND external_reference IS NULL
            AND idempotency_key IS NOT NULL
            AND refund_of_transaction_id IS NULL
        )
        OR
        (
            kind = 'REFUND'
            AND source_account_id IS NOT NULL
            AND source_account_id <> destination_account_id
            AND external_reference IS NULL
            AND idempotency_key IS NOT NULL
            AND fee = 0
            AND service_charge_id IS NOT NULL
            AND refund_of_transaction_id IS NOT NULL
            AND refund_of_transaction_id <> id
        )
    );

-- Mesmo com tentativas diferentes, um pagamento pode ter
-- somente um estorno concluído.
CREATE UNIQUE INDEX IF NOT EXISTS transactions_completed_refund_unique
    ON transactions (refund_of_transaction_id)
    WHERE kind = 'REFUND' AND status = 'COMPLETED';

ALTER TABLE service_charges
    DROP CONSTRAINT IF EXISTS service_charges_status_check;

ALTER TABLE service_charges
    ADD CONSTRAINT service_charges_status_check
    CHECK (status IN ('OPEN', 'PAID', 'CANCELED', 'REFUNDED'));

ALTER TABLE service_charges
    DROP CONSTRAINT IF EXISTS service_charges_payment_state_check;

ALTER TABLE service_charges
    ADD CONSTRAINT service_charges_payment_state_check CHECK (
        (
            status = 'OPEN'
            AND paid_transaction_id IS NULL
            AND paid_at IS NULL
            AND canceled_at IS NULL
            AND refunded_transaction_id IS NULL
            AND refunded_at IS NULL
        )
        OR
        (
            status = 'PAID'
            AND paid_transaction_id IS NOT NULL
            AND paid_at IS NOT NULL
            AND canceled_at IS NULL
            AND refunded_transaction_id IS NULL
            AND refunded_at IS NULL
        )
        OR
        (
            status = 'CANCELED'
            AND paid_transaction_id IS NULL
            AND paid_at IS NULL
            AND canceled_at IS NOT NULL
            AND refunded_transaction_id IS NULL
            AND refunded_at IS NULL
        )
        OR
        (
            status = 'REFUNDED'
            AND paid_transaction_id IS NOT NULL
            AND paid_at IS NOT NULL
            AND canceled_at IS NULL
            AND refunded_transaction_id IS NOT NULL
            AND refunded_at IS NOT NULL
            AND refunded_transaction_id <> paid_transaction_id
        )
    );

COMMIT;