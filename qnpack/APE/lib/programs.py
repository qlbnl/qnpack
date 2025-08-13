import numpy as np
import netsquid.components.instructions as instr
from netsquid.components.qprogram import QuantumProgram
from netsquid.components.qprocessor import PhysicalInstruction
from netsquid.qubits import qubitapi as qapi
from netsquid.qubits import operators as ops
from qnpack.common.utils import ForcedRNG
from qnpack.APE.lib.custom_qubitapi import my_measure
from qnpack.APE.lib.custom_errormodels import (
    myT1T2NoiseModel,
    myEmitterT1T2NoiseModel
)


class myIMeasure(instr.IMeasure):
    """Overwrite execute() to pass a RNG inside. Only aim to perform single-qubit Clifford measurement here.
    Instruction to do a measurement.

    Default is to create an instruction that measures in the standard basis.

    Parameters
    ----------
    name : str
        Name of instruction for identification purposes.
    observable : :obj:`~netsquid.qubits.operators.Operator`, optional
        Hermitian operator to measure qubit with. Default is ``Z`` i.e.
        the standard basis.
    meas_operators : list of :obj:`~netsquid.qubits.operators.Operator`, optional
        List of measurement operators to measure qubit(s) with. If not None,
        this will override the ``observable`` parameter.

    """

    def __init__(self, name, observable=ops.Z, meas_operators=None, rng_measure=None):
        self._name = name
        if not isinstance(observable, ops.Operator):
            raise TypeError("{} is not an Operator".format(observable))
        self._observable = observable
        self._meas_operators = meas_operators
        self._rng_measure = rng_measure

    def execute(self, quantum_memory, positions, *args, meas_operators=None, inplace=True, **kwargs):
        r"""Execute instruction on a quantum memory.

        Parameters
        ----------
        quantum_memory : :obj:`~netsquid.components.qmemory.QuantumMemory`
            Quantum memory to execute instruction on.
        positions : list of int
            Memory positions to do instruction on.
        meas_operators : :obj:`~netsquid.qubits.operators.Operator`, optional
            Measurement operators, which if not ``None`` will override the
            default measurement observable or operators. Can be used to do noisy measurements.
            A list of operators :math:`M_i` that should satisfy the
            completeness equation :math:`\sum_i M_i^\dagger M_i = I`, though this is not checked.
        inplace : bool, optional
            Whether to keep the qubit on the memory position, or remove it.
        \*args : list
            Additional arguments that can be used to extend this method.
        \*\*kwargs : dict
            Keyword arguments that can be used to to extend this method.

        Returns
        -------
        list of int
            List of 0 or 1 for positive or negative eigenvalue of observable, respectively.
            Or in case of measurement operators the index of the operator
            that succeeded.

        Notes
        -----
            For the measurement output to be modifiable by a classical noise model,
            it must be a mutable object, hence we always return a list.

        """
        meas_operators = meas_operators if meas_operators else self._meas_operators

        assert len(positions) == 1, "More than one qubit for myIMeasure"
        qubit_position = positions[0]

        [qubit] = quantum_memory.peek(qubit_position)
        # print("inside myIMeasure",self._rng_measure)
        results, prob = my_measure(qubit, self._observable, rng_measure=self._rng_measure)
        # qapi.operate([emitter_qubit, emission_qubit], ops.CNOT)

        # Important that we return a mutable list for classical noise models
        # results = quantum_memory.measure(positions, observable=self._observable,
        #                                 meas_operators=meas_operators,
        #                                 discard=not inplace)[0]
        # if not inplace:
        #     super().pop(positions)
        # return results
        return [results]


class IRx(instr.IRotationGate):
    """Instruction to perform rotation x. Used in ancilla qubit for performing local complementation of graph state
    """
    @property
    def num_positions(self):
        return 1

    def execute(self, quantum_memory, positions, angle=np.pi/2, axis=(1, 0, 0), *args, **kwargs):
        return super().execute(quantum_memory, positions, angle=angle, axis=axis, *args,  **kwargs)


class IEmitPhoton(instr.Instruction):
    """Instruction to emit a qubit that is entangled with a qubit in memory.
    The emitted qubit is put in a message on the qout port.
    """

    @property
    def name(self):
        return "emit_photon"

    @property
    def num_positions(self):
        return 1

    def execute(self, quantum_memory, positions, *args, **kwargs):
        """Perform emission of entangled qubit.

        Parameters
        ----------
        quantum_memory : :obj:`~netsquid.components.qmemory.QuantumMemory`
            Quantum memory to execute instruction on.
        positions : list of int, length 2
            Memory positions involved in emission.
            The first is the position of the memory qubit that is entangled with the emitted qubit,
            the second is the auxiliary position used to perform the emission.
        \\*args : list
            Additional arguments that can be used to extend this method.
        \\*\\*kwargs : dict
            Keyword arguments that can be used to to extend this method.

        """
        emitter_position = positions[0]
        # create photon
        [emitter_qubit] = quantum_memory.peek(emitter_position)
        # [emission_qubit] = qapi.create_qubits(1)
        photon_cnt = quantum_memory.properties["emitted_photon_cnt"]
        [emission_qubit] = qapi.create_qubits(1, system_name=f"{quantum_memory.name}_{photon_cnt}-")
        quantum_memory.properties["emitted_photon_cnt"] += 1
        qapi.operate([emitter_qubit, emission_qubit], ops.CNOT)
        # print(f'{ns.sim_time():.1f}:IEmitPhoton is executed with photonic qubit {emission_qubit}')
        # print(f'{ns.sim_time()}:IEmitPhoton is executed with photonic qubit {emission_qubit}')
        # print(quantum_memory)
        quantum_memory.ports[f"qout{emitter_position}"].tx_output(emission_qubit)


class EndNodeEmitterInitProgram(QuantumProgram):
    """Program to initialize matter qubit before each photon emission in end node
        """

    def __init__(self):
        super().__init__(num_qubits=1)

    def program(self):
        [emitter_index] = self.get_qubit_indices(self.num_qubits)
        self.apply(instr.INSTR_INIT, [emitter_index])
        self.apply(instr.INSTR_H, [emitter_index])
        yield self.run()


class EmitterInitProgram(QuantumProgram):
    """Program to initialize quantum emitter and entangle it with ancilla. It is used every time after the emitter is being measured. 
    """

    def __init__(self):
        super().__init__(num_qubits=2)

    def program(self):
        emitter_index, ancilla_index = self.get_qubit_indices(self.num_qubits)
        self.apply(instr.INSTR_INIT, [emitter_index])
        # print(f"{ns.sim_time():.1f}:instr.INSTR_INIT finished in EmitterInitProgram")
        self.apply(instr.INSTR_H, [emitter_index])
        # print(f"{ns.sim_time():.1f}:instr.INSTR_H finished in EmitterInitProgram")
        self.apply(instr.INSTR_CZ, [emitter_index, ancilla_index])
        # print(f"{ns.sim_time():.1f}:instr.INSTR_CZ finished in EmitterInitProgram")
        yield self.run()


class EmitterAncillaInitProgram(QuantumProgram):
    """Program to initialize quantum emitter and ancilla in the very beginning.
    """

    def __init__(self):
        super().__init__(num_qubits=2)

    def program(self):
        emitter_index, ancilla_index = self.get_qubit_indices(self.num_qubits)
        # self.apply(instr.INSTR_INIT, [emitter_index, ancilla_index])
        self.apply(instr.INSTR_INIT, [emitter_index])
        self.apply(instr.INSTR_INIT, [ancilla_index])
        self.apply(instr.INSTR_H, [emitter_index])
        self.apply(instr.INSTR_H, [ancilla_index])
        self.apply(instr.INSTR_CZ, [emitter_index, ancilla_index])
        yield self.run()


class EmitterAncillaInitProgramWithoutTree(QuantumProgram):
    """Program to initialize quantum emitter and ancilla in the very beginning.
    """

    def __init__(self):
        super().__init__(num_qubits=2)

    def program(self):
        emitter_index, ancilla_index = self.get_qubit_indices(self.num_qubits)
        # self.apply(instr.INSTR_INIT, [emitter_index, ancilla_index])
        self.apply(instr.INSTR_INIT, [emitter_index])
        self.apply(instr.INSTR_INIT, [ancilla_index])
        self.apply(instr.INSTR_H, [emitter_index])
        self.apply(instr.INSTR_H, [ancilla_index])
        self.apply(instr.INSTR_CZ, [emitter_index, ancilla_index])
        yield self.run()


def get_apeqr_node_instructions(cfg, noise=False, rng_noise=None, rng_measure=None):

    if not noise:
        emitter_noise_model = None
    else:
        # Allowed physical instructions on quantum processor in apeqr node
        # Later verify different apeqr node noise use same rng_noise
        emitter_noise_model = myEmitterT1T2NoiseModel(T1=cfg.emitter.emitter_T1,
                                                      T2=cfg.emitter.emitter_T2,
                                                      my_rng=rng_noise)

    phys_instructions = [
        # Here if we do not specify topology of INSTR_INIT, the noise model on quantum processor applies extra error on emitter during the following Hadamard gate due to unknown reason.
        PhysicalInstruction(instr.INSTR_INIT, duration=cfg.emitter.INIT_duration, parallel=True, topology=[0]),
        PhysicalInstruction(instr.INSTR_INIT, duration=cfg.emitter.INIT_duration, parallel=True, topology=[1]),
        PhysicalInstruction(instr.INSTR_INIT, duration=cfg.emitter.INIT_duration, parallel=True, topology=[2]),
        PhysicalInstruction(instr.INSTR_H, duration=cfg.emitter.H_duration, parallel=True,
                            topology=[0], quantum_noise_model=emitter_noise_model),
        PhysicalInstruction(instr.INSTR_H, duration=cfg.emitter.H_duration, parallel=True, topology=[1]),
        PhysicalInstruction(instr.INSTR_H, duration=cfg.emitter.H_duration, parallel=True, topology=[2]),
        PhysicalInstruction(INSTR_EMIT_PHOTON, duration=cfg.emitter.EMIT_PHOTON_duration, parallel=False, topology=[
                            0], quantum_noise_model=emitter_noise_model, apply_q_noise_after=False),
        PhysicalInstruction(instr.INSTR_CZ, duration=cfg.emitter.CZ_duration, topology=[
                            (0, 1)], quantum_noise_model=emitter_noise_model),
        PhysicalInstruction(instr.INSTR_CZ, duration=cfg.emitter.CZ_duration, topology=[
                            (0, 2)], quantum_noise_model=emitter_noise_model),
        PhysicalInstruction(instr.INSTR_CZ, duration=cfg.emitter.CZ_duration, topology=[
                            (1, 2)], quantum_noise_model=emitter_noise_model),
        # PhysicalInstruction(instr.INSTR_MEASURE, duration=cfg.emitter.MEASURE_duration, parallel=False, topology=[0],quantum_noise_model=emitter_noise_model,apply_q_noise_after=False),
        PhysicalInstruction(my_INSTR_MEASURE_Z, duration=cfg.emitter.MEASURE_duration, parallel=False, topology=[
                            0], quantum_noise_model=emitter_noise_model, apply_q_noise_after=False),
        PhysicalInstruction(my_INSTR_MEASURE_X, duration=cfg.emitter.MEASURE_duration, parallel=False, topology=[
                            0], quantum_noise_model=emitter_noise_model, apply_q_noise_after=False),
        PhysicalInstruction(my_INSTR_MEASURE_X, duration=cfg.emitter.MEASURE_duration, parallel=False, topology=[1]),
        PhysicalInstruction(my_INSTR_MEASURE_Y, duration=cfg.emitter.MEASURE_duration, parallel=False, topology=[2]),
        PhysicalInstruction(INSTR_Rx, duration=cfg.emitter.H_duration, parallel=False, topology=[1]),
        PhysicalInstruction(INSTR_Rx, duration=cfg.emitter.H_duration, parallel=False, topology=[2])
    ]
    return phys_instructions


def get_apeqr_node_instructions_withoutTree(cfg, noise=False, rng_noise=None):

    if not noise:
        emitter_noise_model = None
    else:
        # Allowed physical instructions on quantum processor in apeqr node
        # Later verify different apeqr node noise use same rng_noise
        emitter_noise_model = myEmitterT1T2NoiseModel(T1=cfg.emitter.emitter_T1,
                                                      T2=cfg.emitter.emitter_T2,
                                                      my_rng=rng_noise)

    phys_instructions = [
        # Here if we do not specify topology of INSTR_INIT, the noise model on quantum processor applies extra error on emitter during the following Hadamard gate due to unknown reason.
        PhysicalInstruction(instr.INSTR_INIT, duration=cfg.emitter.INIT_duration, parallel=True, topology=[0]),
        PhysicalInstruction(instr.INSTR_INIT, duration=cfg.emitter.INIT_duration, parallel=True, topology=[1]),
        PhysicalInstruction(instr.INSTR_H, duration=cfg.emitter.H_duration, parallel=True,
                            topology=[0], quantum_noise_model=emitter_noise_model),
        PhysicalInstruction(instr.INSTR_H, duration=cfg.emitter.H_duration, parallel=True, topology=[1]),
        PhysicalInstruction(INSTR_EMIT_PHOTON, duration=cfg.emitter.EMIT_PHOTON_duration, parallel=False, topology=[
                            0], quantum_noise_model=emitter_noise_model, apply_q_noise_after=False),
        PhysicalInstruction(instr.INSTR_CZ, duration=cfg.emitter.CZ_duration, topology=[
                            (0, 1)], quantum_noise_model=emitter_noise_model),
        PhysicalInstruction(instr.INSTR_MEASURE, duration=cfg.emitter.MEASURE_duration, parallel=False, topology=[
                            0], quantum_noise_model=emitter_noise_model, apply_q_noise_after=False),
        PhysicalInstruction(instr.INSTR_MEASURE, duration=cfg.emitter.MEASURE_duration, parallel=False, topology=[1]),
        PhysicalInstruction(INSTR_Rx, duration=cfg.emitter.H_duration, parallel=False, topology=[1])
    ]
    return phys_instructions


def get_end_node_instructions(cfg, rng_noise):

    memory_noise_model = myT1T2NoiseModel(T1=0, T2=3000, my_rng=rng_noise)

    INSTR_EMIT_PHOTON = IEmitPhoton()
    # Allowed physical instructions on quantum processor in apeqr node

    matter_qubits = list(range(cfg.rgs.num_branches_half ))
    phys_instructions = [
        PhysicalInstruction(instr.INSTR_INIT, duration=cfg.emitter.INIT_duration),
        PhysicalInstruction(instr.INSTR_H, duration=cfg.emitter.H_duration, parallel=True,
                            topology=matter_qubits),
        PhysicalInstruction(INSTR_EMIT_PHOTON, duration=cfg.emitter.EMIT_PHOTON_duration,
                            parallel=False, topology=matter_qubits),
        PhysicalInstruction(INSTR_EMIT_PHOTON, duration=cfg.emitter.EMIT_PHOTON_duration,
                            parallel=False, topology=matter_qubits),
        PhysicalInstruction(instr.INSTR_I, duration=1,
                            parallel=False, topology=[0], quantum_noise_model=memory_noise_model),

        PhysicalInstruction(instr.INSTR_MEASURE, duration=20,
                            parallel=False, topology=matter_qubits)
        # PhysicalInstruction(my_INSTR_MEASURE_Z, duration=cfg.emitter.MEASURE_duration,
        #                   parallel=False, topology=matter_qubits)
    ]
    return phys_instructions


INSTR_EMIT_PHOTON = IEmitPhoton()
INSTR_Rx = IRx(name="INSTR_Rx")
INSTR_MEASURE_Y = instr.IMeasure("measure_y", observable=ops.Y)

# rng_measure_mem=np.random.RandomState(0)
rng_measure_mem = ForcedRNG(0)

my_INSTR_MEASURE_Z = myIMeasure("measure_z", observable=ops.Z, rng_measure=rng_measure_mem)
my_INSTR_MEASURE_Y = myIMeasure("measure_y", observable=ops.Y, rng_measure=rng_measure_mem)
my_INSTR_MEASURE_X = myIMeasure("measure_x", observable=ops.X, rng_measure=rng_measure_mem)
