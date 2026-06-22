"""Central trusted-extraction model policy — BAKER_DASHBOARD_V2_MODEL_LOCK_1.

Director ruling (hard): Gemini Flash is barred from any extraction or generation
that can feed a Director-visible *trusted* surface. A path is **trusted** if its
model output can become any of:

  - an alert (T1/T2)
  - a deadline row
  - a promise / commitment
  - a decision
  - a signal_candidate / signal_extraction
  - a verified_item
  - a Today / Matter Room / People card
  - a Director-visible proposed action or recommendation

Trusted extraction uses **Gemini Pro minimum**; trusted verification / promotion
(candidate -> verified) uses Opus-class reasoning, Cortex, or human ratification.

Cost is controlled by reducing volume, batching, or skipping extraction — never
by lowering model quality on a trusted path (Director: "do not fix cost by
lowering quality").

This module is the single source of truth for that policy. Trusted call sites
import :func:`call_trusted` (or, where they must keep their own call shape,
:func:`assert_trusted_model`) rather than re-implementing the rule ad hoc.

Non-trusted housekeeping paths (internal SQL generation, routing/branch labels,
tool-parameter JSON, sentiment/telemetry, transcription, ephemeral UI drafts that
cannot create/promote/alter an actionable object) may continue to call Flash.
"""
import logging
import os
import time

logger = logging.getLogger("baker.model_policy")

# Policy floor for trusted extraction. Overridable via Tranche-0 flag
# EXTRACTION_MIN_MODEL; default is Gemini Pro. Must never resolve to a Flash
# model — guarded at resolve time below.
_DEFAULT_TRUSTED_EXTRACTION_MODEL = "gemini-2.5-pro"


class TrustedModelPolicyError(RuntimeError):
    """Raised when a barred (Flash-class) model is used on a trusted path."""


def is_flash(model: str) -> bool:
    """True if ``model`` is a Gemini Flash-class model (any flash variant)."""
    return "flash" in (model or "").lower()


def is_allowed_for_trusted(model: str) -> bool:
    """True if ``model`` may feed a Director-visible trusted surface.

    Empty/unknown models are disallowed (fail closed). Flash is barred.
    """
    if not model:
        return False
    return not is_flash(model)


def trusted_extraction_model() -> str:
    """Resolve the trusted-extraction model floor.

    Reads ``EXTRACTION_MIN_MODEL`` each call so an ops override takes effect
    without a restart. If the override is itself a Flash model the policy
    refuses it and falls back to the safe default (logged LOUD).
    """
    model = os.getenv("EXTRACTION_MIN_MODEL", _DEFAULT_TRUSTED_EXTRACTION_MODEL).strip()
    if not model or is_flash(model):
        logger.error(
            "EXTRACTION_MIN_MODEL=%r is empty or a barred Flash model — ignoring; "
            "falling back to %s for trusted extraction.",
            model, _DEFAULT_TRUSTED_EXTRACTION_MODEL,
        )
        return _DEFAULT_TRUSTED_EXTRACTION_MODEL
    return model


def assert_trusted_model(model: str, *, context: str = "") -> None:
    """Raise :class:`TrustedModelPolicyError` if ``model`` is barred from a
    trusted path. Call this in any trusted site that builds its own request."""
    if not is_allowed_for_trusted(model):
        raise TrustedModelPolicyError(
            f"Model {model!r} is barred from trusted extraction/generation "
            f"({context or 'unspecified context'}); minimum trusted model is "
            f"{trusted_extraction_model()}."
        )


def log_model_provenance(*, model: str, trusted: bool, source_channel: str = "",
                         output_type: str = "", context: str = "") -> None:
    """AC6 — record model provenance for a trusted extraction / candidate creation.

    Minimum fields: model id, trusted/untrusted flag, source channel, output
    object type, timestamp. Emitted as a single structured log line that the
    System / model-telemetry surface can scrape.
    """
    logger.info(
        "MODEL_PROVENANCE model=%s trusted=%s source=%s output=%s context=%s ts=%.3f",
        model, trusted, source_channel or "-", output_type or "-",
        context or "-", time.time(),
    )


def call_trusted(messages: list, *, max_tokens: int = 2000, system: str = None,
                 response_format: str = None, thinking_budget: int = None,
                 source_channel: str = "", output_type: str = "",
                 context: str = ""):
    """Trusted-path model call.

    Routes to Gemini Pro (the policy floor), refuses Flash, and records model
    provenance. Use this anywhere the model output could become an alert,
    deadline, promise, decision, signal_candidate, card, or Director-visible
    proposal — i.e. anywhere the brief calls "trusted".

    Drop-in for ``call_flash(...)`` at trusted sites: same return shape
    (``GeminiResponse`` with ``.text`` and ``.usage``).
    """
    from orchestrator.gemini_client import call_pro

    model = trusted_extraction_model()
    assert_trusted_model(model, context=context)
    resp = call_pro(
        messages=messages, max_tokens=max_tokens, system=system,
        response_format=response_format, thinking_budget=thinking_budget,
    )
    log_model_provenance(
        model=model, trusted=True, source_channel=source_channel,
        output_type=output_type, context=context,
    )
    return resp
