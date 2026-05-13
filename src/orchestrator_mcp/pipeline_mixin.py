"""PipelineMixin — combines entry, steps, and finalise into one mixin class."""
from __future__ import annotations

from src.orchestrator_mcp.pipeline_entry    import PipelineEntryMixin
from src.orchestrator_mcp.pipeline_steps    import PipelineStepsMixin
from src.orchestrator_mcp.pipeline_finalise import PipelineFinaliseMixin


class PipelineMixin(PipelineEntryMixin, PipelineStepsMixin, PipelineFinaliseMixin):
    """Provides handle_build_failure + the full 6-agent auto-heal pipeline.

    Split across three focused modules:
      - pipeline_entry.py    — HTTP endpoint, sync/background runners
      - pipeline_steps.py    — agent steps, diff engine, regression guard
      - pipeline_finalise.py — report_data assembly, PR creation, result builders
    """
