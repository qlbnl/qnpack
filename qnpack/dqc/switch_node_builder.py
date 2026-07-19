"""
switch_node_builder.py
----------------------
Factory functions for creating Quantum Switch and Classical Switch nodes
and wiring them into the NetSquid network.

Used when the topology has multiple BSM nodes (``len(bsm_nodes) > 1``).

Connection topology (switch mode)
----------------------------------
The following connections go through the switch nodes:

  QUANTUM (FullMeshOpticalSwitch routing table + QuantumSwitchProtocol):
    QPU.q_to_{bsm_label}           →[QuantumChannel]→  QuantumSwitchNode.qin_{qpu_label}
    QuantumSwitchNode.qout_{bsm_label}_left   →[QuantumChannel]→  BSMNode.{name}_left_port
    QuantumSwitchNode.qout_{bsm_label}_right  →[QuantumChannel]→  BSMNode.{name}_right_port

  CLASSICAL BSM→QPU only (ClassicalSwitch routes automatically):
    BSMNode.clk_to_left      →[ClassicalChannel]→  ClassicalSwitchNode.sw_{bsm}_clk_left
    BSMNode.clk_to_right     →[ClassicalChannel]→  ClassicalSwitchNode.sw_{bsm}_clk_right
    BSMNode.BSM_res_to_left  →[ClassicalChannel]→  ClassicalSwitchNode.sw_{bsm}_res_left
    BSMNode.BSM_res_to_right →[ClassicalChannel]→  ClassicalSwitchNode.sw_{bsm}_res_right
    ClassicalSwitchNode.sw_{qpu}_clk  →[ClassicalChannel]→  QPUNode.clk_from_switch
    ClassicalSwitchNode.sw_{qpu}_res  →[ClassicalChannel]→  QPUNode.bsm_res_from_switch

The following connections are DIRECT (not through the switch):

  Controller→BSM:   Controller.ctrl_bsm{i}_port  →  BSMNode.ctrl_port
  Controller→QPU:   Controller.clk{i}_port / ctrl{i}_port  →  QPUNode.clk_port / ctrl_port
  QPU→Controller:   QPUNode.comm_port  →  Controller.comm{i}_port
  QPU↔QPU:          QPUNode.c_to_{id}  ↔  QPUNode.c_from_{id}

Functions
---------
    create_switch_nodes      — Build both switch components, wrap them in
                               separate Nodes (QuantumSwitchNode and
                               ClassicalSwitchNode), and register all
                               QPUs/BSMs with the classical switch.
    build_switch_connections — Wire the switch nodes into the NetSquid network
                               (quantum and classical channels).
    get_bsm_to_qpus_map      — Build bsm_label -> {left, right} map from bsm_info.
    print_network_connections — Print a full human-readable summary of all
                               node ports and network connections.
"""

import logging

from netsquid.nodes import Node
from netsquid.components.qchannel import QuantumChannel
from netsquid.components.cchannel import ClassicalChannel
from netsquid.components.models.delaymodels import FibreDelayModel

log = logging.getLogger(__name__)


def get_bsm_to_qpus_map(bsm_info: dict) -> dict:
    """Build a ``bsm_label -> {'left': qpu_label, 'right': qpu_label}`` map.

    Parameters
    ----------
    bsm_info : dict
        As returned by ``create_bsm_nodes_from_topology``.

    Returns
    -------
    dict
    """
    return {
        label: {
            'left': info.get('left_qpu'),
            'right': info.get('right_qpu'),
        }
        for label, info in bsm_info.items()
    }


def create_switch_nodes(
    qpu_nodes: list,
    qpu_info: dict,
    bsm_nodes: list,
    bsm_info: dict,
):
    """Create separate QuantumSwitchNode and ClassicalSwitchNode.

    Quantum routing
    ~~~~~~~~~~~~~~~
    The ``FullMeshOpticalSwitch`` is used **as a routing-table data structure
    only**.  Its ``routing_table`` dict is read by ``QuantumSwitchProtocol``
    to decide where to forward qubits.  The protocol reads qubits directly
    from ``QuantumSwitchNode.{qpu_sw_port}`` and writes them to
    ``QuantumSwitchNode.{bsm_sw_port}`` — **no** ``forward_input`` wiring to
    the switch component ports is done here, because those ports are
    unconnected dead-ends inside the component.

    Classical routing (BSM → QPU only)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    The ``ClassicalSwitch`` handles ALL BSM→QPU clock and result routing.
    Both left and right BSM output ports (``clk_to_left``, ``clk_to_right``,
    ``BSM_res_to_left``, ``BSM_res_to_right``) are wired into the switch so
    that both the left QPU and right QPU receive clock ticks and BSM results.

    - ClassicalSwitchNode port names ARE the switch component port names
    - ``add_subcomponent`` with ``forward_input`` and ``forward_output`` wires
      all ports bidirectionally so the Switch._input_handler is properly triggered

    The following connections are NOT through the switch:
    - Controller → BSM (direct via ``ctrl_bsm{i}_port``)
    - Controller → QPU (direct via ``clk{i}_port``, ``ctrl{i}_port``)
    - QPU → Controller (direct via ``comm_port``)
    - QPU ↔ QPU (direct classical channels)

    Parameters
    ----------
    qpu_nodes : list[Node]
        All QPU nodes (ordered by qpu_id, 0-indexed).
    qpu_info : dict
        QPU topology metadata (as returned by ``QPUNodeBuilder``).
    bsm_nodes : list[Node]
        All BSM nodes (ordered by bsm_id, 0-indexed).
    bsm_info : dict
        BSM topology metadata (as returned by ``create_bsm_nodes_from_topology``).

    Returns
    -------
    tuple
        ``(quantum_switch_node, classical_switch_node, q_switch, c_switch)``
    """
    from qnpack.dqc.qswitch import FullMeshOpticalSwitch, ClassicalSwitch

    # Build label → node maps
    label_to_qpu_node = {
        label: qpu_nodes[info["qpu_id"] - 1]
        for label, info in qpu_info.items()
    }
    label_to_bsm_node = {
        label: bsm_nodes[info["bsm_id"] - 1]
        for label, info in bsm_info.items()
    }

    # ── Optical switch port names ─────────────────────────────────────────────
    # These names are used ONLY as keys in the routing_table dict.
    # The switch component ports themselves are NOT connected to anything —
    # QuantumSwitchProtocol reads the routing_table and routes qubits manually.
    #   - Each QPU has one input port: q_from_{qpu_label}
    #   - Each BSM has TWO output ports: q_to_{bsm_label}_left and q_to_{bsm_label}_right
    #     so that the left QPU's photon goes to BSM.left_port and the right QPU's
    #     photon goes to BSM.right_port.
    q_port_names = []
    for qpu_label in qpu_info:
        q_port_names.append(f"q_from_{qpu_label}")
    for bsm_label in bsm_info:
        q_port_names.append(f"q_to_{bsm_label}_left")
        q_port_names.append(f"q_to_{bsm_label}_right")

    q_switch = FullMeshOpticalSwitch(
        name="QuantumSwitch",
        q_port_names=q_port_names,
    )
    log.debug(f"Created FullMeshOpticalSwitch with routing-table ports: {q_port_names}")

    # ── Quantum switch node ───────────────────────────────────────────────────
    # Port names on the QuantumSwitchNode:
    #   qin_{qpu_label}         — quantum input from QPU
    #   qout_{bsm_label}_left   — quantum output to BSM left port (left QPU's photon)
    #   qout_{bsm_label}_right  — quantum output to BSM right port (right QPU's photon)
    q_node_port_names = []
    for qpu_label in qpu_info:
        q_node_port_names.append(f"qin_{qpu_label}")
    for bsm_label in bsm_info:
        q_node_port_names.append(f"qout_{bsm_label}_left")
        q_node_port_names.append(f"qout_{bsm_label}_right")

    quantum_switch_node = Node("QuantumSwitchNode", port_names=q_node_port_names)
    quantum_switch_node.add_subcomponent(q_switch, name="QuantumSwitch")
    log.debug(
        f"Created QuantumSwitchNode with ports: {q_node_port_names}"
    )

    # ── Classical switch ──────────────────────────────────────────────────────
    c_switch = ClassicalSwitch(name="ClassicalSwitch")

    for i, (qpu_label, info) in enumerate(qpu_info.items()):
        qpu_node = label_to_qpu_node[qpu_label]
        c_switch.register_qpu(qpu_node.name, i)
        log.debug(f"Registered QPU {qpu_node.name} (index {i}) with ClassicalSwitch")

    for i, (bsm_label, info) in enumerate(bsm_info.items()):
        bsm_node = label_to_bsm_node[bsm_label]
        c_switch.register_bsm(bsm_node.name, i)
        log.debug(f"Registered BSM {bsm_node.name} (index {i}) with ClassicalSwitch")

        # Set static entanglement context (left/right QPU per BSM)
        left_qpu_label = info.get("left_qpu")
        right_qpu_label = info.get("right_qpu")
        if left_qpu_label and right_qpu_label:
            left_qpu_name = label_to_qpu_node[left_qpu_label].name
            right_qpu_name = label_to_qpu_node[right_qpu_label].name
            c_switch.set_entanglement_context(
                bsm_node.name, left_qpu_name, right_qpu_name
            )
            log.debug(
                f"Set entanglement context: {bsm_node.name} -> "
                f"({left_qpu_name}, {right_qpu_name})"
            )

    # ── Classical switch node ─────────────────────────────────────────────────
    # - Node port names ARE the switch component port names
    # - add_subcomponent with forward_input/forward_output wires all ports
    #   bidirectionally so Switch._input_handler is properly triggered
    classical_switch_ports = list(c_switch.ports.keys())
    classical_switch_node = Node("ClassicalSwitchNode", port_names=classical_switch_ports)

    fwd_input = [(p, p) for p in classical_switch_ports]
    fwd_output = [(p, p) for p in classical_switch_ports]
    classical_switch_node.add_subcomponent(
        c_switch, name="ClassicalSwitch",
        forward_input=fwd_input,
        forward_output=fwd_output,
    )
    log.debug(
        f"Created ClassicalSwitchNode with {len(classical_switch_ports)} ports "
        f"(forward_input + forward_output wired)"
    )

    return quantum_switch_node, classical_switch_node, q_switch, c_switch


def build_switch_connections(
    net,
    quantum_switch_node: Node,
    classical_switch_node: Node,
    qpu_nodes: list,
    qpu_info: dict,
    bsm_nodes: list,
    bsm_info: dict,
    q_lightspeed: float = 200000,
    c_lightspeed: float = 200000,
    photon_loss: float = 0,
    init_photon_loss: float = 0,
    fiber_depolar_rate: float = 0,
    time_independent: bool = True,
):
    """Wire the switch nodes into the NetSquid network.

    Creates quantum and classical channels between:

    1. Each QPU node → QuantumSwitchNode (quantum, one channel per QPU)
    2. QuantumSwitchNode → Each BSM node (quantum, one channel per BSM)
    3. Each BSM node → ClassicalSwitchNode (classical result + clock, BOTH left and right)
    4. ClassicalSwitchNode → Each QPU node (classical result + clock, one each per QPU)

    Also adds ``bsm_res_from_switch`` and ``clk_from_switch`` ports to each
    QPU node (needed by ``SwitchedEntanglementWorker``).

    The following connections are NOT created here (they are direct, set up in sim.py):
    - Controller → BSM (start_entanglement via ctrl_bsm{i}_port)
    - Controller → QPU (clock/ctrl via clk{i}_port, ctrl{i}_port)
    - QPU → Controller (comm via comm_port)
    - QPU ↔ QPU (classical channels)

    Parameters
    ----------
    net : Network
        The NetSquid network.
    quantum_switch_node : Node
        The quantum switch node (from ``create_switch_nodes``).
    classical_switch_node : Node
        The classical switch node (from ``create_switch_nodes``).
    qpu_nodes : list[Node]
        All QPU nodes.
    qpu_info : dict
        QPU topology metadata.
    bsm_nodes : list[Node]
        All BSM nodes.
    bsm_info : dict
        BSM topology metadata.
    q_lightspeed : float
        Speed of light in quantum fibre (km/s).
    c_lightspeed : float
        Speed of light in classical fibre (km/s).
    photon_loss : float
        Photon loss per km in quantum channel.
    init_photon_loss : float
        Initial photon loss (e.g. due to QFC).
    fiber_depolar_rate : float
        Depolarization rate in quantum fibre.
    time_independent : bool
        Whether depolar rate is time-independent.
    """
    from qnpack.dqc.node_builder import SafeDepolarNoiseModel
    from qnpack.dqc.qswitch import ClassicalSwitch
    from netsquid.components.models.qerrormodels import FibreLossModel

    label_to_qpu_node = {
        label: qpu_nodes[info["qpu_id"] - 1]
        for label, info in qpu_info.items()
    }
    label_to_bsm_node = {
        label: bsm_nodes[info["bsm_id"] - 1]
        for label, info in bsm_info.items()
    }

    # Get the ClassicalSwitch component from the node
    c_switch = classical_switch_node.subcomponents.get("ClassicalSwitch")

    def _make_qch_models():
        delay = FibreDelayModel(c=q_lightspeed * 1000)
        loss = (
            FibreLossModel(p_loss_init=init_photon_loss, p_loss_length=photon_loss)
            if (photon_loss or init_photon_loss) else None
        )
        noise = (
            SafeDepolarNoiseModel(depolar_rate=fiber_depolar_rate,
                                  time_independent=time_independent)
            if fiber_depolar_rate else None
        )
        m = {"delay_model": delay}
        if loss:
            m["quantum_loss_model"] = loss
        if noise:
            m["quantum_noise_model"] = noise
        return m

    c_delay_models = {"delay_model": FibreDelayModel(c=c_lightspeed * 1000)}

    # ── Step 1: QPU → QuantumSwitchNode (quantum, one channel per QPU) ────────
    for qpu_label, info in qpu_info.items():
        qpu_node = label_to_qpu_node[qpu_label]
        qpu_name = qpu_node.name
        node_in = f"qin_{qpu_label}"

        # Find the first BSM quantum-out port on this QPU
        bsm_quantum_outs = info.get("bsm_quantum_out", [])
        if not bsm_quantum_outs:
            log.debug(f"QPU {qpu_label} has no BSM quantum-out connections; skipping")
            continue

        first_bsm_label = bsm_quantum_outs[0]["bsm_node"]
        qpu_out_port = f"q_to_{first_bsm_label}"

        if qpu_out_port not in qpu_node.ports:
            log.warning(f"QPU {qpu_label} has no port '{qpu_out_port}'; skipping")
            continue

        net.add_connection(
            qpu_node,
            quantum_switch_node,
            channel_to=QuantumChannel(
                name=f"qch_{qpu_name}_to_QuantumSwitchNode",
                length=0.01,
                models=_make_qch_models(),
            ),
            port_name_node1=qpu_out_port,
            port_name_node2=node_in,
            label=f"quantum_{qpu_name}_to_QuantumSwitchNode",
        )
        log.debug(f"Quantum: {qpu_name}.{qpu_out_port} -> QuantumSwitchNode.{node_in}")

        # Forward additional q_to_{bsm_label} ports to the same first port
        # (the switch routes based on configured route, not port name)
        for bsm_conn in bsm_quantum_outs[1:]:
            bsm_label = bsm_conn["bsm_node"]
            extra_port = f"q_to_{bsm_label}"
            if extra_port in qpu_node.ports:
                qpu_node.ports[extra_port].forward_output(qpu_node.ports[qpu_out_port])
                log.debug(
                    f"Quantum (forward): {qpu_name}.{extra_port} -> "
                    f"{qpu_name}.{qpu_out_port}"
                )

    # ── Step 2: QuantumSwitchNode → BSM nodes (quantum, two channels per BSM) ──
    # Following the dqc branch pattern: each BSM has a left and right quantum port.
    # The left QPU's photon goes to BSM.left_port, the right QPU's photon to BSM.right_port.
    for bsm_label, bsm_inf in bsm_info.items():
        bsm_node = label_to_bsm_node[bsm_label]
        bsm_name = bsm_node.name
        bsm_node_name = bsm_inf["node_name"]
        node_out_left = f"qout_{bsm_label}_left"
        node_out_right = f"qout_{bsm_label}_right"
        bsm_left_port = f"{bsm_node_name}_left_port"
        bsm_right_port = f"{bsm_node_name}_right_port"

        net.add_connection(
            quantum_switch_node,
            bsm_node,
            channel_to=QuantumChannel(
                name=f"qch_QuantumSwitchNode_to_{bsm_name}_left",
                length=0.01,
                models=_make_qch_models(),
            ),
            port_name_node1=node_out_left,
            port_name_node2=bsm_left_port,
            label=f"quantum_QuantumSwitchNode_to_{bsm_name}_left",
        )
        log.debug(f"Quantum: QuantumSwitchNode.{node_out_left} -> {bsm_name}.{bsm_left_port}")

        net.add_connection(
            quantum_switch_node,
            bsm_node,
            channel_to=QuantumChannel(
                name=f"qch_QuantumSwitchNode_to_{bsm_name}_right",
                length=0.01,
                models=_make_qch_models(),
            ),
            port_name_node1=node_out_right,
            port_name_node2=bsm_right_port,
            label=f"quantum_QuantumSwitchNode_to_{bsm_name}_right",
        )
        log.debug(f"Quantum: QuantumSwitchNode.{node_out_right} -> {bsm_name}.{bsm_right_port}")

    # ── Step 3: BSM nodes → ClassicalSwitchNode (classical result + clock) ────
    # Both BSM_res_to_left/right and clk_to_left/right are wired through the
    # classical switch so that both the left QPU and right QPU receive results
    # and clock ticks.
    for bsm_label, bsm_inf in bsm_info.items():
        bsm_node = label_to_bsm_node[bsm_label]
        bsm_name = bsm_node.name

        # BSM result: left side
        res_left_sw_port = c_switch.get_switch_port(bsm_name, "res_left")
        net.add_connection(
            bsm_node,
            classical_switch_node,
            channel_to=ClassicalChannel(
                name=f"cch_bsm_res_left_{bsm_name}_to_ClassicalSwitchNode",
                length=0.01,
                models=c_delay_models,
            ),
            port_name_node1="BSM_res_to_left",
            port_name_node2=res_left_sw_port,
            label=f"bsm_result_left_{bsm_name}_to_ClassicalSwitchNode",
        )
        log.debug(
            f"BSM Result (left): {bsm_name}.BSM_res_to_left -> "
            f"ClassicalSwitchNode.{res_left_sw_port}"
        )

        # BSM result: right side
        res_right_sw_port = c_switch.get_switch_port(bsm_name, "res_right")
        net.add_connection(
            bsm_node,
            classical_switch_node,
            channel_to=ClassicalChannel(
                name=f"cch_bsm_res_right_{bsm_name}_to_ClassicalSwitchNode",
                length=0.01,
                models=c_delay_models,
            ),
            port_name_node1="BSM_res_to_right",
            port_name_node2=res_right_sw_port,
            label=f"bsm_result_right_{bsm_name}_to_ClassicalSwitchNode",
        )
        log.debug(
            f"BSM Result (right): {bsm_name}.BSM_res_to_right -> "
            f"ClassicalSwitchNode.{res_right_sw_port}"
        )

        # BSM clock: left side
        clk_left_sw_port = c_switch.get_switch_port(bsm_name, "clk_left")
        net.add_connection(
            bsm_node,
            classical_switch_node,
            channel_to=ClassicalChannel(
                name=f"cch_bsm_clk_left_{bsm_name}_to_ClassicalSwitchNode",
                length=0.01,
                models=c_delay_models,
            ),
            port_name_node1="clk_to_left",
            port_name_node2=clk_left_sw_port,
            label=f"bsm_clk_left_{bsm_name}_to_ClassicalSwitchNode",
        )
        log.debug(
            f"BSM Clock (left): {bsm_name}.clk_to_left -> "
            f"ClassicalSwitchNode.{clk_left_sw_port}"
        )

        # BSM clock: right side
        clk_right_sw_port = c_switch.get_switch_port(bsm_name, "clk_right")
        net.add_connection(
            bsm_node,
            classical_switch_node,
            channel_to=ClassicalChannel(
                name=f"cch_bsm_clk_right_{bsm_name}_to_ClassicalSwitchNode",
                length=0.01,
                models=c_delay_models,
            ),
            port_name_node1="clk_to_right",
            port_name_node2=clk_right_sw_port,
            label=f"bsm_clk_right_{bsm_name}_to_ClassicalSwitchNode",
        )
        log.debug(
            f"BSM Clock (right): {bsm_name}.clk_to_right -> "
            f"ClassicalSwitchNode.{clk_right_sw_port}"
        )

    # ── Step 4: ClassicalSwitchNode → QPU nodes (classical result + clock) ────
    for qpu_label, info in qpu_info.items():
        qpu_node = label_to_qpu_node[qpu_label]
        qpu_name = qpu_node.name

        # Add switch ports to QPU node if not already present
        for port_name in ("bsm_res_from_switch", "clk_from_switch"):
            if port_name not in qpu_node.ports:
                qpu_node.add_ports([port_name])
                log.debug(f"Added port '{port_name}' to {qpu_name}")

        # BSM result: ClassicalSwitchNode → QPU.bsm_res_from_switch
        res_sw_port = c_switch.get_switch_port(qpu_name, "res")
        net.add_connection(
            classical_switch_node,
            qpu_node,
            channel_to=ClassicalChannel(
                name=f"cch_ClassicalSwitchNode_bsm_res_to_{qpu_name}",
                length=0.01,
                models=c_delay_models,
            ),
            port_name_node1=res_sw_port,
            port_name_node2="bsm_res_from_switch",
            label=f"bsm_result_ClassicalSwitchNode_to_{qpu_name}",
        )
        log.debug(
            f"BSM Result: ClassicalSwitchNode.{res_sw_port} -> {qpu_name}.bsm_res_from_switch"
        )

        # BSM clock: ClassicalSwitchNode → QPU.clk_from_switch
        clk_sw_port = c_switch.get_switch_port(qpu_name, "clk")
        net.add_connection(
            classical_switch_node,
            qpu_node,
            channel_to=ClassicalChannel(
                name=f"cch_ClassicalSwitchNode_clk_to_{qpu_name}",
                length=0.01,
                models=c_delay_models,
            ),
            port_name_node1=clk_sw_port,
            port_name_node2="clk_from_switch",
            label=f"bsm_clk_ClassicalSwitchNode_to_{qpu_name}",
        )
        log.debug(
            f"BSM Clock: ClassicalSwitchNode.{clk_sw_port} -> {qpu_name}.clk_from_switch"
        )

    log.debug("Switch connections wired successfully")


def print_network_connections(
    net,
    qpu_nodes: list,
    qpu_info: dict,
    bsm_nodes: list,
    bsm_info: dict,
    ctrl_node=None,
    quantum_switch_node=None,
    classical_switch_node=None,
    q_switch=None,
    c_switch=None,
    use_switch: bool = False,
    # Legacy parameter names for backward compatibility
    switch_node=None,
):
    """Print a comprehensive human-readable summary of all network connections.

    Parameters
    ----------
    net : Network
        The NetSquid network.
    qpu_nodes : list[Node]
        All QPU nodes.
    qpu_info : dict
        QPU topology metadata.
    bsm_nodes : list[Node]
        All BSM nodes.
    bsm_info : dict
        BSM topology metadata.
    ctrl_node : Node or None
        The controller node.
    quantum_switch_node : Node or None
        The quantum switch node.
    classical_switch_node : Node or None
        The classical switch node.
    q_switch : FullMeshOpticalSwitch or None
        The optical switch component.
    c_switch : ClassicalSwitch or None
        The classical switch component.
    use_switch : bool
        Whether switch mode is active.
    switch_node : Node or None
        Legacy parameter (ignored, kept for backward compatibility).
    """
    label_to_qpu_node = {
        label: qpu_nodes[info["qpu_id"] - 1]
        for label, info in qpu_info.items()
    }
    label_to_bsm_node = {
        label: bsm_nodes[info["bsm_id"] - 1]
        for label, info in bsm_info.items()
    }

    qpu_names = [n.name for n in qpu_nodes]
    bsm_names = [n.name for n in bsm_nodes]
    ctrl_name = ctrl_node.name if ctrl_node else "N/A"
    qsw_name = quantum_switch_node.name if quantum_switch_node else "N/A"
    csw_name = classical_switch_node.name if classical_switch_node else "N/A"

    print("\n" + "=" * 70)
    print("  NETWORK CONNECTION SUMMARY")
    print("=" * 70)
    print(f"  Mode: {'SWITCH (FullMeshOpticalSwitch + ClassicalSwitch)' if use_switch else 'DIRECT'}")
    print(f"  QPU nodes  : {qpu_names}")
    print(f"  BSM nodes  : {bsm_names}")
    print(f"  Controller : {ctrl_name}")
    if use_switch:
        print(f"  QuantumSwitchNode  : {qsw_name}")
        print(f"  ClassicalSwitchNode: {csw_name}")

    print("\n" + "-" * 70)
    print("  QPU NODES")
    print("-" * 70)

    for qpu_label, info in qpu_info.items():
        qpu_node = label_to_qpu_node[qpu_label]
        print(f"\n  QPU: {qpu_node.name}  (label={qpu_label}, id={info['qpu_id']})")
        all_ports = sorted(qpu_node.ports.keys())
        print(f"  All ports: {all_ports}")

        # Quantum outputs
        q_out_ports = [p for p in all_ports if p.startswith("q_to_")]
        if q_out_ports:
            print("  Quantum outputs (q_to_*):")
            for p in q_out_ports:
                port = qpu_node.ports[p]
                connected = _describe_port_connection(port, net)
                print(f"    {p}  ->  {connected}")

        # BSM result/clock inputs
        if use_switch:
            for sw_port in ("bsm_res_from_switch", "clk_from_switch"):
                if sw_port in qpu_node.ports:
                    port = qpu_node.ports[sw_port]
                    connected = _describe_port_connection(port, net)
                    label = "BSM result" if "res" in sw_port else "BSM clock"
                    print(f"  {label} inputs:")
                    print(f"    {sw_port}  <-  {connected}")
        else:
            res_ports = [p for p in all_ports if p.startswith("bsm_res_from_")]
            clk_ports = [p for p in all_ports if p.startswith("clk_from_")]
            if res_ports:
                print("  BSM result inputs:")
                for p in res_ports:
                    print(f"    {p}")
            if clk_ports:
                print("  BSM clock inputs:")
                for p in clk_ports:
                    print(f"    {p}")

        # Controller ports
        ctrl_ports = [p for p in all_ports if p in ("clk_port", "ctrl_port", "comm_port")]
        if ctrl_ports:
            print("  Controller ports (DIRECT):")
            for p in ctrl_ports:
                print(f"    {p}  <->  {ctrl_name}")

        # QPU-QPU classical ports
        qpu_qpu_ports = [p for p in all_ports if p.startswith("c_from_") or p.startswith("c_to_")]
        if qpu_qpu_ports:
            print("  QPU-QPU classical ports (DIRECT):")
            for p in qpu_qpu_ports:
                print(f"    {p}")

    print("\n" + "-" * 70)
    print("  BSM NODES")
    print("-" * 70)

    for bsm_label, info in bsm_info.items():
        bsm_node = label_to_bsm_node[bsm_label]
        print(f"\n  BSM: {bsm_node.name}  (label={bsm_label}, id={info['bsm_id']})")
        print(f"    left_qpu={info.get('left_qpu')}, right_qpu={info.get('right_qpu')}")
        all_ports = sorted(bsm_node.ports.keys())
        print(f"  All ports: {all_ports}")

        if use_switch:
            print("  Quantum inputs (via QuantumSwitchNode):")
            for p in all_ports:
                if "_left_port" in p or "_right_port" in p:
                    port = bsm_node.ports[p]
                    connected = _describe_port_connection(port, net)
                    print(f"    {p}  <-  {connected}")
            print("  Classical outputs (via ClassicalSwitchNode):")
            for p in ("BSM_res_to_left", "BSM_res_to_right", "clk_to_left", "clk_to_right"):
                if p in bsm_node.ports:
                    port = bsm_node.ports[p]
                    connected = _describe_port_connection(port, net)
                    print(f"    {p}  ->  {connected}")
        print("  Controller ports (DIRECT):")
        for p in ("ctrl_port", "clk_port", "comm_port"):
            if p in bsm_node.ports:
                print(f"    {p}  <->  {ctrl_name}")

    if use_switch and quantum_switch_node:
        print("\n" + "-" * 70)
        print("  QUANTUM SWITCH NODE")
        print("-" * 70)
        all_ports = sorted(quantum_switch_node.ports.keys())
        print(f"  All ports: {all_ports}")
        print("  QPU inputs (qin_*):")
        for p in [x for x in all_ports if x.startswith("qin_")]:
            port = quantum_switch_node.ports[p]
            connected = _describe_port_connection(port, net)
            print(f"    {p}  <-  {connected}")
        print("  BSM outputs (qout_*):")
        for p in [x for x in all_ports if x.startswith("qout_")]:
            port = quantum_switch_node.ports[p]
            connected = _describe_port_connection(port, net)
            print(f"    {p}  ->  {connected}")

        if q_switch:
            print("  QuantumSwitch routing table:")
            for (src, dst), active in q_switch.routing_table.items():
                print(f"    {src} -> {dst}: {'ACTIVE' if active else 'inactive'}")

    if use_switch and classical_switch_node:
        print("\n" + "-" * 70)
        print("  CLASSICAL SWITCH NODE")
        print("-" * 70)
        all_ports = sorted(classical_switch_node.ports.keys())
        print(f"  All ports: {all_ports}")
        if c_switch:
            print("  ClassicalSwitch port map:")
            for node_name, port_map in c_switch.node_port_map.items():
                print(f"    {node_name}: {port_map}")
            print("  Active entanglement contexts:")
            for bsm_name, (left, right) in c_switch.active_entanglements.items():
                print(f"    {bsm_name}: left={left}, right={right}")

    print("\n" + "=" * 70 + "\n")


def _describe_port_connection(port, net):
    """Return a human-readable description of what a port is connected to.

    Uses ``port.connected_port`` which returns the port on the
    ``DirectConnection`` object that this node port is wired to.  From there
    we can reach the other side of the connection and the remote node port.
    """
    try:
        # Check forwarded ports first (subcomponent forwarding)
        if hasattr(port, 'forwarded_ports') and port.forwarded_ports:
            fwd = list(port.forwarded_ports)
            return f"[forwarded] -> {fwd}"

        # port.connected_port is the Port on the DirectConnection (side 'A' or 'B')
        conn_port = port.connected_port
        if conn_port is None:
            return "(not connected)"

        conn = conn_port.component          # DirectConnection object
        side = conn_port.name               # 'A' or 'B'
        other_side = 'B' if side == 'A' else 'A'

        # The remote node port is what the other DirectConnection side connects to
        other_conn_port = conn.ports[other_side]
        remote_port = other_conn_port.connected_port
        if remote_port is None:
            return f"[{conn.name}] -> (other side not connected)"

        remote_node = remote_port.component.name
        remote_port_name = remote_port.name

        # Channel in the direction away from this port
        ch = conn.channel_AtoB if side == 'A' else conn.channel_BtoA
        ch_name = ch.name if ch else "direct"

        return f"[{ch_name}] -> {remote_node}.{remote_port_name}"
    except Exception as e:
        return f"(error: {e})"
