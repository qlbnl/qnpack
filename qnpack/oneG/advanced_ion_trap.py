from netsquid.qubits.ketstates import BellIndex
from netsquid_trappedions.instructions import IonTrapMSGate, IonTrapMultiQubitRotation
from netsquid.components.instructions import INSTR_ROT_Z, INSTR_MEASURE, INSTR_EMIT, INSTR_MEASURE_BELL
from netsquid.components import QuantumProgram, INSTR_INIT
import logging
import numpy as np
import random as rand
# import matplotlib.pyplot as plt
from netsquid_trappedions.ion_trap import IonTrap
from netsquid.qubits import qubitapi as qapi
# from netsquid.qubits import ketstates as ks
from netsquid.qubits.state_sampler import StateSampler
from netsquid.qubits.kettools import KetRepr
from netsquid.components.instructions import Instruction
from netsquid.components.qprogram import QuantumProgram
from netsquid.components.qprocessor import PhysicalInstruction
from netsquid.components.instructions import INSTR_X, INSTR_Z, IEmit
from netsquid.qubits import operators as ops
from qnpack.common.config import Config
from qnpack.common.logging import setup_logging
from netsquid.components.models import DepolarNoiseModel
from netsquid.qubits.sparsedmtools import SparseDMRepr
from itertools import combinations
import netsquid as ns

log = logging.getLogger(__name__)

ms_instruction = IonTrapMSGate(2, np.pi / 2)


class InitProgram(QuantumProgram):

    default_num_qubits = 1

    def program(self):
        memory_position = self.get_qubit_indices(1)
        self.apply(instruction=INSTR_INIT, qubit_indices=[
                   memory_position])
        yield self.run()


class RInitProgram(QuantumProgram):

    default_num_qubits = 2

    def program(self):
        memory_position1, memory_position2 = self.get_qubit_indices(2)
        self.apply(instruction=INSTR_INIT,
                   qubit_indices=[memory_position1, memory_position2])
        yield self.run()


class AdvIonTrapSwapProgram(QuantumProgram):
    """
    Internal working
    ----------------
    A few private attributes:
      * _NAME_OUTCOME_CONTROL : str
      * _NAME_OUTCOME_TARGET : str
      * _OUTCOME_TO_BELL_INDEX : dict with keys (int, int) and values :class:`netsquid.qubits.ketstates.BellIndex`

           Indicates how the two measurement outcomes are related to the
           state that is measured. Its keys are tuples of the two measurement
           outcomes (control, target) and its values is the Bell state index.
    """

    default_num_qubits = 2
    _NAME_OUTCOME_CONTROL = "control-qubit-outcome"
    _NAME_OUTCOME_TARGET = "target-qubit-outcome"
    _OUTCOME_TO_BELL_INDEX = {(1, 1): BellIndex.PHI_PLUS, (0, 1): BellIndex.PSI_PLUS,
                              (1, 0): BellIndex.PSI_MINUS, (0, 0): BellIndex.PHI_MINUS}
    keep_measured_qubits = False

    def program(self):
        q1, q2 = self.get_qubit_indices(2)
        self.apply(INSTR_ROT_Z, q1, angle=np.pi / 4)
        self.apply(INSTR_ROT_Z, q2, angle=-np.pi / 4)
        self.apply(ms_instruction, qubit_indices=[q1, q2])
        self.apply(INSTR_MEASURE, q1, output_key=self._NAME_OUTCOME_CONTROL,
                   keep=self.keep_measured_qubits)
        self.apply(INSTR_MEASURE, q2, output_key=self._NAME_OUTCOME_TARGET,
                   keep=self.keep_measured_qubits)
        yield self.run()
        self.output["bell_index"] = self.get_outcome_as_bell_index

    @property
    def get_outcome_as_bell_index(self):
        m_outcome_control = self.output[self._NAME_OUTCOME_CONTROL][0]
        m_outcome_target = self.output[self._NAME_OUTCOME_TARGET][0]
        return self._OUTCOME_TO_BELL_INDEX[(m_outcome_control, m_outcome_target)]


class IPhotonIonTrap(Instruction):

    @property
    def name(self):
        return "emit_ent_qubit"

    @property
    def num_positions(self):
        return 2

    def execute(self, quantum_memory, positions, *args, **kwargs):
        """Perform emission of entangled qubit.
        """

        # Since only a |0> state can create an entangled photon, the qubit is measured.
        # Maybe it would be better to model this conditional emission by entangling the photon's presence
        # with the ion state, but since this would require qudits we instead collapse the wave function.
        # [memory_state], _ = quantum_memory.measure(memory_position)

        # # create photon
        # if memory_state == 1:
        #     log.debug("Inside emit instruction")
        #     # emission not possible
        #     # [emission_qubit] = qapi.create_qubits(1, no_state=True)
        #     log.debug("No photon emitted")
        # else:
        # create entangled pair
        emitter_position = positions[0]
        # create photon
        [memory_qubit] = quantum_memory.peek(emitter_position)
        [emission_qubit] = qapi.create_qubits(1)
        qapi.operate(memory_qubit, ops.H)
        qapi.operate([memory_qubit, emission_qubit], ops.CNOT)
        quantum_memory.ports[f"qout{emitter_position}"].tx_output(
            emission_qubit)
        log.debug(
            f"Matter qubit state in emit function after emission,{quantum_memory.peek(positions=emitter_position)[0].qstate.qrepr} {ns.sim_time()}")


ADV_EMIT = IPhotonIonTrap()
ADV_EMIT_RETRY = IPhotonIonTrap()  # write a diff name


class AdvEmitProgram(QuantumProgram):

    default_num_qubits = 2

    def program(self):
        memory_position, emission_position = self.get_qubit_indices()
        self.apply(instruction=ADV_EMIT, qubit_indices=[
                   memory_position, emission_position])
        yield self.run()


class AdvRetryEmitProgram(QuantumProgram):

    default_num_qubits = 2

    def program(self):
        memory_position, emission_position = self.get_qubit_indices()
        self.apply(instruction=ADV_EMIT_RETRY, qubit_indices=[
                   memory_position, emission_position])
        yield self.run()


class Adv_Ion_Trap(IonTrap):
    # extend ion trap class for fallback_to_nonphysical
    def __init__(self, cfg, noise_model, num_positions, coherence_time=0., init_depolar_prob=0., rot_z_depolar_prob=0.,
                 multi_qubit_xy_rotation_depolar_prob=0., ms_depolar_prob=0., emission_fidelity=1., measurement_duration=0,
                 collection_efficiency=1., emission_duration=0., ms_pi_over_2_duration=0, initialization_duration=0.,
                 prob_error_0=0., prob_error_1=0., z_depolar_prob=0, x_depolar_prob=0, z_gate_duration=0, x_gate_duration=0,
                 retry_duration=0, fallback_to_nonphysical=False):
        super().__init__(num_positions=num_positions, coherence_time=coherence_time, prob_error_0=prob_error_0,
                         prob_error_1=prob_error_1, init_depolar_prob=init_depolar_prob,
                         rot_z_depolar_prob=rot_z_depolar_prob,
                         multi_qubit_xy_rotation_depolar_prob=multi_qubit_xy_rotation_depolar_prob,
                         ms_depolar_prob=ms_depolar_prob, emission_fidelity=emission_fidelity,
                         collection_efficiency=collection_efficiency, emission_duration=emission_duration,
                         measurement_duration=measurement_duration, initialization_duration=initialization_duration,
                         z_rotation_duration=0., ms_pi_over_2_duration=ms_pi_over_2_duration,
                         multi_qubit_xy_rotation_duration=0., ms_optimization_angle=np.pi / 2)
        self.cfg = cfg
        self.noise_model = noise_model
        emit_topologies = [(ion_position, self.emission_position)
                           for ion_position in range(self.num_ions)]
        emit_instruction = PhysicalInstruction(instruction=ADV_EMIT,
                                               duration=self.properties["emission_duration"],
                                               topology=emit_topologies)
        emit_instruction1 = PhysicalInstruction(instruction=ADV_EMIT_RETRY,
                                                duration=retry_duration,
                                                topology=emit_topologies)
        # choose topologies such that auxiliary emission position ("cavity") is excluded
        one_ion_topologies = list(range(self.num_ions))

        any_ion_topologies = []
        for num_qubits in range(1, self.num_ions + 1):
            for topology in combinations(one_ion_topologies, num_qubits):
                any_ion_topologies.append(topology)

        emit_topologies = [(ion_position, self.emission_position)
                           for ion_position in range(self.num_ions)]

        x_gate_instruction = PhysicalInstruction(instruction=INSTR_X, duration=z_gate_duration,
                                                 parallel=False,
                                                 q_noise_model=DepolarNoiseModel(z_depolar_prob,
                                                                                 time_independent=True),
                                                 apply_q_noise_after=False,
                                                 topology=one_ion_topologies)
        z_gate_instruction = PhysicalInstruction(instruction=INSTR_Z, duration=x_gate_duration,
                                                 parallel=False,
                                                 q_noise_model=DepolarNoiseModel(x_depolar_prob,
                                                                                 time_independent=True),
                                                 apply_q_noise_after=False,
                                                 topology=one_ion_topologies)
        self.add_physical_instruction(emit_instruction)
        self.add_physical_instruction(x_gate_instruction)
        self.add_physical_instruction(z_gate_instruction)
        self.add_physical_instruction(emit_instruction1)

    def doppler_cooling(self, initial_velocity=None, ion_mass=None,
                        decay_rate=None, rabi_frequency=None,
                        laser_wavelength=None,
                        resonant_frequency=None,
                        oscillation_frequency=None,
                        doppler_sim_time=None):
        """
        Args:
        - initial_velocity (float): Initial velocity of the ion (m/s).
        - ion_mass (float): Mass of the ion (kg).
        - decay_rate (float): Decay rate of the excited state (1/s)..
        - laser_frequency (float): Frequency of the cooling laser (Hz).
        - resonant_frequency (float): Resonant frequency of the ion (Hz).
        - oscillation_frequency (float): Frequency of the ion's oscillatory motion (Hz).
        - max_simulation_time (float): Maximum time for the simulation (s).
        """
        initial_velocity = initial_velocity or self.cfg.ion_trap.initial_velocity
        ion_mass = ion_mass or self.cfg.ion_trap.ion_mass
        decay_rate = decay_rate or self.cfg.ion_trap.decay_rate
        rabi_frequency = rabi_frequency or self.cfg.ion_trap.rabi_frequency
        laser_wavelength = laser_wavelength or self.cfg.ion_trap.laser_wavelength
        resonant_frequency = resonant_frequency or self.cfg.ion_trap.resonant_frequency
        oscillation_frequency = oscillation_frequency or self.cfg.ion_trap.oscillation_frequency
        doppler_sim_time = doppler_sim_time or self.cfg.ion_trap.doppler_sim_time
        # Constants
        hbar = 1.0545718e-34  # Reduced Planck constant in J*s
        boltzmann_constant = 1.380649e-23  # Boltzmann constant in J/K
        speed_of_light = 3e8  # Speed of light in m/s
        recoil_kick = 2/5  # geometry factor reflects the average component of
        # the emission recoil kick along the x axis

        # Calculate the motional frequency
        # omega = 2 * np.pi * oscillation_frequency
        laser_frequency = speed_of_light / laser_wavelength
        wave_vector = (2 * np.pi * laser_wavelength) / speed_of_light

        # Calculate the detuning (delta) from the resonant frequency
        detuning = laser_frequency - resonant_frequency

        # Calculate the effective detuning including the Doppler shift
        effective_detuning = detuning - \
            (initial_velocity / speed_of_light) * laser_wavelength

        # Calculate the saturation parameter
        saturation_parameter = (2*np.abs(rabi_frequency)
                                ** 2) / (effective_detuning**2)

        # Calculate the excited state probability
        excited_state_probability = (saturation_parameter/2) / (
            1 + saturation_parameter + (((2*effective_detuning)/decay_rate) ** 2))

        # Calculate the cooling force
        cooling_force = hbar*wave_vector*decay_rate*excited_state_probability

        # Calculate the cooling rate (force per unit mass)
        cooling_rate = cooling_force / ion_mass
        log.debug(f"Excited state probability: {excited_state_probability}")
        log.debug(f"Wave vector: {wave_vector}")
        log.debug(f"Cooling force: {cooling_force}")
        log.debug(f"Cooling rate: {cooling_rate}")
        # Update the velocity after the cooling process (subtracting since it's cooling)
        final_velocity = initial_velocity - \
            (cooling_rate * (doppler_sim_time/1000000))
        log.debug(f"Final velocity: {final_velocity}")
        # Ensure the final velocity is not negative
        if final_velocity < 0:
            raise ValueError("Negative Final Velocity")

        # Calculate the final temperature
        final_temperature = (ion_mass * final_velocity**2) / \
            (boltzmann_constant * oscillation_frequency)

        T_min = hbar * decay_rate * \
            np.sqrt(1 + saturation_parameter) * \
            (1 + recoil_kick) / (4 * boltzmann_constant)

        # Calculate the mean excitation number
        # mean_excitation_number = 1 / (np.exp(hbar * omega / (boltzmann_constant * final_temperature)) - 1)
        # exponent = hbar * omega / (boltzmann_constant * final_temperature)
        # if exponent > 700:  # Large value threshold to prevent overflow
        #     # For large exponent, mean excitation number approaches zero
        #     mean_excitation_number = 0
        # else:
        #     mean_excitation_number = 1 / (np.exp(exponent) - 1)
        # log.debug("Mean excitation number", mean_excitation_number)

        # Ensure the mean excitation number is not below 0.484
        # if mean_excitation_number <= 0.484:
        #     raise ValueError("Reached Doppler Threshold")

        # Update the parameters based on mean excitation number and simulation time
        log.debug(f"Final temperature: {final_temperature}")
        log.debug(f"Minimum Temperature: {T_min}")
        if self.noise_model == 1:
            if doppler_sim_time > 0:
                if final_temperature <= T_min:
                    self.init_depolar_prob = self.cfg.ion_trap.init_depolar_prob
                    self.emission_fidelity = self.cfg.ion_trap.emission_fidelity
                    self.collection_efficiency = self.cfg.ion_trap.collection_efficiency
                    log.debug("Noisy values")
                else:
                    self.init_depolar_prob = 0.15
                    self.emission_fidelity = 0.97
                    self.collection_efficiency = 0.97
        else:
            self.init_depolar_prob = 0
            self.coherence_time = 0
            self.emission_fidelity = 1
            self.collection_efficiency = 1

        # return self.emission_fidelity

    def sideband_cooling(self, initial_mean_excitation_number=None,
                         decay_rate=None,
                         rabi_frequency=None,
                         lamb_dicke_parameter=None,
                         sideband_sim_time=None):
        """
        Args:
        - initial_mean_excitation_number (float): The initial mean excitation number from Doppler cooling.
        - decay_rate (float): Decay rate (G).
        - rabi_frequency (float): Rabi frequency (Ω).
        - detuning (float): Detuning (Δ).
        - lamb_dicke_parameter (float): Lamb-Dicke parameter (η).
        - sideband_simulation_time (float): Simulation time for sideband cooling.
        """
        initial_mean_excitation_number = initial_mean_excitation_number or self.cfg.ion_trap.initial_mean_excitation_number
        decay_rate = decay_rate or self.cfg.ion_trap.decay_rate
        rabi_frequency = rabi_frequency or self.cfg.ion_trap.rabi_frequency
        lamb_dicke_parameter = lamb_dicke_parameter or self.cfg.ion_trap.lamb_dicke_parameter
        sideband_sim_time = sideband_sim_time or self.cfg.ion_trap.sideband_sim_time
        # Excited-state occupation probability
        pe = (lamb_dicke_parameter * np.sqrt(initial_mean_excitation_number) * rabi_frequency)**2 / (
            2 * (lamb_dicke_parameter * np.sqrt(initial_mean_excitation_number)
                 * rabi_frequency)**2 + decay_rate**2)

        # Cooling rate
        cooling_rate = decay_rate * pe

        # final_mean_excitation_number = initial_mean_excitation_number * \
        #     np.exp(-cooling_rate * sideband_sim_time)
        final_mean_excitation_number = cooling_rate/(1 - cooling_rate)
        # Ensure mean excitation number doesn't go below a minimum threshold
        # if final_mean_excitation_number <= 0.484:
        #     raise ValueError("Reached Cooling Threshold")
        # different modes for understanding internal values received
        if self.noise_model == 1:
            if sideband_sim_time > 0:
                if final_mean_excitation_number < .5 and final_mean_excitation_number >= .484:
                    self.init_depolar_prob = self.cfg.ion_trap.init_depolar_prob
                    self.emission_fidelity = self.cfg.ion_trap.emission_fidelity
                    self.collection_efficiency = self.cfg.ion_trap.collection_efficiency
                    log.debug("Noisy values")
                else:
                    self.init_depolar_prob = 0.3
                    self.emission_fidelity = 0.985
                    self.collection_efficiency = 0.985
        else:
            self.init_depolar_prob = 0
            self.coherence_time = 0
            self.emission_fidelity = 1
            self.collection_efficiency = 1

            # return final_mean_excitation_number

        # return self.init_depolar_prob, self.coherence_time, self.emission_fidelity, self.collection_efficiency
    def raman_excitation(self, raman_ex_sim_time=None):
        raman_ex_sim_time = raman_ex_sim_time or self.cfg.ion_trap.raman_ex_sim_time
        if self.noise_model == 1:
            if raman_ex_sim_time > 0:
                if raman_ex_sim_time > 100 and raman_ex_sim_time < 300:
                    self.init_depolar_prob = self.cfg.ion_trap.init_depolar_prob  # 0.35
                    # self.coherence_time = self.cfg.ion_trap.coherence_time   #0.25
                    self.emission_fidelity = self.cfg.ion_trap.emission_fidelity
                    self.collection_efficiency = self.cfg.ion_trap.collection_efficiency
                    prob_range1 = np.arange(.98, .99, 0.001)
                    gs_prob = rand.choice(prob_range1)
                    log.debug("Noisy values")
                else:
                    self.init_depolar_prob = 0.32
                    # self.coherence_time = 0.22
                    self.emission_fidelity = 0.95
                    self.collection_efficiency = .69
                    prob_range2 = np.arange(.98, .985, 0.001)
                    gs_prob = rand.choice(prob_range2)
        else:
            self.init_depolar_prob = 0
            self.coherence_time = 0
            self.emission_fidelity = 1
            self.collection_efficiency = 1
            gs_prob = 1

    def spin_echo(self, spin_echo_sim_time):
        spin_echo_sim_time = spin_echo_sim_time or self.cfg.ion_trap.spin_echo_sim_time
        if self.noise_model == 1:
            if spin_echo_sim_time > 0:
                if spin_echo_sim_time > 10 and spin_echo_sim_time < 20:
                    self.init_depolar_prob = self.cfg.ion_trap.init_depolar_prob
                    self.emission_fidelity = self.cfg.ion_trap.emission_fidelity
                    self.collection_efficiency = self.cfg.ion_trap.collection_efficiency
                    prob_range1 = np.arange(.98, .99, 0.001)
                    gs_prob = rand.choice(prob_range1)
                    log.debug("Noisy values")
                else:
                    self.init_depolar_prob = 0.32
                    self.emission_fidelity = 0.95
                    self.collection_efficiency = .69
                    prob_range2 = np.arange(.98, .985, 0.001)
                    gs_prob = rand.choice(prob_range2)
        else:
            self.init_depolar_prob = 0
            self.coherence_time = 0
            self.emission_fidelity = 1
            self.collection_efficiency = 1
            gs_prob = 1

    def optical_pumping(self, init_sim_time=None,
                        pump_sim_time=None,
                        doppler_sim_time=None,
                        sideband_sim_time=None,
                        raman_ex_sim_time=None,
                        gs_prob=0.85):

        init_sim_time = init_sim_time or self.cfg.ion_trap.init_sim_time
        pump_sim_time = pump_sim_time or self.cfg.ion_trap.pump_sim_time
        doppler_sim_time = doppler_sim_time or self.cfg.ion_trap.doppler_sim_time
        sideband_sim_time = sideband_sim_time or self.cfg.ion_trap.sideband_sim_time
        raman_ex_sim_time = raman_ex_sim_time or self.cfg.ion_trap.raman_ex_sim_time
        self.emission_duration = (doppler_sim_time +
                                  sideband_sim_time + pump_sim_time + raman_ex_sim_time) * 1000  # convert to ns
        self.initialization_duration = init_sim_time * 1000
        if self.noise_model == 1:
            if pump_sim_time > 0:
                if pump_sim_time > 100 and pump_sim_time < 300:
                    self.init_depolar_prob = self.cfg.ion_trap.init_depolar_prob
                    self.emission_fidelity = self.cfg.ion_trap.emission_fidelity
                    self.collection_efficiency = self.cfg.ion_trap.collection_efficiency
                    prob_range1 = np.arange(.98, .99, 0.001)
                    gs_prob = rand.choice(prob_range1)
                    log.debug("Noisy values")
                else:
                    self.init_depolar_prob = 0.35
                    self.emission_fidelity = 0.92
                    self.collection_efficiency = .55
                    prob_range2 = np.arange(.98, .985, 0.001)
                    gs_prob = rand.choice(prob_range2)
        else:
            self.init_depolar_prob = 0
            self.coherence_time = 0
            self.emission_fidelity = 1
            self.collection_efficiency = 1
            gs_prob = 1
        # return gs_prob

    def create_qubits(self, node_name):
        num_matter_positions = self.num_ions
        qubits = qapi.create_qubits(
            num_matter_positions, system_name=f"{node_name} Qubit")
        if num_matter_positions == 1:
            self.ports["qin0"].tx_input(qubits[0])
            log.debug(
                f"Ion state initialized in ion-trap for {node_name} as {qubits[0].qstate.qrepr}")
        else:
            self.ports["qin0"].tx_input(qubits[0])
            self.ports["qin1"].tx_input(qubits[1])
            log.debug(
                f"Ion state initialized in ion-trap for {node_name} as {qubits[0].qstate.qrepr}, {qubits[1].qstate.qrepr}")

    def state_initialization(self, node_name, gs_probability=None, topo=[]):
        gs_probability = gs_probability or self.cfg.ion_trap.gs_prob
        num_matter_positions = self.num_ions
        if num_matter_positions == 1:
            eigen_state1 = SparseDMRepr(dm=[[1, 0], [0, 0]])
            state_sampler = StateSampler([eigen_state1],
                                         probabilities=[gs_probability])
            qapi.assign_qstate(self.peek(positions=0)[0], state_sampler)
        else:
            eigen_state1 = SparseDMRepr(dm=[[1, 0], [0, 0]])
            state_sampler = StateSampler([eigen_state1],
                                         probabilities=[gs_probability])
            if topo == [0]:
                qapi.assign_qstate(self.peek(positions=0)[0], state_sampler)
            elif topo == [1]:
                qapi.assign_qstate(self.peek(positions=1)[0], state_sampler)
            else:
                qapi.assign_qstate(self.peek(positions=0)[0], state_sampler)
                qapi.assign_qstate(self.peek(positions=1)[0], state_sampler)

    def Advreset(self):
        """Reset the ion trap and resample the dephasing rate.

        """
        super().reset()
        self.resample()
