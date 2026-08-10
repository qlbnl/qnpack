"""
Quantum and Classical Switch Implementation for Entanglement Networks

This module provides:
- FullMeshOpticalSwitch: Quantum switch for photon routing between QPUs and BSMs
- ClassicalSwitch: Switch-based routing for clock signals and BSM results
- EntanglementQueue: Manages entanglement requests with parallelization support

Message Flow (switch mode):
1. QPU --[quantum photon]--> QuantumSwitchNode --> BSM (measurement)
2. BSM --[CLK_SIGNAL]--> ClassicalSwitchNode --> QPU_left, QPU_right (clock tick)
3. BSM --[BSM_RESULT]--> ClassicalSwitchNode --> QPU_left, QPU_right (result)

Direct connections (NOT through switch):
- Controller <--> QPU  (ctrl, clk, comm)
- Controller <--> BSM  (ctrl, clk, comm)
- QPU <--> QPU         (classical peer channels)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Set
from netsquid.components import Component
from netsquid.components.switch import Switch
from netsquid.components.models.delaymodels import FibreDelayModel
from netsquid.components.qchannel import QuantumChannel
from netsquid.components.component import Message
import logging

log = logging.getLogger(__name__)


@dataclass
class QuantumMessage:
    """
    Attributes:
        source_qpu: Name of the source QPU
        destination_bsm: Name of the destination BSM
        qubit_id: Identifier for the qubit being sent
        label: label for debugging
    """
    source_qpu: str
    destination_bsm: str
    qubit_id: int = 0
    label: str = ""

    def __repr__(self):
        return f"[{self.label}] QUBIT: {self.source_qpu}[{self.qubit_id}] -> {self.destination_bsm}"


@dataclass
class EntanglementRequest:
    """
    Represents a request to entangle two QPUs via a BSM.

    Attributes:
        qpu_left: Name of the left QPU
        qpu_right: Name of the right QPU
        assigned_bsm: Name of the assigned BSM (None if not yet assigned)
        status: Current status of the request
    """
    qpu_left: str
    qpu_right: str
    assigned_bsm: Optional[str] = None
    status: str = "pending"

    def __repr__(self):
        bsm = self.assigned_bsm or "unassigned"
        return f"EntReq({self.qpu_left} <-> {self.qpu_right} via {bsm}) [{self.status}]"


class EntanglementQueue:
    """
    Manages entanglement requests with parallelization support.

    When multiple BSMs are available, requests can be processed in parallel
    as long as they use different BSMs. A BSM can only handle one entanglement
    request at a time.
    """

    def __init__(self, bsm_nodes: List[str]):
        self.pending_requests: List[EntanglementRequest] = []
        self.active_requests: Dict[str, EntanglementRequest] = {}  # bsm_name -> request
        self.completed_requests: List[EntanglementRequest] = []
        self.available_bsms: Set[str] = set(bsm_nodes)
        self.all_bsms: Set[str] = set(bsm_nodes)

    def add_request(self, qpu_left: str, qpu_right: str):
        """Add a new entanglement request to the queue."""
        req = EntanglementRequest(qpu_left=qpu_left, qpu_right=qpu_right)
        self.pending_requests.append(req)
        log.debug(f"Added entanglement request: {req}")
        return req

    def _get_busy_qpus(self) -> Set[str]:
        """Return the set of QPU names currently involved in active requests."""
        busy: Set[str] = set()
        for req in self.active_requests.values():
            busy.add(req.qpu_left)
            busy.add(req.qpu_right)
        return busy

    def get_next_assignments(self) -> List[Tuple[EntanglementRequest, str]]:
        """
        Get the next batch of requests that can be processed in parallel.

        A request is only assigned if **both** of its QPUs are free (not
        involved in any other active request).  Requests whose QPUs conflict
        are left in the pending queue for the next scheduling round.

        Returns:
            List of (request, bsm_name) tuples for parallel execution
        """
        assignments = []
        busy_qpus = self._get_busy_qpus()
        still_pending = []

        for req in self.pending_requests:
            if not self.available_bsms:
                # No more BSMs available — keep remaining requests pending
                still_pending.append(req)
                continue

            if req.qpu_left in busy_qpus or req.qpu_right in busy_qpus:
                # One or both QPUs are busy — defer this request
                log.debug(f"Deferring {req}: QPU conflict (busy: {busy_qpus})")
                still_pending.append(req)
                continue

            # Both QPUs are free and a BSM is available — assign
            bsm = self.available_bsms.pop()
            req.assigned_bsm = bsm
            req.status = "active"
            self.active_requests[bsm] = req
            assignments.append((req, bsm))
            busy_qpus.add(req.qpu_left)
            busy_qpus.add(req.qpu_right)
            log.debug(f"Assigned {req} to {bsm}")

        self.pending_requests = still_pending
        return assignments

    def complete_request(self, bsm_name: str, success: bool = True):
        """Mark a request as completed and free the BSM."""
        if bsm_name in self.active_requests:
            req = self.active_requests.pop(bsm_name)
            req.status = "success" if success else "failed"
            self.completed_requests.append(req)
            self.available_bsms.add(bsm_name)
            log.debug(f"Completed {req}, BSM {bsm_name} now available")
            return req
        return None

    def has_pending(self) -> bool:
        """Check if there are pending or active requests."""
        return bool(self.pending_requests) or bool(self.active_requests)

    def get_qpus_for_bsm(self, bsm_name: str) -> Optional[Tuple[str, str]]:
        """Get the QPU pair assigned to a BSM."""
        if bsm_name in self.active_requests:
            req = self.active_requests[bsm_name]
            return (req.qpu_left, req.qpu_right)
        return None


class ClassicalSwitch(Switch):
    """
    Classical message switch for routing BSM clock signals and results to QPUs.

    Extends netsquid.components.switch.Switch to use the built-in routing_table()
    mechanism.  When messages arrive on any port, the Switch base class calls
    routing_table() which returns (message, output_port) pairs for forwarding.

    Only BSM→QPU clock and result messages are routed through this switch.
    All other connections (Controller↔QPU, Controller↔BSM, QPU↔QPU) are direct.

    Port naming convention
    ----------------------
    QPU ports (output only):
        sw_{qpu_name}_clk   — clock tick delivered to QPU
        sw_{qpu_name}_res   — BSM result delivered to QPU

    BSM ports (input only):
        sw_{bsm_name}_clk_left   — clock from BSM for the left QPU
        sw_{bsm_name}_clk_right  — clock from BSM for the right QPU
        sw_{bsm_name}_res_left   — BSM result for the left QPU
        sw_{bsm_name}_res_right  — BSM result for the right QPU

    Routing logic
    -------------
    - ``clk_left``  → left QPU's ``clk`` port
    - ``clk_right`` → right QPU's ``clk`` port
    - ``res_left``  → left QPU's ``res`` port
    - ``res_right`` → right QPU's ``res`` port

    The left/right QPU mapping is set via :meth:`set_entanglement_context`.
    """

    def __init__(self, name: str):
        super().__init__(name=name)

        # Port mappings: node_name -> {port_type -> switch_port_name}
        self.node_port_map: Dict[str, Dict[str, str]] = {}

        # Reverse mapping: switch_port_name -> (node_name, port_type)
        self.port_to_node: Dict[str, Tuple[str, str]] = {}

        # Entanglement context: bsm_name -> (qpu_left, qpu_right)
        self.active_entanglements: Dict[str, Tuple[str, str]] = {}

    def register_qpu(self, qpu_name: str, qpu_index: int):
        """Register a QPU node with its output ports on the switch.

        Only ``clk`` and ``res`` ports are created — QPU control signals
        go directly from the Controller and do not pass through this switch.
        """
        port_map = {
            "clk": f"sw_{qpu_name}_clk",
            "res": f"sw_{qpu_name}_res",
        }
        self.node_port_map[qpu_name] = port_map

        port_names = list(port_map.values())
        self.add_ports(port_names)
        for port_type, port_name in port_map.items():
            self.port_to_node[port_name] = (qpu_name, port_type)

        log.debug(f"Registered QPU {qpu_name} with ports: {port_map}")

    def register_bsm(self, bsm_name: str, bsm_index: int):
        """Register a BSM node with its input ports on the switch.

        Only clock and result ports are created — BSM control signals go
        directly from the Controller and do not pass through this switch.
        """
        port_map = {
            "clk_left":  f"sw_{bsm_name}_clk_left",
            "clk_right": f"sw_{bsm_name}_clk_right",
            "res_left":  f"sw_{bsm_name}_res_left",
            "res_right": f"sw_{bsm_name}_res_right",
        }
        self.node_port_map[bsm_name] = port_map

        port_names = list(port_map.values())
        self.add_ports(port_names)
        for port_type, port_name in port_map.items():
            self.port_to_node[port_name] = (bsm_name, port_type)

        log.debug(f"Registered BSM {bsm_name} with ports: {port_map}")

    def set_entanglement_context(self, bsm_name: str, qpu_left: str, qpu_right: str):
        """Set the current entanglement context for a BSM.

        This tells the switch which QPUs are paired with which BSM,
        enabling correct routing of clock signals and BSM results.
        """
        self.active_entanglements[bsm_name] = (qpu_left, qpu_right)
        log.debug(f"Set entanglement context: {bsm_name} -> ({qpu_left}, {qpu_right})")

    def clear_entanglement_context(self, bsm_name: str):
        """Clear the entanglement context for a BSM."""
        if bsm_name in self.active_entanglements:
            del self.active_entanglements[bsm_name]

    def routing_table(self, input_port, message):
        """Route BSM clock and result messages to the correct QPU.

        Called automatically by the Switch base class when a message arrives
        on any port.  Returns a list of ``(Message, output_port_name)`` pairs.

        Routing logic:
        - ``clk_left`` / ``clk_right``  → left / right QPU ``clk`` port
        - ``res_left`` / ``res_right``  → left / right QPU ``res`` port
        """
        results = []
        source_node, source_type = self.port_to_node.get(input_port, (None, None))

        if not message or not message.items:
            return results

        for item in message.items:
            results.extend(self._route_message(item, source_node, source_type))

        return results

    def _route_message(self, item, source_node: str, source_type: str):
        """Route a single message item based on input port context."""
        results = []

        if source_type in ("clk_left", "clk_right"):
            # Clock signal from BSM — route to the appropriate QPU
            if source_node in self.active_entanglements:
                qpu_left, qpu_right = self.active_entanglements[source_node]
                target_qpu = qpu_left if source_type == "clk_left" else qpu_right
                dest_port = self.node_port_map.get(target_qpu, {}).get("clk")
                if dest_port:
                    log.debug(
                        f"ROUTING CLK ({source_type}): "
                        f"{source_node} -> {target_qpu} via {dest_port}"
                    )
                    results.append((Message([item]), dest_port))
                else:
                    log.warning(
                        f"No clk port for QPU {target_qpu} "
                        f"(source={source_node}, type={source_type})"
                    )

        elif source_type in ("res_left", "res_right"):
            # BSM result — route to the appropriate QPU
            if source_node in self.active_entanglements:
                qpu_left, qpu_right = self.active_entanglements[source_node]
                target_qpu = qpu_left if source_type == "res_left" else qpu_right
                dest_port = self.node_port_map.get(target_qpu, {}).get("res")
                if dest_port:
                    log.debug(
                        f"ROUTING BSM_RES ({source_type}): "
                        f"{source_node} -> {target_qpu} via {dest_port}"
                    )
                    results.append((Message([item]), dest_port))
                else:
                    log.warning(
                        f"No res port for QPU {target_qpu} "
                        f"(source={source_node}, type={source_type})"
                    )
        else:
            log.warning(
                f"Unhandled message on port type '{source_type}' "
                f"from '{source_node}': {item}"
            )

        return results

    def get_switch_port(self, node_name: str, port_type: str) -> Optional[str]:
        """Get the switch port name for a node's logical port."""
        return self.node_port_map.get(node_name, {}).get(port_type)


class OpticalSwitch(Component, ABC):
    """
    Optical Switch with n generic quantum ports. Ports can be connected to QPUs or BSM nodes.
    Routing table controls which ports are connected internally.

    This switch handles ONLY quantum channels. Classical communication is handled
    by a separate ClassicalSwitch component.
    """

    def __init__(self, name: str, q_port_names: List[str],
                 port_insertion_loss: float = 0.0,
                 loss_model=None,
                 mems_latency: float = 0.01):
        super().__init__(name=name)
        self.q_port_names = q_port_names
        self.port_insertion_loss = port_insertion_loss
        self.loss_model = loss_model
        self.mems_latency = mems_latency
        self.delay = FibreDelayModel(c=2e5)
        self.add_ports(q_port_names)

        # Internal quantum channels: (port_a, port_b) -> QuantumChannel
        self.internal_channels: Dict[Tuple[str, str], QuantumChannel] = {}

        # Routing table: (port_a, port_b) -> active (bool)
        self.routing_table: Dict[Tuple[str, str], bool] = {}

        # Qubit tracking for debugging
        self.qubit_log: List[QuantumMessage] = []

    def _make_qchannel(self, name: str, length_km: float = 0.01):
        models = {"delay_model": self.delay}
        if self.loss_model is not None:
            models["quantum_loss_model"] = self.loss_model
        return QuantumChannel(name, length=length_km * 1000, models=models)

    def configure_route(self, port_src: str, port_dst: str, active: bool = True):
        """Configure a route between two ports."""
        if (port_src, port_dst) not in self.internal_channels:
            raise RuntimeError(f"No internal channel between {port_src} and {port_dst}")
        self.routing_table[(port_src, port_dst)] = active
        log.debug(f"Quantum route {port_src} -> {port_dst}: {'ACTIVE' if active else 'INACTIVE'}")
        return self.mems_latency

    def is_route_active(self, port_src: str, port_dst: str) -> bool:
        return self.routing_table.get((port_src, port_dst), False)

    def list_links(self) -> List[Tuple[str, str]]:
        return list(self.internal_channels.keys())

    def log_qubit_transmission(self, source_qpu: str, dest_bsm: str, qubit_id: int = 0):
        """Log a qubit transmission for debugging."""
        qmsg = QuantumMessage(
            source_qpu=source_qpu,
            destination_bsm=dest_bsm,
            qubit_id=qubit_id,
            label=f"QUBIT_{source_qpu}[{qubit_id}]->{dest_bsm}"
        )
        self.qubit_log.append(qmsg)
        log.info(f"QUANTUM: {qmsg}")

    @abstractmethod
    def create_internal_topology(self):
        pass


class FullMeshOpticalSwitch(OpticalSwitch):
    """
    Full-mesh optical switch: all quantum ports connected to all other quantum ports.
    """

    def __init__(self, name: str, q_port_names: List[str],
                 port_insertion_loss: float = 0.0,
                 loss_model=None,
                 mems_latency: float = 0.01):
        super().__init__(name, q_port_names, port_insertion_loss, loss_model, mems_latency)
        self.create_internal_topology()

    def create_internal_topology(self):
        for i, a in enumerate(self.q_port_names):
            for j, b in enumerate(self.q_port_names):
                if i >= j:
                    continue
                ch_name = f"ch_{a}_to_{b}"
                ch = self._make_qchannel(ch_name)
                self.add_subcomponent(ch, ch_name)
                self.internal_channels[(a, b)] = ch
                self.internal_channels[(b, a)] = ch
                self.routing_table[(a, b)] = False
                self.routing_table[(b, a)] = False

    def activate_all_routes(self):
        for key in self.routing_table:
            self.routing_table[key] = True

    def deactivate_all_routes(self):
        for key in self.routing_table:
            self.routing_table[key] = False
