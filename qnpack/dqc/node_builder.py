"""
node_builder.py
---------------
QPU and BSM node construction utilities for the DQC simulation.

Classes
-------
    SafeDepolarNoiseModel       — DepolarNoiseModel wrapper that skips lost qubits
    CustomEmissionNoiseModel    — Models noise/loss during photon emission
    QPUNodeBuilder              — Builds QPU nodes from topology JSON

Functions
---------
    create_gated_bsm_nodes          — Create n generic BSM nodes
    create_bsm_nodes_from_topology  — Create BSM nodes from topology JSON
"""

import os
import logging
import random
from netsquid.components import QuantumProcessor
from netsquid.components.models.qerrormodels import (
    DepolarNoiseModel,
    T1T2NoiseModel,
    QuantumErrorModel,
)
from netsquid.nodes import Node
from netsquid.components.clock import Clock
from netsquid.qubits import qubitapi as qapi
from netsquid.components.qprocessor import PhysicalInstruction
from netsquid.components.instructions import (
    IInit,
    INSTR_H,
    INSTR_CNOT,
    INSTR_X,
    INSTR_Z,
    INSTR_S,
    INSTR_MEASURE,
    INSTR_MEASURE_X,
    INSTR_CROT_Z,
    INSTR_ROT_Z,
    INSTR_ROT_X,
    INSTR_ROT_Y,
    INSTR_EMIT,
    INSTR_TOFFOLI,
    INSTR_CCX,
)
from qnpack.common.logging import setup_logging
from qnpack.common.config import Config
from qnpack.oneG.lib.operators import create_meas_ops
from qnpack.oneG.lib.models import BSMGatedQuantumDetector


log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Noise models
# ---------------------------------------------------------------------------

class SafeDepolarNoiseModel(QuantumErrorModel):
    """DepolarNoiseModel wrapper that skips qubits whose qstate is None.

    NetSquid's built-in :class:`DepolarNoiseModel` crashes with an
    ``AttributeError`` when applied (via ``quantum_noise_model``) to a
    qubit that has already been lost (e.g. by collection-efficiency loss
    in :class:`CustomEmissionNoiseModel`).  This wrapper guards against
    that by checking ``qubit.qstate`` before delegating.

    Parameters
    ----------
    depolar_rate : float
        Depolarization probability (if *time_independent*) or rate in Hz.
    time_independent : bool
        If True, *depolar_rate* is a fixed probability per qubit.
    """

    def __init__(self, depolar_rate, time_independent=False, **kwargs):
        super().__init__(**kwargs)
        self._inner = DepolarNoiseModel(
            depolar_rate=depolar_rate,
            time_independent=time_independent,
        )

    def error_operation(self, qubits, delta_time=0, **kwargs):
        for q in qubits:
            if q is not None and q.qstate is not None:
                self._inner.error_operation([q], delta_time=delta_time, **kwargs)


class CustomEmissionNoiseModel(QuantumErrorModel):
    """Models noise and loss of the emission of an (entangled) photon.

    Parameters
    ----------
    emission_fidelity : float in [0.25, 1]
        If the emitted qubit is in the Phi+ Bell state with some other qubit,
        the noise model will turn it into a Werner state with fidelity
        ``emission_fidelity`` to the Phi+ Bell state.
    collection_efficiency : float in [0, 1]
        Probability that the qubit is not lost during emission.

    Notes
    -----
    Noise model must be assigned as ``qout_noise_model`` to a quantum memory,
    since it uses the ``pop()`` method.

    Designed primarily for use with ``INSTR_EMIT``.

    ``qapi.depolarize`` is used for noise.  The depolarization probability is
    related to ``emission_fidelity`` by ``P = 4 / 3 * (1 - F)``.
    """

    def __init__(self, emission_fidelity, collection_efficiency, **kwargs):
        super().__init__(**kwargs)
        self.fidelity = emission_fidelity
        self.collection_efficiency = collection_efficiency

    def error_operation(self, qubits, delta_time=0, **properties):
        if random.random() > self.collection_efficiency:
            if len(qubits[0].qstate.qubits) > 1:
                qapi.discard(qubits[0].qstate.qubits[1])

        if qubits[0] is not None and qubits[0].qstate is not None:
            depol_prob = 4 / 3 * (1 - self.fidelity)
            qapi.depolarize(qubits[0], depol_prob)


# ---------------------------------------------------------------------------
# QPU node builder
# ---------------------------------------------------------------------------

class QPUNodeBuilder:
    """Utility class for generating QPU nodes from topology JSON.

    Each node has a single QPU (QuantumProcessor) with both quantum and
    classical ports for communication.

    Parameters
    ----------
    n : int
        Number of QPU nodes.
    num_qubits : int
        Default number of qubits per QPU (overridden by topology).
    qpu_name_prefix : str
        Prefix for QPU node names.
    T1, T2 : float
        Memory coherence times (ns).  Defaults are effectively infinite.
    depolar_rate : float
        Global depolarization rate (legacy; prefer two_q/one_q_depolar_prob).
    two_q_depolar_prob : float
        Depolarization probability for 2-qubit gates.
    one_q_depolar_prob : float
        Depolarization probability for 1-qubit gates.
    emission_fidelity : float
        Fidelity of photon emission.
    collection_efficiency : float
        Probability that an emitted photon is collected.
    one_q_gate_duration : float
        Duration of 1-qubit gates (ns).
    two_q_gate_duration : float
        Duration of 2-qubit gates (ns).
    fiber_depolar_rate : float
        Depolarization rate in the fiber channel.
    """

    def __init__(
        self,
        n: int,
        num_qubits: int = 3,
        qpu_name_prefix: str = "QPU",
        T1: float = 1e15,
        T2: float = 1e15,
        depolar_rate: float = 0,
        two_q_depolar_prob: float = 0,
        one_q_depolar_prob: float = 0,
        emission_fidelity: float = 1.0,
        collection_efficiency: float = 1.0,
        one_q_gate_duration: float = 5000,
        two_q_gate_duration: float = 107000,
        fiber_depolar_rate: float = 400,
    ):
        self.n = n
        self.num_qubits = num_qubits
        self.qpu_name_prefix = qpu_name_prefix
        self.T1 = T1
        self.T2 = T2
        self.depolar_rate = depolar_rate
        self.two_q_depolar_prob = two_q_depolar_prob
        self.one_q_depolar_prob = one_q_depolar_prob
        self.emission_fidelity = emission_fidelity
        self.collection_efficiency = collection_efficiency
        self.one_q_gate_duration = one_q_gate_duration
        self.two_q_gate_duration = two_q_gate_duration
        self.fiber_depolar_rate = fiber_depolar_rate

    def _create_physical_instructions(self):
        """Define physical instructions available to all QPUs."""
        # Import here to avoid circular dependency with protocols/qpu.py
        from .protocols.qpu import DQC_EMIT

        _1q_noise = (
            DepolarNoiseModel(self.one_q_depolar_prob, time_independent=True)
            if self.one_q_depolar_prob
            else None
        )
        _2q_noise = (
            DepolarNoiseModel(self.two_q_depolar_prob, time_independent=True)
            if self.two_q_depolar_prob
            else None
        )

        phys_instr = [
            PhysicalInstruction(IInit(), duration=0, parallel=True),
            # --- 1-qubit gates ---
            PhysicalInstruction(INSTR_H,     duration=self.one_q_gate_duration, parallel=False, topology=None, q_noise_model=_1q_noise),
            PhysicalInstruction(INSTR_X,     duration=self.one_q_gate_duration, parallel=False, topology=None, q_noise_model=_1q_noise),
            PhysicalInstruction(INSTR_Z,     duration=self.one_q_gate_duration, parallel=False, topology=None, q_noise_model=_1q_noise),
            PhysicalInstruction(INSTR_S,     duration=self.one_q_gate_duration, parallel=False, topology=None, q_noise_model=_1q_noise),
            PhysicalInstruction(INSTR_ROT_Z, duration=self.one_q_gate_duration, parallel=False, topology=None, q_noise_model=_1q_noise),
            PhysicalInstruction(INSTR_ROT_X, duration=self.one_q_gate_duration, parallel=False, topology=None, q_noise_model=_1q_noise),
            PhysicalInstruction(INSTR_ROT_Y, duration=self.one_q_gate_duration, parallel=False, topology=None, q_noise_model=_1q_noise),
            # --- 2-qubit gates ---
            PhysicalInstruction(INSTR_CNOT,    duration=self.two_q_gate_duration, parallel=False, topology=None, q_noise_model=_2q_noise),
            PhysicalInstruction(INSTR_CROT_Z,  duration=self.two_q_gate_duration, parallel=False, topology=None, q_noise_model=_2q_noise),
            # --- 3-qubit gates ---
            PhysicalInstruction(INSTR_TOFFOLI, duration=self.two_q_gate_duration, parallel=False, topology=None, q_noise_model=_2q_noise),
            PhysicalInstruction(INSTR_CCX,     duration=self.two_q_gate_duration, parallel=False, topology=None, q_noise_model=_2q_noise),
            PhysicalInstruction(INSTR_EMIT,    duration=0, parallel=False, topology=None),
            PhysicalInstruction(
                DQC_EMIT,
                duration=0,
                parallel=False,
                topology=None,
                q_noise_model=CustomEmissionNoiseModel(
                    emission_fidelity=self.emission_fidelity,
                    collection_efficiency=self.collection_efficiency,
                ),
            ),
            # --- Measurement (no gate noise) ---
            PhysicalInstruction(INSTR_MEASURE,   duration=0, parallel=False, topology=None),
            PhysicalInstruction(INSTR_MEASURE_X, duration=0, parallel=False, topology=None),
        ]
        return phys_instr

    def _create_qpu(self, name: str, num_positions: int = None):
        """Create a single QPU with basic gate set and noise models."""
        mem_noise = T1T2NoiseModel(T1=self.T1, T2=self.T2)
        phys_instr = self._create_physical_instructions()
        n_pos = num_positions if num_positions is not None else self.num_qubits

        qpu = QuantumProcessor(
            name,
            num_positions=n_pos,
            mem_noise_models=[mem_noise] * n_pos,
            phys_instructions=phys_instr,
        )
        return qpu

    def create_nodes_from_topology(self, topology_data):
        """Create QPU nodes based on topology JSON data.

        Parses the topology to determine:
        - Which QPU nodes exist (type == "QNode")
        - What qubits each QPU has (communication vs data)
        - What classical connections exist between QPUs
        - What quantum/BSM result/clock connections exist to BSM nodes

        Parameters
        ----------
        topology_data : list
            The parsed topology JSON (list with one element containing
            nodes/edges).

        Returns
        -------
        tuple
            ``(qpu_nodes, qpu_info)`` where ``qpu_info`` maps QPU label to
            qubit/connection info.
        """
        topo = topology_data[0]
        all_nodes = topo["nodes"]

        # Identify QPU nodes (QNode type) and sort by label for consistent ordering
        qpu_node_data = sorted(
            [n for n in all_nodes if n["systemSettings"]["type"] == "QNode"],
            key=lambda n: n["id"],
        )

        # Build a label→index mapping first so we can reference other QPUs
        label_to_idx = {}
        for idx, qpu_data in enumerate(qpu_node_data, start=1):
            label_to_idx[qpu_data["id"]] = idx

        qpu_info = {}
        qpu_nodes = []

        for idx, qpu_data in enumerate(qpu_node_data, start=1):
            label = qpu_data["id"]  # e.g., "LBNL-A"

            # Parse qubit settings: ID:1 -> qubit 0, ID:2 -> qubit 1, etc.
            qubits = []
            for q in qpu_data["qubitSettings"]["qubits"]:
                qubit_id = int(q["ID"])
                qubit_type = q["type"]  # "communication" or "data"
                local_index = qubit_id - 1
                qubits.append({
                    "id": qubit_id,
                    "type": qubit_type,
                    "local_index": local_index,
                })

            # Parse channels to find all connections
            classical_neighbors = {}
            bsm_quantum_out = []
            bsm_result_in = []
            bsm_clk_in = []

            for ch in qpu_data["channels"]:
                ch_type = ch["type"]
                ch_dir = ch["direction"]
                neighbor_ref = ch["neighbor"]["systemRef"]
                neighbor_type = ch["neighbor"].get("type", "")
                length = ch.get("length", {}).get("value", 1) if "length" in ch else 1

                if ch_type == "classic_clk" and neighbor_type != "BSMNode":
                    if neighbor_ref not in classical_neighbors:
                        classical_neighbors[neighbor_ref] = {"length": length}
                    if ch_dir == "out":
                        classical_neighbors[neighbor_ref]["out_ch"] = ch["ID"]
                    else:
                        classical_neighbors[neighbor_ref]["in_ch"] = ch["ID"]

                elif ch_type == "quantum" and ch_dir == "out":
                    bsm_quantum_out.append({
                        "bsm_node": neighbor_ref,
                        "channel_id": ch["ID"],
                        "bsm_channel_ref": ch["neighbor"]["channelRef"],
                        "length": length,
                    })

                elif ch_type == "classic_bsm_result" and ch_dir == "in":
                    bsm_result_in.append({
                        "bsm_node": neighbor_ref,
                        "channel_id": ch["ID"],
                        "bsm_channel_ref": ch["neighbor"]["channelRef"],
                        "length": length,
                    })

                elif ch_type == "classic_clk" and ch_dir == "in" and neighbor_type == "BSMNode":
                    bsm_clk_in.append({
                        "bsm_node": neighbor_ref,
                        "channel_id": ch["ID"],
                        "bsm_channel_ref": ch["neighbor"]["channelRef"],
                        "length": length,
                    })

            qpu_info[label] = {
                "qpu_id": idx,
                "label": label,
                "qubits": qubits,
                "num_qubits": len(qubits),
                "classical_neighbors": classical_neighbors,
                "bsm_quantum_out": bsm_quantum_out,
                "bsm_result_in": bsm_result_in,
                "bsm_clk_in": bsm_clk_in,
            }

            # Build port names for this QPU node
            port_names = ["ctrl_port", "clk_port", "comm_port"]

            for neighbor_label in classical_neighbors:
                if neighbor_label in label_to_idx:
                    other_idx = label_to_idx[neighbor_label]
                    port_names.append(f"c_to_{other_idx}")
                    port_names.append(f"c_from_{other_idx}")

            for bsm_conn in bsm_quantum_out:
                bsm_name = bsm_conn["bsm_node"]
                port_names.append(f"q_to_{bsm_name}")

            for bsm_res in bsm_result_in:
                bsm_name = bsm_res["bsm_node"]
                port_names.append(f"bsm_res_from_{bsm_name}")

            for bsm_clk in bsm_clk_in:
                bsm_name = bsm_clk["bsm_node"]
                port_names.append(f"clk_from_{bsm_name}")

            # Remove duplicates while preserving order
            seen = set()
            unique_ports = []
            for p in port_names:
                if p not in seen:
                    seen.add(p)
                    unique_ports.append(p)

            node_name = f"QPU_{idx}"
            node = Node(node_name, port_names=unique_ports)

            qpu = self._create_qpu(f"{node_name}_proc", num_positions=len(qubits))
            node.add_subcomponent(qpu, name="QPU")
            qpu_nodes.append(node)

            log.debug(
                f"Created QPU node {node_name} ({label}) with {len(qubits)} qubits "
                f"({[q['type'] for q in qubits]}), ports: {unique_ports}"
            )

        return qpu_nodes, qpu_info

    @staticmethod
    def forward_qmemory_output(node, qmem_out_port: str, dest_qpu_id: int):
        q_port_name = f"q_to_{dest_qpu_id}"
        if q_port_name not in node.ports:
            raise ValueError(f"{node.name} has no quantum port '{q_port_name}'")
        node.qmemory.ports[qmem_out_port].forward_output(node.ports[q_port_name])


# ---------------------------------------------------------------------------
# BSM node factories
# ---------------------------------------------------------------------------

def create_gated_bsm_nodes(
    n: int,
    detection_window: int = 4320000,
    system_delay: int = 0,
    coupling_efficiency: float = 1,
):
    """Create *n* generic BSM nodes with gated quantum detectors.

    Each node has:
    - Two quantum input ports (left / right QPU)
    - Clock and BSM result output ports to QPUs
    - Controller / clock / comm ports

    Parameters
    ----------
    n : int
        Number of BSM nodes to create.
    detection_window : int
        Detector gate window (ns).
    system_delay : int
        System delay (ns).
    coupling_efficiency : float
        Detector coupling efficiency.

    Returns
    -------
    list[Node]
    """
    bsm_nodes = []
    for i in range(1, n + 1):
        node_name = f"BSM_Node{i}"
        port_names = [
            f"{node_name}_left_port",
            f"{node_name}_right_port",
            "clk_to_left",
            "clk_to_right",
            "BSM_res_to_left",
            "BSM_res_to_right",
            "ctrl_port",
            "clk_port",
            "comm_port",
        ]
        node = Node(node_name, port_names=port_names)

        clk = Clock(f"{node_name}_CLK", frequency=1000000, max_ticks=-1)
        node.add_subcomponent(clk)

        bsm_detector = BSMGatedQuantumDetector(
            f"{node_name}_Detector",
            detection_window=detection_window,
            system_delay=system_delay,
            meas_operators=create_meas_ops(),
            num_input_ports=2,
            num_output_ports=2,
            coupling_efficiency=coupling_efficiency,
            error_on_fail=False,
        )
        node.add_subcomponent(bsm_detector)

        node.ports[port_names[0]].forward_input(bsm_detector.ports["qin0"])
        node.ports[port_names[1]].forward_input(bsm_detector.ports["qin1"])

        bsm_nodes.append(node)

    return bsm_nodes


def create_bsm_nodes_from_topology(
    topology_data,
    detection_window: int = 4320000,
    system_delay: int = 0,
    coupling_efficiency: float = 1,
):
    """Create BSM nodes based on topology JSON data.

    Parses the topology to find BSMNode entries and creates gated BSM nodes
    with appropriate port names and wiring.

    Channel mapping from JSON:
    - quantum IN channel ID 1  → left_port  (left QPU)
    - quantum IN channel ID 2  → right_port (right QPU)
    - classic_bsm_result OUT channel ID 3 → BSM_res_to_left
    - classic_bsm_result OUT channel ID 4 → BSM_res_to_right
    - classic_clk OUT channel ID 5        → clk_to_left
    - classic_clk OUT channel ID 6        → clk_to_right

    Parameters
    ----------
    topology_data : list
        The parsed topology JSON.
    detection_window : int
        Detector gate window (ns).
    system_delay : int
        System delay (ns).
    coupling_efficiency : float
        Detector coupling efficiency.

    Returns
    -------
    tuple
        ``(bsm_nodes, bsm_info)`` where ``bsm_info`` maps BSM label to
        connection info.
    """
    topo = topology_data[0]
    all_nodes = topo["nodes"]

    bsm_node_data = sorted(
        [n for n in all_nodes if n["systemSettings"]["type"] == "BSMNode"],
        key=lambda n: n["id"],
    )

    bsm_nodes = []
    bsm_info = {}

    for idx, bsm_data in enumerate(bsm_node_data, start=1):
        label = bsm_data["id"]
        node_name = f"BSM_Node{idx}"

        left_qpu = None
        right_qpu = None
        result_left = None
        result_right = None
        clk_left = None
        clk_right = None
        channel_lengths = {}

        for ch in bsm_data["channels"]:
            ch_type = ch["type"]
            ch_id = ch["ID"]
            ch_dir = ch["direction"]
            neighbor_ref = ch["neighbor"]["systemRef"]
            length = ch.get("length", {}).get("value", 1) if "length" in ch else 1

            if ch_type == "quantum" and ch_dir == "in":
                if ch_id == "1":
                    left_qpu = neighbor_ref
                    channel_lengths["q_left"] = length
                elif ch_id == "2":
                    right_qpu = neighbor_ref
                    channel_lengths["q_right"] = length

            elif ch_type == "classic_bsm_result" and ch_dir == "out":
                if ch_id == "3":
                    result_left = {"target": neighbor_ref, "length": length}
                elif ch_id == "4":
                    result_right = {"target": neighbor_ref, "length": length}

            elif ch_type == "classic_clk" and ch_dir == "out":
                if ch_id == "5":
                    clk_left = {"target": neighbor_ref, "length": length}
                elif ch_id == "6":
                    clk_right = {"target": neighbor_ref, "length": length}

        bsm_info[label] = {
            "bsm_id": idx,
            "label": label,
            "node_name": node_name,
            "left_qpu": left_qpu,
            "right_qpu": right_qpu,
            "result_left": result_left,
            "result_right": result_right,
            "clk_left": clk_left,
            "clk_right": clk_right,
            "channel_lengths": channel_lengths,
        }

        port_names = [
            f"{node_name}_left_port",
            f"{node_name}_right_port",
            "clk_to_left",
            "clk_to_right",
            "BSM_res_to_left",
            "BSM_res_to_right",
            "ctrl_port",
            "clk_port",
            "comm_port",
        ]
        node = Node(node_name, port_names=port_names)

        clk = Clock(f"{node_name}_CLK", frequency=1000000, max_ticks=-1)
        node.add_subcomponent(clk)

        bsm_detector = BSMGatedQuantumDetector(
            f"{node_name}_Detector",
            detection_window=detection_window,
            system_delay=system_delay,
            meas_operators=create_meas_ops(),
            num_input_ports=2,
            num_output_ports=2,
            coupling_efficiency=coupling_efficiency,
            error_on_fail=False,
        )
        node.add_subcomponent(bsm_detector)

        node.ports[f"{node_name}_left_port"].forward_input(bsm_detector.ports["qin0"])
        node.ports[f"{node_name}_right_port"].forward_input(bsm_detector.ports["qin1"])

        bsm_nodes.append(node)

        log.debug(
            f"Created BSM node {node_name} ({label}): left={left_qpu}, right={right_qpu}, "
            f"result_left={result_left}, result_right={result_right}, "
            f"clk_left={clk_left}, clk_right={clk_right}"
        )

    return bsm_nodes, bsm_info
