"""
instruction_set.py
------------------
Single source of truth for the DQC canonical instruction set.

Every operation that can appear in the per-QPU command IR is registered
here as an :class:`OpSpec`.  The registry is used by:

* **validation.py** — to reject unknown or malformed commands before
  simulation.
* **QPUProtocol** — to derive the ``_GATE_OPS`` allowlist at import
  time rather than hard-coding it.
* **Frontends** — to verify that emitted op names are valid.

Op-name lookup is always **case-insensitive**: ``lookup("H")`` and
``lookup("h")`` return the same :class:`OpSpec`.

Parameter convention
~~~~~~~~~~~~~~~~~~~~
All angle parameters in the canonical IR are in **units of pi**.
For example, ``params=[0.5]`` means ``0.5 * pi`` radians.
Both frontends (Tket and QASM3) normalise to this convention before
emitting commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, FrozenSet, Optional


# ---------------------------------------------------------------------------
# OpCategory
# ---------------------------------------------------------------------------

class OpCategory(Enum):
    """Broad categories of operations in the DQC instruction set."""

    GATE_1Q = auto()
    """Single-qubit unitary gate."""

    GATE_2Q = auto()
    """Two-qubit unitary gate."""

    GATE_3Q = auto()
    """Three-qubit unitary gate (e.g. Toffoli)."""

    GATE_MULTI_Q = auto()
    """Multi-controlled gate with variable qubit count (e.g. CnX/MCX)."""

    MEASUREMENT = auto()
    """Qubit measurement (intermediate or final)."""

    INIT = auto()
    """Qubit (re-)initialisation."""

    ENTANGLEMENT = auto()
    """Bell-pair / entanglement generation request."""

    CLASSICAL_MSG = auto()
    """Cross-QPU classical-bit exchange."""

    EJPP = auto()
    """EJPP (Entanglement-based Joint Parity Protocol) step."""

    CONDITIONAL = auto()
    """Classically-conditioned gate."""


# ---------------------------------------------------------------------------
# OpSpec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpSpec:
    """Specification for a single operation in the canonical IR.

    Parameters
    ----------
    name : str
        Canonical **lowercase** name (e.g. ``"cx"``).
    category : OpCategory
        Broad category.
    aliases : frozenset[str]
        Alternative names that map to the same spec (e.g. ``"cnot"``
        is an alias for ``"cx"``).
    num_qubits : int
        Expected number of qubit operands.  ``-1`` means *variable*
        (e.g. CnX can act on 3+ qubits).
    num_params : int
        Expected number of float parameters.  ``-1`` means *variable*.
        ``0`` means the gate is parameter-free.
    description : str
        Human-readable one-liner.
    decomposition : str or None
        If the gate is *synthetic* (implemented as a sequence of
        primitive NetSquid instructions), a short description of
        the decomposition.
    """

    name: str
    category: OpCategory
    aliases: FrozenSet[str] = frozenset()
    num_qubits: int = 1
    num_params: int = 0
    description: str = ""
    decomposition: Optional[str] = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Keyed by **lowercase** name (including aliases).
INSTRUCTION_SET: Dict[str, OpSpec] = {}


def _register(*specs: OpSpec) -> None:
    """Register one or more OpSpecs (and their aliases) in the global registry."""
    for spec in specs:
        key = spec.name.lower()
        if key in INSTRUCTION_SET:
            raise ValueError(
                f"Duplicate instruction-set registration: {key!r} "
                f"(existing: {INSTRUCTION_SET[key]!r})"
            )
        INSTRUCTION_SET[key] = spec
        for alias in spec.aliases:
            alias_key = alias.lower()
            if alias_key in INSTRUCTION_SET:
                raise ValueError(
                    f"Duplicate alias registration: {alias_key!r} "
                    f"(existing: {INSTRUCTION_SET[alias_key]!r})"
                )
            INSTRUCTION_SET[alias_key] = spec


# ── 1-qubit gates ────────────────────────────────────────────────────────────

_register(
    OpSpec("h",   OpCategory.GATE_1Q, description="Hadamard gate"),
    OpSpec("x",   OpCategory.GATE_1Q, description="Pauli-X gate"),
    OpSpec("y",   OpCategory.GATE_1Q, description="Pauli-Y gate"),
    OpSpec("z",   OpCategory.GATE_1Q, description="Pauli-Z gate"),
    OpSpec("rx",  OpCategory.GATE_1Q, num_params=1,
           description="Rotation around X axis"),
    OpSpec("ry",  OpCategory.GATE_1Q, num_params=1,
           description="Rotation around Y axis"),
    OpSpec("rz",  OpCategory.GATE_1Q, num_params=1,
           description="Rotation around Z axis"),
    OpSpec("u1",  OpCategory.GATE_1Q, num_params=1,
           description="U1 phase gate (equivalent to Rz)"),
    OpSpec("u2",  OpCategory.GATE_1Q, num_params=2,
           description="U2 gate",
           decomposition="Rz(lam) . Ry(pi/2) . Rz(phi)"),
    OpSpec("u3",  OpCategory.GATE_1Q, num_params=3,
           description="U3 gate",
           decomposition="Rz(lam) . Ry(theta) . Rz(phi)"),
    OpSpec("sx",  OpCategory.GATE_1Q,
           description="sqrt(X) gate",
           decomposition="Rx(pi/2)"),
    OpSpec("s",   OpCategory.GATE_1Q,
           description="S (phase) gate",
           decomposition="Rz(pi/2)"),
    OpSpec("sdg", OpCategory.GATE_1Q,
           description="S-dagger gate",
           decomposition="Rz(-pi/2)"),
    OpSpec("t",   OpCategory.GATE_1Q,
           description="T gate",
           decomposition="Rz(pi/4)"),
    OpSpec("tdg", OpCategory.GATE_1Q,
           description="T-dagger gate",
           decomposition="Rz(-pi/4)"),
)

# ── 2-qubit gates ────────────────────────────────────────────────────────────

_register(
    OpSpec("cx",  OpCategory.GATE_2Q, num_qubits=2,
           aliases=frozenset({"cnot"}),
           description="Controlled-NOT (CNOT) gate"),
    OpSpec("cu1", OpCategory.GATE_2Q, num_qubits=2, num_params=1,
           description="Controlled-U1 (controlled phase) gate",
           decomposition="Rz(lam/2) . CX . Rz(-lam/2) . CX . Rz(lam/2)"),
)

# ── 3-qubit gates ────────────────────────────────────────────────────────────

_register(
    OpSpec("ccx", OpCategory.GATE_3Q, num_qubits=3,
           aliases=frozenset({"toffoli"}),
           description="Toffoli (CCX) gate"),
)

# ── Multi-qubit gates ────────────────────────────────────────────────────────

_register(
    OpSpec("cnx", OpCategory.GATE_MULTI_Q, num_qubits=-1,
           aliases=frozenset({"mcx"}),
           description="Multi-controlled X gate (3+ qubits)"),
)

# ── Initialisation ───────────────────────────────────────────────────────────

_register(
    OpSpec("reset", OpCategory.INIT,
           description="Re-initialise qubit to |0>"),
)

# ── Measurement ──────────────────────────────────────────────────────────────

_register(
    OpSpec("measure",       OpCategory.MEASUREMENT,
           description="Intermediate Z-basis measurement"),
    OpSpec("measure_final", OpCategory.MEASUREMENT,
           description="Final output measurement"),
)

# ── Entanglement ─────────────────────────────────────────────────────────────

_register(
    OpSpec("entanglement_gen", OpCategory.ENTANGLEMENT,
           description="Bell-pair generation request"),
)

# ── Classical messaging ──────────────────────────────────────────────────────

_register(
    OpSpec("msg_sender",   OpCategory.CLASSICAL_MSG,
           description="Send classical bit to peer QPU"),
    OpSpec("msg_receiver", OpCategory.CLASSICAL_MSG,
           description="Receive classical bit from peer QPU"),
)

# ── EJPP ─────────────────────────────────────────────────────────────────────

_register(
    OpSpec("ejpp_start",      OpCategory.EJPP,
           description="EJPP start (data side)"),
    OpSpec("ejpp_start_link", OpCategory.EJPP,
           description="EJPP start (link side)"),
    OpSpec("ejpp_end",        OpCategory.EJPP,
           description="EJPP end (data side)"),
    OpSpec("ejpp_end_link",   OpCategory.EJPP,
           description="EJPP end (link side)"),
)

# ── Conditional ──────────────────────────────────────────────────────────────

_register(
    OpSpec("if_gate", OpCategory.CONDITIONAL,
           description="Classically-conditioned gate application"),
)

# ── QASM3 "gate" wrapper ────────────────────────────────────────────────────
# The QASM3Frontend wraps every gate in {"op": "gate", "gate": "<name>", …}.
# We register "gate" as a pseudo-op so the validator can recognise the
# wrapper and inspect the inner gate name.

_register(
    OpSpec("gate", OpCategory.GATE_1Q, num_qubits=-1, num_params=-1,
           description="QASM3Frontend gate wrapper (delegates to 'gate' field)"),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def lookup(op_name: str) -> Optional[OpSpec]:
    """Look up an operation by name (case-insensitive).

    Returns the :class:`OpSpec` if found, otherwise ``None``.
    """
    return INSTRUCTION_SET.get(op_name.lower())


def is_valid_op(op_name: str) -> bool:
    """Return ``True`` if *op_name* is a recognised operation."""
    return op_name.lower() in INSTRUCTION_SET


# ---------------------------------------------------------------------------
# Derived sets (useful for QPUProtocol)
# ---------------------------------------------------------------------------

#: Set of canonical gate op names (including aliases) that should be
#: handled by ``QPUProtocol._apply_gate_by_name()``.
GATE_OPS: FrozenSet[str] = frozenset(
    name
    for name, spec in INSTRUCTION_SET.items()
    if spec.category in (
        OpCategory.GATE_1Q,
        OpCategory.GATE_2Q,
        OpCategory.GATE_3Q,
        OpCategory.GATE_MULTI_Q,
        OpCategory.INIT,
    )
    # Exclude the "gate" pseudo-op wrapper — it is handled separately
    and spec.name != "gate"
)
