class ForcedRNG:
    def __init__(self, forced_outcome: int):
        self.forced_outcome = forced_outcome

    def randint(self, *args, **kwargs):
        return self.forced_outcome

    def seed(self, seed):
        return


def calculate_distances(node_pos, num_repeaters, node_distance):
    """
    Calculate distances from a control node (node_c) to all other nodes in the network
    based on node_distance.
    """
    # Node positions
    node_q1_pos = 1  # First end node
    node_q2_pos = (2 * num_repeaters) + 3  # Last end node

    # Calculate positions of repeater and BSM nodes
    # Odd positions for repeaters
    repeater_positions = [2 * i + 1 for i in range(1, num_repeaters + 1)]
    # Even positions for BSM nodes
    bsm_positions = [2 * i for i in range(1, num_repeaters + 2)]

    # Combine all node positions
    all_positions = {"node_q1": node_q1_pos, "node_q2": node_q2_pos}
    for i, pos in enumerate(repeater_positions, 1):
        all_positions[f"node_r{i}"] = pos
    for i, pos in enumerate(bsm_positions):
        all_positions[f"node_bsm{i + 1}"] = pos

    # Adjusting `node_pos` so it starts from the correct reference point
    adjusted_node_pos = node_pos + 1

    # Calculate distances
    distances = {
        node: abs(adjusted_node_pos - pos) * node_distance
        for node, pos in all_positions.items()
    }

    return distances
