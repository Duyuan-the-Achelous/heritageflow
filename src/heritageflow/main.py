from contextlib import asynccontextmanager
import logging
import re
import time
from typing import Annotated, Any
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status

from .auth import Principal, authenticate, require_roles
from .config import Settings, load_settings
from .db import Database
from .dynamo_service import DynamoReservationService
from .observability import configure_http_logger
from .schemas import (
    AttractionOut,
    ReservationCreate,
    ReservationOut,
    SlotCreate,
    SlotOut,
    TenantMetricsOut,
    ValidationCreate,
    ValidationOut,
)
from .seed import seed
from .service import CapacityError, ConflictError, NotFoundError, ReservationService


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    http_logger = configure_http_logger()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = app_settings
        if app_settings.storage_backend == "dynamodb":
            reservation_service = DynamoReservationService(
                table_name=app_settings.dynamodb_table,
                visitor_hash_key=app_settings.visitor_hash_key,
                region_name=app_settings.aws_region,
                endpoint_url=app_settings.dynamodb_endpoint_url,
            )
            if app_settings.seed_demo:
                reservation_service.seed_demo_data()
        else:
            database = Database(app_settings.database_path)
            seed(database)
            reservation_service = ReservationService(database, app_settings.visitor_hash_key)
        app.state.service = reservation_service
        yield

    application = FastAPI(
        title="HeritageFlow API",
        version="0.1.0",
        description="Multi-tenant reservation and admission-control prototype",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_observability(request, call_next):
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", supplied_id) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            http_logger.exception(
                "request failed",
                extra={"event": "http_request_exception", "request_id": request_id},
            )
            raise
        finally:
            http_logger.log(
                logging.ERROR if status_code >= 500 else logging.INFO,
                "request completed",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "tenant_id": getattr(request.state, "tenant_id", None),
                },
            )

    def service() -> Any:
        return application.state.service

    PrincipalDep = Annotated[Principal, Depends(authenticate)]
    ServiceDep = Annotated[Any, Depends(service)]

    @application.exception_handler(NotFoundError)
    async def not_found_handler(_request, exc: NotFoundError):
        return _error_response(status.HTTP_404_NOT_FOUND, str(exc))

    @application.exception_handler(CapacityError)
    async def capacity_handler(_request, exc: CapacityError):
        return _error_response(status.HTTP_409_CONFLICT, str(exc))

    @application.exception_handler(ConflictError)
    async def conflict_handler(_request, exc: ConflictError):
        return _error_response(status.HTTP_409_CONFLICT, str(exc))

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready")
    def ready(reservation_service: ServiceDep) -> dict[str, str]:
        try:
            reservation_service.ready()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="storage dependency unavailable") from exc
        return {"status": "ready"}

    @application.get("/v1/attractions", response_model=list[AttractionOut])
    def list_attractions(principal: PrincipalDep, reservation_service: ServiceDep):
        return reservation_service.list_attractions(principal.tenant_id)

    @application.get("/v1/slots", response_model=list[SlotOut])
    def list_slots(
        attraction_id: Annotated[str, Query(min_length=1)],
        principal: PrincipalDep,
        reservation_service: ServiceDep,
    ):
        return reservation_service.list_slots(principal.tenant_id, attraction_id)

    @application.post("/v1/admin/slots", response_model=SlotOut, status_code=status.HTTP_201_CREATED)
    def create_slot(body: SlotCreate, principal: PrincipalDep, reservation_service: ServiceDep):
        require_roles(principal, "platform_admin", "tenant_admin")
        if body.ends_at <= body.starts_at:
            raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
        return reservation_service.create_slot(
            principal.tenant_id,
            body.attraction_id,
            body.starts_at.isoformat(),
            body.ends_at.isoformat(),
            body.capacity,
        )

    @application.post("/v1/reservations", response_model=ReservationOut)
    def create_reservation(
        body: ReservationCreate,
        response: Response,
        principal: PrincipalDep,
        reservation_service: ServiceDep,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
    ):
        reservation, created = reservation_service.create_reservation(
            principal.tenant_id,
            body.attraction_id,
            body.slot_id,
            body.visitor_reference,
            body.quantity,
            idempotency_key,
        )
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return reservation

    @application.get("/v1/reservations/{reservation_id}", response_model=ReservationOut)
    def get_reservation(
        reservation_id: str,
        principal: PrincipalDep,
        reservation_service: ServiceDep,
    ):
        return reservation_service.get_reservation(principal.tenant_id, reservation_id)

    @application.post("/v1/reservations/{reservation_id}/cancel", response_model=ReservationOut)
    def cancel_reservation(
        reservation_id: str,
        principal: PrincipalDep,
        reservation_service: ServiceDep,
    ):
        return reservation_service.cancel_reservation(principal.tenant_id, reservation_id)

    @application.post("/v1/validations", response_model=ValidationOut)
    def validate_admission(
        body: ValidationCreate,
        principal: PrincipalDep,
        reservation_service: ServiceDep,
    ):
        require_roles(principal, "platform_admin", "tenant_admin", "validator")
        return reservation_service.validate_admission(principal.tenant_id, body.validation_code)

    @application.get("/v1/admin/metrics", response_model=TenantMetricsOut)
    def tenant_metrics(principal: PrincipalDep, reservation_service: ServiceDep):
        require_roles(principal, "platform_admin", "tenant_admin")
        return reservation_service.tenant_metrics(principal.tenant_id)

    return application


def _error_response(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


app = create_app()

