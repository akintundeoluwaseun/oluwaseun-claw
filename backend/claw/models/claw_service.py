"""The Claw service: the hosted brain Claw Online thinks with.

It speaks the same OpenAI-compatible protocol as a local llama-server, so the
adapter is the same one with three differences:

- its address and credential come from the build's edition profile, never from
  the user, who has no API key to type;
- the wording of its failures is about *this computer's* internet connection,
  because that is what a person can do something about;
- it says plainly when the build carries no service address at all.

What it is NOT: remote control of this computer. The service proposes an action
and reads what came back. Every action is validated against the tool schemas,
the permission policy and the approval rules on this machine before anything
happens, exactly as it is for a local brain. Nothing the service returns can
reach the desktop without passing those checks.
"""

from __future__ import annotations

from claw.edition import Edition
from claw.models.base import ModelError, ModelServerUnavailable
from claw.models.openai_compat import OpenAICompatAdapter

#: What the service calls the brain it runs. Sent as the model name; a service
#: that offers something else is told so by its own error.
DEFAULT_SERVICE_MODEL = "claw-1"


class ClawServiceUnconfigured(ModelError):
    """This build has no service address, so there is nothing to ask."""


class ClawServiceAdapter(OpenAICompatAdapter):
    provider = "claw_service"
    vision = True  # the hosted brain reads screenshots

    def missing_model_hint(self) -> str:
        return "The Claw service does not offer that brain. Update Claw."

    async def _request(self, method: str, path: str, **kw):
        try:
            return await super()._request(method, path, **kw)
        except ModelServerUnavailable as exc:
            # The same failure for a hosted brain means something different to the
            # person than it does for a server on their own machine.
            raise ModelServerUnavailable(
                "Claw could not reach the Claw service.",
                "Check this computer's internet connection and try again. "
                "Claw Online needs the internet to think; the rest of Claw still works.",
            ) from exc


def build_service_adapter(edition: Edition, timeout_s: float, temperature: float,
                          model: str = "") -> ClawServiceAdapter:
    if not edition.service_configured:
        ok, why = edition.allows_mode("service")
        raise ClawServiceUnconfigured(why or "No Claw service address was built into this copy of Claw.",
                                      "Install Claw Online from a build that names a service.")
    adapter = ClawServiceAdapter(
        base_url=edition.service_url,
        model=model.strip() or DEFAULT_SERVICE_MODEL,
        timeout_s=timeout_s,
        temperature=temperature,
    )
    adapter.api_key = edition.service_token
    return adapter
