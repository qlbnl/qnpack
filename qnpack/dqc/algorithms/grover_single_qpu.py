"""
Grover's Algorithm — Single-QPU execution via NetSquid.

This file parses the Grover QASM circuit (N=16, target |1011⟩) using pytket,
extracts the gate commands, builds a single QPU node with INSTR_CCX (Toffoli)
support, sends all commands to that QPU, and runs the simulation.

This is a standalone test file — the original distributed implementation in
dqc_protocols.py / sim.py is left untouched.
"""

import os
import re
import sys
import math
import json
import logging
from collections import Counter

import netsquid as ns
import pydynaa as pd
import matplotlib.pyplot as plt
from netsquid.qubits.qformalism import QFormalism
from netsquid.nodes import Node, Network
from netsquid.components import QuantumProcessor
from netsquid.components.qprocessor import PhysicalInstruction
from netsquid.components.instructions import (
    IInit, INSTR_INIT, INSTR_H, INSTR_X, INSTR_Z, INSTR_CNOT,
    INSTR_MEASURE, INSTR_MEASURE_X, INSTR_ROT_Z, INSTR_CROT_Z,
    INSTR_CCX, INSTR_EMIT,
)
from netsquid.components.models.qerrormodels import DepolarNoiseModel
from netsquid.components.cchannel import ClassicalChannel
from netsquid.components.clock import Clock
from netsquid.components.component import Message
from netsquid.protocols.nodeprotocols import NodeProtocol, LocalProtocol
from netsquid.protocols.protocol import Signals
from netsquid.qubits import qubitapi as qapi
from netsquid.util.datacollector import DataCollector

from pytket.qasm import circuit_from_qasm_str
from pytket import Circuit, OpType

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1.  QASM string for Grover's Algorithm  (N=16, target |1011⟩)
# ---------------------------------------------------------------------------
GROVER_QASM = """
OPENQASM 2.0;
include "qelib1.inc";

qreg q[5];
creg m[4];

// Initialization
h q[0]; h q[1]; h q[2]; h q[3];

// Grover Iteration 1
// Oracle for |1011> (q0=1, q1=0, q2=1, q3=1)
x q[1];
h q[3];
ccx q[0], q[1], q[4];
ccx q[4], q[2], q[3];
ccx q[0], q[1], q[4];
h q[3];
x q[1];

// Diffusion operator
h q[0]; h q[1]; h q[2]; h q[3];
x q[0]; x q[1]; x q[2]; x q[3];
h q[3];
ccx q[0], q[1], q[4];
ccx q[4], q[2], q[3];
ccx q[0], q[1], q[4];
h q[3];
x q[0]; x q[1]; x q[2]; x q[3];
h q[0]; h q[1]; h q[2]; h q[3];

// Grover Iteration 2
x q[1];
h q[3];
ccx q[0], q[1], q[4];
ccx q[4], q[2], q[3];
ccx q[0], q[1], q[4];
h q[3];
x q[1];

h q[0]; h q[1]; h q[2]; h q[3];
x q[0]; x q[1]; x q[2]; x q[3];
h q[3];
ccx q[0], q[1], q[4];
ccx q[4], q[2], q[3];
ccx q[0], q[1], q[4];
h q[3];
x q[0]; x q[1]; x q[2]; x q[3];
h q[0]; h q[1]; h q[2]; h q[3];

// Grover Iteration 3
x q[1];
h q[3];
ccx q[0], q[1], q[4];
ccx q[4], q[2], q[3];
ccx q[0], q[1], q[4];
h q[3];
x q[1];

h q[0]; h q[1]; h q[2]; h q[3];
x q[0]; x q[1]; x q[2]; x q[3];
h q[3];
ccx q[0], q[1], q[4];
ccx q[4], q[2], q[3];
ccx q[0], q[1], q[4];
h q[3];
x q[0]; x q[1]; x q[2]; x q[3];
h q[0]; h q[1]; h q[2]; h q[3];

// Measurement
measure q[0] -> m[0];
measure q[1] -> m[1];
measure q[2] -> m[2];
measure q[3] -> m[3];
"""

# ---------------------------------------------------------------------------
# 2.  Parse QASM → list of command dicts for a single QPU
# ---------------------------------------------------------------------------

def parse_qasm_to_commands(qasm_str):
    """Parse a QASM string via pytket and return a flat list of command dicts.

    Each dict has:
        op   : str   – gate name (H, X, CCX, Measure, …)
        qubits: list – qubit indices (0-based)
        params: list – gate parameters (floats), empty for most gates

    All qubits are mapped directly by their register index (q[i] → i).
    """
    circ = circuit_from_qasm_str(qasm_str)
    commands = []
    for cmd in circ.get_commands():
        # Determine operation name
        if hasattr(cmd.op, 'get_name'):
            op_name = cmd.op.get_name()
        else:
            op_name = cmd.op.type.name

        # Map pytket qubit objects to integer indices
        qubit_indices = [q.index[0] for q in cmd.qubits]

        # Extract parameters
        params = list(cmd.op.params) if hasattr(cmd.op, 'params') and cmd.op.params else []

        commands.append({
            'op': op_name,
            'qubits': qubit_indices,
            'params': params,
        })

    log.info(f"Parsed {len(commands)} commands from QASM circuit")
    return commands


# ---------------------------------------------------------------------------
# 3.  Build a single QPU node with INSTR_CCX support
# ---------------------------------------------------------------------------

def create_single_qpu_node(num_qubits=5, depolar_rate=0.0):
    """Create a single QPU node with H, X, Z, CNOT, CCX, Measure, Rz gates.

    Parameters
    ----------
    num_qubits : int
        Number of qubit positions in the quantum processor.
    depolar_rate : float
        Depolarisation noise rate (0 = noiseless).

    Returns
    -------
    Node
        A NetSquid node named ``QPU_1`` with a ``QuantumProcessor``
        subcomponent named ``QPU``.
    """
    depolar_model = DepolarNoiseModel(depolar_rate=depolar_rate) if depolar_rate > 0 else None

    phys_instructions = [
        PhysicalInstruction(IInit(), duration=0, parallel=True),
        PhysicalInstruction(INSTR_H, duration=0, parallel=False),
        PhysicalInstruction(INSTR_X, duration=0, parallel=False),
        PhysicalInstruction(INSTR_Z, duration=0, parallel=False),
        PhysicalInstruction(INSTR_CNOT, duration=0, parallel=False),
        PhysicalInstruction(INSTR_CCX, duration=0, parallel=False),
        PhysicalInstruction(INSTR_MEASURE, duration=0, parallel=False,
                            quantum_noise_model=depolar_model),
        PhysicalInstruction(INSTR_MEASURE_X, duration=0, parallel=False,
                            quantum_noise_model=depolar_model),
        PhysicalInstruction(INSTR_ROT_Z, duration=0, parallel=False),
        PhysicalInstruction(INSTR_CROT_Z, duration=0, parallel=False),
        PhysicalInstruction(INSTR_EMIT, duration=0, parallel=False),
    ]

    qpu = QuantumProcessor(
        "QPU_1_proc",
        num_positions=num_qubits,
        phys_instructions=phys_instructions,
    )

    port_names = ["ctrl_port", "clk_port", "comm_port"]
    node = Node("QPU_1", port_names=port_names)
    node.add_subcomponent(qpu, name="QPU")

    log.info(f"Created single QPU node with {num_qubits} qubits and INSTR_CCX support")
    return node


# ---------------------------------------------------------------------------
# 4.  Controller protocol — sends commands to the single QPU
# ---------------------------------------------------------------------------

class SingleQPUControllerProtocol(NodeProtocol):
    """Controller that sends all circuit commands to a single QPU and waits
    for it to finish."""

    def __init__(self, node, commands, name=None):
        super().__init__(node, name=name or "SingleQPUController")
        self.commands = commands
        self.clk = self.node.subcomponents["CtrlCLK"]

    def run(self):
        log.info(f"[{self.node.name}] Controller starting at t={ns.sim_time()}")

        # Send all commands to QPU_1
        port_name = "ctrl1_port"
        if port_name in self.node.ports:
            msg = Message(items={'commands': self.commands, 'qpu_id': 1})
            self.node.ports[port_name].tx_output(msg)
            log.info(f"[{self.node.name}] Sent {len(self.commands)} commands to QPU_1")
        else:
            log.error(f"[{self.node.name}] Port {port_name} not found")
            return

        # Wait for QPU to signal done
        comm_port = self.node.ports["comm1_port"]
        yield self.await_port_input(comm_port)
        msg = comm_port.rx_input()
        if msg is not None:
            item = msg.items[0]
            log.info(f"[{self.node.name}] QPU_1 finished: {item.get('type')}")

        log.info(f"[{self.node.name}] Execution completed at t={ns.sim_time()}")
        self.send_signal(Signals.SUCCESS)


# ---------------------------------------------------------------------------
# 5.  QPU protocol — executes gate commands locally
# ---------------------------------------------------------------------------

class SingleQPUProtocol(NodeProtocol):
    """Protocol running on a single QPU node.  Receives commands from the
    controller and executes them sequentially — no distribution, no
    entanglement, no sync points."""

    def __init__(self, node, qpu_id=1, name=None):
        super().__init__(node, name=name or "SingleQPUProtocol")
        self.qpu_id = qpu_id
        self.ctrl_port = self.node.ports["ctrl_port"]
        self.comm_port = self.node.ports["comm_port"]

    # ---- gate execution ----

    def execute_gate(self, cmd):
        """Execute a single gate command on the QPU's quantum memory."""
        op = cmd['op']
        qubits = cmd['qubits']
        params = cmd.get('params', [])

        log.debug(f"[{self.node.name}] {op} qubits={qubits} params={params}")

        if op == 'H':
            self.node.qmemory.execute_instruction(INSTR_H, qubit_mapping=[qubits[0]])
            yield self.await_program(self.node.qmemory)

        elif op == 'X':
            self.node.qmemory.execute_instruction(INSTR_X, qubit_mapping=[qubits[0]])
            yield self.await_program(self.node.qmemory)

        elif op == 'Z':
            self.node.qmemory.execute_instruction(INSTR_Z, qubit_mapping=[qubits[0]])
            yield self.await_program(self.node.qmemory)

        elif op == 'Rz':
            angle_rad = float(params[0]) * math.pi
            self.node.qmemory.execute_instruction(
                INSTR_ROT_Z, qubit_mapping=[qubits[0]], angle=angle_rad)
            yield self.await_program(self.node.qmemory)

        elif op == 'CNOT' or op == 'CX':
            self.node.qmemory.execute_instruction(
                INSTR_CNOT, qubit_mapping=[qubits[0], qubits[1]])
            yield self.await_program(self.node.qmemory)

        elif op == 'CCX':
            self.node.qmemory.execute_instruction(
                INSTR_CCX, qubit_mapping=[qubits[0], qubits[1], qubits[2]])
            yield self.await_program(self.node.qmemory)

        elif op == 'Measure' or op == 'MEASURE':
            self.node.qmemory.execute_instruction(
                INSTR_MEASURE, qubit_mapping=[qubits[0]])
            yield self.await_program(self.node.qmemory)

        else:
            log.warning(f"[{self.node.name}] Unknown gate: {op}")

    # ---- main protocol loop ----

    def run(self):
        log.info(f"[{self.node.name}] QPU protocol started, waiting for commands…")

        # Wait for commands from controller
        yield self.await_port_input(self.ctrl_port)
        msg = self.ctrl_port.rx_input()
        item = msg.items[0]
        commands = item.get('commands', [])
        log.info(f"[{self.node.name}] Received {len(commands)} commands")

        # Initialise all qubits
        self.node.qmemory.execute_instruction(IInit())
        yield self.await_program(self.node.qmemory)
        log.info(f"[{self.node.name}] All qubits initialised")

        # Execute every command sequentially
        for i, cmd in enumerate(commands):
            yield from self.execute_gate(cmd)

        # Signal done
        done_msg = Message(items={'type': 'done', 'qpu_id': self.qpu_id})
        self.comm_port.tx_output(done_msg)
        log.info(f"[{self.node.name}] All {len(commands)} commands executed "
                 f"at t={ns.sim_time()}")
        self.send_signal(Signals.SUCCESS)


# ---------------------------------------------------------------------------
# 6.  Top-level protocol
# ---------------------------------------------------------------------------

class GroverSingleQPUProtocol(LocalProtocol):
    """Orchestrates the controller + single QPU sub-protocols."""

    def __init__(self, network, ctrl_node, qpu_node, commands):
        super().__init__(nodes=network.nodes)
        self.ctrl_node = ctrl_node
        self.qpu_node = qpu_node

        ctrl_proto = SingleQPUControllerProtocol(
            ctrl_node, commands, name="ControllerProtocol")
        self.add_subprotocol(ctrl_proto)

        qpu_proto = SingleQPUProtocol(
            qpu_node, qpu_id=1, name="QPUProtocol_1")
        self.add_subprotocol(qpu_proto)

    def run(self):
        self.start_subprotocols()


# ---------------------------------------------------------------------------
# 7.  Network builder
# ---------------------------------------------------------------------------

def build_single_qpu_network(num_qubits=5):
    """Build a minimal network: one controller + one QPU node.

    Returns
    -------
    tuple
        (network, ctrl_node, qpu_node)
    """
    net = Network("grover-single-qpu")

    # QPU node
    qpu_node = create_single_qpu_node(num_qubits=num_qubits)
    net.add_node(qpu_node)

    # Controller node
    ctrl_port_names = ["ctrl1_port", "comm1_port", "clk1_port"]
    ctrl = Node("Controller", port_names=ctrl_port_names)
    clk = Clock("CtrlCLK", frequency=1_000_000, max_ticks=-1)
    ctrl.add_subcomponent(clk)
    net.add_node(ctrl)

    # Classical channels: Controller ↔ QPU
    ctrl_ch = ClassicalChannel("cch_ctrl_to_qpu", length=1)
    net.add_connection(
        ctrl, qpu_node,
        channel_to=ctrl_ch,
        port_name_node1="ctrl1_port",
        port_name_node2="ctrl_port",
        label="ctrl_to_qpu",
    )

    comm_ch = ClassicalChannel("cch_qpu_to_ctrl", length=1)
    net.add_connection(
        qpu_node, ctrl,
        channel_to=comm_ch,
        port_name_node1="comm_port",
        port_name_node2="comm1_port",
        label="comm_qpu_to_ctrl",
    )

    log.info("Built single-QPU network: Controller + QPU_1")
    return net, ctrl, qpu_node


# ---------------------------------------------------------------------------
# 8.  Run simulation
# ---------------------------------------------------------------------------

def run_grover_single_qpu(num_runs=100):
    """Parse the Grover QASM, build a single-QPU network, and run the
    circuit ``num_runs`` times.  Prints a measurement histogram.

    The 4 data qubits are q[0]–q[3]; q[4] is the ancilla.
    We measure q[0]–q[3] after the protocol completes.
    """
    ns.set_qstate_formalism(QFormalism.KET)

    # Parse QASM → command list
    commands = parse_qasm_to_commands(GROVER_QASM)

    # Print parsed commands for inspection
    print(f"\n{'='*60}")
    print(f"Grover's Algorithm — Single QPU Test")
    print(f"{'='*60}")
    print(f"Total commands: {len(commands)}")
    gate_counts = Counter(c['op'] for c in commands)
    for gate, count in sorted(gate_counts.items()):
        print(f"  {gate}: {count}")
    print(f"{'='*60}\n")

    # Qubit positions to measure (data qubits 0–3)
    measure_positions = [0, 1, 2, 3]

    results = []
    for run_idx in range(num_runs):
        ns.sim_reset()
        ns.set_random_state(seed=run_idx)

        # Build network
        net, ctrl, qpu_node = build_single_qpu_network(num_qubits=5)

        # Create and start protocol
        protocol = GroverSingleQPUProtocol(net, ctrl, qpu_node, commands)

        # Data collector — measure data qubits when controller signals SUCCESS
        def collect_measurements(evexpr):
            row = {}
            for pos in measure_positions:
                q, = qpu_node.qmemory.peek(positions=[pos])
                m, _ = ns.qubits.measure(q)
                row[f"q{pos}"] = m
            return row

        dc = DataCollector(collect_measurements, include_entity_name=False)
        dc.collect_on(pd.EventExpression(
            source=protocol.subprotocols["ControllerProtocol"],
            event_type=Signals.SUCCESS.value,
        ))

        protocol.start()
        ns.sim_run()

        # Collect result
        if len(dc.dataframe) > 0:
            row = dc.dataframe.iloc[-1].to_dict()
            row["run"] = run_idx
            results.append(row)
        else:
            row = {"run": run_idx}
            for pos in measure_positions:
                row[f"q{pos}"] = None
            results.append(row)

    # ---- Print results ----
    col_names = [f"q{p}" for p in measure_positions]
    header = f"{'Run':>4}" + "".join(f"  {c:>6}" for c in col_names)
    print("\n" + "=" * len(header))
    print(f"MEASUREMENT RESULTS  ({num_runs} runs)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for r in results:
        vals = f"{r['run']:>4}"
        for c in col_names:
            v = r.get(c)
            vals += f"  {int(v) if v is not None else 'N/A':>6}"
        print(vals)
    print("=" * len(header))

    # ---- Histogram ----
    bitstrings = []
    for r in results:
        bits = "".join(
            str(int(r[c])) if r.get(c) is not None else "?"
            for c in col_names
        )
        bitstrings.append(bits)

    counts = Counter(bitstrings)
    labels = sorted(counts.keys())
    values = [counts[l] for l in labels]

    print(f"\nBitstring histogram:")
    for label, val in sorted(counts.items(), key=lambda x: -x[1]):
        bar = "█" * val
        print(f"  |{label}⟩  {val:>4}  {bar}")

    # Target state check
    target = "1101"  # q0=1, q1=1, q2=0, q3=1  (|1011⟩ in big-endian → 1101 in q0q1q2q3)
    target_count = counts.get(target, 0)
    print(f"\nTarget |1011⟩ (q0q1q2q3 = {target}): {target_count}/{num_runs} "
          f"({100*target_count/num_runs:.1f}%)")

    # Plot
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(labels, values, color="steelblue", edgecolor="black")
    ax.set_xlabel("Measurement outcome (q0 q1 q2 q3)")
    ax.set_ylabel("Count")
    ax.set_title(f"Grover's Algorithm — Single QPU ({num_runs} runs)\n"
                 f"Target: |1011⟩")
    ax.yaxis.get_major_locator().set_params(integer=True)
    for i, v in enumerate(values):
        ax.text(i, v + 0.3, str(v), ha="center", fontweight="bold", fontsize=8)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    hist_path = os.path.join(os.path.dirname(__file__),
                             "grover_single_qpu_histogram.png")
    plt.savefig(hist_path, dpi=150)
    print(f"\nHistogram saved to {hist_path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 9.  Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    num_runs = 100
    if len(sys.argv) > 1:
        num_runs = int(sys.argv[1])
    run_grover_single_qpu(num_runs=num_runs)
