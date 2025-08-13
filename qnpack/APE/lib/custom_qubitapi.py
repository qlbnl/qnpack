import numpy as np
from netsquid.qubits.operators import *
from netsquid.qubits import operators as ops
from netsquid.qubits.qubitapi import operate,discard,assign_qstate,reduced_dm,_qrepr,_idx,_to_qubits_list
from netsquid.qubits.qubit import Qubit
from netsquid.qubits.qstate import QStateCombineError, QState
from netsquid.qubits.qformalism import get_qstate_formalism

def my_measure(qubit, observable=ops.Z, keep_combined=False, discard=False,rng_measure=None):
    """Projectively measure a qubit. 
    Code is adapted from netsquid.qubits.qubitapi.measure(). The only difference is to pass a custom parameter 'rng_measure' 
    to be used during measurement.
    """
    # If discarding then always drop the qubit (i.e. do not keep state combined)
    if discard:
        drop_qubit = True
    else:
        drop_qubit = not keep_combined
    if not isinstance(qubit, Qubit):
        raise TypeError("The qubit given must be a qubit object")
    if qubit.qstate is None:
        raise ValueError("Cannot measure a qstate that is None.")
    if not drop_qubit:
        _, m, p = _qrepr(qubit).measure(_idx(qubit)[0], observable, modify=True,rng=rng_measure)
        return m, p
    qrepr, m, p = _qrepr(qubit).measure_discard(_idx(qubit)[0], observable,rng=rng_measure)
    qubit.qstate.drop_qubit(qubit, new_qrepr=qrepr)
    if not discard:
        QState([qubit], get_qstate_formalism().create_in_basis([m], observable))
    return m, p


def my_gmeasure(qubits, meas_operators, check_operators=False,rng_measure=None):
    """Make a general qubit measurement with the specified measurement operators.
    Code is adapted from netsquid.qubits.qubitapi.gmeasure(). The only difference is to pass a custom parameter 'rng_measure' 
    to be used during measurement.
    """
    if check_operators:
        if isinstance(meas_operators, ops.Operator):
            if not meas_operators.is_hermitian:
                raise ValueError("The observable is not Hermitian.")
        else:
            ops.check_measurement_operators(meas_operators)
    qubits = _to_qubits_list(qubits, combine=True)
    _, m, p = _qrepr(qubits).gmeasure(_idx(qubits), meas_operators, modify=True,rng=rng_measure)
    return m, p