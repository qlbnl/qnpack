import itertools
from pytket.qasm import circuit_from_qasm_str
from pytket.extensions.qiskit import AerBackend


# ─────────────────────────────────────────────
# 1. CORRECT QAOA QASM GENERATOR (MaxCut)
# ─────────────────────────────────────────────
def generate_qaoa_qasm(n_qubits, edges, gammas, betas):

    if len(gammas) != len(betas):
        raise ValueError("gammas and betas must match")

    p = len(gammas)

    lines = [
        'OPENQASM 2.0;',
        'include "qelib1.inc";',
        f'qreg q[{n_qubits}];',
        f'creg c[{n_qubits}];'
    ]

    # ── Initial state ──
    lines.append('// Initial state')
    for i in range(n_qubits):
        lines.append(f'h q[{i}];')

    # ── QAOA layers ──
    for layer in range(p):
        gamma = gammas[layer]
        beta = betas[layer]

        lines.append(f'\n// --- Layer {layer+1} ---')

        # ── COST HAMILTONIAN ──
        lines.append('// Cost Hamiltonian (MaxCut ZZ)')
        for i, j in edges:
            lines.append(f'cx q[{i}], q[{j}];')
            lines.append(f'rz({-gamma}) q[{j}];')       # ✅ -gamma
            lines.append(f'cx q[{i}], q[{j}];')

        # ── MIXER ──
        lines.append('// Mixer Hamiltonian')
        for i in range(n_qubits):
            lines.append(f'rx({2 * beta}) q[{i}];')

    # ── Measurement ──
    lines.append('\n// Measurement')
    for i in range(n_qubits):
        lines.append(f'measure q[{i}] -> c[{i}];')

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 2. MAXCUT COST FUNCTION
# ─────────────────────────────────────────────
def maxcut_value(bitstring, edges):
    return sum(1 for i, j in edges if bitstring[i] != bitstring[j])


# ─────────────────────────────────────────────
# 3. BRUTE FORCE OPTIMUM
# ─────────────────────────────────────────────
def brute_force_maxcut(n_qubits, edges):
    best_cost = -1
    best_states = []

    for bits in itertools.product('01', repeat=n_qubits):
        b = ''.join(bits)
        c = maxcut_value(b, edges)

        if c > best_cost:
            best_cost = c
            best_states = [b]
        elif c == best_cost:
            best_states.append(b)

    return best_cost, best_states


# ─────────────────────────────────────────────
# 4. ENDIANNESS FIX (IMPORTANT)
# ─────────────────────────────────────────────
def tuple_to_bitstring(t):
    return ''.join(str(b) for b in t)


# ─────────────────────────────────────────────
# 5. CONFIG
# ─────────────────────────────────────────────
N_QUBITS = 9

# FIX: Use complete graph instead of ring graph
# This ensures all qubits interact, even when distributed across QPUs
edges = [(i, j) for i in range(N_QUBITS) for j in range(i+1, N_QUBITS)]

gammas = [0.8, 1.2, 1.6, 2.0]
betas  = [0.4, 0.3, 0.2, 0.1]

# gammas = [0.75, 0.75]
# betas = [0.5, 0.25]

SHOTS = 1000

# ─────────────────────────────────────────────
# 5.5 CONSISTENCY CHECKS
# ─────────────────────────────────────────────
assert len(gammas) == len(betas), "Gammas and betas must have same length"
assert all(len(e) == 2 for e in edges), "All edges must be pairs"
assert all(0 <= i < N_QUBITS and 0 <= j < N_QUBITS for i, j in edges), \
    "All edge indices must be in range [0, N_QUBITS)"

print("✅ Configuration validated:")
print(f"   Qubits: {N_QUBITS}")
print(f"   Edges: {len(edges)} (complete graph)")
print(f"   QAOA layers: {len(gammas)}")
print(f"   Gammas: {gammas}")
print(f"   Betas: {betas}")
print()

print("Edges:", edges)
print("Total edges:", len(edges))
for i, j in edges[:3]:
    print(i, j)
# ─────────────────────────────────────────────
# 6. BUILD CIRCUIT
# ─────────────────────────────────────────────
qasm = generate_qaoa_qasm(N_QUBITS, edges, gammas, betas)
print(qasm)

circ = circuit_from_qasm_str(qasm, maxwidth=64)

backend = AerBackend()
compiled = backend.get_compiled_circuit(circ)


# ─────────────────────────────────────────────
# 7. RUN
# ─────────────────────────────────────────────
print(f"\nRunning QAOA (p={len(gammas)}, qubits={N_QUBITS})")

handle = backend.process_circuit(compiled, n_shots=SHOTS)
result = backend.get_result(handle)
counts = result.get_counts()

sorted_counts = dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))


# ─────────────────────────────────────────────
# 8. TOP RESULTS
# ─────────────────────────────────────────────
print("\nTop 3 results:")

top5 = list(sorted_counts.items())[:3]

for out, c in top5:
    print(f"{tuple_to_bitstring(out)} : {c}")


# ─────────────────────────────────────────────
# 9. QAOA VERIFICATION
# ─────────────────────────────────────────────
print("\nVerification (Top 3):")

best_state = None
best_cost = -1

for out, c in top5:
    b = tuple_to_bitstring(out)
    cost = maxcut_value(b, edges)

    if cost > best_cost:
        best_cost = cost
        best_state = b

    print(f"{b} | hits={c} | cost={cost}")

print(f"\nBest QAOA state: {best_state} (cost={best_cost})")


# ─────────────────────────────────────────────
# 10. TRUE OPTIMUM
# ─────────────────────────────────────────────
opt_cost, opt_states = brute_force_maxcut(N_QUBITS, edges)
assert opt_cost <= len(edges)
print(f"\nOptimal MaxCut: {opt_cost}")
print(f"Number of optimal states: {len(opt_states)}")


# ─────────────────────────────────────────────
# 11. FINAL METRIC
# ─────────────────────────────────────────────
ratio = best_cost / opt_cost
print(f"\nApproximation ratio: {ratio:.3f}")

if best_cost == opt_cost:
    print("✅ Optimal solution found!")
else:
    print("⚠️ Suboptimal QAOA solution")