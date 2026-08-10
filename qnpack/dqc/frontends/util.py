"""
frontends/util.py
---------------
Shared constants and qubit-mapping utilities for frontend implementations.

Layout constants (``COMM_REGION_SIZE``, ``DATA_REGION_START``, …) are used
by both frontends.  The qubit-mapping helpers are split by source format:

Tket-specific (pytket Circuit / dist_commands.txt)
    ``get_server_id_from_qubit``  — extract server ID from a pytket Qubit
    ``is_link_register``          — test whether a pytket Qubit is a comm qubit
    ``map_qubit_to_local``        — pytket Qubit → local QPU memory index
    ``_parse_qubit_str``          — parse ``server_0[1]`` string form
    ``_map_qubit_str_to_local``   — string form → local QPU memory index
    ``_num_comm_qubits_for_qpu``  — comm-qubit count from qpu_info (both shapes)

QASM3-specific (QASM 3.0 files)
    ``_parse_qasm3_qubit_name``   — parse ``_qubit{QPU}_{idx}`` / ``_comm_qubit{QPU}_{N}``
"""

# ── Memory layout constants ──────────────────────────────────────────────────
COMM_REGION_SIZE = 20
DATA_REGION_START = 20
DATA_REGION_SIZE = 20


# ── Shared qubit-mapping utilities ───────────────────────────────────────────

import re
import logging

log = logging.getLogger(__name__)


def _num_comm_qubits_for_qpu(qpu_id, qpu_info):
    """Return the number of communication qubits for a QPU given qpu_info."""
    if not qpu_info:
        return 1

    # cisco shape: {label: {"qpu_id": int, "qubits": [{"type": ...}, ...]}}
    for _label, info in qpu_info.items():
        if not isinstance(info, dict):
            continue
        if "qpu_id" in info and info["qpu_id"] == qpu_id:
            return sum(1 for q in info["qubits"] if q["type"] == "communication")

    # tket shape: {qpu_id: {"num_qubits": int}}  — no comm/data split in qpu_info,
    # so fall back to the hardware constant (comm region is always COMM_REGION_SIZE).
    if qpu_id in qpu_info and isinstance(qpu_info[qpu_id], dict):
        return COMM_REGION_SIZE

    return 1


def _parse_qubit_str(qubit_str):
    """Parse ``server_0[1]`` or ``server_2_link_register[0]``.

    Returns (reg_name, server_id, qubit_idx, is_link).
    """
    qubit_str = qubit_str.strip().rstrip(";")
    match = re.match(r"(server_(\d+)(?:_link_register)?)\[(\d+)\]", qubit_str)
    if not match:
        raise ValueError(f"Cannot parse qubit string: {qubit_str!r}")
    reg_name = match.group(1)
    server_id = int(match.group(2))
    qubit_idx = int(match.group(3))
    is_link = "link_register" in reg_name
    return reg_name, server_id, qubit_idx, is_link


def _map_qubit_str_to_local(qubit_str, qpu_info=None):
    """Map a qubit string to a local QPU memory index."""
    _, server_id, idx, is_link = _parse_qubit_str(qubit_str)
    if is_link:
        return idx
    qpu_id = server_id + 1
    num_comm = _num_comm_qubits_for_qpu(qpu_id, qpu_info)
    return num_comm + idx


def get_server_id_from_qubit(qubit):
    """Extract server ID from a pytket qubit register name."""
    reg_name = qubit.reg_name
    match = re.search(r"server_(\d+)", reg_name)
    if match:
        return int(match.group(1))
    raise ValueError(f"Unknown register name: {reg_name}")


def is_link_register(qubit):
    """Return True if qubit is a link (communication) register qubit."""
    return "link_register" in qubit.reg_name


def map_qubit_to_local(qubit, qpu_info=None, server_id=None):
    """Map a pytket qubit object to a local QPU memory index."""
    reg_name = qubit.reg_name
    idx = qubit.index[0]

    if server_id is None:
        server_id = get_server_id_from_qubit(qubit)

    qpu_id = server_id + 1
    num_comm = _num_comm_qubits_for_qpu(qpu_id, qpu_info)

    if "link_register" in reg_name:
        if idx >= COMM_REGION_SIZE:
            raise ValueError(
                f"QPU {qpu_id}: comm qubit {idx} exceeds "
                f"hardware capacity {COMM_REGION_SIZE}"
            )
        return idx
    else:
        if idx >= DATA_REGION_SIZE:
            raise ValueError(
                f"QPU {qpu_id}: data qubit {idx} exceeds "
                f"hardware capacity {DATA_REGION_SIZE}"
            )
        return DATA_REGION_START + idx


def _parse_qasm3_qubit_name(name):
    """Parse a QASM 3.0 qubit name into (qpu_id, local_index, is_comm, original)."""
    orig = name.strip()
    base = re.sub(r"\[\d+\]$", "", orig)

    m = re.match(r"_comm_qubit(\d+)_(\d+)$", base)
    if m:
        qpu_id = int(m.group(1))
        comm_n = int(m.group(2))
        local_index = comm_n - 1
        return qpu_id, local_index, True, orig

    m = re.match(r"_qubit(\d+)_(\d+)$", base)
    if m:
        qpu_id = int(m.group(1))
        data_idx = int(m.group(2))
        local_index = DATA_REGION_START + (data_idx - 1)
        return qpu_id, local_index, False, orig

    raise ValueError(f"Cannot parse QASM 3.0 qubit name: {name!r}")
