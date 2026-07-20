import json
import os
import re
import warnings
import logging
import netsquid as ns
import pydynaa as pd
import pandas
import matplotlib.pyplot as plt

from netsquid.components.models.delaymodels import FibreDelayModel
from netsquid.nodes import Node, Network
from netsquid.components.qchannel import QuantumChannel
from netsquid.components.cchannel import ClassicalChannel
from netsquid.protocols import Signals
from netsquid.util.datacollector import DataCollector
from netsquid.components.models.qerrormodels import FibreLossModel
from netsquid.qubits.qformalism import QFormalism
from netsquid.components.clock import Clock

from qnpack.dqc.protocols import DQCProtocol
from qnpack.dqc.models.node_builder import QPUNodeBuilder, create_bsm_nodes_from_topology, SafeDepolarNoiseModel
from qnpack.dqc.frontends import load_frontend
from qnpack.common.logging import setup_logging
from qnpack.common.constants import Constants
from qnpack.common.simulation import Simulation
from qnpack.dqc.models.switch_node_builder import (
    create_switch_nodes,
    build_switch_connections,
    print_network_connections,
)

log = logging.getLogger(__name__)


def _resolve_measure_qubits(circuit_cfg):
    """Parse measure_qubits from config, or return None to auto-derive.

    Only meaningful for ``mode='tket'``; all other modes derive
    ``measure_qubits`` from the circuit itself (via the frontend).

    Parameters
    ----------
    circuit_cfg : Munch or None
        The ``circuit:`` block from parameters.yml.

    Returns
    -------
    dict or None
    """
    import ast
    mode = getattr(circuit_cfg, 'mode', 'tket') if circuit_cfg else 'tket'
    if mode != 'tket':
        return None

    raw = getattr(circuit_cfg, 'measure_qubits', None) if circuit_cfg else None
    if raw is None:
        log.info("circuit.measure_qubits not set — will auto-derive from topology")
        return None

    try:
        return {int(k): list(v) for k, v in ast.literal_eval(str(raw)).items()}
    except (ValueError, SyntaxError) as e:
        log.warning(
            f"Could not parse circuit.measure_qubits={raw!r}: {e}. "
            f"Will auto-derive from topology."
        )
        return None


def _auto_derive_measure_qubits(qpu_info):
    """Derive measure_qubits from topology when the frontend doesn't provide one.

    Parameters
    ----------
    qpu_info : dict
        As returned by ``setup_network_from_topology``.

    Returns
    -------
    collections.OrderedDict
        ``{qpu_id: [local_qubit_index, …]}`` for all data qubits, sorted by
        QPU id and qubit index.
    """
    from collections import OrderedDict
    measure_qubits = OrderedDict()
    sorted_info = sorted(qpu_info.values(), key=lambda x: x["qpu_id"])
    for info in sorted_info:
        qid = info["qpu_id"]
        data_positions = sorted(
            q["local_index"] for q in info["qubits"] if q["type"] == "data"
        )
        if data_positions:
            measure_qubits[qid] = data_positions
    log.info(f"Auto-derived measure_qubits from topology: {dict(measure_qubits)}")
    return measure_qubits


class DQCSimulation(Simulation):
    def __init__(self, logfile=None, base_dir=None, topology_file=None,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.base_dir = base_dir
        self._topology_file = topology_file

        setup_logging(name=__name__,
                      level=logging.DEBUG if self.cfg.sim.debug else logging.INFO,
                      logfile=logfile)
        log.debug(f"Configuration:\n{self.cfg}")

    def finalize(self):
        pass

    def load_topology(self, topology_file=None):
        """Load topology from a local JSON file.

        Parameters
        ----------
        topology_file : str or None
            Path to the topology JSON file.  Falls back to the value
            passed at construction time, then to
            ``topology/topology_v2.json``.  Relative paths are resolved
            against ``self.base_dir`` when set.

        Returns
        -------
        list
            Parsed topology data.
        """
        if topology_file is None:
            topology_file = self._topology_file or "topology/topology_v2.json"

        if self.base_dir is not None and not os.path.isabs(topology_file):
            topology_file = os.path.join(self.base_dir, topology_file)

        with open(topology_file, "r") as f:
            data = json.load(f)

        log.debug(f"Loaded topology from {topology_file}")
        log.debug(
            f"Topology: {data[0]['num_nodes']} nodes, "
            f"{data[0]['num_channels']} channels"
        )
        return data

    def setup_network_from_topology(self, topology_data):
        """Build the entire network from topology JSON data.

        Creates:
        1. QPU nodes with ports based on topology connections
        2. BSM nodes with gated quantum detectors
        3. Controller node with per-QPU ports
        4. All channels: quantum (QPU→BSM), classical QPU↔QPU,
           BSM result (BSM→QPU), clock (BSM→QPU), controller↔QPU

        When the topology specifies ``num_bsms``, a
        ``FullMeshOpticalSwitch`` and ``ClassicalSwitch`` are created and
        wired in place of the direct QPU↔BSM quantum/classical channels.
        The switch components are stored on the returned network as
        ``net.q_switch`` and ``net.c_switch``.

        Parameters
        ----------
        topology_data : list
            Parsed topology JSON.

        Returns
        -------
        tuple
            (net, qpu_nodes, bsm_nodes, ctrl, qpu_info, bsm_info)
        """
        net = Network("dqc-net")

        # --- Channel parameters ---
        q_lightspeed      = getattr(self.cfg.channel, 'q_lightspeed',      200000)
        c_lightspeed      = getattr(self.cfg.channel, 'c_lightspeed',      200000)
        photon_loss       = getattr(self.cfg.channel, 'photon_loss',       0)
        init_photon_loss  = getattr(self.cfg.channel, 'init_photon_loss',  0)
        fiber_depolar_rate = getattr(self.cfg.channel, 'fiber_depolar_rate', 0)
        time_independent  = getattr(self.cfg.channel, 'time_independent',  False)

        # --- Create QPU nodes from topology ---
        builder = QPUNodeBuilder(
            n=self.cfg.qpu.num_qpu_nodes,
            num_qubits=self.cfg.qpu.qubits,
            T1=float(getattr(self.cfg.memory, 'T1', 1e15)),
            T2=float(getattr(self.cfg.memory, 'T2', 1e15)),
            two_q_depolar_prob=getattr(self.cfg.qpu, 'two_q_depolar_prob', 0),
            one_q_depolar_prob=getattr(self.cfg.qpu, 'one_q_depolar_prob', 0),
            emission_fidelity=getattr(self.cfg.qpu, 'emission_fidelity', 1.0),
            collection_efficiency=getattr(self.cfg.qpu, 'collection_efficiency', 1.0),
            one_q_gate_duration=getattr(self.cfg.gate_durations, 'one_q_gate_duration', 5000),
            two_q_gate_duration=getattr(self.cfg.gate_durations, 'two_q_gate_duration', 107000),
            fiber_depolar_rate=fiber_depolar_rate,
        )
        qpu_nodes, qpu_info = builder.create_nodes_from_topology(topology_data)
        for node in qpu_nodes:
            net.add_node(node)

        # Build label→node mapping for QPUs
        label_to_qpu_node = {
            label: qpu_nodes[info["qpu_id"] - 1]
            for label, info in qpu_info.items()
        }

        # --- Create BSM nodes from topology ---
        bsm_nodes, bsm_info = create_bsm_nodes_from_topology(
            topology_data,
            detection_window=getattr(self.cfg.bsm, 'detection_window', 4320000),
            system_delay=getattr(self.cfg.bsm, 'system_delay', 0),
            coupling_efficiency=getattr(self.cfg.bsm, 'coupling_efficiency', 1),
        )
        for node in bsm_nodes:
            net.add_node(node)

        # Build label→node mapping for BSM nodes
        label_to_bsm_node = {
            label: bsm_nodes[info["bsm_id"] - 1]
            for label, info in bsm_info.items()
        }

        # --- Detect switch mode: use switches when there are multiple BSM nodes ---
        num_bsm_nodes = len(bsm_nodes)
        use_switch = num_bsm_nodes > 1
        if use_switch:
            log.info(
                f"Switch mode enabled: {num_bsm_nodes} BSM nodes detected. "
                f"Using FullMeshOpticalSwitch + ClassicalSwitch."
            )

        # --- Create controller node ---
        num_qpu_nodes = len(qpu_nodes)
        ctrl_port_names = []
        for i in range(1, num_qpu_nodes + 1):
            ctrl_port_names += [f"clk{i}_port", f"ctrl{i}_port", f"comm{i}_port"]
        for i in range(1, num_bsm_nodes + 1):
            ctrl_port_names += [f"clk_bsm{i}_port", f"ctrl_bsm{i}_port", f"comm_bsm{i}_port"]

        ctrl = Node("Central Controller", port_names=ctrl_port_names)
        net.add_node(ctrl)
        clk = Clock("CtrlCLK", self.cfg.clock.HZ, max_ticks=self.cfg.clock.max_ticks)
        ctrl.add_subcomponent(clk)

        # --- Debug: print node ports ---
        for node in net.nodes.values():
            log.debug(f"{node.name} Ports: {list(node.ports.keys())}")
        log.debug("")

        # --- Controller ↔ QPU channels ---
        for i, qpu_node in enumerate(qpu_nodes, start=1):
            net.add_connection(
                ctrl, qpu_node,
                channel_to=ClassicalChannel(f"cch_clk_ctrl_to_{qpu_node.name}", length=0.01),
                port_name_node1=f"clk{i}_port",
                port_name_node2="clk_port",
                label=f"clk_{qpu_node.name}",
            )
            log.debug(f"Clock: {ctrl.name}.clk{i}_port -> {qpu_node.name}.clk_port")

            net.add_connection(
                ctrl, qpu_node,
                channel_to=ClassicalChannel(f"cch_ctrl_ctrl_to_{qpu_node.name}", length=0.01),
                port_name_node1=f"ctrl{i}_port",
                port_name_node2="ctrl_port",
                label=f"ctrl_{qpu_node.name}",
            )
            log.debug(f"Control: {ctrl.name}.ctrl{i}_port -> {qpu_node.name}.ctrl_port")

            net.add_connection(
                qpu_node, ctrl,
                channel_to=ClassicalChannel(f"cch_comm_{qpu_node.name}_to_ctrl", length=0.01),
                port_name_node1="comm_port",
                port_name_node2=f"comm{i}_port",
                label=f"comm_{qpu_node.name}",
            )
            log.debug(f"Comm: {qpu_node.name}.comm_port -> {ctrl.name}.comm{i}_port")

        # --- Controller ↔ BSM channels ---
        for i, bsm_node in enumerate(bsm_nodes, start=1):
            net.add_connection(
                ctrl, bsm_node,
                channel_to=ClassicalChannel(f"cch_clk_ctrl_to_{bsm_node.name}", length=0.01),
                port_name_node1=f"clk_bsm{i}_port",
                port_name_node2="clk_port",
                label=f"clk_{bsm_node.name}",
            )
            log.debug(f"Clock: {ctrl.name}.clk_bsm{i}_port -> {bsm_node.name}.clk_port")

            net.add_connection(
                ctrl, bsm_node,
                channel_to=ClassicalChannel(f"cch_ctrl_ctrl_to_{bsm_node.name}", length=0.01),
                port_name_node1=f"ctrl_bsm{i}_port",
                port_name_node2="ctrl_port",
                label=f"ctrl_{bsm_node.name}",
            )
            log.debug(f"Control: {ctrl.name}.ctrl_bsm{i}_port -> {bsm_node.name}.ctrl_port")

            net.add_connection(
                bsm_node, ctrl,
                channel_to=ClassicalChannel(f"cch_comm_{bsm_node.name}_to_ctrl", length=0.01),
                port_name_node1="comm_port",
                port_name_node2=f"comm_bsm{i}_port",
                label=f"comm_{bsm_node.name}",
            )
            log.debug(f"Comm: {bsm_node.name}.comm_port -> {ctrl.name}.comm_bsm{i}_port")

        # --- Classical channels between QPUs ---
        connected_classical = set()
        for label, info in qpu_info.items():
            qpu_node = label_to_qpu_node[label]
            qpu_id   = info["qpu_id"]
            for neighbor_label, conn_info in info["classical_neighbors"].items():
                if neighbor_label not in qpu_info:
                    continue
                neighbor_node = label_to_qpu_node[neighbor_label]
                neighbor_id   = qpu_info[neighbor_label]["qpu_id"]
                conn_key = (label, neighbor_label)
                if conn_key not in connected_classical:
                    length   = conn_info.get("length", 1)
                    c_to     = f"c_to_{neighbor_id}"
                    c_from   = f"c_from_{qpu_id}"
                    net.add_connection(
                        qpu_node, neighbor_node,
                        channel_to=ClassicalChannel(
                            name=f"cch_{qpu_node.name}_to_{neighbor_node.name}",
                            length=0.01,
                        ),
                        port_name_node1=c_to,
                        port_name_node2=c_from,
                        label=f"classical_{qpu_node.name}_to_{neighbor_node.name}",
                    )
                    connected_classical.add(conn_key)
                    log.debug(
                        f"Classical: {qpu_node.name}.{c_to} -> "
                        f"{neighbor_node.name}.{c_from} (length={length} km)"
                    )

        # --- Quantum channels: QPU → BSM (direct or via switch) ---
        def _make_qch_models():
            """Build models dict for a quantum channel from current cfg."""
            delay  = FibreDelayModel(c=q_lightspeed * 1000)
            loss   = FibreLossModel(p_loss_init=init_photon_loss, p_loss_length=photon_loss) \
                     if (photon_loss or init_photon_loss) else None
            noise  = SafeDepolarNoiseModel(depolar_rate=fiber_depolar_rate,
                                           time_independent=time_independent) \
                     if fiber_depolar_rate else None
            m = {"delay_model": delay}
            if loss:
                m["quantum_loss_model"] = loss
            if noise:
                m["quantum_noise_model"] = noise
            return m

        if use_switch:
            # --- Switch mode: create switch nodes and wire connections ---
            quantum_switch_node, classical_switch_node, q_switch, c_switch = create_switch_nodes(
                qpu_nodes=qpu_nodes,
                qpu_info=qpu_info,
                bsm_nodes=bsm_nodes,
                bsm_info=bsm_info,
            )
            net.add_node(quantum_switch_node)
            net.add_node(classical_switch_node)
            build_switch_connections(
                net=net,
                quantum_switch_node=quantum_switch_node,
                classical_switch_node=classical_switch_node,
                qpu_nodes=qpu_nodes,
                qpu_info=qpu_info,
                bsm_nodes=bsm_nodes,
                bsm_info=bsm_info,
                q_lightspeed=q_lightspeed,
                c_lightspeed=c_lightspeed,
                photon_loss=photon_loss,
                init_photon_loss=init_photon_loss,
                fiber_depolar_rate=fiber_depolar_rate,
                time_independent=time_independent,
            )
            # Store switch components on the network for DQCProtocol to access
            net.q_switch = q_switch
            net.c_switch = c_switch
            net.quantum_switch_node = quantum_switch_node
            net.classical_switch_node = classical_switch_node
            log.info("Switch network wiring complete")
        else:
            # --- Direct mode: QPU → BSM quantum channels ---
            net.q_switch = None
            net.c_switch = None

            for bsm_label, bsm_inf in bsm_info.items():
                bsm_node      = label_to_bsm_node[bsm_label]
                bsm_node_name = bsm_inf["node_name"]

                left_label  = bsm_inf["left_qpu"]
                right_label = bsm_inf["right_qpu"]

                if left_label and left_label in label_to_qpu_node:
                    left_node = label_to_qpu_node[left_label]
                    length    = bsm_inf["channel_lengths"].get("q_left", 1)
                    net.add_connection(
                        left_node, bsm_node,
                        channel_to=QuantumChannel(
                            name=f"qch_{left_node.name}_to_{bsm_node.name}",
                            length=0.01,
                            models=_make_qch_models(),
                        ),
                        port_name_node1=f"q_to_{bsm_label}",
                        port_name_node2=f"{bsm_node_name}_left_port",
                        label=f"quantum_{left_node.name}_to_{bsm_node.name}_left",
                    )
                    log.debug(
                        f"Quantum: {left_node.name}.q_to_{bsm_label} -> "
                        f"{bsm_node.name}.{bsm_node_name}_left_port (length={length} km)"
                    )

                if right_label and right_label in label_to_qpu_node:
                    right_node = label_to_qpu_node[right_label]
                    length     = bsm_inf["channel_lengths"].get("q_right", 1)
                    net.add_connection(
                        right_node, bsm_node,
                        channel_to=QuantumChannel(
                            name=f"qch_{right_node.name}_to_{bsm_node.name}",
                            length=0.01,
                            models=_make_qch_models(),
                        ),
                        port_name_node1=f"q_to_{bsm_label}",
                        port_name_node2=f"{bsm_node_name}_right_port",
                        label=f"quantum_{right_node.name}_to_{bsm_node.name}_right",
                    )
                    log.debug(
                        f"Quantum: {right_node.name}.q_to_{bsm_label} -> "
                        f"{bsm_node.name}.{bsm_node_name}_right_port (length={length} km)"
                    )

            # --- BSM result channels: BSM → QPU ---
            c_delay_models = {"delay_model": FibreDelayModel(c=c_lightspeed * 1000)}

            for bsm_label, bsm_inf in bsm_info.items():
                bsm_node = label_to_bsm_node[bsm_label]

                if bsm_inf["result_left"]:
                    target_label = bsm_inf["result_left"]["target"]
                    length       = bsm_inf["result_left"]["length"]
                    if target_label in label_to_qpu_node:
                        target_node = label_to_qpu_node[target_label]
                        net.add_connection(
                            bsm_node, target_node,
                            channel_to=ClassicalChannel(
                                name=f"cch_bsm_res_{bsm_node.name}_to_{target_node.name}",
                                length=0.01,
                                models=c_delay_models,
                            ),
                            port_name_node1="BSM_res_to_left",
                            port_name_node2=f"bsm_res_from_{bsm_label}",
                            label=f"bsm_result_{bsm_node.name}_to_{target_node.name}",
                        )
                        log.debug(
                            f"BSM Result: {bsm_node.name}.BSM_res_to_left -> "
                            f"{target_node.name}.bsm_res_from_{bsm_label} (length={length} km)"
                        )

                if bsm_inf["result_right"]:
                    target_label = bsm_inf["result_right"]["target"]
                    length       = bsm_inf["result_right"]["length"]
                    if target_label in label_to_qpu_node:
                        target_node = label_to_qpu_node[target_label]
                        net.add_connection(
                            bsm_node, target_node,
                            channel_to=ClassicalChannel(
                                name=f"cch_bsm_res_{bsm_node.name}_to_{target_node.name}_right",
                                length=0.01,
                                models=c_delay_models,
                            ),
                            port_name_node1="BSM_res_to_right",
                            port_name_node2=f"bsm_res_from_{bsm_label}",
                            label=f"bsm_result_{bsm_node.name}_to_{target_node.name}_right",
                        )
                        log.debug(
                            f"BSM Result: {bsm_node.name}.BSM_res_to_right -> "
                            f"{target_node.name}.bsm_res_from_{bsm_label} (length={length} km)"
                        )

            # --- BSM clock channels: BSM → QPU ---
            for bsm_label, bsm_inf in bsm_info.items():
                bsm_node = label_to_bsm_node[bsm_label]

                if bsm_inf["clk_left"]:
                    target_label = bsm_inf["clk_left"]["target"]
                    length       = bsm_inf["clk_left"]["length"]
                    if target_label in label_to_qpu_node:
                        target_node = label_to_qpu_node[target_label]
                        net.add_connection(
                            bsm_node, target_node,
                            channel_to=ClassicalChannel(
                                name=f"cch_bsm_clk_{bsm_node.name}_to_{target_node.name}",
                                length=0.01,
                                models=c_delay_models,
                            ),
                            port_name_node1="clk_to_left",
                            port_name_node2=f"clk_from_{bsm_label}",
                            label=f"bsm_clk_{bsm_node.name}_to_{target_node.name}",
                        )
                        log.debug(
                            f"BSM Clock: {bsm_node.name}.clk_to_left -> "
                            f"{target_node.name}.clk_from_{bsm_label} (length={length} km)"
                        )

                if bsm_inf["clk_right"]:
                    target_label = bsm_inf["clk_right"]["target"]
                    length       = bsm_inf["clk_right"]["length"]
                    if target_label in label_to_qpu_node:
                        target_node = label_to_qpu_node[target_label]
                        net.add_connection(
                            bsm_node, target_node,
                            channel_to=ClassicalChannel(
                                name=f"cch_bsm_clk_{bsm_node.name}_to_{target_node.name}_right",
                                length=0.01,
                                models=c_delay_models,
                            ),
                            port_name_node1="clk_to_right",
                            port_name_node2=f"clk_from_{bsm_label}",
                            label=f"bsm_clk_{bsm_node.name}_to_{target_node.name}_right",
                        )
                        log.debug(
                            f"BSM Clock: {bsm_node.name}.clk_to_right -> "
                            f"{target_node.name}.clk_from_{bsm_label} (length={length} km)"
                        )

        # --- Print full connection summary (always, for debugging) ---
        # print_network_connections(
        #     net=net,
        #     qpu_nodes=qpu_nodes,
        #     qpu_info=qpu_info,
        #     bsm_nodes=bsm_nodes,
        #     bsm_info=bsm_info,
        #     ctrl_node=ctrl,
        #     quantum_switch_node=getattr(net, 'quantum_switch_node', None),
        #     classical_switch_node=getattr(net, 'classical_switch_node', None),
        #     q_switch=getattr(net, 'q_switch', None),
        #     c_switch=getattr(net, 'c_switch', None),
        #     use_switch=use_switch,
        # )

        return net, qpu_nodes, bsm_nodes, ctrl, qpu_info, bsm_info

    def setup_datacollector(self, qpu_nodes, measure_qubits, protocol):
        """Setup a DataCollector that measures data qubits from selected QPU
        nodes when the ControllerProtocol signals SUCCESS.

        Parameters
        ----------
        qpu_nodes : list of Node
            All QPU nodes (0-indexed; QPU_1 is ``qpu_nodes[0]``).
        measure_qubits : dict
            Mapping of 1-based QPU ID → list of qubit positions to measure.
            Example: ``{1: [2, 3], 2: [1]}``
        protocol : DQCProtocol
            The top-level protocol whose ControllerProtocol emits
            ``Signals.SUCCESS``.

        Returns
        -------
        DataCollector
        """
        targets = [
            (qid, qpu_nodes[qid - 1], pos)
            for qid, positions in measure_qubits.items()
            for pos in positions
        ]

        def collect_measurements(evexpr):
            row = {}
            for qid, node, pos in targets:
                q, = node.qmemory.peek(pos)
                m, _ = ns.qubits.measure(q)
                col = f"QPU_{qid}_q{pos}"
                row[col] = m
                log.debug(f"DataCollector: {node.name} qubit {pos} = {m}")
            return row

        dc = DataCollector(collect_measurements, include_entity_name=False)
        dc.collect_on(pd.EventExpression(
            source=protocol,
            event_type=Signals.SUCCESS.value,
        ))
        return dc

    def _run_single_config(self, num_runs, measure_qubits, frontend, topology_data):
        """Run num_runs simulations for the current cfg noise settings.

        Parameters
        ----------
        num_runs : int
        measure_qubits : dict or None
            If ``None`` and the frontend does not provide one, it is
            auto-derived from topology on the first run.
        frontend : BaseFrontend
            The loaded frontend instance.
        topology_data : list
            As returned by ``load_topology()``.

        Returns
        -------
        tuple
            ``(results, col_names, num_output_bits, output_reg_name)``
        """
        results = []

        for run_idx in range(num_runs):
            ns.sim_reset()
            # ns.set_random_state()
            net, qpu_nodes, bsm_nodes, ctrl, qpu_info, bsm_info = \
                self.setup_network_from_topology(topology_data)

            if run_idx == 0:
                log.debug("=== Network Summary ===")
                log.debug(f"QPU Nodes: {len(qpu_nodes)}")
                for label, info in qpu_info.items():
                    qubit_types = [
                        f"q{q['local_index']}={q['type']}" for q in info['qubits']
                    ]
                    log.debug(f"  {label} (QPU_{info['qpu_id']}): {', '.join(qubit_types)}")
                log.debug(f"BSM Nodes: {len(bsm_nodes)}")
                for label, info in bsm_info.items():
                    log.debug(
                        f"  {label} ({info['node_name']}): "
                        f"left={info['left_qpu']}, right={info['right_qpu']}"
                    )
                log.debug(f"Controller: {ctrl.name}")
                log.debug("=" * 40)

                if measure_qubits is None:
                    measure_qubits = _auto_derive_measure_qubits(qpu_info)

            protocol = DQCProtocol(
                self.cfg, network=net, qpu_nodes=qpu_nodes,
                controller_node=ctrl, qpu_info=qpu_info,
                bsm_info=bsm_info, bsm_nodes=bsm_nodes,
                run_idx=run_idx, frontend=frontend,
                q_switch=getattr(net, 'q_switch', None),
                switch_node=getattr(net, 'quantum_switch_node', None),
            )

            sim_start_time = ns.sim_time()
            log.info(f"--- Run {run_idx}: SIMULATION START TIME: {sim_start_time} ns ---")

            if frontend.needs_datacollector:
                dc = self.setup_datacollector(
                    qpu_nodes, measure_qubits=measure_qubits, protocol=protocol
                )

            protocol.start()
            ns.sim_run()

            col_names = frontend.get_col_names(measure_qubits)

            if frontend.needs_datacollector:
                if len(dc.dataframe) > 0:
                    row = dc.dataframe.iloc[-1].to_dict()
                else:
                    row = {c: None for c in col_names}
            else:
                row = frontend.get_result_row(protocol, run_idx, col_names, qpu_nodes)

            row["run"] = run_idx
            results.append(row)

            bitstring = frontend.get_bitstring(row, col_names)
            bit_vals  = "  ".join(f"{c}={row.get(c, '?')}" for c in col_names)
            log.info(f"--- Run {run_idx}: {bit_vals}  =>  bitstring={bitstring} ---")

            sim_end_time     = ns.sim_time()
            sim_duration_ns  = sim_end_time - sim_start_time
            sim_duration_s   = sim_duration_ns / 1e9
            log.info(f"--- Run {run_idx}: SIMULATION END TIME: {sim_end_time} ns ---")
            log.info(
                f"--- Run {run_idx}: SIMULATION DURATION: "
                f"{sim_duration_ns} ns ({sim_duration_s:.6f} s) ---"
            )

            results[-1]["sim_duration_s"] = sim_duration_s
            if (hasattr(protocol, 'global_entanglement_durations')
                    and protocol.global_entanglement_durations):
                results[-1]["entanglement_durations"] = \
                    protocol.global_entanglement_durations.copy()

            protocol.stop()

        num_output_bits = getattr(frontend, 'num_output_bits', len(col_names))
        output_reg_name = getattr(frontend, 'output_reg_name', 'm')

        # Print summary table
        header = f"{'Run':>4}" + "".join(f"  {c:>12}" for c in col_names)
        log.info("=" * len(header))
        log.info(f"MEASUREMENT RESULTS ({len(col_names)} data qubits)")
        log.info("=" * len(header))
        log.info(header)
        log.info("-" * len(header))
        for r in results:
            vals = f"{r['run']:>4}"
            for c in col_names:
                v = r.get(c)
                vals += f"  {int(v) if v is not None else 'N/A':>12}"
            log.info(vals)
        log.info("=" * len(header))

        return results, col_names, num_output_bits, output_reg_name

    def plot(self, final_data, filename="12q_1qpu_2qnoise1000.png"):
        """Plot combined noiseless vs noisy bitstring histograms.

        Parameters
        ----------
        final_data : list of dict
            Each dict has keys: 'noise_label', 'two_q_prob', 'one_q_prob',
            'counts' (Counter), 'col_names', 'num_runs'.
        filename : str
            Output filename (saved in results/ directory).
        """
        n_configs = len(final_data)
        fig, axes = plt.subplots(
            1, n_configs, figsize=(max(8, n_configs * 7), 5), squeeze=False
        )
        axes = axes[0]
        os.makedirs(self.output_dir, exist_ok=True)

        for ax, entry in zip(axes, final_data):
            counts      = entry['counts']
            noise_label = entry['noise_label']
            num_runs    = entry['num_runs']
            two_q       = entry['two_q_prob']
            one_q       = entry['one_q_prob']

            labels = sorted(counts.keys())
            values = [counts[lbl] for lbl in labels]
            bar_color = "steelblue" if (two_q == 0 and one_q == 0) else "tomato"

            ax.bar(labels, values, color=bar_color, edgecolor="black")
            ax.set_xlabel("Measurement outcome", fontsize=9)
            ax.set_ylabel("Count")
            ax.set_title(f"{noise_label}\n({num_runs} runs)", fontsize=10)
            ax.yaxis.get_major_locator().set_params(integer=True)
            ax.tick_params(axis='x', rotation=90, labelsize=7)
            for i, v in enumerate(values):
                ax.text(i, v + 0.1, str(v), ha="center", fontsize=7, fontweight="bold")

        plt.suptitle(
            "DQC Measurement Distribution: Noiseless vs Noisy", fontsize=12, y=1.02
        )
        plt.tight_layout()
        hist_path = os.path.join(results_dir, filename)
        plt.savefig(hist_path, dpi=150, bbox_inches="tight")
        log.info(f"Combined histogram saved to {hist_path}")
        plt.close(fig)

    def start(self, num_runs=10):
        """Run the DQC simulation, sweeping over all varying_params combinations.

        Parameter resolution priority (highest → lowest):
          1. ``varying_params``  — list of values to sweep
          2. ``fixed_params``    — single scalar override
          3. ``cfg`` (parameters.yml) — default from config file

        Parameters
        ----------
        num_runs : int
            Number of independent simulation runs per parameter combination.
        """
        import itertools
        from collections import Counter

        ns.set_qstate_formalism(QFormalism.KET)

        circuit_cfg = getattr(self.cfg, 'circuit', None)

        # --- Load frontend ---
        frontend, source = load_frontend(circuit_cfg, base_dir=self.base_dir)
        log.info(f"Frontend loaded: mode={circuit_cfg.mode!r}, source={source}")
        measure_qubits = _resolve_measure_qubits(circuit_cfg)

        topology_data = self.load_topology()

        # --- Build parameter sweep lists ---
        _qpu_cfg     = getattr(self.cfg, 'qpu',            None)
        _memory_cfg  = getattr(self.cfg, 'memory',         None)
        _gate_cfg    = getattr(self.cfg, 'gate_durations', None)
        _channel_cfg = getattr(self.cfg, 'channel',        None)

        def _sweep_list(param_name, module_cfg, cfg_default=0):
            if param_name in self.varying_params:
                return self.varying_params[param_name]
            if param_name in self.fixed_params:
                return [self.fixed_params[param_name]]
            return [getattr(module_cfg, param_name, cfg_default) or cfg_default]

        two_q_sweep       = _sweep_list('two_q_depolar_prob',    _qpu_cfg,     0)
        one_q_sweep       = _sweep_list('one_q_depolar_prob',    _qpu_cfg,     0)
        ef_sweep          = _sweep_list('emission_fidelity',     _qpu_cfg,     1.0)
        ce_sweep          = _sweep_list('collection_efficiency', _qpu_cfg,     1.0)
        T1_sweep          = _sweep_list('T1',                    _memory_cfg,  1e15)
        T2_sweep          = _sweep_list('T2',                    _memory_cfg,  1e15)
        one_q_dur_sweep   = _sweep_list('one_q_gate_duration',   _gate_cfg,    0)
        two_q_dur_sweep   = _sweep_list('two_q_gate_duration',   _gate_cfg,    0)
        photon_loss_sweep = _sweep_list('photon_loss',           _channel_cfg, 0)
        init_loss_sweep   = _sweep_list('init_photon_loss',      _channel_cfg, 0)
        fiber_depol_sweep = _sweep_list('fiber_depolar_rate',    _channel_cfg, 0)

        param_names  = [
            'two_q_depolar_prob', 'one_q_depolar_prob',
            'emission_fidelity',  'collection_efficiency',
            'T1', 'T2',
            'one_q_gate_duration', 'two_q_gate_duration',
            'photon_loss', 'init_photon_loss', 'fiber_depolar_rate',
        ]
        param_sweeps = [
            two_q_sweep, one_q_sweep, ef_sweep, ce_sweep,
            T1_sweep, T2_sweep,
            one_q_dur_sweep, two_q_dur_sweep,
            photon_loss_sweep, init_loss_sweep, fiber_depol_sweep,
        ]

        all_combos = list(itertools.product(*param_sweeps))
        log.info(f"Running simulation with parameters: {dict(zip(param_names, param_sweeps))}")
        log.info(f"Fixed parameters: {self.fixed_params}")
        log.info(f"Total combinations: {len(all_combos)} × {num_runs} runs each")

        final_data = []

        for combo in all_combos:
            param_dict       = dict(zip(param_names, combo))
            two_q            = param_dict['two_q_depolar_prob']
            one_q            = param_dict['one_q_depolar_prob']
            emission_fidelity = param_dict['emission_fidelity']
            collection_eff   = param_dict['collection_efficiency']
            T1               = param_dict['T1']
            T2               = param_dict['T2']
            one_q_dur        = param_dict['one_q_gate_duration']
            two_q_dur        = param_dict['two_q_gate_duration']
            photon_loss      = param_dict['photon_loss']
            init_loss        = param_dict['init_photon_loss']
            fiber_depol      = param_dict['fiber_depolar_rate']

            # Apply to cfg so setup_network_from_topology picks them up
            self.cfg.qpu.two_q_depolar_prob            = two_q
            self.cfg.qpu.one_q_depolar_prob            = one_q
            self.cfg.qpu.emission_fidelity             = emission_fidelity
            self.cfg.qpu.collection_efficiency         = collection_eff
            self.cfg.memory.T1                         = T1
            self.cfg.memory.T2                         = T2
            self.cfg.gate_durations.one_q_gate_duration = one_q_dur
            self.cfg.gate_durations.two_q_gate_duration = two_q_dur
            self.cfg.channel.photon_loss               = photon_loss
            self.cfg.channel.init_photon_loss          = init_loss
            self.cfg.channel.fiber_depolar_rate        = fiber_depol

            # Build noise label
            noise_parts = []
            if two_q != 0 or one_q != 0:
                noise_parts.append(f"QPU(2q={two_q}, 1q={one_q})")
            if T1 != 600000000 or T2 != 60000000:
                noise_parts.append(f"Memory(T1={T1}ns, T2={T2}ns)")
            if emission_fidelity != 1.0:
                noise_parts.append(f"Emit(F={emission_fidelity})")
            if photon_loss != 0 or init_loss != 0:
                noise_parts.append(f"Channel(loss={photon_loss}, init={init_loss})")
            if fiber_depol != 400:
                noise_parts.append(f"Fiber(depol={fiber_depol})")
            if one_q_dur != 5000 or two_q_dur != 107000:
                noise_parts.append(f"Gates(1q={one_q_dur}ns, 2q={two_q_dur}ns)")
            noise_label = " | ".join(noise_parts) if noise_parts else "Noiseless"

            log.info(f"=== Config: {noise_label} ===")

            results, col_names, num_output_bits, output_reg_name = \
                self._run_single_config(
                    num_runs=num_runs,
                    measure_qubits=measure_qubits,
                    frontend=frontend,
                    topology_data=topology_data,
                )

            bitstrings = [
                "".join(
                    str(int(r[c])) if r.get(c) is not None else "?"
                    for c in col_names
                )
                for r in results
            ]
            counts = Counter(bitstrings)
            log.info(f"Bitstring counts: {dict(counts)}")
            top_5 = counts.most_common(5)
            log.info("Top 5 bitstrings:")
            for bitstring, count in top_5:
                log.info(f"  {bitstring}: {count}")

            final_data.append({
                'noise_label':        noise_label,
                'two_q_prob':         two_q,
                'one_q_prob':         one_q,
                'emission_fidelity':  emission_fidelity,
                'collection_efficiency': collection_eff,
                'T1':                 T1,
                'T2':                 T2,
                'one_q_gate_duration': one_q_dur,
                'two_q_gate_duration': two_q_dur,
                'photon_loss':        photon_loss,
                'init_photon_loss':   init_loss,
                'fiber_depolar_rate': fiber_depol,
                'counts':             counts,
                'col_names':          col_names,
                'num_runs':           num_runs,
                'num_output_bits':    num_output_bits,
                'results':            results,
                'top_5_bitstrings':   top_5,
            })

        # --- Save results to CSV ---
        os.makedirs(self.output_dir, exist_ok=True)
        csv_rows = []

        for entry in final_data:
            col_names   = entry['col_names']
            noise_label = entry['noise_label'].replace('\n', ' ')
            for r in entry['results']:
                bitstring = "".join(
                    str(int(r[c])) if r.get(c) is not None else "?"
                    for c in col_names
                )
                run_avg_ent = None
                if r.get('entanglement_durations'):
                    durs = list(r['entanglement_durations'].values())
                    run_avg_ent = sum(durs) / len(durs)
                row_dict = {
                    'noise_label':          noise_label,
                    'two_q_depolar_prob':   entry['two_q_prob'],
                    'one_q_depolar_prob':   entry['one_q_prob'],
                    'emission_fidelity':    entry['emission_fidelity'],
                    'collection_efficiency': entry['collection_efficiency'],
                    'T1':                   entry['T1'],
                    'T2':                   entry['T2'],
                    'one_q_gate_duration':  entry['one_q_gate_duration'],
                    'two_q_gate_duration':  entry['two_q_gate_duration'],
                    'photon_loss':          entry['photon_loss'],
                    'init_photon_loss':     entry['init_photon_loss'],
                    'fiber_depolar_rate':   entry['fiber_depolar_rate'],
                    'run':                  r.get('run', ''),
                    'bitstring':            bitstring,
                    'sim_duration_s':       r.get('sim_duration_s'),
                    'avg_entanglement_time_s': run_avg_ent,
                }
                for c in col_names:
                    row_dict[c] = r.get(c)
                csv_rows.append(row_dict)

        df = pandas.DataFrame(csv_rows)

        # Simulation duration statistics
        log.info("\n" + "=" * 80)
        log.info("SIMULATION TIME STATISTICS (per run)")
        log.info("=" * 80)
        if 'sim_duration_s' in df.columns:
            sim_durations = df['sim_duration_s'].dropna()
            if len(sim_durations) > 0:
                for idx, dur in enumerate(sim_durations):
                    log.info(f"  Run {idx:>3}: {dur:.6f} s")
                log.info(f"  ---")
                log.info(
                    f"  Total simulation time ({len(sim_durations)} runs): "
                    f"{sim_durations.sum():.6f} s"
                )
                log.info(
                    f"  Average simulation time per run: "
                    f"{sim_durations.mean():.6f} s"
                )
        log.info("=" * 80)

        # Entanglement statistics
        log.info("\n" + "=" * 80)
        log.info("SUCCESSFUL ENTANGLEMENT STATISTICS")
        log.info("=" * 80)

        all_entanglement_durations = {}
        for entry in final_data:
            for r in entry['results']:
                for ent_label, duration_s in r.get('entanglement_durations', {}).items():
                    all_entanglement_durations.setdefault(ent_label, []).append(duration_s)

        if all_entanglement_durations:
            all_flat = [
                d
                for durs in all_entanglement_durations.values()
                for d in durs
            ]
            total_count = len(all_flat)
            total_time  = sum(all_flat)
            log.info(f"\nTotal number of entanglement events: {total_count}")
            log.info(f"Total entanglement time (all events): {total_time:.6f} s")
            log.info(
                f"Average entanglement time per event: "
                f"{total_time / total_count:.6f} s "
                f"(= {total_time:.6f} / {total_count})"
            )
        else:
            log.info("No entanglement data collected")
        log.info("=" * 80 + "\n")

        # Build CSV filename
        _pre_sched = getattr(circuit_cfg, 'pre_schedule_entanglement', False)
        _pre_tag   = "prescheduled" if _pre_sched else "nopresched"
        _src_file  = (
            getattr(circuit_cfg, 'qasm_file', 'unknown')
            if circuit_cfg.get('mode') == 'cisco'
            else getattr(circuit_cfg, 'dist_commands_file', 'unknown')
        )
        _cmd_stem = os.path.splitext(os.path.basename(_src_file))[0]
        csv_name  = f"{_cmd_stem}_{num_runs}iter_{_pre_tag}.csv"
        csv_path  = os.path.join(self.output_dir, csv_name)
        df.to_csv(csv_path, index=False)
        log.info(f"Results saved to CSV: {csv_path}")

        return final_data


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="dqc-sim",
        description="Run a Distributed Quantum Computing (DQC) simulation.",
    )
    parser.add_argument(
        "-p", "--parameters",
        default=Constants.DEFAULT_PARAM_FILE,
        metavar="FILE",
        help=(
            "Path to the parameters YAML configuration file "
            f"(default: {Constants.DEFAULT_PARAM_FILE})"
        ),
    )
    parser.add_argument(
        "-b", "--base-dir",
        default=None,
        metavar="DIR",
        help=(
            "Base directory for resolving relative circuit file paths "
            "(QASM files, dist_commands files).  When set, the path in "
            "parameters.yml (e.g. circuit.qasm_file) is joined with this "
            "directory."
        ),
    )
    parser.add_argument(
        "-t", "--topology",
        default=None,
        metavar="FILE",
        help="Path to the topology JSON file (overrides default).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=Constants.DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=(
            "Directory for output results "
            f"(default: {Constants.DEFAULT_OUTPUT_DIR})"
        ),
    )
    parser.add_argument(
        "-n", "--num-runs",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Number of simulation iterations (overrides the value in "
            "the parameters file)."
        ),
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        default=False,
        help="Enable debug-level logging.",
    )

    args = parser.parse_args()

    # Build fixed_params to inject CLI overrides into the config
    fixed_params = {}
    if args.debug:
        fixed_params.setdefault("sim", {})["debug"] = True

    sim = DQCSimulation(
        fixed_params=fixed_params,
        varying_params={},
        parameter_file=args.parameters,
        output_dir=args.output_dir,
        base_dir=args.base_dir,
        topology_file=args.topology,
    )

    num_runs = args.num_runs if args.num_runs is not None else sim.cfg.sim.iterations
    sim.start(num_runs=num_runs)


if __name__ == "__main__":
    main()
