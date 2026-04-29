"""WorkflowApiMixin — REST endpoints for direct workflow CRUD."""
from __future__ import annotations

from aiohttp import web

from src.shared.models import WorkflowState, WorkflowStatus
from src.orchestrator_mcp.workflow import (
    InvalidTransitionError,
    WorkflowNotFoundError,
)


def _serialise(state: WorkflowState) -> dict:
    return {
        "build_id":      state.build_id,
        "status":        state.status.value,
        "retry_count":   state.retry_count,
        "error_message": state.error_message,
        "created_at":    state.created_at.isoformat(),
        "updated_at":    state.updated_at.isoformat(),
    }


class WorkflowApiMixin:
    """Pure REST CRUD endpoints — no pipeline logic."""

    async def create_workflow(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)
        build_id = data.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)
        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        return web.json_response(_serialise(state), status=201)

    async def get_workflow(self, request: web.Request) -> web.Response:
        build_id = request.match_info["build_id"]
        try:
            state = self.engine.get(build_id)
        except WorkflowNotFoundError:
            return web.json_response({"error": "workflow not found"}, status=404)
        return web.json_response(_serialise(state))

    async def advance_workflow(self, request: web.Request) -> web.Response:
        build_id = request.match_info["build_id"]
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)
        next_status_str = data.get("next_status", "")
        try:
            next_status = WorkflowStatus(next_status_str)
        except ValueError:
            return web.json_response(
                {"error": f"unknown status '{next_status_str}'"}, status=400,
            )
        try:
            state = self.engine.advance(build_id, next_status)
        except WorkflowNotFoundError:
            return web.json_response({"error": "workflow not found"}, status=404)
        except InvalidTransitionError as exc:
            return web.json_response({"error": str(exc)}, status=422)
        return web.json_response(_serialise(state))

    async def list_active(self, _request: web.Request) -> web.Response:
        return web.json_response([_serialise(s) for s in self.engine.list_active()])

    async def get_workflow_status(self, request: web.Request) -> web.Response:
        build_id = request.query.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)
        try:
            state = self.engine.get(build_id)
        except WorkflowNotFoundError:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"build_id": build_id, "status": state.status.value})
