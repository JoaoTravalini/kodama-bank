ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS service_charge_id INTEGER
    REFERENCES service_charges(id);

CREATE INDEX IF NOT EXISTS transactions_service_charge_idx
    ON transactions (service_charge_id)
    WHERE service_charge_id IS NOT NULL;