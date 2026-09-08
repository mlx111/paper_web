"""YAML workflow schema parser — WorkflowDef / StepDef dataclasses and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass
class WorkflowConfig:
    model: str | None = None
    max_tool_rounds: int = 3
    model_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepDef:
    type: str                         # "task" | "for_each" | "if" | "set_variable" | control steps
    name: str = ""
    instruction: str = ""
    enabled_tools: list[str] = field(default_factory=list)
    disabled_tools: list[str] = field(default_factory=list)
    save_as: str = ""
    model_kwargs: dict[str, Any] = field(default_factory=dict)
    # for_each
    in_ref: str = ""                  # template ref to list
    item_var: str = "item"
    steps: list[StepDef] = field(default_factory=list)
    # if
    condition: str = ""
    then_steps: list[StepDef] = field(default_factory=list)
    else_steps: list[StepDef] = field(default_factory=list)
    # set_variable
    variables: dict[str, str] = field(default_factory=dict)
    # AgentSPEX-style control steps
    target: str = ""
    amount: int | float = 1
    max_iterations: int = 100
    branches: list[StepDef] = field(default_factory=list)
    workflow: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowDef:
    name: str
    description: str = ""
    config: WorkflowConfig = field(default_factory=WorkflowConfig)
    parameters: dict[str, Any] = field(default_factory=dict)
    steps: list[StepDef] = field(default_factory=list)


# ---------------------------------------------------------------------------
# template helpers
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


def extract_template_vars(text: str) -> list[str]:
    """Extract all {{variable}} names from a template string."""
    return _TEMPLATE_RE.findall(text)


# ---------------------------------------------------------------------------
# loader
# ---------------------------------------------------------------------------

class WorkflowLoader:
    """Load and validate YAML workflow definitions."""

    def __init__(self, workflows_dir: str | Path = ""):
        if not workflows_dir:
            workflows_dir = Path(__file__).resolve().parent.parent / "workflows"
        self.workflows_dir = Path(workflows_dir)

    def load(self, name: str) -> WorkflowDef:
        path = self.workflows_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Workflow not found: {path}")

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Workflow YAML must be a mapping, got {type(raw)}")

        return self._parse(raw)

    def _parse(self, raw: dict[str, Any]) -> WorkflowDef:
        name = raw.get("name")
        if not name:
            raise ValueError("Workflow must have a 'name' field")

        config_raw = raw.get("config", {}) or {}
        config = WorkflowConfig(
            model=config_raw.get("model"),
            max_tool_rounds=int(config_raw.get("max_tool_rounds", 3)),
            model_kwargs=dict(config_raw.get("model_kwargs", {}) or {}),
        )

        steps = self._parse_steps(raw.get("workflow", []) or [])

        return WorkflowDef(
            name=str(name),
            description=str(raw.get("description", "")),
            config=config,
            parameters=dict(raw.get("parameters", {}) or {}),
            steps=steps,
        )

    def _parse_steps(self, raw_steps: list[dict[str, Any]]) -> list[StepDef]:
        steps: list[StepDef] = []
        for raw in raw_steps:
            step = self._parse_step(raw)
            if step:
                steps.append(step)
        return steps

    def _parse_step(self, raw: dict[str, Any]) -> StepDef | None:
        if not isinstance(raw, dict):
            return None

        # task
        if "task" in raw:
            t = raw["task"]
            return StepDef(
                type="task",
                name=str(t.get("name", "")),
                instruction=str(t.get("instruction", "")),
                enabled_tools=self._as_str_list(t.get("enabled_tools")),
                disabled_tools=self._as_str_list(t.get("disabled_tools")),
                save_as=str(t.get("save_as", "")),
                model_kwargs=dict(t.get("model_kwargs", {}) or {}),
            )

        # for_each
        if "for_each" in raw:
            fe = raw["for_each"]
            return StepDef(
                type="for_each",
                name=str(fe.get("name", "")),
                in_ref=str(fe.get("in", "")),
                item_var=str(fe.get("item_var", "item")),
                steps=self._parse_steps(fe.get("steps", []) or []),
            )

        # if
        if "if" in raw:
            if_raw = raw["if"]
            return StepDef(
                type="if",
                name=str(if_raw.get("name", "")),
                condition=str(if_raw.get("condition", "")),
                then_steps=self._parse_steps(if_raw.get("then", []) or []),
                else_steps=self._parse_steps(if_raw.get("else", []) or []),
            )

        # set_variable
        if "set_variable" in raw:
            sv = raw["set_variable"]
            if isinstance(sv, dict):
                return StepDef(
                    type="set_variable",
                variables={str(k): str(v) for k, v in sv.items()},
                )

        # increment
        if "increment" in raw:
            inc = raw["increment"]
            if isinstance(inc, dict):
                return StepDef(
                    type="increment",
                    name=str(inc.get("name", "")),
                    target=str(inc.get("var") or inc.get("target") or ""),
                    amount=inc.get("by", inc.get("amount", 1)),
                )

        # while
        if "while" in raw:
            wh = raw["while"]
            return StepDef(
                type="while",
                name=str(wh.get("name", "")),
                condition=str(wh.get("condition", "")),
                max_iterations=int(wh.get("max_iterations", 100)),
                steps=self._parse_steps(wh.get("steps", []) or []),
            )

        # goto
        if "goto" in raw:
            gt = raw["goto"]
            target = gt.get("target", "") if isinstance(gt, dict) else gt
            return StepDef(
                type="goto",
                name=str(gt.get("name", "")) if isinstance(gt, dict) else "",
                target=str(target),
            )

        # parallel
        if "parallel" in raw:
            par = raw["parallel"]
            branches: list[StepDef] = []
            for branch in par.get("branches", []) or []:
                if not isinstance(branch, dict):
                    continue
                branches.append(StepDef(
                    type="branch",
                    name=str(branch.get("name", "")),
                    steps=self._parse_steps(branch.get("steps", []) or []),
                ))
            return StepDef(
                type="parallel",
                name=str(par.get("name", "")),
                save_as=str(par.get("save_as", par.get("name", ""))),
                branches=branches,
            )

        # call / submodule
        for key in ("call", "submodule"):
            if key in raw:
                call = raw[key]
                return StepDef(
                    type=key,
                    name=str(call.get("name", "")),
                    workflow=str(call.get("workflow", "")),
                    params=dict(call.get("params", {}) or {}),
                    save_as=str(call.get("save_as", "")),
                )

        raise ValueError(f"Unknown step type in: {list(raw.keys())}")

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value]
        return []
