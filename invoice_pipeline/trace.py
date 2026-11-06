from __future__ import annotations

import time
from typing import List, Optional
from invoice_pipeline.models import TraceEntry


class TraceRecorder:
    """Records timing, status, inputs, outputs, and warnings for each pipeline stage."""

    def __init__(self) -> None:
        self.entries: List[TraceEntry] = []
        self._active_stage: Optional[str] = None
        self._stage_start_ns: Optional[int] = None
        self._stage_inputs: Optional[str] = None

    def start_stage(self, stage: str, inputs_summary: Optional[str] = None) -> None:
        self._active_stage = stage
        self._stage_inputs = inputs_summary
        self._stage_start_ns = time.perf_counter_ns()

    def end_stage(
        self,
        stage: str,
        status: str = "ok",
        summary: str = "",
        outputs_summary: Optional[str] = None,
        warnings: Optional[List[str]] = None,
    ) -> TraceEntry:
        duration_ms = 0
        if self._stage_start_ns is not None:
            duration_ms = int((time.perf_counter_ns() - self._stage_start_ns) / 1_000_000)
            self._stage_start_ns = None
            self._active_stage = None

        entry = TraceEntry(
            stage=stage,
            status=status,
            duration_ms=max(0, duration_ms),
            inputs_summary=self._stage_inputs,
            outputs_summary=outputs_summary,
            summary=summary,
            warnings=warnings or [],
        )
        self._stage_inputs = None
        self.entries.append(entry)
        return entry

    def record(
        self,
        stage: str,
        status: str = "ok",
        duration_ms: int = 0,
        inputs_summary: Optional[str] = None,
        outputs_summary: Optional[str] = None,
        summary: str = "",
        warnings: Optional[List[str]] = None,
    ) -> TraceEntry:
        entry = TraceEntry(
            stage=stage,
            status=status,
            duration_ms=max(0, duration_ms),
            inputs_summary=inputs_summary,
            outputs_summary=outputs_summary,
            summary=summary,
            warnings=warnings or [],
        )
        self.entries.append(entry)
        return entry

    def to_list(self) -> List[TraceEntry]:
        return list(self.entries)
