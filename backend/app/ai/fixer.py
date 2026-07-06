"""The AI fix loop: an LLM decides, deterministic code applies, a boot verifies.

The model is a *decider*, never a file-writer (roadmap non-goal). Each turn it
must choose exactly one discrete action through a strict tool — guaranteed
parseable — and every mutation runs through the same reversible machinery the
UI uses (:mod:`app.resolve.mixins`), so the whole loop is undoable via the
returned manifest. After each mutating action the set is re-booted and diffed
against the baseline run; the loop ends on ``fixed``, on ``stop``, or at the
iteration / token caps.

BYO key: the Anthropic API key is the user's own (Settings or
``EMENDATOR_ANTHROPIC_API_KEY``); nothing is bundled. Long-running: every
iteration includes a real Docker boot.
"""

import json
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types import ToolParam

from app.models import AiFixIteration, AiFixResult
from app.profile import VersionProfile
from app.resolve.mixins import apply_mixin_fixes, plan_mixin_fixes, verify_mixin_fixes
from app.runner.artifacts import read_run_verdict

_SYSTEM = """\
You fix Minecraft modpack mixin conflicts through Emendator's reversible fix
ladder. You are given the pack's planned fixes (per conflict: the loser mod
and the cheapest viable rung — the mod's own mixin toggle, a filter-mod
config, or disabling the jar) plus the failing boot's evidence.

Every turn, call choose_action exactly once:
- apply_fixes: execute the planned fixes (optionally overriding losers or
  restricting to specific conflict targets). The pack is then re-booted and
  the result is reported back to you.
- rollback_mod: swap one jar for the previous Modrinth release (use when the
  evidence says the current build introduced the conflict).
- disable_mod: sideline one jar (last resort).
- stop: nothing left worth trying, or the problem is out of scope.

Prefer the least destructive action that plausibly removes the crash
signature. Everything you do is recorded in a revert manifest, but each
attempt costs a real server boot — be decisive, not exploratory.\
"""

_TOOL: ToolParam = {
    "name": "choose_action",
    "description": (
        "Choose the single next action. Use empty strings/arrays for fields "
        "that don't apply to the chosen action."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "reasoning", "losers", "targets", "jar"],
        "properties": {
            "action": {
                "type": "string",
                "enum": ["apply_fixes", "rollback_mod", "disable_mod", "stop"],
            },
            "reasoning": {
                "type": "string",
                "description": "One or two sentences: why this action, what it trades away.",
            },
            "losers": {
                "type": "array",
                "description": "apply_fixes only: override the planner's loser per conflict.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["target", "mod"],
                    "properties": {
                        "target": {"type": "string"},
                        "mod": {"type": "string"},
                    },
                },
            },
            "targets": {
                "type": "array",
                "description": "apply_fixes only: restrict to these conflict target classes.",
                "items": {"type": "string"},
            },
            "jar": {
                "type": "string",
                "description": "rollback_mod / disable_mod only: the jar filename.",
            },
        },
    },
}


def run_ai_fix(
    root: Path,
    profile: VersionProfile,
    *,
    api_key: str,
    model: str,
    max_iterations: int,
    token_cap: int,
    baseline_run_id: str | None,
) -> AiFixResult:
    """Drive the decide → apply → verify loop until fixed, stopped, or capped."""
    client = anthropic.Anthropic(api_key=api_key)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _gather_evidence(root, profile, baseline_run_id)}
    ]

    iterations: list[AiFixIteration] = []
    input_tokens = output_tokens = 0
    manifest: str | None = None

    for _step in range(max(1, max_iterations)):
        try:
            response = _create_message(client, model=model, messages=messages)
        except anthropic.AuthenticationError:
            return _result(
                "error",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                "Anthropic rejected the API key — check it in Settings.",
            )
        except anthropic.RateLimitError:
            return _result(
                "error",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                "Anthropic rate limit hit — try again in a moment.",
            )
        except anthropic.APIStatusError as exc:
            return _result(
                "error",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                f"Anthropic API error {exc.status_code}: {exc.message}",
            )
        except anthropic.APIConnectionError:
            return _result(
                "error",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                "Could not reach the Anthropic API — check your connection.",
            )

        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use is None:
            # Text-only turn: the model considers itself done explaining.
            text = next((b.text for b in response.content if b.type == "text"), "")
            return _result(
                "stopped",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                text or "The model ended without choosing an action.",
            )

        action = dict(tool_use.input) if isinstance(tool_use.input, dict) else {}
        kind = str(action.get("action") or "stop")
        reasoning = str(action.get("reasoning") or "")

        if kind == "stop":
            iterations.append(AiFixIteration(action="stop", reasoning=reasoning, outcome="—"))
            return _result(
                "stopped",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                reasoning or "The model chose to stop.",
            )

        outcome, new_manifest = _execute(root, profile, kind, action)
        manifest = new_manifest or manifest

        verify = verify_mixin_fixes(root, profile, baseline_run_id)
        outcome["verify"] = {
            "bootStatus": verify.verdict.status,
            "fixed": verify.fixed,
            "cause": verify.verdict.cause.summary if verify.verdict.cause else None,
            "exportsRemoved": verify.exports_removed[:20],
        }
        iterations.append(
            AiFixIteration(
                action=kind,
                reasoning=reasoning,
                outcome=f"boot {verify.verdict.status}"
                + (", signature gone" if verify.fixed else ""),
            )
        )
        if verify.fixed:
            return _result(
                "fixed",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                "The baseline crash signature is gone.",
            )

        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(outcome),
                    }
                ],
            }
        )

        if input_tokens + output_tokens > token_cap:
            return _result(
                "not_fixed",
                iterations,
                manifest,
                input_tokens,
                output_tokens,
                "Token cap reached before the crash signature was gone.",
            )

    return _result(
        "not_fixed",
        iterations,
        manifest,
        input_tokens,
        output_tokens,
        "Iteration cap reached before the crash signature was gone.",
    )


def _create_message(client: "anthropic.Anthropic", *, model: str, messages: list) -> Any:
    """The single API seam (monkeypatched in tests)."""
    return client.messages.create(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "auto"},
        messages=messages,
    )


def _gather_evidence(root: Path, profile: VersionProfile, baseline_run_id: str | None) -> str:
    """The context the model decides from: plan + baseline boot evidence."""
    plan = plan_mixin_fixes(root, profile)
    parts: list[str] = [
        f"Minecraft {profile.profile}, loader {plan.loader}.",
        "Planned fixes (per actionable mixin conflict):",
        json.dumps(plan.model_dump(by_alias=True), indent=1)[:12000],
    ]
    baseline = read_run_verdict(baseline_run_id) if baseline_run_id else None
    if baseline is not None:
        parts.append("Baseline failing boot:")
        parts.append(
            json.dumps(
                {
                    "status": baseline.status,
                    "cause": baseline.cause.model_dump(by_alias=True) if baseline.cause else None,
                    "logTail": baseline.log_tail,
                },
                indent=1,
            )[:8000]
        )
    else:
        parts.append("No baseline run available — the first verify boot sets the bar.")
    return "\n\n".join(parts)


def _execute(
    root: Path, profile: VersionProfile, kind: str, action: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Run one decided action through the deterministic machinery."""
    from app.enrich.install import disable_mod, rollback_mod
    from app.runner.runner import detect_loader
    from app.sources.instance import detect_instance, mods_jars

    if kind == "apply_fixes":
        losers = {
            str(pair["target"]): str(pair["mod"])
            for pair in action.get("losers") or []
            if isinstance(pair, dict) and pair.get("target") and pair.get("mod")
        }
        targets = [str(t) for t in action.get("targets") or [] if t] or None
        result = apply_mixin_fixes(root, profile, losers=losers or None, targets=targets)
        return result.model_dump(by_alias=True), result.manifest

    jars = mods_jars(detect_instance(root))
    mods_dir = jars[0].parent if jars else root
    jar = str(action.get("jar") or "")
    if kind == "rollback_mod":
        outcome = rollback_mod(mods_dir, jar, detect_loader(mods_dir), profile.profile)
        return outcome.model_dump(by_alias=True), None
    if kind == "disable_mod":
        outcome = disable_mod(mods_dir, jar)
        return outcome.model_dump(by_alias=True), None
    return {"error": f"unknown action: {kind}"}, None


def _result(
    status: str,
    iterations: list[AiFixIteration],
    manifest: str | None,
    input_tokens: int,
    output_tokens: int,
    message: str,
) -> AiFixResult:
    return AiFixResult(
        status=status,  # type: ignore[arg-type]
        iterations=iterations,
        manifest=manifest,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        message=message,
    )
