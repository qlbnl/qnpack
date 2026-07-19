"""
frontends/tket_frontend.py
--------------------------
TketFrontend: parses a pytket distributed Circuit object or uses pytket's
QASM parser for dist_commands.txt files. Converts to canonical per-QPU
command IR consumed by ControllerProtocol / QPUProtocol.

This is a **pure parser** — it emits raw command dicts with no labels
assigned and no ``entanglement_gen`` commands inserted. All labeling is
handled by the ``qnpack.dqc.labeling`` package after parsing.

Op names emitted (canonical):
    ejpp_start        — data-side EJPP start
    ejpp_start_link   — link-side EJPP start
    ejpp_end          — data-side EJPP end
    ejpp_end_link     — link-side EJPP end
"""

import json
import logging
from pytket import OpType

from .base import BaseFrontend
from .util import (
    _num_comm_qubits_for_qpu,
    _parse_qubit_str,
    _map_qubit_str_to_local,
    get_server_id_from_qubit,
    is_link_register,
    map_qubit_to_local,
)

log = logging.getLogger(__name__)


class TketFrontend(BaseFrontend):
    """Parse a pytket distributed Circuit object or dist_commands.txt file
    into canonical per-QPU commands using pytket's parser.

    Two source modes
    ----------------
    * **Circuit mode** (``needs_datacollector=True``): caller passes a pytket
      ``Circuit`` to :meth:`load`; results are harvested via a NetSquid
      DataCollector.
    * **File mode** (``needs_datacollector=False``): caller passes a
      ``dist_commands.txt`` path to :meth:`load`; results are read directly
      from QPU protocol state via :meth:`get_result_row`.
    """

    def __init__(self, num_output_bits=1, output_reg_name='m'):
        self._source = None
        self._ir = {}
        self._num_output_bits = num_output_bits
        self._output_reg_name = output_reg_name
        self._needs_datacollector = True  # updated by parse()

    # ── BaseFrontend abstract properties ────────────────────────────────────

    @property
    def needs_datacollector(self):
        """``True`` in Circuit mode; ``False`` in file mode."""
        return self._needs_datacollector

    # ── Source loading ───────────────────────────────────────────────────────

    def load(self, source):
        """Ingest a circuit source.

        * ``str`` ending in ``.json`` → JSON schedule/sidecar; top-level
          keys are cached in ``self._ir``.
        * Other ``str`` → dist_commands.txt or similar; stored as-is and
          parsed lazily by :meth:`parse`.
        * Anything else → stored as-is (pytket Circuit).

        Parameters
        ----------
        source : str | Circuit
            Path to a ``.json`` schedule, a ``dist_commands.txt``, or a
            pytket distributed Circuit.
        """
        super().load(source)
        if isinstance(source, str) and source.endswith(".json"):
            with open(source, "r") as f:
                self._ir = json.load(f)
            log.debug(f"[TketFrontend] Loaded IR from {source} "
                      f"(keys: {list(self._ir.keys())})")

    # ── Metadata helpers ─────────────────────────────────────────────────────

    def get_measure_qubits(self, extra_context=None):
        """Return the ``measure_qubits`` dict.

        Checks *extra_context* first (Circuit mode), then falls back to the
        loaded JSON schedule (file mode).

        Parameters
        ----------
        extra_context : dict | None
            May contain a ``'measure_qubits'`` key mapping
            ``qpu_id`` → ``[qubit_position, …]``.

        Returns
        -------
        dict | None
        """
        if extra_context and 'measure_qubits' in extra_context:
            return extra_context['measure_qubits']
        return self._ir.get("measure_qubits", None)

    def get_col_names(self, measure_qubits=None):
        """Return column names for the output register.

        Derives names from *measure_qubits*: ``["QPU_{qid}_q{pos}", …]``.
        The DataCollector uses these as column headers.

        Parameters
        ----------
        measure_qubits : dict | None
            Mapping of ``qpu_id`` → ``[qubit_position, …]``.
        """
        return [
            f"QPU_{qid}_q{pos}"
            for qid, positions in (measure_qubits or {}).items()
            for pos in positions
        ]

    def get_result_row(self, protocol, run_idx, col_names, qpu_nodes):
        """Return ``None`` — TketFrontend always uses the DataCollector
        path for result collection.

        Parameters
        ----------
        protocol : DQCProtocol
        run_idx : int
        col_names : list[str]
        qpu_nodes : list

        Returns
        -------
        None
        """
        return None

    # ── Parsing ──────────────────────────────────────────────────────────────

    def parse(self, qpu_info=None):
        """Parse the previously loaded source and return ``{qpu_id: [cmd, …]}``.

        Dispatches on the type of ``self._source``:

        * ``str``  → file path; delegates to :func:`_partition_commands_from_file`
        * anything else → pytket Circuit; delegates to :func:`_partition_commands`

        Both paths require a DataCollector to harvest measurement results,
        because the tket dist_commands format does not include explicit
        measurement instructions — the ``measure_qubits`` config
        determines which qubit positions are measured after the circuit
        completes.

        Parameters
        ----------
        qpu_info : dict | None
            Topology info used for qubit-index mapping.

        Returns
        -------
        dict[int, list[dict]]
        """
        source = self._source
        # Both file and Circuit modes need the DataCollector to measure
        # data qubits after the circuit executes.  The dist_commands.txt
        # format does not contain measurement ops; the measure_qubits
        # config specifies which positions to read.
        self._needs_datacollector = True
        if isinstance(source, str):
            return _partition_commands_from_file(source, qpu_info=qpu_info)
        return _partition_commands(source, qpu_info=qpu_info)


# ---------------------------------------------------------------------------
# Internal implementation — tket circuit parser
# ---------------------------------------------------------------------------

def _partition_commands(dist_circ, qpu_info=None):
    """Partition a pytket distributed Circuit into canonical per-QPU command dicts.

    Pure parser: emits canonical op names only. No labels are assigned and no
    ``entanglement_gen`` commands are inserted here — that is handled by the
    labeling layer (``qnpack.dqc.labeling``).
    
    Uses pytket's Command API to extract operations by matching on OpType names.
    """
    qpu_commands = {1: [], 2: [], 3: []}

    for cmd in dist_circ.get_commands():
        # Get operation name - match on actual OpType
        if hasattr(cmd.op, 'get_name'):
            op_name = cmd.op.get_name()
        else:
            op_name = cmd.op.type.name

        params = (
            list(cmd.op.params)
            if hasattr(cmd.op, 'params') and cmd.op.params
            else []
        )

        # Match on operation type instead of regex
        is_ejpp_start = op_name.startswith("starting_process")
        is_ejpp_end = op_name.startswith("ending_process")

        if is_ejpp_start or is_ejpp_end:
            both_link = all(is_link_register(q) for q in cmd.qubits)

            if both_link:
                data_qubit = cmd.qubits[0]
                link_qubit = cmd.qubits[1]
            else:
                data_qubit = None
                link_qubit = None
                for q in cmd.qubits:
                    if is_link_register(q):
                        link_qubit = q
                    else:
                        data_qubit = q

            if data_qubit is None or link_qubit is None:
                log.warning(
                    f"Could not identify data/link qubits in {op_name}: {cmd.qubits}"
                )
                continue

            data_server_id = get_server_id_from_qubit(data_qubit)
            link_server_id = get_server_id_from_qubit(link_qubit)
            link_qubit_idx = link_qubit.index[0]
            data_qpu_id = data_server_id + 1
            link_qpu_id = link_server_id + 1

            data_local = map_qubit_to_local(
                data_qubit, qpu_info=qpu_info, server_id=data_server_id
            )

            if both_link:
                num_comm = _num_comm_qubits_for_qpu(data_qpu_id, qpu_info)
                l_local = None
                for c in range(num_comm):
                    if c != data_local:
                        l_local = c
                        break
                if l_local is None:
                    log.warning(
                        f"Link-link EJPP on QPU_{data_qpu_id} but only {num_comm} "
                        f"comm qubit(s); reusing position 0 for emission"
                    )
                    l_local = 0
            else:
                l_local = 0

            # ── EJPP data-side command ─────────────────────────────────
            qpu_commands[data_qpu_id].append({
                "op": "ejpp_start" if is_ejpp_start else "ejpp_end",
                "params": params,
                "data_qubit": data_local,
                "l_local": l_local,
                "original_qubits": [str(q) for q in cmd.qubits],
                "is_remote": True,
                "link_qpu_id": link_qpu_id,
                "link_qubit_idx": link_qubit_idx,
                "data_qpu_id": data_qpu_id,
                "start_label": None,
                "end_label": None,
            })

            # ── EJPP link-side command ─────────────────────────────────
            qpu_commands[link_qpu_id].append({
                "op": "ejpp_start_link" if is_ejpp_start else "ejpp_end_link",
                "params": params,
                "qubits": [link_qubit_idx],
                "original_qubits": [str(q) for q in cmd.qubits],
                "is_remote": True,
                "data_qpu_id": data_qpu_id,
                "link_qubit_idx": link_qubit_idx,
                "start_label": None,
                "end_label": None,
            })

        # Match on CU1 OpType
        elif cmd.op.type == OpType.CU1 or "CU1" in op_name:
            local_qubits = [
                map_qubit_to_local(q, qpu_info=qpu_info) for q in cmd.qubits
            ]
            qpu_commands[1].append({
                "op": op_name.lower(),
                "params": params,
                "qubits": local_qubits,
                "original_qubits": [str(q) for q in cmd.qubits],
                "is_remote": False,
                "start_label": None,
                "end_label": None,
            })

        else:
            first_qubit = cmd.qubits[0]
            server_id = get_server_id_from_qubit(first_qubit)
            qpu_id = server_id + 1
            local_idx = map_qubit_to_local(first_qubit, qpu_info=qpu_info)
            qpu_commands[qpu_id].append({
                "op": op_name.lower(),
                "params": params,
                "qubits": [local_idx],
                "original_qubits": [str(q) for q in cmd.qubits],
                "is_remote": False,
                "start_label": None,
                "end_label": None,
            })

    return qpu_commands


# ---------------------------------------------------------------------------
# Internal implementation — file parser using pytket
# ---------------------------------------------------------------------------

def _partition_commands_from_file(filepath, qpu_info=None):
    """Parse a dist_commands.txt file using pytket's QASM parser.

    Pure parser: emits canonical op names only. No labels are assigned and no
    ``entanglement_gen`` commands are inserted here — that is handled by the
    labeling layer (``qnpack.dqc.labeling``).

    Canonical op name mapping:
        starting_process       → ejpp_start
        starting_process_link  → ejpp_start_link
        ending_process         → ejpp_end
        ending_process_link    → ejpp_end_link
    """
    with open(filepath, "r") as f:
        lines = f.readlines()

    qpu_commands = {1: [], 2: [], 3: []}

    # Filter out header/metadata lines
    filtered_lines = []
    for raw_line in lines:
        line = raw_line.strip()
        
        # Skip line number prefixes
        if line and line[0].isdigit() and ':' in line:
            line = line.split(':', 1)[1].strip()
        
        # Skip metadata and empty lines
        if (
            not line
            or line.startswith("Distributed Circuit")
            or line.startswith("Circuit Commands")
            or line.startswith("-")
            or line.startswith("=")
            or line.startswith("Qubits:")
            or line.startswith("Servers:")
            or line.startswith("Total commands:")
            or line.startswith("Circuit depth:")
            or line.startswith("2-qubit gates:")
            or line.startswith("Multi-qubit gates:")
            or line.startswith("Gate breakdown:")
            or line.startswith("Target state:")
            or line.startswith("Total states:")
            or line.startswith("Optimal iterations:")
            or line.startswith("Used iterations:")
            or line.startswith("Oracle type:")
            or line.startswith("Secret")
            or line.startswith("Ancilla")
            or line.startswith("Graph:")
            or line.startswith("Edges:")
            or line.startswith("QAOA")
            or line.startswith("Gammas:")
            or line.startswith("Betas:")
            or line.startswith("Note:")
            or line.startswith("Running")
            or line.startswith("Oracle")
            or line.startswith("No ancilla")
            or line.startswith("Uses multi")
            or line.startswith("  ")
            or ("|" in line and "qubits" in line)
            or (
                line
                and line[0].isalpha()
                and ":" in line
                and not line.startswith("starting_process")
                and not line.startswith("ending_process")
            )
        ):
            continue
        
        filtered_lines.append(line.rstrip(";").strip())

    # Process each instruction line by matching on operation name
    for line in filtered_lines:
        # Match on EJPP operations
        is_ejpp_start = line.startswith("starting_process ")
        is_ejpp_end = line.startswith("ending_process ")

        if is_ejpp_start or is_ejpp_end:
            prefix = "starting_process " if is_ejpp_start else "ending_process "
            args_str = line[len(prefix):]
            qubit_strs = [q.strip() for q in args_str.split(",")]

            both_link = all("link_register" in qs for qs in qubit_strs)

            if both_link:
                data_str = qubit_strs[0]
                link_str = qubit_strs[1]
            else:
                data_str = None
                link_str = None
                for qs in qubit_strs:
                    if "link_register" in qs:
                        link_str = qs
                    else:
                        data_str = qs

            if data_str is None or link_str is None:
                log.warning(
                    f"Could not identify data/link qubits in line: {line}"
                )
                continue

            _, data_server_id, data_qubit_idx, data_is_link = _parse_qubit_str(data_str)
            _, link_server_id, link_qubit_idx, _ = _parse_qubit_str(link_str)

            data_qpu_id = data_server_id + 1
            link_qpu_id = link_server_id + 1

            data_local = _map_qubit_str_to_local(data_str, qpu_info)

            if both_link:
                num_comm = _num_comm_qubits_for_qpu(data_qpu_id, qpu_info)
                l_local = None
                for c in range(num_comm):
                    if c != data_local:
                        l_local = c
                        break
                if l_local is None:
                    log.warning(
                        f"Link-link EJPP on QPU_{data_qpu_id} but only {num_comm} "
                        f"comm qubit(s); reusing position 0 for emission"
                    )
                    l_local = 0
            else:
                l_local = 0

            # ── EJPP data-side command ─────────────────────────────────
            if is_ejpp_start:
                data_cmd = {
                    "op": "ejpp_start",
                    "params": [],
                    "label": None,
                    "start_label": None,
                    "end_label": None,
                    "qubit": data_local,
                    "data_qubit": data_local,
                    "l_local": l_local,
                    "clbit": None,
                    "peer_qpu_id": link_qpu_id,
                    "link_qpu_id": link_qpu_id,
                    "link_qubit_idx": link_qubit_idx,
                    "data_qpu_id": data_qpu_id,
                    "original_qubits": qubit_strs,
                    "is_remote": True,
                }
                link_cmd = {
                    "op": "ejpp_start_link",
                    "params": [],
                    "label": None,
                    "start_label": None,
                    "end_label": None,
                    "qubit": link_qubit_idx,
                    "qubits": [link_qubit_idx],
                    "link_qubit_idx": link_qubit_idx,
                    "clbit": None,
                    "peer_qpu_id": data_qpu_id,
                    "data_qpu_id": data_qpu_id,
                    "original_qubits": qubit_strs,
                    "is_remote": True,
                }
            else:
                data_cmd = {
                    "op": "ejpp_end",
                    "params": [],
                    "label": None,
                    "start_label": None,
                    "end_label": None,
                    "comm_qubit": l_local,
                    "data_qubit": data_local,
                    "l_local": l_local,
                    "clbit": None,
                    "peer_qpu_id": link_qpu_id,
                    "link_qpu_id": link_qpu_id,
                    "link_qubit_idx": link_qubit_idx,
                    "data_qpu_id": data_qpu_id,
                    "original_qubits": qubit_strs,
                    "is_remote": True,
                }
                link_cmd = {
                    "op": "ejpp_end_link",
                    "params": [],
                    "label": None,
                    "start_label": None,
                    "end_label": None,
                    "qubit": link_qubit_idx,
                    "qubits": [link_qubit_idx],
                    "link_qubit_idx": link_qubit_idx,
                    "clbit": None,
                    "peer_qpu_id": data_qpu_id,
                    "data_qpu_id": data_qpu_id,
                    "original_qubits": qubit_strs,
                    "is_remote": True,
                }

            qpu_commands[data_qpu_id].append(data_cmd)
            qpu_commands[link_qpu_id].append(link_cmd)

        # Match on CU1 by operation name
        elif line.startswith("CU1"):
            parts = line.split(None, 1)
            if len(parts) < 2:
                log.warning(f"Cannot parse CU1 line: {line}")
                continue
            
            op_with_param = parts[0]  # e.g., "CU1(0.5)"
            qubit_part = parts[1]
            
            # Extract parameter
            param = 0.0
            if '(' in op_with_param and ')' in op_with_param:
                try:
                    param_str = op_with_param.split('(')[1].split(')')[0]
                    param = float(param_str)
                except (ValueError, IndexError):
                    pass
            
            qubit_strs = [q.strip() for q in qubit_part.split(",")]
            local_qubits = [_map_qubit_str_to_local(q, qpu_info) for q in qubit_strs]
            _, cu1_server_id, _, _ = _parse_qubit_str(qubit_strs[0])
            cu1_qpu_id = cu1_server_id + 1
            qpu_commands[cu1_qpu_id].append({
                "op": "cu1",
                "params": [param],
                "qubits": local_qubits,
                "original_qubits": qubit_strs,
                "is_remote": False,
                "start_label": None,
                "end_label": None,
            })

        # Match on CNOT/CX by operation name
        elif line.startswith("CNOT") or line.startswith("CX") or line.startswith("cx"):
            parts = line.split(None, 1)
            if len(parts) < 2:
                log.warning(f"Cannot parse CNOT/CX line: {line}")
                continue
            
            op_name = parts[0].lower()
            qubit_strs = [q.strip() for q in parts[1].split(",")]
            
            if len(qubit_strs) < 2:
                log.warning(f"CNOT/CX requires 2 qubits: {line}")
                continue
            if len(qubit_strs) != len(set(qubit_strs)):
                log.error(f"CNOT/CX has duplicate qubits: {line}")
                continue
            
            local_qubits = [_map_qubit_str_to_local(q, qpu_info) for q in qubit_strs]
            _, cnot_server_id, _, _ = _parse_qubit_str(qubit_strs[0])
            cnot_qpu_id = cnot_server_id + 1
            qpu_commands[cnot_qpu_id].append({
                "op": op_name,
                "params": [],
                "qubits": local_qubits,
                "original_qubits": qubit_strs,
                "is_remote": False,
                "start_label": None,
                "end_label": None,
            })

        # Match on CCX/Toffoli by operation name
        elif line.startswith("CCX") or line.startswith("ccx") or \
             line.startswith("Toffoli") or line.startswith("toffoli"):
            parts = line.split(None, 1)
            if len(parts) < 2:
                log.warning(f"Cannot parse CCX/Toffoli line: {line}")
                continue
            
            op_name = parts[0].lower()
            qubit_strs = [q.strip() for q in parts[1].split(",")]
            
            if len(qubit_strs) < 3:
                log.warning(f"CCX/Toffoli requires 3 qubits: {line}")
                continue
            if len(qubit_strs) != len(set(qubit_strs)):
                log.error(f"CCX/Toffoli has duplicate qubits: {line}")
                continue
            
            local_qubits = [_map_qubit_str_to_local(q, qpu_info) for q in qubit_strs]
            _, ccx_server_id, _, _ = _parse_qubit_str(qubit_strs[0])
            ccx_qpu_id = ccx_server_id + 1
            qpu_commands[ccx_qpu_id].append({
                "op": op_name,
                "params": [],
                "qubits": local_qubits,
                "original_qubits": qubit_strs,
                "is_remote": False,
                "start_label": None,
                "end_label": None,
            })

        # Match on CnX/MCX by operation name
        elif line.startswith("CnX") or line.startswith("cnx") or \
             line.startswith("MCX") or line.startswith("mcx"):
            parts = line.split(None, 1)
            if len(parts) < 2:
                log.warning(f"Cannot parse CnX/MCX line: {line}")
                continue
            
            op_name = parts[0].lower()
            qubit_strs = [q.strip() for q in parts[1].split(",")]
            
            if len(qubit_strs) < 3:
                log.warning(f"CnX/MCX requires 3+ qubits: {line}")
                continue
            if len(qubit_strs) != len(set(qubit_strs)):
                log.error(f"CnX/MCX has duplicate qubits: {line}")
                continue
            
            local_qubits = [_map_qubit_str_to_local(q, qpu_info) for q in qubit_strs]
            _, cnx_server_id, _, _ = _parse_qubit_str(qubit_strs[0])
            cnx_qpu_id = cnx_server_id + 1
            qpu_commands[cnx_qpu_id].append({
                "op": op_name,
                "params": [],
                "qubits": local_qubits,
                "original_qubits": qubit_strs,
                "is_remote": False,
                "start_label": None,
                "end_label": None,
            })

        # Generic single-qubit gate with optional parameter
        else:
            # Split on whitespace to get operation and qubit
            parts = line.split(None, 1)
            if len(parts) < 2:
                log.warning(f"Cannot parse gate line: {line}")
                continue
            
            op_with_param = parts[0]
            qubit_str = parts[1].strip()
            
            # Extract operation name and parameters
            if '(' in op_with_param and ')' in op_with_param:
                op_name = op_with_param.split('(')[0]
                param_str = op_with_param.split('(')[1].split(')')[0]
                try:
                    # Try to evaluate parameter (handles pi, etc.)
                    import math
                    param_str_eval = param_str.replace("pi", str(math.pi))
                    params = [float(eval(param_str_eval))]
                except Exception:
                    try:
                        params = [float(param_str)]
                    except ValueError:
                        params = []
            else:
                op_name = op_with_param
                params = []
            
            bare_op_name = op_name.lower()

            try:
                _, server_id, _, _ = _parse_qubit_str(qubit_str)
                qpu_id = server_id + 1
                local_idx = _map_qubit_str_to_local(qubit_str, qpu_info)
            except ValueError as e:
                log.warning(f"Cannot parse qubit in gate line: {line} - {e}")
                continue

            qpu_commands[qpu_id].append({
                "op": bare_op_name,
                "params": params,
                "qubits": [local_idx],
                "original_qubits": [qubit_str],
                "is_remote": False,
                "start_label": None,
                "end_label": None,
            })

    log.debug(
        f"Parsed {filepath}: QPU_1={len(qpu_commands[1])} cmds, "
        f"QPU_2={len(qpu_commands[2])} cmds, QPU_3={len(qpu_commands[3])} cmds"
    )
    return qpu_commands
