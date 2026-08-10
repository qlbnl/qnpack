"""
validation.py
-------------
Pre-simulation validation of the per-QPU canonical IR.

Call :func:`validate_commands` on the dict returned by a frontend's
``parse()`` method **before** handing it to the ControllerProtocol.
Any issues are returned as a list of :class:`ValidationError` objects.

An empty list means the commands are well-formed with respect to the
:mod:`~qnpack.dqc.models.instruction_set` registry.

Usage
~~~~~
::

    from qnpack.dqc.models.validation import validate_commands

    qpu_commands = frontend.parse(qpu_info=qpu_info)
    errors = validate_commands(qpu_commands)
    for e in errors:
        print(e)
    if any(e.severity == "error" for e in errors):
        raise ValueError("Validation failed")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List

from .instruction_set import (
    OpCategory,
    OpSpec,
    lookup,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single validation issue found in a command.

    Attributes
    ----------
    qpu_id : int
        QPU that owns the command.
    cmd_index : int
        Index of the command in that QPU's command list.
    op_name : str
        The operation name that caused the issue.
    message : str
        Human-readable description of the problem.
    severity : str
        ``"error"`` for hard failures, ``"warning"`` for issues that
        may be intentional or benign.
    """

    qpu_id: int
    cmd_index: int
    op_name: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        tag = self.severity.upper()
        return (
            f"[{tag}] QPU_{self.qpu_id} cmd[{self.cmd_index}] "
            f"op={self.op_name!r}: {self.message}"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_commands(
    qpu_commands: Dict[int, List[dict]],
    *,
    strict: bool = True,
) -> List[ValidationError]:
    """Validate all commands in a per-QPU command dict.

    Checks performed
    ~~~~~~~~~~~~~~~~
    1. **Op name recognised** — the ``op`` field (or the ``gate`` field
       inside a ``"gate"`` wrapper) exists in :data:`INSTRUCTION_SET`.
    2. **Qubit count** — for gate-category ops with a fixed
       ``num_qubits``, the number of qubit operands must match.
    3. **Parameter count** — for parameterised gates with a fixed
       ``num_params``, the number of ``params`` must match.  Reported
       as a *warning* rather than an error because some callers omit
       optional parameters.

    Parameters
    ----------
    qpu_commands : dict[int, list[dict]]
        ``{qpu_id: [cmd, …]}`` as returned by a frontend's ``parse()``.
    strict : bool
        If ``True`` (default), unknown ops are severity ``"error"``.
        If ``False``, they are severity ``"warning"`` (useful for
        exploratory / partially-supported circuits).

    Returns
    -------
    list[ValidationError]
        Empty when all commands are valid.
    """
    errors: List[ValidationError] = []

    for qpu_id, cmds in qpu_commands.items():
        for idx, cmd in enumerate(cmds):
            _validate_one(qpu_id, idx, cmd, errors, strict=strict)

    return errors


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _resolve_op(cmd: dict) -> tuple[str, OpSpec | None]:
    """Return ``(effective_op_name, spec)`` for a command dict.

    For the QASM3Frontend ``"gate"`` wrapper, the effective name is the
    inner ``cmd["gate"]`` field.  For everything else it is ``cmd["op"]``.

    CU1 ops from the TketFrontend may arrive as ``"CU1(1)"`` — we strip
    the parameter suffix to get the bare name.
    """
    op_name: str = cmd.get("op", "")

    # QASM3Frontend gate wrapper
    if op_name.lower() == "gate":
        inner = cmd.get("gate", "")
        return inner, lookup(inner)

    # TketFrontend CU1 with embedded parameter, e.g. "CU1(1)"
    bare = re.sub(r"\([^)]*\)$", "", op_name)
    spec = lookup(bare)
    return bare, spec


def _extract_qubits(cmd: dict) -> list:
    """Return the list of qubit operands from a command dict.

    Commands may store qubits as ``"qubits"`` (list), ``"qubit"`` (int),
    or both.  We prefer ``"qubits"`` when present.
    """
    qubits = cmd.get("qubits")
    if qubits:
        return list(qubits)
    qubit = cmd.get("qubit")
    if qubit is not None:
        return [qubit]
    return []


_GATE_CATEGORIES = frozenset({
    OpCategory.GATE_1Q,
    OpCategory.GATE_2Q,
    OpCategory.GATE_3Q,
    OpCategory.GATE_MULTI_Q,
    OpCategory.INIT,
})


def _validate_one(
    qpu_id: int,
    idx: int,
    cmd: dict,
    errors: List[ValidationError],
    *,
    strict: bool,
) -> None:
    """Validate a single command and append any issues to *errors*."""

    effective_name, spec = _resolve_op(cmd)

    if spec is None:
        severity = "error" if strict else "warning"
        errors.append(ValidationError(
            qpu_id, idx, effective_name,
            f"Unknown operation {effective_name!r}",
            severity=severity,
        ))
        return

    # --- Qubit-count check (gate-category ops only) -----------------------
    if spec.category in _GATE_CATEGORIES and spec.num_qubits > 0:
        qubits = _extract_qubits(cmd)
        if len(qubits) != spec.num_qubits:
            errors.append(ValidationError(
                qpu_id, idx, effective_name,
                f"Expected {spec.num_qubits} qubit(s), got {len(qubits)}",
            ))

    # --- Parameter-count check (parameterised gates only) -----------------
    if spec.category in _GATE_CATEGORIES and spec.num_params > 0:
        params = cmd.get("params", [])
        if len(params) != spec.num_params:
            errors.append(ValidationError(
                qpu_id, idx, effective_name,
                f"Expected {spec.num_params} param(s), got {len(params)}",
                severity="warning",
            ))

    # --- Conditional gate: validate the inner gate name -------------------
    if spec.category == OpCategory.CONDITIONAL:
        inner_gate = cmd.get("gate") or cmd.get("if_gate", {}).get("gate")
        if inner_gate and lookup(inner_gate) is None:
            errors.append(ValidationError(
                qpu_id, idx, effective_name,
                f"Unknown inner gate {inner_gate!r} in if_gate",
            ))
