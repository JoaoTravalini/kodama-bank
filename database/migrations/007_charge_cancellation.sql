ALTER TABLE service_charges
    ADD COLUMN IF NOT EXISTS canceled_at TIMESTAMP;

ALTER TABLE service_charges
    DROP CONSTRAINT IF EXISTS service_charges_status_check;

ALTER TABLE service_charges
    ADD CONSTRAINT service_charges_status_check
    CHECK (status IN ('OPEN', 'PAID', 'CANCELED'));

ALTER TABLE service_charges
    DROP CONSTRAINT IF EXISTS service_charges_payment_state_check;

ALTER TABLE service_charges
    ADD CONSTRAINT service_charges_payment_state_check CHECK (
        (status = 'OPEN' AND paid_transaction_id IS NULL
            AND paid_at IS NULL AND canceled_at IS NULL)
        OR (status = 'PAID' AND paid_transaction_id IS NOT NULL
            AND paid_at IS NOT NULL AND canceled_at IS NULL)
        OR (status = 'CANCELED' AND paid_transaction_id IS NULL
            AND paid_at IS NULL AND canceled_at IS NOT NULL)
    );