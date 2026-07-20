"""
qnpack.dqc.models
==================
Node construction, switch models, and instruction-set definitions for the
DQC simulation.

Modules
-------
    qswitch             — Quantum and classical switch implementations
    node_builder        — QPU and BSM node construction utilities
    switch_node_builder — Switch node factory and wiring functions
    instruction_set     — Canonical DQC instruction-set registry
    validation          — Pre-simulation command validation
"""

from .qswitch import (
    FullMeshOpticalSwitch,
    ClassicalSwitch,
    OpticalSwitch,
    EntanglementQueue,
    EntanglementRequest,
    QuantumMessage,
)
from .node_builder import (
    QPUNodeBuilder,
    SafeDepolarNoiseModel,
    CustomEmissionNoiseModel,
    create_gated_bsm_nodes,
    create_bsm_nodes_from_topology,
)
from .switch_node_builder import (
    create_switch_nodes,
    build_switch_connections,
    print_network_connections,
    get_bsm_to_qpus_map,
)
from .instruction_set import (
    OpCategory,
    OpSpec,
    INSTRUCTION_SET,
    GATE_OPS,
    lookup,
    is_valid_op,
)
from .validation import (
    ValidationError,
    validate_commands,
)

__all__ = [
    # qswitch
    "FullMeshOpticalSwitch",
    "ClassicalSwitch",
    "OpticalSwitch",
    "EntanglementQueue",
    "EntanglementRequest",
    "QuantumMessage",
    # node_builder
    "QPUNodeBuilder",
    "SafeDepolarNoiseModel",
    "CustomEmissionNoiseModel",
    "create_gated_bsm_nodes",
    "create_bsm_nodes_from_topology",
    # switch_node_builder
    "create_switch_nodes",
    "build_switch_connections",
    "print_network_connections",
    "get_bsm_to_qpus_map",
    # instruction_set
    "OpCategory",
    "OpSpec",
    "INSTRUCTION_SET",
    "GATE_OPS",
    "lookup",
    "is_valid_op",
    # validation
    "ValidationError",
    "validate_commands",
]
