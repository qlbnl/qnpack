"""
protocols/core.py
-----------------
DQCProtocol — top-level LocalProtocol that orchestrates the full DQC simulation.

Instantiates and manages:
  - One ControllerProtocol (on the controller node)
  - N QPUProtocols (one per QPU node)
  - M BSMProtocols (one per BSM node)
"""

import logging

import netsquid as ns
from netsquid.protocols.nodeprotocols import LocalProtocol
from netsquid.protocols.protocol import Signals

from .controller import ControllerProtocol
from .qpu import QPUProtocol
from .bsm import BSMProtocol
from .switch import QuantumSwitchProtocol

log = logging.getLogger(__name__)


class DQCProtocol(LocalProtocol):
    def __init__(self, cfg, network, controller_node, qpu_nodes,
                 qpu_info=None, bsm_info=None, bsm_nodes=None, run_idx=0,
                 frontend=None, q_switch=None, switch_node=None,
                 pre_labeled_commands=None, pre_process_maps=None):
        super().__init__(nodes=network.nodes)
        self.cfg = cfg
        self.run_idx = run_idx
        self.network = network
        self.controller_node = controller_node
        self.qpu_nodes = qpu_nodes
        self.qpu_info = qpu_info or {}
        self.bsm_info = bsm_info or {}
        self.bsm_nodes = bsm_nodes or []
        self.frontend = frontend
        self.q_switch = q_switch
        self.switch_node = switch_node
        self.pre_labeled_commands = pre_labeled_commands
        self.pre_process_maps = pre_process_maps
        self.controller_protocol = None
        self.qpu_protocols = []
        self.bsm_protocols = []
        self.global_entanglement_durations = {}
        self._add_subprotocols()

    def _add_subprotocols(self):
        controller_protocol = ControllerProtocol(
            self.cfg,
            node=self.controller_node,
            qpu_nodes=self.qpu_nodes,
            qpu_info=self.qpu_info,
            bsm_info=self.bsm_info,
            name="ControllerProtocol",
            run_idx=self.run_idx,
            frontend=self.frontend,
            pre_labeled_commands=self.pre_labeled_commands,
            pre_process_maps=self.pre_process_maps,
        )
        self.add_subprotocol(controller_protocol)

        # When switch mode is active, start QuantumSwitchProtocol on the switch node.
        # It listens on all QPU input ports and forwards qubits to BSM output ports
        # based on the active routing table of the FullMeshOpticalSwitch.
        # Each BSM has two output ports (left/right) matching the dqc branch pattern.
        if self.q_switch is not None and self.switch_node is not None:
            qpu_port_map = {
                label: f"qin_{label}" for label in self.qpu_info
            }
            # bsm_port_map maps bsm_label -> (left_node_port, right_node_port)
            bsm_port_map = {
                label: (f"qout_{label}_left", f"qout_{label}_right")
                for label in self.bsm_info
            }
            qs_proto = QuantumSwitchProtocol(
                node=self.switch_node,
                q_switch=self.q_switch,
                qpu_port_map=qpu_port_map,
                bsm_port_map=bsm_port_map,
                name="QuantumSwitchProtocol",
            )
            self.add_subprotocol(qs_proto)
            log.debug(
                f"Added QuantumSwitchProtocol on {self.switch_node.name} "
                f"(QPU ports: {list(qpu_port_map.values())}, "
                f"BSM ports: {list(bsm_port_map.values())})"
            )

        # Build a label→index map so we can look up each QPU's topology label
        # (qpu_info maps label -> {qpu_id, ...}; we invert it here)
        id_to_label = {info["qpu_id"]: label for label, info in self.qpu_info.items()}

        for i, qpu_node in enumerate(self.qpu_nodes, start=1):
            qpu_label = id_to_label.get(i)
            qpu_proto = QPUProtocol(
                self.cfg,
                node=qpu_node,
                qpu_id=i,
                qpu_label=qpu_label,
                q_switch=self.q_switch,
                bsm_info=self.bsm_info,
                name=f"QPUProtocol_{i}"
            )
            qpu_proto.global_entanglement_durations = self.global_entanglement_durations
            self.add_subprotocol(qpu_proto)

        sorted_bsm_info = sorted(self.bsm_info.values(), key=lambda x: x["bsm_id"])
        for i, bsm_node in enumerate(self.bsm_nodes, start=1):
            channel_length = 1
            if i - 1 < len(sorted_bsm_info):
                bsm_inf = sorted_bsm_info[i - 1]
                lengths = bsm_inf.get("channel_lengths", {})
                q_left = lengths.get("q_left", 1)
                q_right = lengths.get("q_right", 1)
                channel_length = max(q_left, q_right)
            bsm_proto = BSMProtocol(
                node=bsm_node,
                bsm_id=i,
                cfg=self.cfg,
                channel_length=channel_length,
                name=f"BSMProtocol_{i}"
            )
            self.add_subprotocol(bsm_proto)

        log.debug(
            f"DQC Protocol setup complete: 1 controller, "
            f"{len(self.qpu_nodes)} QPUs, {len(self.bsm_nodes)} BSMs"
            + (", 1 QuantumSwitchProtocol" if self.q_switch is not None else "")
        )

    def run(self):
        self.start_subprotocols()

        # Wait for controller to finish dispatching
        controller = self.subprotocols["ControllerProtocol"]
        yield self.await_signal(controller, Signals.SUCCESS)

        log.debug("[DQCProtocol] Controller finished. Waiting for QPUs to complete.")

        # When pre-labeled commands are provided only a subset of QPUs may have
        # work.  Idle QPUs suspend at await_port_input(ctrl_port) indefinitely
        # and never emit SUCCESS, so sim_run() never terminates.  Derive the
        # active set from pre_labeled_commands (already int-keyed at this point)
        # and skip — then stop — any QPU that is not in it.
        active_qpu_ids = (
            set(self.pre_labeled_commands.keys())
            if self.pre_labeled_commands is not None
            else None
        )

        qpu_protos = [
            proto for proto in self.subprotocols.values()
            if isinstance(proto, QPUProtocol)
        ]
        idle_qpu_protos = []

        for qpu_proto in qpu_protos:
            if active_qpu_ids is not None and qpu_proto.qpu_id not in active_qpu_ids:
                idle_qpu_protos.append(qpu_proto)
                continue
            if qpu_proto.is_running:
                yield self.await_signal(qpu_proto, Signals.SUCCESS)
                log.debug(f"[DQCProtocol] {qpu_proto.name} finished at {ns.sim_time()}")

        log.debug("[DQCProtocol] All QPUs finished. Cleaning up.")

        # Stop BSMs, QuantumSwitchProtocol, BSM workers, and any idle QPUs.
        for name, proto in self.subprotocols.items():
            if isinstance(proto, BSMProtocol):
                proto.stop()
            elif isinstance(proto, QuantumSwitchProtocol):
                if proto.is_running:
                    proto.stop()
            elif isinstance(proto, QPUProtocol):
                if proto in idle_qpu_protos and proto.is_running:
                    proto.stop()
                for bsm_lbl, worker in list(proto._bsm_workers.items()):
                    if worker.is_running:
                        worker.stop()
                proto._bsm_workers.clear()

        log.debug(f"[DQCProtocol] All protocols completed at time {ns.sim_time()}")
        self.send_signal(Signals.SUCCESS)
