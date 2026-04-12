"""Base class for all MCP services — provides /health and /metrics."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from aiohttp import web

from src.shared.metrics import generate_metrics_output

logger = logging.getLogger(__name__)


class MCPServiceBase(ABC):
    """Base class for all 7 MCP services.

    Provides:
    - GET /health  → JSON {service, status}
    - GET /metrics → Prometheus text format

    Subclasses must implement setup_routes() to add service-specific routes.

    Args:
        service_name: Human-readable service identifier.
        port: Port to listen on.
    """

    def __init__(self, service_name: str, port: int) -> None:
        self.service_name = service_name
        self.port = port
        self.app = web.Application()
        self.app.router.add_get("/health", self.health_handler)
        self.app.router.add_get("/metrics", self.metrics_handler)

    async def health_handler(self, _request: web.Request) -> web.Response:
        """Return service health status."""
        return web.json_response({
            "service": self.service_name,
            "status": "ok",
        })

    async def metrics_handler(self, _request: web.Request) -> web.Response:
        """Return Prometheus metrics in text format."""
        return web.Response(
            text=generate_metrics_output(),
            content_type="text/plain",
        )

    @abstractmethod
    async def setup_routes(self) -> None:
        """Register service-specific routes on self.app."""

    def run(self) -> None:
        """Start the aiohttp server. Blocks until stopped."""
        async def _start() -> None:
            await self.setup_routes()
            runner = web.AppRunner(self.app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", self.port)  # nosec B104
            await site.start()
            logger.info("service_started service=%s port=%d",
                        self.service_name, self.port)
            await asyncio.Event().wait()

        asyncio.run(_start())
