import logging
import time

from database import SessionLocal
from models.transaction import Transaction
from workers.transfer_processor import TransferProcessor


LOGGER = logging.getLogger(__name__)
BATCH_SIZE = 50


def pending_batch(after_id: int):
    with SessionLocal() as session:
        return (
            session.query(Transaction.id, Transaction.transaction_key)
            .filter(
                Transaction.kind == "TRANSFER",
                Transaction.status == "PENDING",
                Transaction.id > after_id,
            )
            .order_by(Transaction.id)
            .limit(BATCH_SIZE)
            .all()
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cursor = 0
    retry_after = {}
    attempts = {}

    while True:
        try:
            batch = pending_batch(cursor)

            if not batch:
                cursor = 0
                time.sleep(1)
                continue

            for transaction_id, transaction_key in batch:
                cursor = transaction_id

                if time.monotonic() < retry_after.get(transaction_key, 0):
                    continue

                try:
                    with SessionLocal() as session:
                        status = TransferProcessor(session).process(
                            transaction_key
                        )

                    retry_after.pop(transaction_key, None)
                    attempts.pop(transaction_key, None)
                    LOGGER.info(
                        "Transfer %s: %s", transaction_key, status
                    )

                except Exception:
                    count = attempts.get(transaction_key, 0) + 1
                    attempts[transaction_key] = count
                    delay = min(60, 2 ** min(count, 6))
                    retry_after[transaction_key] = time.monotonic() + delay

                    LOGGER.exception(
                        "Transfer %s failed; retry in %s seconds",
                        transaction_key,
                        delay,
                    )

        except Exception:
            LOGGER.exception("Could not fetch pending transfers")
            time.sleep(5)


if __name__ == "__main__":
    main()