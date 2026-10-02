ALTER TABLE transactions
    ADD COLUMN rejection_reason VARCHAR(40);

ALTER TABLE transactions
    ADD CONSTRAINT transactions_rejection_reason_check
    CHECK (
        (status = 'REJECTED' AND rejection_reason IS NOT NULL)
        OR
        (status IN ('PENDING', 'COMPLETED') AND rejection_reason IS NULL)
    );