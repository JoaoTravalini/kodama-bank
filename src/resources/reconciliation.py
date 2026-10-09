from uuid import UUID

from fastapi import Request, status
from fastapi.responses import JSONResponse

from controllers.reconciliation_controller import ReconciliationController


class ReconciliationResource:
    def on_get(
        self,
        request: Request,
        account_key: UUID,
    ) -> JSONResponse:
        result = ReconciliationController().get(account_key)
        return JSONResponse(
            content=result,
            status_code=status.HTTP_200_OK,
        )