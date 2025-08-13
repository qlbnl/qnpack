# QNPack: Modeling and Simulation of Quantum Repeater Networks

QNPack is a simulation toolkit for modeling and analyzing both **1G (memory-based)** and **All-Photonic** quantum repeater architectures.  
It enables rapid prototyping and experimentation using NetSquid-based simulations, supporting advanced concepts such as entanglement swapping, purification, and error correction.

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

#### Source Installation

1. **Install NetSquid and Dependencies**  
   Register at [http://netsquid.org](http://netsquid.org) and install the following packages:

   ```bash
   pip3 install --extra-index-url https://pypi.netsquid.org netsquid netsquid-trappedions netsquid-netconf
   ```

2. **Install QNPack**  
   From inside the QNPack source directory:

   ```bash
   pip3 install -r requirements.txt
   pip install -e .
   ```

---
