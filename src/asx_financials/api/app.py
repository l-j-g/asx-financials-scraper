from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from asx_financials.application.interfaces import IngestionUseCase, ReadUseCase
from asx_financials.application.services import (
    IngestTickerCommand,
    SystemClock,
    TickerIngestionService,
    TickerReadService,
)
from asx_financials.config import get_settings
from asx_financials.infrastructure.persistence.store import create_mongo_data_store
from asx_financials.infrastructure.providers.yfinance_provider import YFinanceProvider


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    ingestion_service: IngestionUseCase
    read_service: ReadUseCase


def create_app() -> FastAPI:
    settings = get_settings()
    store = create_mongo_data_store(settings.mongodb_uri, settings.mongodb_database)
    provider = YFinanceProvider()
    container = ServiceContainer(
        ingestion_service=TickerIngestionService(provider, store, SystemClock()),
        read_service=TickerReadService(store),
    )

    app = FastAPI(title="ASX Financials Backend", version="0.1.0")
    app.state.services = container

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ingestions/{ticker}")
    def ingest_ticker(
        ticker: str,
        include_annual: bool = True,
        include_quarterly: bool = True,
    ) -> JSONResponse:
        try:
            result = app.state.services.ingestion_service.ingest(
                IngestTickerCommand(
                    ticker=ticker,
                    include_annual=include_annual,
                    include_quarterly=include_quarterly,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return JSONResponse(content=jsonable_encoder(result))

    @app.get("/ingestions/{ticker}")
    def get_latest_ingestion(ticker: str) -> JSONResponse:
        try:
            result = app.state.services.read_service.get_latest_ingestion(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if result is None:
            raise HTTPException(status_code=404, detail="Ticker ingestion was not found.")

        return JSONResponse(content=jsonable_encoder(result))

    @app.get("/companies/{ticker}")
    def get_company(ticker: str) -> JSONResponse:
        try:
            result = app.state.services.read_service.get_company(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if result is None:
            raise HTTPException(status_code=404, detail="Company was not found.")

        return JSONResponse(content=jsonable_encoder(result))

    return app
