"""Data shapes for tasks and plans.

A step moves through explicit states so the app never confuses "the agent
wants to do X" with "X was done and checked":
  proposed → approved/denied → attempted → verified/failed
Batch 1 only produces *proposed* steps; execution arrives in later batches.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from claw.permissions.policy import Decision, RiskLevel


class Capability(StrEnum):
    """What a step needs, and therefore which tools the model is shown for it.

    These are a context budget as much as a description. The whole catalogue is
    ~8.9k tokens against the built-in engine's 8192-token window, so a step that
    only needs the calendar must not drag in spreadsheets and OCR.
    """

    BROWSER = "browser"
    DESKTOP = "desktop"
    FILES = "files"
    DOCUMENTS = "documents"     # PDFs, Word, images: reading rather than filing
    ORGANISER = "organiser"     # calendar, reminders, what Claw remembers
    REASONING = "reasoning"


class StepState(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    DENIED = "denied"
    ATTEMPTED = "attempted"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    PLANNED = "planned"
    FAILED = "failed"


class ModelPlanStep(BaseModel):
    """One step exactly as the model must return it (validated before use)."""

    model_config = ConfigDict(extra="ignore")

    description: str = Field(min_length=3, max_length=400)
    capability: Capability
    risk: RiskLevel
    expected_result: str = Field(min_length=3, max_length=400)


class ModelPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # A short name for the conversation (2-6 words), written by the model from the request.
    title: str = Field(default="", max_length=120)
    goal: str = Field(min_length=3, max_length=500)
    steps: list[ModelPlanStep] = Field(min_length=1, max_length=15)
    questions: list[str] = Field(default_factory=list, max_length=5)


class PlanStep(ModelPlanStep):
    index: int
    state: StepState = StepState.PROPOSED
    permission: Decision


class Plan(BaseModel):
    title: str = ""
    goal: str
    steps: list[PlanStep]
    questions: list[str]
    executable: bool = False  # True once execution tools exist (Batch 2+)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=3, max_length=4000)
    # Continue an existing chat (a retry or a follow-up) instead of starting a new one.
    thread_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
