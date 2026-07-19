"""
protocols/switch.py
-------------------
Switch-aware entanglement protocols for multi-BSM topologies.

When the topology specifies more than one BSM node, photons from all QPU nodes
are routed through a shared **FullMeshOpticalSwitch** to the correct BSM node,
and BSM results / clock ticks are routed back through a shared
**ClassicalSwitch**.

This module provides:

``QuantumSwitchProtocol``
    Node protocol that runs on the SwitchNode and actively routes qubits
    arriving on QPU input ports to the correct BSM output port based on the
    ``FullMeshOpticalSwitch`` routing table.

``SwitchedEntanglementWorker``
    Drop-in replacement for :class:`~qnpack.dqc.protocols.qpu.EntanglementWorkerProtocol`
    that routes photons through the quantum switch and receives results/clocks
    through the classical switch.

Network wiring is handled by :mod:`qnpack.dqc.switch_node_builder`.

Design
------
The ``SwitchedEntanglementWorker`` is identical to the base
``EntanglementWorkerProtocol`` except:

1. Before emitting a photon it configures the optical switch route so the
   switch knows which BSM to forward to.
2. It reads BSM results from ``bsm_res_from_switch`` (not ``bsm_res_from_{bsm_label}``).
3. It reads clock ticks from ``clk_from_switch`` (not ``clk_from_{bsm_label}``).
4. It still calls ``_forward_qout_to_bsm`` with the BSM label so the QPU's
   qmemory output is forwarded to the correct ``q_to_{bsm_label}`` port,
   which is wired to the optical switch input.
"""

import random
import logging
from typing import Dict, Optional

import netsquid as ns
from netsquid.protocols.nodeprotocols import NodeProtocol
from netsquid.components.component import Message
from netsquid.qubits import qubitapi as qapi
from netsquid.qubits import operators as ops

log = logging.getLogger(__name__)

# BSM detector output values that indicate successful Bell measurement
BSM_SUCCESS = [[2], [3]]


# ---------------------------------------------------------------------------
# QuantumSwitchProtocol
# ---------------------------------------------------------------------------

class QuantumSwitchProtocol(NodeProtocol):
    """Protocol that runs on the SwitchNode and routes qubits from QPU ports
    to BSM ports based on the active routing table of the
    ``FullMeshOpticalSwitch``.

    This is the quantum-plane counterpart of the ``ClassicalSwitch``'s
    automatic message routing.  Without this protocol, qubits arriving at
    the switch node's QPU input ports would never be forwarded.

    Parameters
    ----------
    node : Node
        The switch node (``SwitchNode``).
    q_switch : FullMeshOpticalSwitch
        The optical switch component (from ``qnpack.dqc.qswitch``).
    qpu_port_map : dict
        Mapping of ``qpu_label -> switch_node_port_name`` for QPU inputs
        (e.g. ``{'LBNL-A': 'qin_LBNL-A', ...}``).
    bsm_port_map : dict
        Mapping of ``bsm_label -> switch_node_port_name`` for BSM outputs
        (e.g. ``{'BSM-1': 'qout_BSM-1', ...}``).
    name : str or None
        Protocol name.
    """

    def __init__(
        self,
        node,
        q_switch,
        qpu_port_map: Dict[str, str],
        bsm_port_map: Dict,
        name=None,
    ):
        if name is None:
            name = f"QuantumSwitchProtocol_{node.name}"
        super().__init__(node, name=name)
        self.q_switch = q_switch
        self.qpu_port_map = qpu_port_map   # qpu_label -> node port name (e.g. "qin_{qpu_label}")
        self.bsm_port_map = bsm_port_map   # bsm_label -> (left_node_port, right_node_port)
        # Map: switch-component port "q_to_{bsm_label}_left/right" -> node port
        self._sw_port_to_node_port: Dict[str, str] = {}
        for bsm_label, ports in bsm_port_map.items():
            if isinstance(ports, tuple):
                left_port, right_port = ports
                self._sw_port_to_node_port[f"q_to_{bsm_label}_left"] = left_port
                self._sw_port_to_node_port[f"q_to_{bsm_label}_right"] = right_port
            else:
                # Legacy: single port string
                self._sw_port_to_node_port[f"q_to_{bsm_label}"] = ports

    def _get_destination_node_port(self, source_sw_port: str) -> Optional[str]:
        """Return the switch-node output port for a given switch-component
        source port, based on the active routing table."""
        for (src, dst), active in self.q_switch.routing_table.items():
            if active and src == source_sw_port:
                return self._sw_port_to_node_port.get(dst)
        return None

    def run(self):
        """Listen on all QPU input ports and forward qubits to BSM ports."""
        log.info(f"[{self.node.name}] QuantumSwitchProtocol started")

        # Collect the node-level port names for QPU inputs
        qpu_node_ports = list(self.qpu_port_map.values())

        while True:
            # Build a combined wait expression for all QPU input ports
            port_waits = []
            valid_ports = []
            for port_name in qpu_node_ports:
                if port_name in self.node.ports:
                    port_waits.append(self.await_port_input(self.node.ports[port_name]))
                    valid_ports.append(port_name)

            if not port_waits:
                yield self.await_timer(duration=int(1e9))
                continue

            evexpr = port_waits[0]
            for pw in port_waits[1:]:
                evexpr = evexpr | pw

            yield evexpr

            # Forward any received qubits
            for node_port_name in valid_ports:
                port = self.node.ports[node_port_name]
                msg = port.rx_input()
                if msg is None or not msg.items:
                    continue

                # Map node port "qin_{qpu_label}" -> switch-component port "q_from_{qpu_label}"
                qpu_label = node_port_name[len("qin_"):]
                sw_src_port = f"q_from_{qpu_label}"

                dest_node_port = self._get_destination_node_port(sw_src_port)
                if dest_node_port and dest_node_port in self.node.ports:
                    log.debug(
                        f"[{self.node.name}|QSwitch] Forwarding qubit: "
                        f"{node_port_name} -> {dest_node_port}"
                    )
                    self.node.ports[dest_node_port].tx_output(msg)
                else:
                    log.warning(
                        f"[{self.node.name}|QSwitch] No active route for "
                        f"{node_port_name} (sw_port={sw_src_port})"
                    )


# ---------------------------------------------------------------------------
# SwitchedEntanglementWorker
# ---------------------------------------------------------------------------

class SwitchedEntanglementWorker(NodeProtocol):
    """Entanglement worker that routes photons through a quantum switch.

    Drop-in replacement for
    :class:`~qnpack.dqc.protocols.qpu.EntanglementWorkerProtocol`
    for use when a ``FullMeshOpticalSwitch`` / ``ClassicalSwitch`` pair is
    present in the network.

    Differences from the base worker
    ---------------------------------
    1. Before emitting a photon, configures the optical switch route so the
       switch forwards the photon to the correct BSM node.
    2. Reads BSM results from ``bsm_res_from_switch`` on the QPU node
       (instead of ``bsm_res_from_{bsm_label}``).
    3. Reads clock ticks from ``clk_from_switch`` on the QPU node
       (instead of ``clk_from_{bsm_label}``).
    4. Still calls ``_forward_qout_to_bsm`` with the BSM label so the QPU's
       qmemory output is forwarded to ``q_to_{bsm_label}``, which is wired
       to the optical switch input.

    Parameters
    ----------
    node : Node
        The QPU node (shared with QPUProtocol).
    qpu_protocol : QPUProtocol
        Reference to the parent protocol (for shared state access).
    bsm_label : str
        BSM label for routing the photon.
    qpu_label : str
        This QPU's topology label (e.g. ``'LBNL-A'``), used to identify the
        switch input port.
    q_switch : FullMeshOpticalSwitch
        The optical switch component (from ``qnpack.dqc.qswitch``).
    name : str or None
        Protocol name.
    """

    ENTANGLEMENT_DONE = "ENTANGLEMENT_DONE"
    NEW_WORK = "NEW_WORK"

    def __init__(
        self,
        node,
        qpu_protocol,
        bsm_label: str,
        qpu_label: str,
        q_switch,
        bsm_side: str = "left",
        name=None,
    ):
        if name is None:
            name = f"SwitchedEntWorker_{node.name}_{bsm_label}"
        super().__init__(node, name=name)
        self.qpu_protocol = qpu_protocol
        self.bsm_label = bsm_label
        self.qpu_label = qpu_label
        self.q_switch = q_switch
        self.bsm_side = bsm_side  # "left" or "right" — which BSM port this QPU feeds
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
                    f"[{self.node.name}|SwitchedWorker] Photon lost due to "
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
                f"[{self.node.name}|SwitchedWorker] No qout port for position {position}"
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
        """Apply a single-qubit correction gate using qapi."""
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

    def _configure_switch_route(self):
        """Configure the optical switch to route from this QPU to the target BSM.

        Uses the ``FullMeshOpticalSwitch.configure_route`` method to activate
        the route from the QPU input port to the correct BSM side output port.
        Following the dqc branch pattern, each BSM has a left and right port:
          - left QPU's photon -> q_to_{bsm_label}_left
          - right QPU's photon -> q_to_{bsm_label}_right
        """
        qpu_port = f"q_from_{self.qpu_label}"
        bsm_port = f"q_to_{self.bsm_label}_{self.bsm_side}"

        if self.q_switch is None:
            log.error(
                f"[{self.node.name}|SwitchedWorker] No optical switch available"
            )
            return

        # Deactivate all existing routes from this QPU port first
        for (src, dst) in list(self.q_switch.routing_table.keys()):
            if src == qpu_port:
                self.q_switch.configure_route(src, dst, active=False)

        # Activate the route to the target BSM side
        if (qpu_port, bsm_port) in self.q_switch.routing_table:
            self.q_switch.configure_route(qpu_port, bsm_port, active=True)
            log.debug(
                f"[{self.node.name}|SwitchedWorker] Switch route: "
                f"{qpu_port} -> {bsm_port}"
            )
        else:
            log.warning(
                f"[{self.node.name}|SwitchedWorker] No switch route between "
                f"{qpu_port} and {bsm_port} (routing_table keys: "
                f"{list(self.q_switch.routing_table.keys())})"
            )

    def run(self):
        """Process pre-gen requests sequentially from the work queue."""
        parent = self.qpu_protocol
        bsm_label = self.bsm_label

        # With the switch, BSM results and clock ticks arrive on switch ports
        bsm_clk_port = self.node.ports.get("clk_from_switch")
        bsm_res_port = self.node.ports.get("bsm_res_from_switch")

        # Fall back to direct BSM ports if switch ports are not present
        if bsm_clk_port is None:
            bsm_clk_port = self.node.ports.get(f"clk_from_{bsm_label}")
        if bsm_res_port is None:
            bsm_res_port = self.node.ports.get(f"bsm_res_from_{bsm_label}")

        if bsm_clk_port is None or bsm_res_port is None:
            log.error(
                f"[{self.node.name}|SwitchedWorker] Cannot find BSM ports "
                f"for {bsm_label} (tried switch and direct ports)"
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
                f"[{self.node.name}|SwitchedWorker] Generating entanglement for "
                f"start_label={target_start_label} on qubit {actual_emit} "
                f"(bsm={bsm_label}, link_side={is_link_side})"
            )

            self._drain_stale_bsm_results(bsm_res_port)

            # Configure optical switch route BEFORE forwarding qout
            self._configure_switch_route()

            # Forward qmemory output to the q_to_{bsm_label} port
            # (which is wired to the optical switch input)
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

                # Re-configure switch route for each retry
                self._configure_switch_route()
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
                    f"[{self.node.name}|SwitchedWorker] Entanglement SUCCESS for "
                    f"start_label={target_start_label}: actual_emit={actual_emit}, "
                    f"retries={retries}, bsm_data={bsm_data}"
                )
            else:
                log.warning(
                    f"[{self.node.name}|SwitchedWorker] Entanglement FAILED for "
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


