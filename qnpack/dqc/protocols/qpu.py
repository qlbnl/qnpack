"""
protocols/qpu.py
----------------
QPU-side protocols for the DQC simulation.

Classes
-------
    IDQCEmit                    — Custom emit instruction (creates entangled pair)
    DQCEmitProgram              — QuantumProgram wrapper for IDQCEmit
    EntanglementWorkerProtocol  — Persistent per-BSM Bell-pair generator
    QPUProtocol                 — Main QPU execution protocol
"""

import math
import random
import logging

import netsquid as ns
from netsquid.protocols.nodeprotocols import NodeProtocol
from netsquid.components.component import Message
from netsquid.protocols.protocol import Signals
from netsquid.components.instructions import (
    INSTR_INIT,
    INSTR_ROT_Z,
    INSTR_ROT_X,
    INSTR_ROT_Y,
    INSTR_H,
    INSTR_CNOT,
    INSTR_X,
    INSTR_Y,
    INSTR_Z,
    INSTR_MEASURE,
    INSTR_TOFFOLI,
    IInit,
    Instruction,
)
from netsquid.qubits import qubitapi as qapi
from netsquid.qubits import operators as ops
from netsquid.components.qprogram import QuantumProgram

from qnpack.dqc.instruction_set import GATE_OPS

log = logging.getLogger(__name__)

# BSM detector output values that indicate successful Bell measurement
BSM_SUCCESS = [[2], [3]]

# --- Global Timing Variables ---
ENTANGLEMENT_DURATION = 0
MAX_ENTANGLEMENT_TIME = 0
EXECUTION_DURATION = 0
MAX_EXECUTION_TIME = 0
ENTANGLEMENT_START_TIME = 0
ENTANGLEMENT_END_TIME = 0
EXECUTION_START_TIME = 0
EXECUTION_END_TIME = 0
SYNC_PROCESS_DURATION = 0
MAX_SYNC_PROCESS_TIME = 0
SYNC_START_TIME = 0
SYNC_END_TIME = 0


# ---------------------------------------------------------------------------
# Custom emit instruction
# ---------------------------------------------------------------------------

class IDQCEmit(Instruction):
    """Custom emit instruction for DQC that always creates an entangled pair."""

    @property
    def name(self):
        return "dqc_emit_ent_qubit"

    @property
    def num_positions(self):
        return 2

    def execute(self, quantum_memory, positions, *args, **kwargs):
        emitter_position = positions[0]
        [memory_qubit] = quantum_memory.peek(emitter_position)
        [emission_qubit] = qapi.create_qubits(1)
        qapi.operate(memory_qubit, ops.H)
        qapi.operate([memory_qubit, emission_qubit], ops.CNOT)
        quantum_memory.ports[f"qout{emitter_position}"].tx_output(emission_qubit)


DQC_EMIT = IDQCEmit()


class DQCEmitProgram(QuantumProgram):
    """QuantumProgram wrapper that applies :data:`DQC_EMIT`."""

    default_num_qubits = 2

    def program(self):
        memory_position, emission_position = self.get_qubit_indices()
        self.apply(
            instruction=DQC_EMIT,
            qubit_indices=[memory_position, emission_position],
        )
        yield self.run()


# ---------------------------------------------------------------------------
# Entanglement worker
# ---------------------------------------------------------------------------

class EntanglementWorkerProtocol(NodeProtocol):
    """Persistent sub-protocol that generates Bell pairs sequentially.

    A single instance is created per BSM channel and processes all
    pre-entanglement requests from a work queue.  This avoids the
    overhead of creating/destroying many sub-protocol instances and
    eliminates event-handler explosion from concurrent waiters on
    the same BSM clock port.

    Uses ``qapi`` direct qubit operations instead of ``execute_instruction``
    / ``execute_program`` to avoid ``ProcessorBusyError``.

    Parameters
    ----------
    node : Node
        The QPU node (shared with QPUProtocol).
    qpu_protocol : QPUProtocol
        Reference to the parent protocol (for shared state access).
    bsm_label : str
        BSM label for routing the photon.
    name : str or None
        Protocol name (auto-generated if None).
    """

    ENTANGLEMENT_DONE = "ENTANGLEMENT_DONE"
    NEW_WORK = "NEW_WORK"

    def __init__(self, node, qpu_protocol, bsm_label, name=None):
        if name is None:
            name = f"EntWorker_{node.name}_{bsm_label}"
        super().__init__(node, name=name)
        self.qpu_protocol = qpu_protocol
        self.bsm_label = bsm_label
        self._work_queue = []
        self.add_signal(self.ENTANGLEMENT_DONE)
        self.add_signal(self.NEW_WORK)

        self._one_q_gate_duration = float(
            qpu_protocol.cfg.gate_durations.one_q_gate_duration
        )
        self._one_q_depolar_prob = float(
            qpu_protocol.cfg.qpu.one_q_depolar_prob
        )

    def add_work(self, target_start_label, cmd):
        """Add a pre-gen request to the work queue."""
        self._work_queue.append((target_start_label, cmd))
        self.send_signal(self.NEW_WORK)

    def _init_qubit(self, position):
        """Re-initialize a qubit to |0⟩ using qapi (no processor lock)."""
        [qubit] = self.node.qmemory.peek(position)
        if qubit is not None:
            qapi.assign_qstate([qubit], ns.qubits.ketstates.s0)
        else:
            [qubit] = qapi.create_qubits(1)
            self.node.qmemory.put(qubit, positions=[position])

    def _emit_photon(self, position):
        """Create a Bell pair between memory qubit and a fresh photon."""
        [memory_qubit] = self.node.qmemory.peek(position)
        [emission_qubit] = qapi.create_qubits(1)

        qapi.operate(memory_qubit, ops.H)
        qapi.operate([memory_qubit, emission_qubit], ops.CNOT)

        emission_fidelity = self.qpu_protocol.cfg.qpu.emission_fidelity
        if emission_fidelity < 1.0:
            self._apply_emission_noise(memory_qubit, emission_qubit, emission_fidelity)

        collection_efficiency = self.qpu_protocol.cfg.qpu.collection_efficiency
        if collection_efficiency < 1.0:
            if random.random() > collection_efficiency:
                log.debug(
                    f"[{self.node.name}|Worker] Photon lost due to "
                    f"collection efficiency ({collection_efficiency})"
                )
                qapi.discard(emission_qubit)
                qapi.assign_qstate([memory_qubit], ns.qubits.ketstates.s0)
                return False

        qout_port = self.node.qmemory.ports.get(f"qout{position}")
        if qout_port is None:
            qout_port = self.node.qmemory.ports.get("qout")
        if qout_port is None:
            log.error(
                f"[{self.node.name}|Worker] No qout port for position {position}"
            )
            qapi.discard(emission_qubit)
            return False

        qout_port.tx_output(emission_qubit)
        return True

    def _apply_emission_noise(self, matter_qubit, photon_qubit, fidelity):
        """Apply depolarizing noise to simulate emission fidelity."""
        depol_prob = 4 / 3 * (1 - fidelity)
        qapi.depolarize(photon_qubit, depol_prob)

    def _apply_correction(self, position, gate_op):
        """Apply a single-qubit correction gate using qapi.

        Adds a timing delay matching ``one_q_gate_duration`` so that
        T1/T2 memory decoherence accumulates correctly, and manually
        applies depolarising noise matching ``one_q_depolar_prob``.
        """
        [qubit] = self.node.qmemory.peek(position)
        qapi.operate(qubit, gate_op)

        if self._one_q_gate_duration > 0:
            yield self.await_timer(duration=self._one_q_gate_duration)

        if self._one_q_depolar_prob > 0:
            r = random.random()
            p = self._one_q_depolar_prob
            if r < p:
                pauli_r = random.random()
                if pauli_r < 1.0 / 3.0:
                    qapi.operate(qubit, ops.X)
                elif pauli_r < 2.0 / 3.0:
                    qapi.operate(qubit, ops.Y)
                else:
                    qapi.operate(qubit, ops.Z)

    def _drain_stale_bsm_results(self, bsm_res_port):
        """Drain any stale BSM result messages left in the port buffer."""
        drained = 0
        while True:
            stale = bsm_res_port.rx_input()
            if stale is None:
                break
            drained += 1
        return drained

    def run(self):
        """Process pre-gen requests sequentially from the work queue."""
        parent = self.qpu_protocol
        bsm_label = self.bsm_label

        bsm_clk_port_name = f"clk_from_{bsm_label}"
        bsm_res_port_name = f"bsm_res_from_{bsm_label}"
        bsm_clk_port = self.node.ports.get(bsm_clk_port_name)
        bsm_res_port = self.node.ports.get(bsm_res_port_name)

        if bsm_clk_port is None or bsm_res_port is None:
            log.error(
                f"[{self.node.name}|Worker] Cannot find BSM ports for {bsm_label}"
            )
            return

        max_retries = parent.cfg.bsm.max_emission_retries
        retry_duration = parent.cfg.bsm.retry_duration

        while True:
            while not self._work_queue:
                yield self.await_signal(self, self.NEW_WORK)

            target_start_label, cmd = self._work_queue.pop(0)

            if cmd.get('l_local') is not None:
                l_local = cmd['l_local']
                is_link_side = False
                data_qubit = cmd.get('data_qubit')
                exclude = {data_qubit} if data_qubit is not None else set()
            else:
                l_local = cmd['qubits'][0]
                is_link_side = True
                exclude = set()

            actual_emit = parent.find_free_comm_qubit(l_local, exclude=exclude)

            log.debug(
                f"[{self.node.name}|Worker] Generating entanglement for "
                f"start_label={target_start_label} on qubit {actual_emit} "
                f"(bsm={bsm_label}, link_side={is_link_side})"
            )

            self._drain_stale_bsm_results(bsm_res_port)
            parent._forward_qout_to_bsm(bsm_label, actual_emit)

            yield self.await_port_input(bsm_clk_port)
            bsm_clk_port.rx_input()

            self._drain_stale_bsm_results(bsm_res_port)

            ent_start_time = ns.sim_time()
            retries = 0
            success = False
            bsm_data = None

            while retries <= max_retries:
                if retries > 0:
                    yield self.await_port_input(bsm_clk_port)
                    bsm_clk_port.rx_input()
                    self._drain_stale_bsm_results(bsm_res_port)

                self._init_qubit(actual_emit)

                if retries != 0 and retry_duration > 0:
                    yield self.await_timer(duration=retry_duration)

                parent._forward_qout_to_bsm(bsm_label, actual_emit)
                emit_ok = self._emit_photon(actual_emit)
                if not emit_ok:
                    retries += 1
                    continue

                yield self.await_port_input(bsm_res_port)
                res = bsm_res_port.rx_input()

                if res is None or not res.items:
                    retries += 1
                    continue

                item = res.items[0] if isinstance(res.items, list) else res.items
                if isinstance(item, dict):
                    bsm_data = item.get('data')
                else:
                    bsm_data = item

                if bsm_data in BSM_SUCCESS:
                    success = True
                    break
                else:
                    retries += 1

            ent_end_time = ns.sim_time()
            ent_duration_ns = ent_end_time - ent_start_time

            if success:
                if (
                    parent.global_entanglement_durations is not None
                    and target_start_label not in parent.global_entanglement_durations
                ):
                    duration_s = ent_duration_ns / 1e9
                    parent.global_entanglement_durations[target_start_label] = duration_s

                role = cmd.get('role')
                apply_corrections = is_link_side if role is None else (role == 'peer')
                if apply_corrections and bsm_data is not None:
                    if bsm_data == [2] or bsm_data == [3]:
                        yield from self._apply_correction(actual_emit, ops.X)
                    if bsm_data == [3]:
                        yield from self._apply_correction(actual_emit, ops.Z)

                parent.occupied_comm_qubits.add(actual_emit)
                log.debug(
                    f"[{self.node.name}|Worker] Entanglement SUCCESS for "
                    f"start_label={target_start_label}: actual_emit={actual_emit}, "
                    f"retries={retries}, bsm_data={bsm_data}"
                )
            else:
                log.warning(
                    f"[{self.node.name}|Worker] Entanglement FAILED for "
                    f"start_label={target_start_label} after {retries} retries"
                )

            parent.bell_pair_buffer[target_start_label] = {
                'success': success,
                'bsm_data': bsm_data,
                'retries': retries,
                'actual_emit': actual_emit,
                'ent_duration_ns': ent_duration_ns,
                'generation_time': ent_end_time if success else ns.sim_time(),
            }

            self.send_signal(self.ENTANGLEMENT_DONE, result=target_start_label)


# ---------------------------------------------------------------------------
# QPU protocol
# ---------------------------------------------------------------------------

class QPUProtocol(NodeProtocol):
    """Protocol running on a QPU node.

    Entanglement is generated via persistent :class:`EntanglementWorkerProtocol`
    instances (one per BSM channel).  When the main ``run()`` loop reaches
    a ``starting_process`` or ``starting_process_link`` command, it submits
    work to the appropriate worker and blocks until the Bell pair is ready
    in ``bell_pair_buffer``.

    Parameters
    ----------
    cfg : Munch
        Simulation configuration.
    node : Node
        The QPU node this protocol runs on.
    qpu_id : int
        1-based QPU index.
    name : str or None
        Protocol name (auto-generated if None).
    """

    def __init__(self, cfg, node, qpu_id, qpu_label=None, q_switch=None, bsm_info=None, name=None):
        super().__init__(node, name=name)
        self.cfg = cfg
        self.qpu_id = qpu_id
        self.qpu_label = qpu_label   # topology label (e.g. 'LBNL-A'), used by switch
        self.q_switch = q_switch     # FullMeshOpticalSwitch or None
        self.bsm_info = bsm_info or {}  # bsm_label -> {left_qpu, right_qpu, ...}
        self.qpu = node.subcomponents.get("QPU")
        self.pre_schedule_entanglement = cfg.circuit.pre_schedule_entanglement
        self.ctrl_port = self.node.ports["ctrl_port"]
        self.clk_port = self.node.ports["clk_port"]
        self.comm_port = self.node.ports["comm_port"]
        self.commands = []

        self.occupied_comm_qubits: set = set()

        self.NUM_COMM_QUBITS = 20
        self.FIRST_DATA_QUBIT = 20
        self._pending_msg_exchange: dict = {}
        self._pending_classical_msgs: dict = {}
        self.classical_memory: dict = {}
        self.final_measurements = {}

        self.bell_pair_buffer: dict = {}
        self.global_entanglement_durations = None

        # Persistent BSM workers: bsm_label -> EntanglementWorkerProtocol (or SwitchedEntanglementWorker)
        self._bsm_workers: dict = {}

    # ── Worker management ────────────────────────────────────────────────────

    def _get_or_create_bsm_worker(self, bsm_label):
        """Return the persistent worker for *bsm_label*, creating it if needed.

        When a ``FullMeshOpticalSwitch`` is present (``self.q_switch`` is not
        ``None``), a :class:`~qnpack.dqc.protocols.switch.SwitchedEntanglementWorker`
        is created instead of the base
        :class:`~qnpack.dqc.protocols.qpu.EntanglementWorkerProtocol`.
        The switched worker configures the optical switch route before each
        photon emission and reads BSM results / clock ticks from the switch
        output ports on the QPU node.
        """
        if bsm_label not in self._bsm_workers:
            if self.q_switch is not None:
                from qnpack.dqc.protocols.switch import SwitchedEntanglementWorker
                # Determine if this QPU is the left or right side for this BSM
                bsm_inf = self.bsm_info.get(bsm_label, {})
                bsm_side = "left" if bsm_inf.get("left_qpu") == self.qpu_label else "right"
                worker = SwitchedEntanglementWorker(
                    node=self.node,
                    qpu_protocol=self,
                    bsm_label=bsm_label,
                    qpu_label=self.qpu_label,
                    q_switch=self.q_switch,
                    bsm_side=bsm_side,
                )
                log.debug(
                    f"[{self.node.name}] Created SwitchedEntanglementWorker "
                    f"for BSM {bsm_label} (qpu_label={self.qpu_label}, side={bsm_side})"
                )
            else:
                worker = EntanglementWorkerProtocol(
                    node=self.node,
                    qpu_protocol=self,
                    bsm_label=bsm_label,
                )
                log.debug(
                    f"[{self.node.name}] Created EntanglementWorkerProtocol "
                    f"for BSM {bsm_label}"
                )
            self._bsm_workers[bsm_label] = worker
            worker.start()
        return self._bsm_workers[bsm_label]

    # ── Qubit management ─────────────────────────────────────────────────────

    def find_free_comm_qubit(self, preferred: int, exclude: set = None) -> int:
        """Find a free communication qubit, avoiding occupied and excluded positions.

        Parameters
        ----------
        preferred : int
            The preferred comm qubit position.
        exclude : set, optional
            Additional positions to exclude.

        Returns
        -------
        int
            A free comm qubit position.
        """
        if exclude is None:
            exclude = set()

        unavailable = self.occupied_comm_qubits | exclude

        if preferred not in unavailable:
            return preferred

        for pos in range(self.NUM_COMM_QUBITS):
            if pos not in unavailable:
                log.debug(
                    f"[{self.node.name}] Comm qubit {preferred} unavailable "
                    f"(occupied={self.occupied_comm_qubits}, exclude={exclude}); "
                    f"redirecting emission to free comm qubit {pos}"
                )
                return pos

        log.error(
            f"[{self.node.name}] All comm qubits 0-{self.NUM_COMM_QUBITS - 1} "
            f"unavailable! occupied={self.occupied_comm_qubits}, exclude={exclude}. "
            f"Defaulting to preferred={preferred} (may corrupt state)"
        )
        return preferred

    def _log_qubit_state(self, label=""):
        if not log.isEnabledFor(logging.DEBUG):
            return
        try:
            num_pos = self.node.qmemory.num_positions
            for pos in range(num_pos):
                qubit_list = self.node.qmemory.peek(positions=[pos])
                if qubit_list and qubit_list[0] is not None:
                    q = qubit_list[0]
                    if q.qstate is not None:
                        log.debug(
                            f"  [STATE {self.node.name}] {label} qubit[{pos}]: "
                            f"{q.qstate.qrepr}"
                        )
                    else:
                        log.debug(
                            f"  [STATE {self.node.name}] {label} qubit[{pos}]: no qstate"
                        )
                else:
                    log.debug(
                        f"  [STATE {self.node.name}] {label} qubit[{pos}]: empty/None"
                    )
        except Exception as e:
            log.debug(f"  [STATE {self.node.name}] {label} Error logging state: {e}")

    def _forward_qout_to_bsm(self, bsm_label, emit_qubit):
        qout_port_name = f"qout{emit_qubit}"
        qout_port = self.node.qmemory.ports.get(qout_port_name)
        if qout_port is None:
            qout_port = self.node.qmemory.ports.get("qout")
            qout_port_name = "qout"
        if qout_port is None:
            log.error(f"[{self.node.name}] qmemory has no '{qout_port_name}' port")
            return

        q_port_name = f"q_to_{bsm_label}"
        if q_port_name not in self.node.ports:
            log.error(f"[{self.node.name}] Node has no port '{q_port_name}'")
            return

        if qout_port.forwarded_ports:
            qout_port.disconnect()
            log.debug(
                f"[{self.node.name}] Disconnected previous {qout_port_name} forwarding"
            )

        qout_port.forward_output(self.node.ports[q_port_name])
        log.debug(
            f"[{self.node.name}] Forwarded qmemory.{qout_port_name} -> {q_port_name} "
            f"(BSM: {bsm_label})"
        )

    # ── Controller signalling ────────────────────────────────────────────────

    def send_start_ready(self, start_label):
        msg = Message(items={
            'type': 'start_ready',
            'start_label': start_label,
            'qpu_id': self.qpu_id,
        })
        self.comm_port.tx_output(msg)
        log.debug(f"[{self.node.name}] Sent start_ready for label={start_label}")

    def send_end_ready(self, end_label):
        msg = Message(items={
            'type': 'end_ready',
            'end_label': end_label,
            'qpu_id': self.qpu_id,
        })
        self.comm_port.tx_output(msg)
        log.debug(f"[{self.node.name}] Sent end_ready for label={end_label}")

    def send_done(self):
        msg = Message(items={
            'type': 'done',
            'qpu_id': self.qpu_id,
        })
        self.comm_port.tx_output(msg)
        log.debug(f"[{self.node.name}] Sent done signal")

    # ── Port draining ────────────────────────────────────────────────────────

    def _drain_port(self):
        """Drain c_from_* ports and stash classical process messages.

        ``msg_exchange`` messages are stashed in ``_pending_msg_exchange`` so
        ``handle_msg_receiver`` can still find them after drain consumes them
        from the port buffer (``rx_input`` is destructive).
        """
        c_from_ports = [
            (pname, port)
            for pname, port in self.node.ports.items()
            if pname.startswith("c_from_")
        ]
        for port_name, port in c_from_ports:
            n = 0
            while True:
                msg = port.rx_input()
                if msg is None:
                    break
                item = msg.items[0] if msg.items else None
                msg_type = item.get('type') if item else None

                if msg_type in ('starting_process', 'ending_process'):
                    self._pending_classical_msgs.setdefault(port_name, []).append(msg)
                    log.debug(
                        f"[{self.node.name}] DRAIN CLASSICAL: "
                        f"{port_name} type={msg_type}"
                    )
                    n += 1
                elif msg_type == 'msg_exchange':
                    self._pending_msg_exchange.setdefault(port_name, []).append(msg)
                    log.debug(
                        f"[{self.node.name}] DRAIN STASH msg_exchange: "
                        f"{port_name} label={item.get('label')} t={ns.sim_time()}"
                    )
                    n += 1
                else:
                    log.warning(
                        f"[{self.node.name}] DRAIN DROP: port={port_name} "
                        f"type={msg_type!r} item={item!r} t={ns.sim_time()}"
                    )
                    n += 1
            if n > 0:
                log.debug(
                    f"[{self.node.name}] DRAIN: {port_name} consumed "
                    f"{n} msgs t={ns.sim_time()}"
                )

    # ── Gate execution ───────────────────────────────────────────────────────

    def execute_gate(self, op):
        """Execute a gate op from canonical IR.

        Parameters
        ----------
        op : dict
            Canonical IR gate op with ``'gate'`` and ``'qubits'``/``'qubit'``.
        """
        gate_name = op.get('gate') or op.get('op', '')
        qubits = op.get('qubits') or (
            [op['qubit']] if op.get('qubit') is not None else []
        )
        params = op.get('params', [])
        log.debug(
            f"[{self.node.name}] GATE {gate_name} qubits={qubits} params={params}"
        )
        yield from self._apply_gate_by_name(gate_name, qubits, params)

    def _apply_gate_by_name(self, gate_name, qubits, params=None):
        """Apply any gate by name to local memory qubit positions.

        Parameters
        ----------
        gate_name : str
            Gate name (case-insensitive).
        qubits : list[int] or int
            Local memory positions.
        params : list[float] or None
            Angle parameters in units of pi.
        """
        if params is None:
            params = []

        if isinstance(qubits, int):
            qubits = [qubits]

        g = gate_name.lower()

        def _p(i, default=0.0):
            return float(params[i]) * math.pi if len(params) > i else default

        q0 = qubits[0] if qubits else 0

        # ── 1-qubit gates ──────────────────────────────────────────────────
        if g == 'h':
            self.node.qmemory.execute_instruction(INSTR_H, qubit_mapping=[q0])
            yield self.await_program(self.node.qmemory)
        elif g == 'x':
            self.node.qmemory.execute_instruction(INSTR_X, qubit_mapping=[q0])
            yield self.await_program(self.node.qmemory)
        elif g == 'y':
            self.node.qmemory.execute_instruction(INSTR_Y, qubit_mapping=[q0])
            yield self.await_program(self.node.qmemory)
        elif g == 'z':
            self.node.qmemory.execute_instruction(INSTR_Z, qubit_mapping=[q0])
            yield self.await_program(self.node.qmemory)
        elif g in ('rz', 'u1'):
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=_p(0))
            yield self.await_program(self.node.qmemory)
        elif g == 'rx':
            self.node.qmemory.execute_instruction(
                INSTR_ROT_X, qubit_mapping=[q0], angle=_p(0))
            yield self.await_program(self.node.qmemory)
        elif g == 'ry':
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Y, qubit_mapping=[q0], angle=_p(0))
            yield self.await_program(self.node.qmemory)
        elif g == 'sx':
            self.node.qmemory.execute_instruction(
                INSTR_ROT_X, qubit_mapping=[q0], angle=math.pi / 2)
            yield self.await_program(self.node.qmemory)
        elif g == 's':
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=math.pi / 2)
            yield self.await_program(self.node.qmemory)
        elif g == 'sdg':
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=-math.pi / 2)
            yield self.await_program(self.node.qmemory)
        elif g == 't':
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=math.pi / 4)
            yield self.await_program(self.node.qmemory)
        elif g == 'tdg':
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=-math.pi / 4)
            yield self.await_program(self.node.qmemory)
        elif g == 'u2':
            # u2(phi, lam) = rz(lam) · ry(pi/2) · rz(phi)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=_p(1))
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Y, qubit_mapping=[q0], angle=math.pi / 2)
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=_p(0))
            yield self.await_program(self.node.qmemory)
        elif g == 'u3':
            # u3(theta, phi, lam) = rz(lam) · ry(theta) · rz(phi)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=_p(2))
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Y, qubit_mapping=[q0], angle=_p(0))
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[q0], angle=_p(1))
            yield self.await_program(self.node.qmemory)
        elif g == 'reset':
            self.node.qmemory.execute_instruction(INSTR_INIT, qubit_mapping=[q0])
            yield self.await_program(self.node.qmemory)

        # ── 2-qubit gates ──────────────────────────────────────────────────
        elif g in ('cx', 'cnot'):
            if len(qubits) < 2:
                log.error(f"[{self.node.name}] {g} requires 2 qubits, got {qubits}")
                return
            self.node.qmemory.execute_instruction(
                INSTR_CNOT, qubit_mapping=[qubits[0], qubits[1]])
            yield self.await_program(self.node.qmemory)
        elif g == 'cu1':
            if len(qubits) < 2:
                log.error(f"[{self.node.name}] cu1 requires 2 qubits, got {qubits}")
                return
            # cu1(λ) decomposition: rz(λ/2) cx rz(-λ/2) cx rz(λ/2)
            half = _p(0) / 2
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[qubits[0]], angle=half)
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_CNOT, qubit_mapping=[qubits[0], qubits[1]])
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[qubits[1]], angle=-half)
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_CNOT, qubit_mapping=[qubits[0], qubits[1]])
            yield self.await_program(self.node.qmemory)
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[qubits[1]], angle=half)
            yield self.await_program(self.node.qmemory)

        # ── 3-qubit gates ──────────────────────────────────────────────────
        elif g in ('ccx', 'toffoli'):
            if len(qubits) < 3:
                raise ValueError(
                    f"[{self.node.name}] {g} requires 3 qubits, got {qubits}"
                )
            self.node.qmemory.execute_instruction(
                INSTR_TOFFOLI, qubit_mapping=[qubits[0], qubits[1], qubits[2]])
            yield self.await_program(self.node.qmemory)

        # ── Multi-qubit gates ──────────────────────────────────────────────
        elif g in ('cnx', 'mcx'):
            if len(qubits) < 3:
                raise ValueError(
                    f"[{self.node.name}] {g} requires 3+ qubits, got {qubits}"
                )
            if len(qubits) == 3:
                # Equivalent to Toffoli
                self.node.qmemory.execute_instruction(
                    INSTR_TOFFOLI, qubit_mapping=[qubits[0], qubits[1], qubits[2]])
                yield self.await_program(self.node.qmemory)
            else:
                # Decompose n-controlled X into a chain of Toffoli gates
                # using n-2 ancilla-free recursive decomposition.
                # For now, raise an error for >3 qubits until a proper
                # decomposition is implemented and validated.
                raise NotImplementedError(
                    f"[{self.node.name}] {g} with {len(qubits)} qubits "
                    f"(>3) is not yet supported. Only 3-qubit CnX/MCX "
                    f"(equivalent to Toffoli) is currently implemented."
                )

        else:
            raise ValueError(
                f"[{self.node.name}] _apply_gate_by_name: "
                f"unsupported gate {gate_name!r} on qubits {qubits}. "
                f"Add the gate to instruction_set.py and _apply_gate_by_name()."
            )

    # ── Measurement ──────────────────────────────────────────────────────────

    def _measure_qubit(self, qubit):
        """Execute a physical measurement on a single local qubit.

        Parameters
        ----------
        qubit : int
            Local memory position.

        Returns
        -------
        int
            Measurement outcome (0 or 1).
        """
        prog = QuantumProgram(num_qubits=1)
        prog.apply(INSTR_MEASURE, [0], output_key='m')
        self.node.qmemory.execute_program(prog, qubit_mapping=[qubit])
        yield self.await_program(self.node.qmemory)
        result = int(prog.output['m'][0])
        log.debug(f"[{self.node.name}] _measure_qubit qubit={qubit} → {result}")
        return result

    def _execute_measure(self, op):
        """Measure a qubit into ``classical_memory[clbit]``."""
        qubit = (
            op.get('qubit') if op.get('qubit') is not None
            else op.get('qubits', [0])[0]
        )
        clbit = op['clbit']
        log.debug(
            f"[{self.node.name}] _execute_measure ENTER qubit={qubit} clbit={clbit}"
        )

        outcome = yield from self._measure_qubit(qubit)
        self.classical_memory[clbit] = outcome
        log.debug(
            f"[{self.node.name}] MEASURE qubit={qubit} clbit={clbit} → {outcome}"
        )

        if qubit < self.NUM_COMM_QUBITS and qubit in self.occupied_comm_qubits:
            self.occupied_comm_qubits.discard(qubit)
            log.debug(
                f"[{self.node.name}] measure: freed comm qubit "
                f"{qubit} from occupied_comm_qubits"
            )

    def _execute_measure_final(self, op):
        """Measure a qubit and store result in ``final_measurements[final_key]``."""
        qubit = (
            op.get('qubit') if op.get('qubit') is not None
            else op.get('qubits', [0])[0]
        )
        final_key = op.get('final_key') or f"m_auto_{qubit}"
        log.debug(
            f"[{self.node.name}] _execute_measure_final ENTER "
            f"qubit={qubit} final_key={final_key}"
        )

        outcome = yield from self._measure_qubit(qubit)
        self.final_measurements[final_key] = outcome
        log.debug(
            f"[{self.node.name}] MEASURE_FINAL qubit={qubit} "
            f"key={final_key} → {outcome}  "
            f"final_measurements={self.final_measurements}"
        )

    def _execute_if_gate(self, op):
        """Conditionally apply a gate based on a classical bit value.

        Parameters
        ----------
        op : dict
            Canonical IR op with ``'gate'``, ``'qubit'``/``'qubits'``,
            ``'params'``, ``'clbit'``, and ``'cond_value'``.
        """
        gate_name = op['gate']
        qubits = op.get('qubits') or (
            [op['qubit']] if op.get('qubit') is not None else []
        )
        params = op.get('params', [])
        clbit = op['clbit']
        cond_value = op.get('cond_value', 1)

        current = self.classical_memory.get(clbit, 0)
        log.debug(
            f"[{self.node.name}] IF clbit={clbit} "
            f"(={current}) == {cond_value} → gate={gate_name} qubits={qubits}"
        )

        if current == cond_value:
            yield from self._apply_gate_by_name(gate_name, qubits, params)

    # ── Classical message exchange ───────────────────────────────────────────

    def handle_msg_sender(self, cmd):
        """Handle the sender side of a QPU-to-QPU classical bit exchange."""
        peer_qpu_id = cmd['peer_qpu_id']
        clbit_name = cmd.get('clbit')
        label = cmd.get('label', '')

        log.debug(
            f"[{self.node.name}] handle_msg_sender: "
            f"label={label}, clbit={clbit_name}, peer=QPU_{peer_qpu_id}"
        )

        bell_key = cmd.get('bell_pair_key')
        actual_emit = cmd.get('comm_qubit')
        if bell_key is not None:
            worker = self._bsm_workers.get(bell_key)
            while bell_key not in self.bell_pair_buffer:
                yield self.await_signal(
                    worker, EntanglementWorkerProtocol.ENTANGLEMENT_DONE
                )
            result = self.bell_pair_buffer.pop(bell_key)
            self._bsm_workers.pop(bell_key, None)
            actual_emit = result['actual_emit']
            log.debug(
                f"[{self.node.name}] msg_sender: consumed Bell pair "
                f"key={bell_key}, actual_emit={actual_emit}"
            )

        cnot_data = cmd.get('cnot_data_qubit')
        if cnot_data is not None and actual_emit is not None:
            num_q = self.node.qmemory.num_positions
            prog = QuantumProgram(num_qubits=num_q)
            prog.apply(INSTR_CNOT, [cnot_data, actual_emit])
            prog.apply(INSTR_MEASURE, actual_emit, output_key="m")
            self.node.qmemory.execute_program(prog, qubit_mapping=list(range(num_q)))
            yield self.await_program(self.node.qmemory)
            m = prog.output["m"][0]
            self.classical_memory[clbit_name] = m
            log.debug(f"[{self.node.name}] msg_sender: CNOT+measure → m={m}")
        elif cmd.get('h_measure_qubit') is not None:
            hq = cmd['h_measure_qubit']
            num_q = self.node.qmemory.num_positions
            prog = QuantumProgram(num_qubits=num_q)
            prog.apply(INSTR_H, hq)
            prog.apply(INSTR_MEASURE, hq, output_key="m")
            self.node.qmemory.execute_program(prog, qubit_mapping=list(range(num_q)))
            yield self.await_program(self.node.qmemory)
            m = prog.output["m"][0]
            self.classical_memory[clbit_name] = m
            log.debug(f"[{self.node.name}] msg_sender: H+measure → m={m}")
        else:
            m = self.classical_memory.get(clbit_name, 0)

        free_q = cmd.get('free_comm_qubit')
        if free_q is None and bell_key is not None and actual_emit is not None:
            free_q = actual_emit
        if free_q is None:
            free_q = (
                cmd.get('qubits', [None])[0] if cmd.get('qubits') else cmd.get('qubit')
            )
        if free_q is not None and free_q in self.occupied_comm_qubits:
            self.occupied_comm_qubits.discard(free_q)
            log.debug(
                f"[{self.node.name}] msg_sender: freed qubit "
                f"{free_q} from occupied_comm_qubits"
            )

        c_port_name = f"c_to_{peer_qpu_id}"
        if c_port_name in self.node.ports:
            payload = {
                'type': 'msg_exchange',
                'label': label,
                'clbit': clbit_name,
                'value': m,
            }
            msg = Message(items=[payload])
            self.node.ports[c_port_name].tx_output(msg)
            log.debug(
                f"[{self.node.name}] msg_sender: "
                f"sent {clbit_name}={m} to QPU_{peer_qpu_id} "
                f"via {c_port_name} (label={label})"
            )
        else:
            log.error(f"[{self.node.name}] Port {c_port_name} not found")

        mark_q = cmd.get('mark_comm_occupied')
        if mark_q is not None:
            self.occupied_comm_qubits.add(mark_q)
            log.debug(
                f"[{self.node.name}] msg_sender: marked qubit {mark_q} as occupied"
            )

        return
        yield  # make this a generator for uniform yield from usage

    def handle_msg_receiver(self, cmd):
        """Handle the receiver side of a QPU-to-QPU classical bit exchange."""
        peer_qpu_id = cmd['peer_qpu_id']
        clbit_name = cmd.get('clbit')
        label = cmd.get('label', '')

        c_port_name = f"c_from_{peer_qpu_id}"
        if c_port_name not in self.node.ports:
            log.error(f"[{self.node.name}] Port {c_port_name} not found")
            return
            yield  # make generator

        port = self.node.ports[c_port_name]

        log.debug(
            f"[{self.node.name}] handle_msg_receiver: "
            f"label={label}, clbit={clbit_name}, peer=QPU_{peer_qpu_id}, "
            f"port={c_port_name} t={ns.sim_time()}"
        )

        bell_key = cmd.get('bell_pair_key')
        if bell_key is not None:
            worker = self._bsm_workers.get(bell_key)
            while bell_key not in self.bell_pair_buffer:
                yield self.await_signal(
                    worker, EntanglementWorkerProtocol.ENTANGLEMENT_DONE
                )
            self.bell_pair_buffer.pop(bell_key)
            self._bsm_workers.pop(bell_key, None)
            log.debug(
                f"[{self.node.name}] msg_receiver: consumed Bell pair key={bell_key}"
            )

        _queue = self._pending_msg_exchange.get(c_port_name)
        if _queue:
            raw = _queue.pop(0)
            if not _queue:
                del self._pending_msg_exchange[c_port_name]
            log.debug(
                f"[{self.node.name}] msg_receiver: stash hit for {c_port_name}"
            )
        else:
            raw = port.rx_input()
            if raw is None:
                log.debug(
                    f"[{self.node.name}] msg_receiver: "
                    f"waiting on {c_port_name} (label={label})"
                )
                yield self.await_port_input(port)
                _queue2 = self._pending_msg_exchange.get(c_port_name)
                if _queue2:
                    raw = _queue2.pop(0)
                    if not _queue2:
                        del self._pending_msg_exchange[c_port_name]
                    log.debug(
                        f"[{self.node.name}] msg_receiver: post-wait stash hit"
                    )
                else:
                    raw = port.rx_input()

        item = raw.items[0] if (raw and raw.items) else {}
        m = item.get('value', 0)
        recv_clbit = item.get('clbit', clbit_name)
        self.classical_memory[recv_clbit] = m
        log.debug(
            f"[{self.node.name}] msg_receiver: "
            f"got {recv_clbit}={m} from QPU_{peer_qpu_id} (label={label})"
        )

        if_gate = cmd.get('if_gate')
        if if_gate is not None:
            yield from self._execute_if_gate(if_gate)

        mark_q = cmd.get('mark_comm_occupied')
        if mark_q is not None:
            self.occupied_comm_qubits.add(mark_q)
            log.debug(
                f"[{self.node.name}] msg_receiver: marked qubit {mark_q} as occupied"
            )
        free_q = cmd.get('free_comm_qubit')
        if free_q is not None:
            self.occupied_comm_qubits.discard(free_q)
            log.debug(
                f"[{self.node.name}] msg_receiver: freed qubit {free_q}"
            )

        self._log_qubit_state("after msg_receiver")
        log.debug(f"[{self.node.name}] handle_msg_receiver done")

    def handle_msg_exchange(self, op):
        """Dispatch to sender or receiver based on ``op['role']``."""
        role = op.get('role', 'sender')
        if role == 'sender':
            yield from self.handle_msg_sender(op)
        else:
            yield from self.handle_msg_receiver(op)

    # ── EJPP handlers ────────────────────────────────────────────────────────

    def handle_ejpp_start_data(self, op):
        """EJPP start correction — data QPU side."""
        label = op['label']
        start_label = op['start_label']
        qubit = op['qubit']
        clbit = op['clbit']
        peer_id = op['peer_qpu_id']

        log.debug(
            f"[{self.node.name}] EJPP_START_DATA label={label} "
            f"start_label={start_label} qubit={qubit} clbit={clbit}"
        )

        self.send_start_ready(start_label)
        while True:
            yield self.await_port_input(self.clk_port)
            tick_item = self.clk_port.rx_input().items[0]
            if tick_item.get('start_label') == start_label:
                break
            log.debug(
                f"[{self.node.name}] ejpp_start_data: ignoring tick, "
                f"waiting for start_label={start_label}"
            )

        send_op = {
            'label': label,
            'role': 'sender',
            'clbit': clbit,
            'msg_type': 'ejpp_start',
            'peer_qpu_id': peer_id,
            'bell_pair_key': start_label,
            'cnot_data_qubit': qubit,
        }
        yield from self.handle_msg_exchange(send_op)

    def handle_ejpp_start_link(self, op):
        """EJPP start correction — link QPU side."""
        label = op['label']
        start_label = op['start_label']
        qubit = op['qubit']
        clbit = op['clbit']
        peer_id = op['peer_qpu_id']

        log.debug(
            f"[{self.node.name}] EJPP_START_LINK label={label} "
            f"start_label={start_label} qubit={qubit} clbit={clbit}"
        )

        self.send_start_ready(start_label)
        while True:
            yield self.await_port_input(self.clk_port)
            tick_item = self.clk_port.rx_input().items[0]
            if tick_item.get('start_label') == start_label:
                break
            log.debug(
                f"[{self.node.name}] ejpp_start_link: ignoring tick, "
                f"waiting for start_label={start_label}"
            )

        recv_op = {
            'label': label,
            'role': 'receiver',
            'clbit': clbit,
            'msg_type': 'ejpp_start',
            'peer_qpu_id': peer_id,
            'bell_pair_key': start_label,
            'mark_comm_occupied': qubit,
            'if_gate': {
                'gate': 'X',
                'qubit': qubit,
                'params': [],
                'clbit': clbit,
                'cond_value': 1,
            },
        }
        yield from self.handle_msg_exchange(recv_op)

    def handle_ejpp_end_data(self, op):
        """EJPP end correction — data QPU side."""
        label = op['label']
        end_label = op['end_label']
        comm_qubit = op['comm_qubit']
        data_qubit = op['data_qubit']
        clbit = op['clbit']
        peer_id = op['peer_qpu_id']

        log.debug(
            f"[{self.node.name}] EJPP_END_DATA label={label} "
            f"comm_qubit={comm_qubit} data_qubit={data_qubit} clbit={clbit}"
        )

        self.send_end_ready(end_label)
        while True:
            yield self.await_port_input(self.clk_port)
            tick_item = self.clk_port.rx_input().items[0]
            if tick_item.get('end_label') == end_label:
                break
            log.debug(
                f"[{self.node.name}] ejpp_end_data: ignoring tick, "
                f"waiting for end_label={end_label}"
            )

        recv_op = {
            'label': label,
            'role': 'receiver',
            'clbit': clbit,
            'msg_type': 'ejpp_end',
            'peer_qpu_id': peer_id,
            'if_gate': {
                'gate': 'Z',
                'qubit': data_qubit,
                'params': [],
                'clbit': clbit,
                'cond_value': 1,
            },
        }
        yield from self.handle_msg_exchange(recv_op)

    def handle_ejpp_end_link(self, op):
        """EJPP end correction — link QPU side."""
        label = op['label']
        end_label = op['end_label']
        qubit = op['qubit']
        clbit = op['clbit']
        peer_id = op['peer_qpu_id']

        log.debug(
            f"[{self.node.name}] EJPP_END_LINK label={label} "
            f"qubit={qubit} clbit={clbit}"
        )

        self.send_end_ready(end_label)
        while True:
            yield self.await_port_input(self.clk_port)
            tick_item = self.clk_port.rx_input().items[0]
            if tick_item.get('end_label') == end_label:
                break
            log.debug(
                f"[{self.node.name}] ejpp_end_link: ignoring tick, "
                f"waiting for end_label={end_label}"
            )

        send_op = {
            'label': label,
            'role': 'sender',
            'clbit': clbit,
            'msg_type': 'ejpp_end',
            'peer_qpu_id': peer_id,
            'h_measure_qubit': qubit,
            'free_comm_qubit': qubit,
        }
        yield from self.handle_msg_exchange(send_op)

    # ── Main run loop ────────────────────────────────────────────────────────

    def run(self):
        log.debug(f"[{self.node.name}] Starting at time:{ns.sim_time()}")
        log.debug(f"[{self.node.name}] Protocol started, waiting for commands...")

        yield self.await_port_input(self.ctrl_port)
        log.debug(f"Received QPU commands from control node at {self.node.name}")
        msg = self.ctrl_port.rx_input()
        item = msg.items[0]
        self.commands = item.get('commands', [])
        log.debug(f"[{self.node.name}] Received {len(self.commands)} commands")

        self.node.qmemory.execute_instruction(IInit())
        yield self.await_program(self.node.qmemory)
        log.debug(f"[{self.node.name}] Initialized all qubits")

        global EXECUTION_START_TIME, EXECUTION_END_TIME, EXECUTION_DURATION, MAX_EXECUTION_TIME
        global SYNC_START_TIME, SYNC_END_TIME, SYNC_PROCESS_DURATION, MAX_SYNC_PROCESS_TIME
        EXECUTION_START_TIME = ns.sim_time()

        # Gate op names derived from the canonical instruction-set registry
        # (imported at module level as GATE_OPS).
        _GATE_OPS = GATE_OPS

        for op in self.commands:
            op_name = op['op']

            if op_name != 'msg_receiver':
                self._drain_port()
            op_name_lower = op_name.lower()

            if op_name_lower == 'gate':
                yield from self.execute_gate(op)

            elif op_name_lower in _GATE_OPS:
                qubits = op.get('qubits') or (
                    [op['qubit']] if op.get('qubit') is not None else []
                )
                params = op.get('params', [])
                log.debug(
                    f"[{self.node.name}] GATE {op_name_lower} "
                    f"qubits={qubits} params={params}"
                )
                yield from self._apply_gate_by_name(op_name_lower, qubits, params)

            elif op_name == 'measure':
                yield from self._execute_measure(op)

            elif op_name == 'measure_final':
                yield from self._execute_measure_final(op)

            elif op_name == 'if_gate':
                yield from self._execute_if_gate(op)

            elif op_name == 'msg_sender':
                end_label = op.get('end_label')
                if end_label is not None:
                    self.send_end_ready(end_label)
                    while True:
                        yield self.await_port_input(self.clk_port)
                        tick_msg = self.clk_port.rx_input()
                        tick_item = tick_msg.items[0]
                        recv_end_label = tick_item.get('end_label')
                        if recv_end_label == end_label:
                            log.debug(
                                f"[{self.node.name}] msg_sender: "
                                f"clock tick for end_label={end_label}"
                            )
                            break
                        else:
                            log.debug(
                                f"[{self.node.name}] msg_sender: "
                                f"ignoring tick, waiting for end_label={end_label}"
                            )
                log.debug(
                    f"[{self.node.name}] STEP msg_sender: "
                    f"label={op.get('label')}, time={ns.sim_time()}"
                )
                yield from self.handle_msg_sender(op)

            elif op_name == 'msg_receiver':
                end_label = op.get('end_label')
                if end_label is not None:
                    self.send_end_ready(end_label)
                    while True:
                        yield self.await_port_input(self.clk_port)
                        tick_msg = self.clk_port.rx_input()
                        tick_item = tick_msg.items[0]
                        recv_end_label = tick_item.get('end_label')
                        if recv_end_label == end_label:
                            log.debug(
                                f"[{self.node.name}] msg_receiver: "
                                f"clock tick for end_label={end_label}"
                            )
                            break
                        else:
                            log.debug(
                                f"[{self.node.name}] msg_receiver: "
                                f"ignoring tick, waiting for end_label={end_label}"
                            )
                log.debug(
                    f"[{self.node.name}] STEP msg_receiver: "
                    f"label={op.get('label')}, time={ns.sim_time()}"
                )
                yield from self.handle_msg_receiver(op)

            elif op_name == 'ejpp_start':
                yield from self.handle_ejpp_start_data(op)

            elif op_name == 'ejpp_start_link':
                yield from self.handle_ejpp_start_link(op)

            elif op_name == 'ejpp_end':
                yield from self.handle_ejpp_end_data(op)

            elif op_name == 'ejpp_end_link':
                yield from self.handle_ejpp_end_link(op)

            elif op_name_lower.startswith('cu1('):
                # TketFrontend emits CU1 with embedded parameter, e.g. "CU1(1)".
                # The parameter is already in cmd['params']; we just need to
                # strip the suffix to get the bare gate name for dispatch.
                qubits = op.get('qubits') or (
                    [op['qubit']] if op.get('qubit') is not None else []
                )
                params = op.get('params', [])
                log.debug(
                    f"[{self.node.name}] GATE cu1 "
                    f"qubits={qubits} params={params}"
                )
                yield from self._apply_gate_by_name('cu1', qubits, params)

            elif op_name == 'entanglement_gen':
                ent_label = op.get('entanglement_label')
                buffer_key = op.get('target_start_label', ent_label)

                self.send_start_ready(ent_label)

                bsm_label = None
                while True:
                    yield self.await_port_input(self.clk_port)
                    tick_msg = self.clk_port.rx_input()
                    tick_item = tick_msg.items[0]
                    recv_start_label = tick_item.get('start_label')
                    if recv_start_label == ent_label:
                        bsm_label = tick_item.get('bsm_label')
                        log.debug(
                            f"[{self.node.name}] entanglement_gen: "
                            f"clock tick for ent_label={ent_label}, "
                            f"bsm_label={bsm_label}"
                        )
                        break
                    else:
                        log.debug(
                            f"[{self.node.name}] entanglement_gen: "
                            f"ignoring tick, waiting for ent_label={ent_label}"
                        )

                worker = self._get_or_create_bsm_worker(bsm_label)
                worker.add_work(buffer_key, op)
                log.debug(
                    f"[{self.node.name}] entanglement_gen: "
                    f"submitted label={ent_label} (buffer_key={buffer_key}) "
                    f"to worker (bsm={bsm_label})"
                )

                while buffer_key not in self.bell_pair_buffer:
                    yield self.await_signal(
                        worker, EntanglementWorkerProtocol.ENTANGLEMENT_DONE
                    )

                log.debug(
                    f"[{self.node.name}] entanglement_gen completed: "
                    f"label={ent_label}, buffer_key={buffer_key}, "
                    f"success={self.bell_pair_buffer[buffer_key]['success']}"
                )

            else:
                raise ValueError(f"[{self.node.name}] Unknown op: {op_name!r}")

        EXECUTION_END_TIME = ns.sim_time()
        EXECUTION_DURATION = EXECUTION_END_TIME - EXECUTION_START_TIME
        if EXECUTION_DURATION > MAX_EXECUTION_TIME:
            MAX_EXECUTION_TIME = EXECUTION_DURATION

        for bsm_label, worker in list(self._bsm_workers.items()):
            if worker.is_running:
                worker.stop()
        self._bsm_workers.clear()
        self.bell_pair_buffer.clear()

        self.send_done()
        log.debug(
            f"[{self.node.name}] --- EXECUTION END TIME: {EXECUTION_END_TIME} ---"
        )
        log.debug(
            f"[{self.node.name}] --- EXECUTION DURATION: {EXECUTION_DURATION} ---"
        )
        log.debug(
            f"[{self.node.name}] --- MAX EXECUTION TIME: {MAX_EXECUTION_TIME} ---"
        )
        log.debug(f"[{self.node.name}] Execution completed at time {ns.sim_time()}")
        log.debug(f"[{self.node.name}] All commands executed")

        self.send_signal(Signals.SUCCESS)
