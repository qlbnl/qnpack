import netsquid as ns
import numpy as np
import math
from netsquid.qubits import operators as ops
from netsquid.util import cymath, simtools
from netsquid.qubits.qformalism import get_qstate_formalism
from netsquid.qubits.qubitapi import _qrepr, _to_qubits_list, operate, multi_operate
from netsquid.components.models import T1T2NoiseModel


class myT1T2NoiseModel(T1T2NoiseModel):
    """Allow a rng to be passed inside
    """

    def __init__(self, T1=0, T2=0, my_rng=None, **kwargs):
        super().__init__(T1=T1, T2=T2, **kwargs)
        self.my_rng = my_rng
        # print("inside myT1T2NoiseModel",my_rng)

    def error_operation(self, qubits, delta_time=0, **kwargs):
        """Error operation to apply to qubits.

        Parameters
        ----------
        qubits : tuple of :obj:`~netsquid.qubits.qubit.Qubit`
            Qubits to apply noise to.
        delta_time : float, optional
            Time qubits have spent on component [ns].

        """
        # print(qubits,"inside error_operation() of myT1T2NoiseModel")
        for qubit in qubits:
            self.apply_noise(qubit, delta_time)

    def _random_pauli_noise(self, qubit, probI, probX, probY, probZ):
        # For now, just apply standard noise.
        # ns.qubits.qubitapi.apply_pauli_noise(qubit, (probI, probX, probY, probZ))
        # print(f'{ns.sim_time():.1f}: memory noise model inside _random_pauli_noise",{qubit},{probI}, {probX}, {probY}, {probZ}')
        my_apply_pauli_noise(qubit, (probI, probX, probY, probZ), my_rng=self.my_rng)


class myEmitterT1T2NoiseModel(T1T2NoiseModel):
    """Only apply noise on emitter qubit, not ancilla qubit
    """

    def __init__(self, T1=0, T2=0, my_rng=None, **kwargs):
        super().__init__(T1=T1, T2=T2, **kwargs)
        self.my_rng = my_rng
        # print("inside myT1T2NoiseModel",my_rng)

    def error_operation(self, qubits, delta_time=0, **kwargs):
        """Error operation to apply to qubits.

        Parameters
        ----------
        qubits : tuple of :obj:`~netsquid.qubits.qubit.Qubit`
            Qubits to apply noise to.
        delta_time : float, optional
            Time qubits have spent on component [ns].

        """

        # assert len(qubits)==2,"CZ gate is applied on more than 2 qubits in myCZT1T2NoiseModel"
        qubit = qubits[0]
        # print(qubit,"in",qubits,"inside error_operation() of myCZT1T2NoiseModel")
        # print(f'{ns.sim_time():.1f}:inside error_operation, delta_time={delta_time},{qubit}')
        self.apply_noise(qubit, delta_time)

    def _random_pauli_noise(self, qubit, probI, probX, probY, probZ):
        # For now, just apply standard noise.
        # ns.qubits.qubitapi.apply_pauli_noise(qubit, (probI, probX, probY, probZ))
        #print(f'{ns.sim_time():.1f}:inside _random_pauli_noise",{qubit},{probI}, {probX}, {probY}, {probZ}')
        my_apply_pauli_noise(qubit, (probI, probX, probY, probZ), my_rng=self.my_rng)


def my_apply_pauli_noise(qubit, p_weights, my_rng=None):
    """Randomly apply pauli noise to a qubit according probability weights.
    Code is adapted from netsquid.qubits.qubitapi.apply_pauli_noise(). The only difference is to pass a custom parameter 'my_rng' 
    to be used during my_stocastic_operate().

    """
    if my_rng == None:
        my_rng = simtools.get_random_state()
    if len(p_weights) != 4:
        raise ValueError(f"length of p_weights tuple {len(p_weights)} != 4")
    if not math.isclose(sum(p_weights), 1.):
        raise ValueError("Input probability weights (p_weights) must sum to one")
    if not np.all([0 <= p <= 1. for p in p_weights]):
        raise ValueError("Input probability weights cannot be negative")
    if p_weights[0] == 1.0:
        return
    if get_qstate_formalism().supports_mixed_states:
        my_stochastic_operate([qubit], [ops.I, ops.X, ops.Y, ops.Z], p_weights=p_weights, my_rng=my_rng)
    else:
        if my_rng.random_sample() > p_weights[0]:
            # print(f'{ns.sim_time():.1f}:inside_my_apply_pauli_noise,going to apply my_stochastic_operate to {qubit}')
            if p_weights[0] == 0.:
                p_weights = p_weights[1:]
            else:
                p_weights = np.array(p_weights[1:])
                p_weights = tuple(p_weights / np.sum(p_weights))
            my_stochastic_operate([qubit], [ops.X, ops.Y, ops.Z], p_weights=p_weights, my_rng=my_rng)


def my_stochastic_operate(qubits, operators, p_weights=None, my_rng=None):
    """Stochastically apply a list of quantum operators to a qubit or list of qubits.
    Code is adapted from netsquid.qubits.qubitapi.stocastic_operate(). The only difference is to pass a custom parameter 'my_rng' 
    to be used. 

    """
    if my_rng == None:
        my_rng = simtools.get_random_state()
    if p_weights is None:
        p_weights = tuple(np.ones(len(operators)) / len(operators))
    elif len(p_weights) != len(operators) or \
            not cymath.isclose(sum(p_weights), 1., rel_tol=1e-5):
        raise ValueError("Invalid 'p_weights' parameter specified")
    qubits = _to_qubits_list(qubits, combine=True)
    if _qrepr(qubits).supports_mixed_states:
        multi_operate(qubits, operators, p_weights)
    else:
        operator = operators[my_rng.choice(len(operators), p=p_weights)]
        # print(f'{ns.sim_time():.1f}:inside_my_stochastic_operate, operate on {qubits} by {operator}')
        operate(qubits, operator)
