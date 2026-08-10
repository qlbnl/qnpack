# QNPack: Modeling and Simulation of Quantum Networks

QNPack is a simulation toolkit for modeling and analyzing both **1G (memory-based)** and **All-Photonic** quantum repeater architectures.  QNPack has also been extended to include a DQC modeling layer that draws from the existing quantum repeater protocols.
The package enables rapid prototyping and experimentation using NetSquid-based simulations, supporting advanced concepts such as entanglement swapping, purification, and error correction.

---

## Quantum Repeater Architectures Modeled

### 1. All-Photonic Entanglement-Based Quantum Repeater (APE-QR)

- Performs end-to-end entanglement and quantum error correction using **photonic graph states**
- Efficient and deterministic graph state generation using **solid-state quantum emitters**
- Utilizes **Time-Division Multiple Access (TDMA)** for state generation, transmission, and reception
- Implements **loss-tolerant, measurement-based quantum error correction**

### 2. 1G Trapped-Ion Quantum Repeater (1G-Trapped-Ion-QR)

- Traditional **memory-based repeater** model with ion-trap qubits
- High-rate, high-fidelity **ion-photon entanglement generation**
- Supports core repeater functions:
  - **Entanglement Generation**
  - **Entanglement Swapping**
  - **Entanglement Purification**
- Photon-mediated entanglement links between nodes

### 3. Distributed Quantum Computing (DQC)

The `qnpack.dqc` module extends QNPack with a full **distributed quantum computing** simulation layer.  It models multi-QPU execution of quantum circuits where non-local (inter-QPU) gates are realized through entanglement-assisted protocols over quantum network links.

#### Architecture

- **Controller–QPU–BSM model**: A central controller dispatches per-QPU command streams to multiple QPU nodes, coordinating entanglement generation through intermediate Bell State Measurement (BSM) nodes.
- **Quantum & classical switching**: An optional `FullMeshOpticalSwitch` routes photons between QPUs and BSMs, with a companion `ClassicalSwitch` for clock signals and measurement results.  Entanglement requests are managed by an `EntanglementQueue` that supports parallel BSM utilization.
- **Topology-driven network construction**: Network layout (QPU sites, BSM nodes, channel lengths, qubit counts, noise parameters) is defined in a JSON topology file.  `QPUNodeBuilder` and `create_bsm_nodes_from_topology` construct the NetSquid network from this specification.

#### Circuit Frontends

DQC accepts circuits through two pluggable frontends:

| Frontend | Input | Description |
|----------|-------|-------------|
| **TketFrontend** | pytket `Circuit` objects or `dist_commands.txt` files | Uses pytket-dqc for circuit partitioning across QPUs with EJPP (Entanglement-assisted Joint Phase Protocol) operations. |
| **QASM3Frontend** | OpenQASM 3.0 files with per-QPU qubit registers | Parses pre-partitioned QASM 3.0 programs via the `openqasm3` AST. |

Both frontends emit a **canonical per-QPU command IR** that is processed by a unified labeling layer (`qnpack.dqc.labeling`) to assign entanglement labels, EJPP start/end labels, and cross-QPU classical message exchange labels before execution.

#### Included Algorithms

Ready-to-run algorithm generators are provided in `qnpack.dqc.algorithms`:

- **Grover's search** — scalable multi-qubit search with ancilla-based decomposition (4–12+ qubits, 1–3 QPUs)
- **Bernstein–Vazirani** — hidden-string identification via the BV algorithm
- **QAOA (MaxCut)** — multi-layer Quantum Approximate Optimization for graph MaxCut problems

Pre-built distributed command files and QASM circuits for various qubit/QPU configurations are included in `commands/` and `qasm/`.

#### Noise & Validation

- Configurable noise models: gate depolarization, T1/T2 memory decoherence, fiber loss, emission fidelity, and BSM detection parameters — all specified in `parameters.yml`.
- Pre-simulation **command validation** (`qnpack.dqc.models.validation`) checks the canonical IR against a registered instruction set before execution.
- Pre-scheduling of entanglement generation to overlap with local gate execution, reducing circuit latency.

#### CLI Entry Point

```bash
dqc-sim                        # run via the installed console script
# or
python -m qnpack.dqc.sim      # run as a module
```

Configuration is driven by `parameters.yml` (simulation, circuit, QPU, memory, channel, BSM settings) and a topology JSON file.

---

## Example Experiments

### 1G Examples (Trapped-Ion Quantum Repeaters)

Provided as Jupyter Notebooks:

- **First 1G Simulation**: Introductory simulation.
- **Parameters for 1G**: Guide to selecting network parameters.
- **Scaling 1G Simulation**: Demonstrates scaling to more repeater nodes.

**Terminal Execution**:

```bash
python qnpack/oneG/iontrap.py
```

> Parameters can be modified via the `parameters.yml` file.

---

### APE Examples (All-Photonic Repeaters)

Provided as Jupyter Notebooks:

- **First APE Simulation**: Introductory simulation.
- **Parameters for APE**: Guide to choosing simulation parameters.
- **Scaling APE Simulation**: Demonstrates scaling the network with additional repeater nodes.

---

## Getting Started

### Environment Setup

#### JupyterHub (JH)

QNPack is pre-installed inside the JupyterHub container image.
If you're using JupyterHub, you can run the example notebooks without any setup.

#### NetSquid Registry Authentication

NetSquid packages are hosted on a private PyPI registry at `https://pypi.netsquid.org`.
You must first register for an account at [https://netsquid.org](https://netsquid.org), then
configure authentication via a `~/.netrc` file:

```bash
cat > ~/.netrc << 'EOF'
machine pypi.netsquid.org
  login YOUR_NETSQUID_USERNAME
  password YOUR_NETSQUID_PASSWORD
EOF
chmod 600 ~/.netrc
```

Replace `YOUR_NETSQUID_USERNAME` and `YOUR_NETSQUID_PASSWORD` with your netsquid.org credentials.
This file is used automatically by both `uv` and `pip` for registry authentication.

#### Installation with uv (Recommended)

[uv](https://docs.astral.sh/uv/) provides fast, reproducible Python environment management.
QNPack is pre-configured with a `[[tool.uv.index]]` entry in `pyproject.toml` that points to the
netsquid private registry, so all dependencies (including `netsquid` and `netsquid-trappedions`)
are resolved automatically.

1. **Install uv** (if not already installed):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Create the environment and install all dependencies**:

   ```bash
   uv sync
   ```

   This creates a `.venv/` in the project directory with Python 3.12 and all packages installed.

3. **Run QNPack**:

   ```bash
   uv run qnpack --help          # run via the installed console script
   uv run python script.py       # run any script in the environment
   source .venv/bin/activate      # or activate the venv traditionally
   ```

#### Installation with pip

1. **Install NetSquid and Dependencies**
   Ensure your `~/.netrc` is configured (see above), then install:

   ```bash
   pip3 install --extra-index-url https://pypi.netsquid.org netsquid netsquid-trappedions netsquid-netconf
   ```

2. **Install QNPack**
   From inside the QNPack source directory:

   ```bash
   pip install -e .
   ```
