"""Model adapter interface shared by every local (and future cloud) provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelInfo(BaseModel):
    name: str
    size_bytes: int | None = None
    details: dict[str, Any] = {}


class ModelStatus(BaseModel):
    server_reachable: bool
    model_available: bool
    provider: str
    base_url: str
    model: str
    message: str
    available_models: list[str] = []
    # Why it is not usable, when it is not. The interface chooses its wording from
    # this rather than guessing from two booleans, which cannot tell a refused key
    # apart from a server that never answered.
    #   ok | unreachable | auth_failed | rate_limited | model_missing | not_configured | error
    reason: str = "ok"


class ModelError(Exception):
    """Base error carrying a user-facing message and a suggested fix."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


class ModelServerUnavailable(ModelError):
    pass


class ModelNotFound(ModelError):
    pass


class ModelBadRequest(ModelError):
    """The server rejected the REQUEST (400), not the credential or the model.

    Separated from the generic error because one specific 400 is recoverable:
    asking a server not to think uses a field that only some servers know, and
    the ones that do not know it answer 400. Being able to tell that apart from
    a server that is down is what lets the adapter drop the field and ask
    again, instead of failing a reply that would have worked.
    """


class ModelAuthFailed(ModelError):
    """The provider answered and refused the credential (401/403).

    Deliberately not a ModelServerUnavailable: the server was reached. Reporting
    this as "unreachable" sends the user to check their internet when the real
    problem is the key.
    """


class ModelRateLimited(ModelError):
    """The provider answered 429. Reachable, authenticated, just too busy or over quota."""


class ModelResponseError(ModelError):
    pass


def why_a_reply_was_empty(thinking: str, cut_off: bool) -> str:
    """An empty reply, explained - because the usual cause is specific.

    Lives here rather than in one adapter because BOTH of them can hit it and
    both must say the same thing. A server that separates a thinking model's
    chain of thought returns HTTP 200 with the answer field empty and all of
    the work in a field nothing reads - `reasoning_content` on llama-server,
    `thinking` on Ollama. See the module docstring of
    claw/models/openai_compat.py for the measurements; the short version is
    that a 2B asked the chat prompt with thinking on produced ZERO characters
    of answer at 512, 1024, 1536 and 2048 tokens.

    Said plainly it is actionable - the budget was too small for this task.
    Reported as "the reply could not be used" it is a mystery, and it is
    exactly the "gets stuck thinking without producing a useful response"
    this project kept hearing about.

    `thinking` is whatever the server filed the monologue under; `cut_off` is
    whether it stopped at the length limit rather than finishing. Only ever
    reached when the reply really is empty, so nothing that would have worked
    is turned into an error.
    """
    if cut_off and thinking.strip():
        return ("The brain used its whole reply budget thinking and never got to an answer. "
                "Give it a larger budget, or a smaller task.")
    if thinking.strip():
        return ("The brain returned only its own reasoning and no answer. "
                "A model that follows instructions more closely would help.")
    if cut_off:
        return "The brain's reply was cut off at its length limit before it said anything."
    return "The model server returned an empty reply."


class ModelAdapter(ABC):
    provider: str

    #: Whether this server understands being asked not to think.
    #:
    #: Thinking models are the single worst performance and correctness problem
    #: Claw has measured. On a real llama-server with Qwen3-2B, "What is the
    #: capital of France?" through the chat prompt NEVER produced an answer:
    #: at 512, 1024, 1536 and 2048 tokens the reply finished on "length" with
    #: the entire budget spent in `reasoning_content` and `content` empty.
    #: Asking the chat template not to think answered it in 1.4 seconds.
    #:
    #: But the field that does the asking is an extension, not part of the
    #: OpenAI protocol, so a cloud provider answers 400 and names it. It is
    #: therefore DISCOVERED rather than assumed: the first rejection sets this
    #: False and the request is sent again without it, so a server that cannot
    #: be asked costs one extra round trip once, not a lost reply.
    #:
    #: SCOPE, deliberately: this is remembered on the ADAPTER, and Claw builds
    #: one adapter per task (claw/api/app.py think_adapter, used for both
    #: make_plan and run_agent). So the worst case on an engine that rejects
    #: the field is one wasted round trip per task - a 400 with no generation
    #: behind it - rather than one per call. It is not cached globally on
    #: purpose: the address and the model can both change between tasks when
    #: somebody edits Settings, and a stale "this engine cannot be asked"
    #: would silently leave thinking on, which is the whole failure this
    #: machinery exists to prevent. A cheap repeated check is the safer error.
    #:
    #: On Windows this path is reachable in normal use: scripts/setup.ps1
    #: fetches whichever llama.cpp build was newest at install time, so an
    #: older installation may not know the field. The rejection is logged
    #: (claw/models/openai_compat.py) because it PREDICTS the next failure.
    quiet_thinking_ok: bool = True

    def __init__(self, base_url: str, model: str, timeout_s: float, temperature: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.temperature = temperature

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return the models the local server can serve."""

    @abstractmethod
    async def chat(self, messages: list[ChatMessage], json_schema: dict[str, Any] | None = None,
                   *, thinking: bool = True) -> str:
        """Return the assistant's reply text. When a schema is given, request JSON output.

        `thinking=False` asks a thinking model to answer directly. It is a
        request, not a guarantee: a server that does not support it is detected
        and the reply is fetched anyway. See `quiet_thinking_ok`.
        """

    async def status(self) -> ModelStatus:
        base = dict(provider=self.provider, base_url=self.base_url, model=self.model)
        try:
            models = await self.list_models()
        except ModelAuthFailed as exc:
            return ModelStatus(
                server_reachable=True, model_available=False, reason="auth_failed",
                message=f"{exc.message} {exc.hint}".strip(), **base,
            )
        except ModelRateLimited as exc:
            return ModelStatus(
                server_reachable=True, model_available=False, reason="rate_limited",
                message=f"{exc.message} {exc.hint}".strip(), **base,
            )
        except ModelServerUnavailable as exc:
            return ModelStatus(
                server_reachable=False, model_available=False, reason="unreachable",
                message=f"{exc.message} {exc.hint}".strip(), **base,
            )
        except ModelError as exc:
            return ModelStatus(
                server_reachable=False, model_available=False, reason="error",
                message=f"{exc.message} {exc.hint}".strip(), **base,
            )
        names = [m.name for m in models]
        if not self.model:
            return ModelStatus(
                server_reachable=True,
                model_available=False,
                message="The model server is running, but no model is selected. Choose one in Settings.",
                available_models=names, reason="not_configured",
                **base,
            )
        if not _model_in(self.model, names):
            return ModelStatus(
                server_reachable=True,
                model_available=False,
                message=f"The model '{self.model}' is not installed on the server. {self.missing_model_hint()}",
                available_models=names, reason="model_missing",
                **base,
            )
        return ModelStatus(
            server_reachable=True,
            model_available=True,
            message=f"Ready: {self.model}",
            available_models=names,
            **base,
        )

    def missing_model_hint(self) -> str:
        return "Pick an installed model in Settings."

    def require_model(self) -> None:
        if not self.model:
            raise ModelNotFound("No model is selected.", "Open Settings and choose a model.")


def _model_in(name: str, available: list[str]) -> bool:
    if name in available:
        return True
    # Ollama treats "qwen2.5" and "qwen2.5:latest" as the same model.
    return f"{name}:latest" in available or name.removesuffix(":latest") in available
