import os
import json
import netsquid as ns
import numpy as np
import logging
import tracemalloc
import argparse
import itertools
import pandas
from matplotlib import pyplot as plt
from matplotlib import rcParams
import matplotlib.colors as mcolors
from netsquid.qubits.qubitapi import assign_qstate
from netsquid.qubits.operators import *
from netsquid.components import ClassicalChannel, QuantumChannel
from netsquid.components.models import FibreDelayModel
from netsquid.nodes.network import Network
from netsquid.components.switch import SimpleSwitch
from netsquid.components.qprocessor import QuantumProcessor
from netsquid.components.clock import Clock
from qnpack.common.simulation import Simulation
from qnpack.common.constants import Constants
from qnpack.common.config import Config
from qnpack.common.logging import setup_logging
from qnpack.APE.lib.params import APEParams
from qnpack.APE.lib.models import (
    FibreDepolarizeModel,
    BSMGatedQuantumDetector,
    LeafPhotonicProcessing,
    CorePhotonicProcessing,
    MyFibreLossModel,
    SPGatedQuantumDetector,
    Level2CorePhotonicProcessing,
    m_collector
)
from qnpack.APE.lib.protocols import (
    setup_repeater_protocol,
    CoreRecvProtocol,
    GraphStateEmissionProtocol
)
from qnpack.APE.lib.programs import (
    get_apeqr_node_instructions,
    get_end_node_instructions,
    rng_measure_mem
)
from qnpack.APE.lib.custom_errormodels import (
    myT1T2NoiseModel,
    my_apply_pauli_noise
)
from qnpack.APE.lib.drawGS import (
    plot_qubit_graph,
    pick_entangled_qubits
)

from qnpack.APE.lib.repeater_rate import (
    cal_exact_prob_2level_tree,
    cal_rate_from_single_data
)
from qnpack.APE.lib.verification import verification

log = logging.getLogger(__name__)


class APESimulation(Simulation):
    def __init__(self, iterations=None, min_successful=None, logfile=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print("self.cfg.network.photon_loss",self.cfg.network.photon_loss)
        self.iterations = iterations or self.cfg.sim.iterations
        self.min_successful=min_successful or self.cfg.sim.min_successful
        setup_logging(name=__name__,
                      level=logging.DEBUG if self.cfg.sim.debug else logging.INFO,logfile=logfile)
                      #logfile=self.mypath+'APE.log')
        log.info(f"Configuration:\n{self.cfg}")
        os.makedirs(self.output_dir, exist_ok=True)

        self.logical_z_fail_cnt = 0
        self.logical_z_cnt = 0
        self.logical_x_fail_cnt = 0
        self.logical_x_cnt = 0

        self.rng_noise = np.random.RandomState(0)
        self.rng_loss = np.random.RandomState(0)
        self.rng_measure = np.random.RandomState(0)

    
    def start(self):
        # starting memory tracing
        tracemalloc.start()

        ns.set_random_state()
        self.final_data = []
        self.total_fidelity_dict = {}
        self.total_prob_dict = {}
        self.total_elasped_time_dict = {}
        self.total_elasped_time_dict_per_run={}

        log.info(f"Running simulation with parameters: {self.varying_params}")
        log.info(f"Fixed parameters: {self.fixed_params}")
        log.info(f"Iterations: {self.iterations}")
        log.info("Starting simulation ...")
        # Names and values to sweep (e.g. {"num_repeaters":[1,3], "distances":[10,50]})
        param_names  = list(self.varying_params.keys())
        param_values = list(self.varying_params.values())
        for combo in itertools.product(*param_values):
            print("combo",combo)
            sweep_params = dict(zip(param_names, combo))
            sim_params   = {**self.fixed_params, **sweep_params}

            # Hard-code: we expect "distance" and "num_repeaters" in varying_params
            distance_val = sim_params["distance"]       # one numeric distance per combo
            num_repeater_val  = sim_params["num_repeaters"]   # may be int or list for inner loop
            #num_repeater_ls = num_rep_val if isinstance(num_rep_val, (list, tuple, range)) else [num_rep_val]

            log.info(f"\tRunning params: distance={distance_val}, num_repeaters={num_repeater_val} [{self.iterations} iters]")
            fidelity_dict, prob_dict, elasped_time_dict, elasped_time_dict_per_run = self.cal_fidelity(total_num_repeater=None,
                                                                                                       total_distance=distance_val,
                                                                                                       num_rgs_branches_half=self.cfg.rgs.num_branches_half,
                                                                                                       num_repeater=num_repeater_val,
                                                                                                       seed=self.cfg.sim.starting_seed,
                                                                                                       total_iteration=self.iterations,
                                                                                                       min_successful_cnt=self.min_successful,
                                                                                                       only_noise=False)
            
            # aggregate by distance then repeater
            dist_key = f"{distance_val}"
            self.total_fidelity_dict.setdefault(dist_key, {}).update(fidelity_dict)
            self.total_prob_dict.setdefault(dist_key, {}).update(prob_dict)
            self.total_elasped_time_dict.setdefault(dist_key, {}).update(elasped_time_dict)
            self.total_elasped_time_dict_per_run.setdefault(dist_key, {}).update(elasped_time_dict_per_run)
        return self.final_data 
            
    def plot(self, final_data, show_theo_rate, x_axis1, y_axis1, xlabel1, ylabel1, label_param1, 
              x_axis2, y_axis2, xlabel2, ylabel2, label_param2,
              title1="Simulation Results",
              title2="Simulation Results",
              filename="simulation_results.png"):
        # Save results
        data = pandas.DataFrame(final_data)
        data.to_csv(f"{self.output_dir}/simulation_results.csv", sep=',')

        ffig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        # Loop over the values of the selected label parameter
        for value in self.varying_params[label_param1]:
            subset = data[data[label_param1] == value]
            if x_axis1 != "init_photon_loss":
                ax1.errorbar(subset[x_axis1], subset[y_axis1], label=f"{label_param1}={value}")
                if y_axis1=='sim_rate' and show_theo_rate:
                    ax1.errorbar(subset[x_axis1], subset['theo_rate'], linestyle='dashdot', label=f"{label_param1}={value} theo. value")

            else:
                ax1.errorbar((1-subset[x_axis1]), subset[y_axis1], label=f"{label_param1}={value}")
    
        ax1.set_xlabel(xlabel1)  # Format axis labels
        ax1.set_ylabel(ylabel1)
        ax1.set_title(title1)
        ax1.legend(title=label_param1.replace("_", " ").title())
        ax1.set_xticks(sorted(data[x_axis1].unique()))

        # Loop over the values of the selected label parameter
        for value in self.varying_params[label_param2]:
            subset = data[data[label_param2] == value]
            if x_axis2 != "init_photon_loss":
                ax2.errorbar(subset[x_axis2], subset[y_axis2], label=f"{label_param2}={value}")
            else:
                ax2.errorbar((1-subset[x_axis2]), subset[y_axis2], label=f"{label_param2}={value}")
    
        ax2.set_xlabel(xlabel2)  # Format axis labels
        ax2.set_ylabel(ylabel2)
        ax2.set_title(title2)
        ax2.legend(title=label_param2.replace("_", " ").title())
        ax2.set_xticks(sorted(data[x_axis2].unique()))

        # Save the figures
        plt.tight_layout()
        plt.savefig(f"{self.output_dir}/{filename}")
        plt.show()

    def finalize(self):
        #self.cal_estimated_running_time(self.total_elasped_time_dict_per_run)
        # displaying the memory
        current, peak = tracemalloc.get_traced_memory()
        print("Current memory [MB]:", round(current/(1024*1024), 4), "Peak memory [MB]:", round(peak/(1024*1024), 4))

        # stopping the library
        tracemalloc.stop()
        CoreRecvProtocol.PostProcessingResult={}
        ns.sim_reset()

    def apeqr_node_setup_withoutTree(self, node, qport_left_name, qport_right_name, apply_emitter_noise=False, rng_noise=None):
        node.add_subcomponent(QuantumProcessor(name="qproc", num_positions=2,
                                               fallback_to_nonphysical=False,
                                               phys_instructions=get_apeqr_node_instructions(self.cfg,
                                                                                             apply_emitter_noise,
                                                                                             self.rng_noise)))
        # Set up optical switch
        switch = SimpleSwitch("switch", {'switch_out_left_leaf': 'switch_out_left_leaf', 'switch_out_left_core': 'switch_out_left_core',
                                         'switch_out_right_leaf': 'switch_out_right_leaf', 'switch_out_right_core': 'switch_out_right_core',
                                         'switch_in': 'switch_in'})
        node.add_subcomponent(switch, name="switch")
        # When photon is emitted from emitter, it comes out at qout port and enters switch_in port
        node.qmemory.ports["qout0"].connect(switch.ports["switch_in"])
        # Set up clock
        clock = Clock("clock", frequency=1/APEParams.apeqr_clock_period(self.cfg))
        node.add_subcomponent(clock, name="clock")

        for dir in ["left", "right"]:
            # Set up passive photonic quantum gate for leaf and core photons respectively
            node.add_subcomponent(LeafPhotonicProcessing(name=f"leaf_photonic_processing_{dir}"))
            node.add_subcomponent(CorePhotonicProcessing(
                name=f"core_photonic_processing_{dir}", delay=APEParams.core_photon_delay(self.cfg)))
            switch.ports[f"switch_out_{dir}_leaf"].connect(
                node.subcomponents[f"leaf_photonic_processing_{dir}"].ports["send"])
            switch.ports[f"switch_out_{dir}_core"].connect(
                node.subcomponents[f"core_photonic_processing_{dir}"].ports["send"])
            # Set up multiplexer
            multiplexer = SimpleSwitch(f"multiplexer_{dir}", {'switch_out': 'switch_out', 'switch_in_leaf': 'switch_out',
                                                              'switch_in_core': 'switch_out'})
            if dir == "left":
                node.add_subcomponent(multiplexer, name=f"multiplexer_{dir}", forward_output=[
                    (qport_left_name, "switch_out")])
            else:
                node.add_subcomponent(multiplexer, name=f"multiplexer_{dir}", forward_output=[
                    (qport_right_name, "switch_out")])
            multiplexer.ports["switch_in_leaf"].connect(
                node.subcomponents[f"leaf_photonic_processing_{dir}"].ports["recv"])
            multiplexer.ports["switch_in_core"].connect(
                node.subcomponents[f"core_photonic_processing_{dir}"].ports["recv"])

    def apeqr_node_setup(self, cfg, node, qport_left_name, qport_right_name, apply_emitter_noise=False,apply_fibre_loss=False, rng_noise=None, rng_measure=None,fiber_loss_model_delay=None):
        qproc = QuantumProcessor(name=f"{node.name}_qproc", num_positions=3,
                                 fallback_to_nonphysical=False,
                                 phys_instructions=get_apeqr_node_instructions(cfg, apply_emitter_noise, rng_noise, rng_measure))
        node.add_subcomponent(qproc)
        qproc.add_property(name="emitted_photon_cnt", value=0, value_type=int)
        # Set up optical switch
        switch = SimpleSwitch("switch", {'switch_out_left_leaf': 'switch_out_left_leaf', 'switch_out_left_level1_core': 'switch_out_left_level1_core',
                                         'switch_out_left_level2_core': 'switch_out_left_level2_core', 'switch_out_right_leaf': 'switch_out_right_leaf', 'switch_out_right_level1_core': 'switch_out_right_level1_core',
                                         'switch_out_right_level2_core': 'switch_out_right_level2_core', 'switch_in': 'switch_in'})
        node.add_subcomponent(switch, name="switch")
        # When photon is emitted from emitter, it comes out at qout port and enters switch_in port
        node.qmemory.ports["qout0"].connect(switch.ports["switch_in"])
        # Set up clock
        clock = Clock("clock", frequency=1/APEParams.apeqr_clock_period(cfg))
        node.add_subcomponent(clock, name="clock")

        for dir in ["left", "right"]:
            # Set up passive photonic quantum gate for leaf and core photons respectively
            if apply_fibre_loss:
                node.add_subcomponent(LeafPhotonicProcessing(name=f"leaf_photonic_processing_{dir}"))
                node.add_subcomponent(CorePhotonicProcessing(
                    name=f"level1_core_photonic_processing_{dir}", delay=APEParams.core_photon_delay(cfg),length=APEParams.core_photon_delay_fibre_length(cfg),models={"quantum_loss_model": fiber_loss_model_delay}))
                node.add_subcomponent(Level2CorePhotonicProcessing(
                    name=f"level2_core_photonic_processing_{dir}", delay=APEParams.core_photon_delay(cfg),length=APEParams.core_photon_delay_fibre_length(cfg),models={"quantum_loss_model": fiber_loss_model_delay}))
            else:
                node.add_subcomponent(LeafPhotonicProcessing(name=f"leaf_photonic_processing_{dir}"))
                node.add_subcomponent(CorePhotonicProcessing(
                    name=f"level1_core_photonic_processing_{dir}", delay=APEParams.core_photon_delay(cfg)))
                node.add_subcomponent(Level2CorePhotonicProcessing(
                    name=f"level2_core_photonic_processing_{dir}", delay=APEParams.core_photon_delay(cfg)))
            switch.ports[f"switch_out_{dir}_leaf"].connect(
                node.subcomponents[f"leaf_photonic_processing_{dir}"].ports["send"])
            switch.ports[f"switch_out_{dir}_level1_core"].connect(
                node.subcomponents[f"level1_core_photonic_processing_{dir}"].ports["send"])
            switch.ports[f"switch_out_{dir}_level2_core"].connect(
                node.subcomponents[f"level2_core_photonic_processing_{dir}"].ports["send"])
            # Set up multiplexer
            multiplexer = SimpleSwitch(f"multiplexer_{dir}", {'switch_out': 'switch_out', 'switch_in_leaf': 'switch_out',
                                                              'switch_in_level1_core': 'switch_out', 'switch_in_level2_core': 'switch_out'})
            if dir == "left":
                node.add_subcomponent(multiplexer, name=f"multiplexer_{dir}", forward_output=[
                    (qport_left_name, "switch_out")])
            else:
                node.add_subcomponent(multiplexer, name=f"multiplexer_{dir}", forward_output=[
                    (qport_right_name, "switch_out")])
            multiplexer.ports["switch_in_leaf"].connect(
                node.subcomponents[f"leaf_photonic_processing_{dir}"].ports["recv"])
            multiplexer.ports["switch_in_level1_core"].connect(
                node.subcomponents[f"level1_core_photonic_processing_{dir}"].ports["recv"])
            multiplexer.ports["switch_in_level2_core"].connect(
                node.subcomponents[f"level2_core_photonic_processing_{dir}"].ports["recv"])

    def measurement_node_setup(self,cfg, node, qport_left_name, qport_right_name, end_node_dir=None,
                               rng_measure=None, is_forced_outcome=False,is_forced_outcome_history=False):
        bsm_detector = BSMGatedQuantumDetector(f'bsm_detector_{node.name}',
                                               detection_window=cfg.bsm.detection_window,
                                               num_input_ports=2, num_output_ports=2,
                                               end_node_dir=end_node_dir,
                                               rng_measure=rng_measure,
                                               is_forced_outcome=is_forced_outcome,
                                               is_forced_outcome_history=is_forced_outcome_history)
        node.add_subcomponent(bsm_detector, 'bsm_detector')
        for dir in ["left", "right"]:
            # Set up optical switches to separate leaf and core photons
            switch = SimpleSwitch(f"switch_{dir}",
                                  {"switch_out_leaf": "switch_out_leaf", "switch_out_core_Z": "switch_out_core_Z",
                                   "switch_out_core_X": "switch_out_core_X", "switch_out_core_X_level1": "switch_out_core_X_level1",
                                   "switch_in": "switch_in"})
            switch.topology = {"switch_in": "switch_out_leaf"}

            if dir == "left":
                node.add_subcomponent(switch, name=f"switch_{dir}", forward_input=[(qport_left_name, "switch_in")])
                switch.ports['switch_out_leaf'].connect(bsm_detector.ports["qin0"])
            else:
                node.add_subcomponent(switch, name=f"switch_{dir}", forward_input=[(qport_right_name, "switch_in")])
                switch.ports['switch_out_leaf'].connect(bsm_detector.ports["qin1"])
            # Set up single-photon detector for core photons
            single_detector_Z = SPGatedQuantumDetector(
                f"single_detector_Z_{dir}_{node.name}", detection_window=cfg.spd.detection_window,
                observable=Z, rng_measure=rng_measure, is_forced_outcome=is_forced_outcome,is_forced_outcome_history=is_forced_outcome_history)
            single_detector_X = SPGatedQuantumDetector(
                f"single_detector_X_{dir}_{node.name}", detection_window=cfg.spd.detection_window,
                observable=X, rng_measure=rng_measure, phase_gate=False, is_forced_outcome=is_forced_outcome,is_forced_outcome_history=is_forced_outcome_history)
            single_detector_X_level1 = SPGatedQuantumDetector(
                f"single_detector_X_level1_{dir}_{node.name}", detection_window=cfg.spd.detection_window,
                observable=X, rng_measure=rng_measure, phase_gate=True, is_forced_outcome=is_forced_outcome,is_forced_outcome_history=is_forced_outcome_history)
            node.add_subcomponent(single_detector_Z, name=f"single_detector_Z_{dir}")
            node.add_subcomponent(single_detector_X, name=f"single_detector_X_{dir}")
            node.add_subcomponent(single_detector_X_level1, name=f"single_detector_X_level1_{dir}")
            switch.ports['switch_out_core_Z'].connect(single_detector_Z.ports["qin0"])
            switch.ports['switch_out_core_X'].connect(single_detector_X.ports["qin0"])
            switch.ports['switch_out_core_X_level1'].connect(single_detector_X_level1.ports["qin0"])

    def end_node_setup(self,cfg, node, qport_name, num_matter_qubit, apply_memory_noise=False):
        # Set up clock
        clock = Clock("clock", frequency=1/APEParams.apeqr_clock_period(cfg))
        node.add_subcomponent(clock, name="clock")

        # Set up matter qubits:
        if apply_memory_noise:
            # Later verify different apeqr node noise use same rng_noise
            memory_noise_model = myT1T2NoiseModel(T1=cfg.emitter.memory_T1,
                                                  T2=cfg.emitter.memory_T2,
                                                  my_rng=self.rng_noise)

            qproc = QuantumProcessor(f"{node.name}_qproc", num_positions=num_matter_qubit, mem_noise_models=memory_noise_model,
                                     fallback_to_nonphysical=False, phys_instructions=get_end_node_instructions(cfg, self.rng_noise))
        else:
            qproc = QuantumProcessor(f"{node.name}_qproc", num_positions=num_matter_qubit,
                                     fallback_to_nonphysical=False, phys_instructions=get_end_node_instructions(cfg, self.rng_noise))
        node.add_subcomponent(qproc)
        qproc.add_property(name="emitted_photon_cnt", value=0, value_type=int)
        # print("matter qubits:",node.qmemory.peek([0,1,2]))
        # Set up multiplexer
        topology_dict = {f"switch_in_{i}": "switch_out" for i in range(num_matter_qubit)}
        topology_dict["switch_out"] = "switch_out"
        multiplexer = SimpleSwitch("multiplexer", topology=topology_dict)
        node.add_subcomponent(multiplexer, name="multiplexer", forward_output=[(qport_name, "switch_out")])

        # Connect ports between QProcessor and multiplexer
        for i in range(num_matter_qubit):
            node.qmemory.ports[f"qout{i}"].connect(multiplexer.ports[f"switch_in_{i}"])

    def network_setup(self, total_num_repeater=None, total_distance=20, num_repeater=2,
                      num_rgs_branches_half=3, p_depol_init=0, p_depol_length=0,
                      seed=None, apply_emitter_noise=False, apply_memory_noise=False,
                      apply_fibre_loss=False, discard=True, rng_noise=None, rng_measure=None,
                      rng_loss=None, is_forced_outcome=False, is_forced_outcome_history=False, hide_fixed_photons=False, is_one_end_noise=False):
        """Calculate average fidelity on repeater chain network.

        Parameters
        ----------
        total_num_repeater : int 
            Total number of repeater. If not None, num_repeaters is the segments of repeater chain out of the total number. 

        total_distance: int
            Total distance between two end nodes in km.     

        num_repeater : int
            Number of repeater in the repeater chains simulation

        num_rgs_branches_half : int
            One half of the total number of branches of RGS. 

        p_depol_init: float
            Not in use now.

        p_depol_length : float
            Not in use now.

        seed : int
            Current seed for random number generator to use for reproducibility

        apply_emitter_noise : bool
            Whether to apply emitter noise in each APE QR node during RGS generation

        apply_memory_noise : bool
            Whether to apply noise in memory qubits in each end node 

        apply_fibre_loss : bool
            Whether to apply fibre loss in each qchannel

        discard : bool
            Whether to perform the discard() method to the lost qubit. In STAB repr, it is equivalent to Z measurement with unrevealed outcome

        rng_noise : 
            RNG for emitter noise and memory noise 

        rng_measure : 
            RNG for matter qubit measurements and photonic measurements

        rng_loss : 
            RNG for photon loss                        

        is_forced_outcome : bool
            This is set to True to force all measurement outcomes. If is_forced_outcome_history=False, BSM still has 50% prob to be successful, while the outcomes are forced to
            be equvalent to perfect local Pauli adjustment.                                                                                                       
        
        is_forced_outcome_history:bool
            This is set to True for the noiseless case and under assumption that previous measurement outcomes of the case with noise has 
            stored all measursements outcomes in the Protocol. Measurements outcome is forced in the physical qubits level of the logical core qubit.
        
        hide_fixed_photons : bool
            This is set to True for the noiseless case. Lost photons will only be hide in the background instead of being discard.

        is_one_end_noise : bool
            Whether to turn off the decoherence noise of memory qubits of the right end node.
            This is set to True when approximating a repeater chain with total length 2x by two repeater chains with total length x.

        """
        cfg=self.cfg
        # print("discard inside network_setup",discard)
        if total_num_repeater == None:  # Fix total distance and calculate node distance by num_repeater
            node_distance = round(total_distance/((num_repeater+1)*2), 5)
            # print("node_distance",node_distance)
        else:  # Fix total_num_repeater and calculate node distance by total_num_repeater
            assert total_num_repeater >= num_repeater, "num_repeater is larger than total_num_repeater"
            node_distance = round(total_distance/((total_num_repeater+1)*2), 5)
        if apply_emitter_noise or p_depol_init or p_depol_length:
            name = f"Repeater_network_{total_distance}_{num_repeater}_noise"
        else:
            name = f"Repeater_network_{total_distance}_{num_repeater}_noiseless"
        network = Network(name)
        # Set up nodes of the repeater chain
        node_a, node_b = network.add_nodes(["node_a", "node_b"])
        bsm_nodes = []
        ape_nodes = []
        for i in range(num_repeater):
            node_bsm, node_ape = network.add_nodes([f"node_bsm{i}", f"node_ape{i}"])
            bsm_nodes.append(f"bsm{i}")
            ape_nodes.append(f"ape{i}")
        network.add_nodes([f"node_bsm{num_repeater}"])
        bsm_nodes.append(f"bsm{num_repeater}")
        end_ape_nodes = ["a"]+ape_nodes+["b"]
        
        # Set up control node
        node_c=network.add_node(f"node_c")
     
        for i in range(len(bsm_nodes)):
            left = end_ape_nodes[i]
            middle = bsm_nodes[i]
            right = end_ape_nodes[i+1]
            left_node = network.get_node(f"node_{left}")
            middle_node = network.get_node(f"node_{middle}")
            right_node = network.get_node(f"node_{right}")

            # Set up cchannel from every bsm nodes to control node (placed in the middle) 
            cchannel_bsm_c = ClassicalChannel(
                f"CChannel_{middle}->c", length=abs(total_distance/2-(2*i+1)*node_distance), models={"delay_model": FibreDelayModel()})
            network.add_connection(node_c, middle_node,  channel_from=cchannel_bsm_c, 
                                   port_name_node1=f"cport_from_bsm{i}", port_name_node2="cport_to_control")
            
            # Set up cchannel from every ape nodes to control node (placed in the middle) 
            #if i<len(bsm_nodes)-1:
            #    cchannel_ape_c = ClassicalChannel(
            #        f"CChannel_{right}->c", length=abs(total_distance/2-2*i*node_distance), models={"delay_model": FibreDelayModel()})
            #    network.add_connection(node_c, middle_node,  channel_from=cchannel_ape_c, 
            #                           port_name_node1=f"cport_from_ape{i}", port_name_node2="cport_to_control")

            # Set up cchannel from control node (placed in the middle) to APE and two end nodes 
            #if i==0:
            #    cchannel_c_a = ClassicalChannel(
            #        f"CChannel_c->a", length=total_distance/2, models={"delay_model": FibreDelayModel()})
            #    network.add_connection(node_c, left_node, channel_from=cchannel_c_a, label="control",
            #                           port_name_node1="cport_to_a", port_name_node2="cport_from_control")
            #else:
            cchannel_c_left = ClassicalChannel(
                f"CChannel_c->{left}", length=abs(total_distance/2-2*i*node_distance), models={"delay_model": FibreDelayModel()})
            network.add_connection(node_c, left_node, channel_from=cchannel_c_left, label="control",
                                   port_name_node1=f"cport_to_{left}", port_name_node2="cport_from_control")
            
            if i==len(bsm_nodes)-1:
                cchannel_c_b = ClassicalChannel(
                    f"CChannel_c->b", length=total_distance/2, models={"delay_model": FibreDelayModel()})
                network.add_connection(node_c, right_node, channel_from=cchannel_c_b, label="control",
                                       port_name_node1="cport_to_b", port_name_node2="cport_from_control")
            

            
            # Setup 1-way clock connections to each bsm node from left node
            cchannel_clock_lm = ClassicalChannel(
                f"CChannel_clock_{left}->{middle}", length=node_distance, models={"delay_model": FibreDelayModel()})
            network.add_connection(middle_node, left_node, channel_from=cchannel_clock_lm, label="clock",
                                   port_name_node1="cport_clock_from_left", port_name_node2="cport_clock_to_right")

            fiber_loss_model = MyFibreLossModel(discard=discard, rng=rng_loss,
                                                hide_fixed_photons=hide_fixed_photons,
                                                p_loss_init=APEParams.p_loss_init(cfg),
                                                p_loss_length=cfg.network.photon_loss)
            
            fiber_loss_model_delay = MyFibreLossModel(discard=discard, rng=rng_loss,
                                                hide_fixed_photons=hide_fixed_photons,
                                                p_loss_init=0,
                                                p_loss_length=cfg.network.photon_loss)
            
            fiber_depol_model = FibreDepolarizeModel(p_depol_init=p_depol_init,
                                                     p_depol_length=p_depol_length,
                                                     rng_noise=rng_noise)

            # Setup 1-way quantum channels to each bsm node from left node
            if apply_fibre_loss:
                qchannel_lm = QuantumChannel(f"QChannel_{left}->{middle}", length=node_distance,
                                             models={"quantum_loss_model": fiber_loss_model,
                                                     "quantum_noise_model": fiber_depol_model,
                                                     "delay_model": FibreDelayModel()})
            else:
                qchannel_lm = QuantumChannel(f"QChannel_{left}->{middle}", length=node_distance,
                                             models={"quantum_noise_model": fiber_depol_model,
                                                     "delay_model": FibreDelayModel()})

            network.add_connection(middle_node, left_node, channel_from=qchannel_lm, label="quantum",
                                   port_name_node1=f"qport_{middle}_{left}", port_name_node2=f"qport_{left}_{middle}")

            # Setup 1-way clock connections to each bsm node from right node
            cchannel_clock_rm = ClassicalChannel(
                f"CChannel_clock_{right}->{middle}", length=node_distance, models={"delay_model": FibreDelayModel()})
            network.add_connection(middle_node, right_node, channel_from=cchannel_clock_rm, label="clock",
                                   port_name_node1="cport_clock_from_right", port_name_node2="cport_clock_to_left")

            # Setup 1-way quantum channels to each bsm node from right node
            if apply_fibre_loss:
                qchannel_rm = QuantumChannel(f"QChannel_{right}->{middle}", length=node_distance,
                                             models={"quantum_loss_model": fiber_loss_model,
                                                     "quantum_noise_model": fiber_depol_model,
                                                     "delay_model": FibreDelayModel()})
            else:
                qchannel_rm = QuantumChannel(f"QChannel_{right}->{middle}", length=node_distance,
                                             models={"quantum_noise_model": fiber_depol_model,
                                                     "delay_model": FibreDelayModel()})
            network.add_connection(middle_node, right_node, channel_from=qchannel_rm, label="quantum",
                                   port_name_node1=f"qport_{middle}_{right}", port_name_node2=f"qport_{right}_{middle}")

            # Setup modules inside measurement nodes. If measurement node is connected to end node, BSM would not implement Rx gate on arrived photon from end node.
            if i == 0:
                end_node_dir = "left"
            elif i == len(bsm_nodes)-1:
                end_node_dir = "right"
            else:
                end_node_dir = None
            # print(f"i={i},end_node_dir={end_node_dir}")
            self.measurement_node_setup(cfg, middle_node, qport_left_name=f"qport_{middle}_{left}",
                                        qport_right_name=f"qport_{middle}_{right}",
                                        end_node_dir=end_node_dir, rng_measure=rng_measure,
                                        is_forced_outcome=is_forced_outcome,is_forced_outcome_history=is_forced_outcome_history)

            # Setup modules inside apeqr (all-photonic entanglement-based quantum repeater) nodes and left end nodes
            # print("num_rgs_branches_half in network setup",num_rgs_branches_half)
            if i == 0:
                self.end_node_setup(cfg, left_node, qport_name=f"qport_{left}_{middle}",
                                    num_matter_qubit=num_rgs_branches_half,
                                    apply_memory_noise=apply_memory_noise)
            else:
                self.apeqr_node_setup(cfg, left_node, qport_left_name=f"qport_{left}_bsm{i-1}",
                                      qport_right_name=f"qport_{left}_bsm{i}",
                                      apply_emitter_noise=apply_emitter_noise,apply_fibre_loss=apply_fibre_loss,
                                      rng_noise=rng_noise, rng_measure=rng_measure,fiber_loss_model_delay=fiber_loss_model_delay)

            # Setup modules inside right end nodes
            if i == len(bsm_nodes)-1:
                if is_one_end_noise:  # Node b has no decoherence
                    self.end_node_setup(cfg, right_node, qport_name=f"qport_{right}_{middle}",
                                        num_matter_qubit=num_rgs_branches_half)
                else:
                    self.end_node_setup(cfg, right_node, qport_name=f"qport_{right}_{middle}",
                                        num_matter_qubit=num_rgs_branches_half,
                                        apply_memory_noise=apply_memory_noise)

        return network, bsm_nodes, ape_nodes, end_ape_nodes

    def collect_statistic(self, network, num_repeater, seed):
        """Calculate average fidelity on repeater chain network.

        Parameters
        ----------
        network : 
            Network instance in NetSquid

        num_repeater : int
            Number of repeater in the repeater chains 

        seed : int
            Current seed for random number generator to use for reproducibility


        Returns
        -------
        repeater_chain_success: bool
            Boolean indicating whether the whole repeater chain scheme succeeds or fails

        data: dict
            If the repeater scheme succeeds, it stores the QRepr and Qubits of the entangled Bell pair across two end nodes. 
            It also stores the measurement outcomes of matter qubits during RGS generation and the measurement outcomes in the measurement nodes

        logical_prob: dict
            For dubugging purpose. Stores the logical X/Z failed count and total counts of the logical core qubits of each BSM nodes.

        """
        all_bsm_success = True
        all_spd_success = True
        # all_spd_success=True
        data = {}
        logical_prob = (CoreRecvProtocol.logical_x_fail_cnt, CoreRecvProtocol.logical_x_cnt,
                        CoreRecvProtocol.logical_z_fail_cnt, CoreRecvProtocol.logical_z_cnt)

        for key, value in CoreRecvProtocol.PostProcessingResult.items():
            if value[0] == False:
                # print("At least one BSM node with all BSM failed")
                all_bsm_success = False
            if value[2] == False:
                all_spd_success = False
            if (not all_bsm_success) and (not all_spd_success):
                break

        repeater_chain_success = all_bsm_success and all_spd_success
        if repeater_chain_success:
            _, bsm_outcomes, _, _ = CoreRecvProtocol.PostProcessingResult['CRPR_bsm0']
            # print("bsm_outcomes inside collect_statistic",bsm_outcomes)
            node_a_1st_successful_index = 0
            node_b_1st_successful_index = 0
            verify_a_successful = False
            verify_b_successful = False

            for i in range(len(bsm_outcomes)):
                if bsm_outcomes[i] == 0 or bsm_outcomes[i] == 1:
                    node_a_1st_successful_index = i
                    verify_a_successful = True
                    break

            _, bsm_outcomes, _, _ = CoreRecvProtocol.PostProcessingResult[f'CRPL_bsm{num_repeater}']
            for i in range(len(bsm_outcomes)):
                if bsm_outcomes[i] == 0 or bsm_outcomes[i] == 1:
                    node_b_1st_successful_index = i
                    verify_b_successful = True
                    break
            assert verify_a_successful & verify_b_successful, "All_bsm_success is True but could not find sucessful bsm outcome in end nodes"

            # print("node_a_1st_successful_index",node_a_1st_successful_index,"node_b_1st_successful_index",node_b_1st_successful_index)
            a_matter_qubits = network.get_node("node_a").qmemory.peek(list(range(self.cfg.rgs.num_branches_half)))
            b_matter_qubits = network.get_node("node_b").qmemory.peek(list(range(self.cfg.rgs.num_branches_half)))
            a_successful_qubit = a_matter_qubits[node_a_1st_successful_index]
            b_successful_qubit = b_matter_qubits[node_b_1st_successful_index]

            # print("all matter qubits in node a:",a_matter_qubits)
            # for qubit in a_matter_qubits:
            #    print(qubit,pick_entangled_qubits(qubit))
            # print("all matter qubits in node b:",b_matter_qubits)
            # for qubit in b_matter_qubits:
            #    print(qubit,pick_entangled_qubits(qubit))

            # Assert that the first successful matter qubit in node a is only entangled with the first successful matter in node b
            picked_qstate_a, picked_qubits_a = pick_entangled_qubits(a_successful_qubit)
            #print("inside collect_statistic:",picked_qstate_a, picked_qubits_a)
            try:
                assert picked_qstate_a.num_qubits == 2, f"seed {seed}:First successful matter qubit in node a is entangled with >1 qubit"
                assert picked_qubits_a[1] == b_successful_qubit, f"seed {seed}:First successful matter qubits in node a and b are not entangled"
            except AssertionError as e:
                with open(error_f, 'a') as f:
                    f.write(f'Assertion failed at the {str(e)} line')
                    f.write(f'picked_qstate_a: {picked_qstate_a}')
                    f.write(f'picked_qubits_a: {picked_qubits_a}')
                repeater_chain_success = False

            data["qrepr"] = picked_qstate_a
            data["qubit"] = picked_qubits_a
            data["GSEP_result"] = GraphStateEmissionProtocol.PostProcessingResult.copy()
            data["CRP_result"] = CoreRecvProtocol.PostProcessingResult.copy()
        else:
            data["qrepr"] = "At least one measurement node has all BSM failed or at least one core qubit measurement is failed."
            data["qubit"] = "At least one measurement node has all BSM failed or at least one core qubit measurement is failed."
            data["GSEP_result"] = GraphStateEmissionProtocol.PostProcessingResult.copy()
            data["CRP_result"] = CoreRecvProtocol.PostProcessingResult.copy()
        return repeater_chain_success, data, logical_prob

    def cal_fidelity(self, total_num_repeater, total_distance, num_rgs_branches_half, num_repeater, seed,
                     total_iteration, min_successful_cnt=0, only_noise=True):
        """Calculate average fidelity on repeater chain network. 
        Across a fixed total distance, for each number of repeater, a network with noise and a network without noise are first set up. 
        When the repeater chain scheme is successful on the network with noise, measurement outcomes would be fed into the noiseless network
        to calculate the expected noiseless Bell pair. Memory noise is applied explicitly here on the memory qubits in 
        the two end nodes according to the time required for classical message to transfer from the leftmost BSM node to the right end node.
        Fidelity of the Bell pair under noise is computed w.r.t. to the expected noiseless Bell pair. 

        Parameters
        ----------
        total distance : int
            Total distance between two end nodes 

        seed : int
            Starting seed for random number generator to use for reproducibility

        total_iteration : int
            Total number to run the repeater simulation. Each run would increment the seed by 1. 

        min_successful_cnt : int, optional
            Successful number of BSM scheme to run the repeater simulation until it stops. When min_successful_cnt>0, it keeps running even the 
            number of count exceeds total_iteration until successful_cnt>=min_successful_cnt

        Returns
        -------
        fidelity_dict: dict 
            Dictionary holding the average fidelity

        prob_dict: dict
            Dictionary holding the total counts and successful counts for each number of repeater 

        elasped_time_dict: dict
            Dictionary holding the total elapsed time 

        elasped_time_dict_per_run: dict 
            Dictionary holding the elapsed time per iteration

        """
        is_one_end_noise = self.cfg.sim.is_one_end_noise
        fidelity_dict = {}
        prob_dict = {}
        elasped_time_dict = {}
        elasped_time_dict_per_run = {}
        #elasped_time_dict = {num_repeater: 0}
        #elasped_time_dict_per_run = {f'{num_repeater}_noise': 0}

        mismatch_dict = {}

        cnt = 0
        successful_cnt = 0
        meas_mismatch_cnt = 0
        fidelity_ls = []
        elasped_time_dict[num_repeater] = 0
        # repeater graph state has rgs_size leaf photons and rgs_size core photons, total number of photon=2*rgs_size
        rgs_size = 2*num_rgs_branches_half
        # with open(debug_f, 'a') as f:
        #     f.write(f'total_distance: {total_distance},num_repeater:{num_repeater} \n')
        log.info(f"\t\ttotal_distance: {total_distance}, num_repeater: {num_repeater}")
        # ns.sim_reset()
        ns.set_qstate_formalism(ns.QFormalism.STAB)
        network_noise, bsm_nodes_noise, ape_nodes_noise, end_ape_nodes_noise = self.network_setup(
            total_num_repeater=total_num_repeater, total_distance=total_distance, num_repeater=num_repeater,
            num_rgs_branches_half=num_rgs_branches_half, apply_fibre_loss=True,
            discard=True, hide_fixed_photons=False, apply_emitter_noise=True, apply_memory_noise=False,
            rng_noise=self.rng_noise, rng_measure=self.rng_measure, rng_loss=self.rng_loss, is_forced_outcome=True,
            is_forced_outcome_history=False,is_one_end_noise=is_one_end_noise)
        protocol_noise = setup_repeater_protocol(self.cfg,network_noise, bsm_nodes_noise,
                                                 ape_nodes_noise, end_ape_nodes_noise,
                                                 rgs_size, num_repeater,is_manual_noise=False)
        
        
        # print("protocol",protocol,"protocol_noise:",protocol_noise)
        while cnt < total_iteration or successful_cnt < min_successful_cnt:
            """When ns.sim_time()>2.9E9, all subsequent iterations would have identical results due to unknown reason.
            Hence we reset the simulation time and define the networks and protocols again whenever ns.sim_time()>1E9 
            """
            if ns.sim_time() > 1E9:
                ns.sim_reset()
                network_noise, bsm_nodes_noise, ape_nodes_noise, end_ape_nodes_noise = self.network_setup(
                    total_num_repeater=total_num_repeater, total_distance=total_distance, num_repeater=num_repeater,
                    num_rgs_branches_half=num_rgs_branches_half, apply_fibre_loss=True,
                    discard=True, hide_fixed_photons=False, apply_emitter_noise=True, apply_memory_noise=False,
                    rng_noise=self.rng_noise, rng_measure=self.rng_measure, rng_loss=self.rng_loss, is_forced_outcome=True,
                    is_forced_outcome_history=False,is_one_end_noise=is_one_end_noise)
                protocol_noise = setup_repeater_protocol(self.cfg,self.cfg_we,network_noise, bsm_nodes_noise,
                                                 ape_nodes_noise, end_ape_nodes_noise,
                                                 rgs_size, num_repeater,is_manual_noise=False)
            #m_collector.reset()  # Reset m_collector which is used to force measurement outcomes of noise case to noiseless case
            #MyFibreLossModel.lost_photon_ls = []  # Reset the list to store the lost photons during the noise case
            repeater_chain_success_noise, data_noise, logical_prob_noise, elapsed_time_noise = self.run_protocol_once(
                network_noise, protocol_noise, seed, num_repeater)
            elasped_time_dict[num_repeater] += elapsed_time_noise
            elasped_time_dict_per_run[f'{num_repeater}_noise'] = elapsed_time_noise
            log.debug("elasped_time_dict_per_run",elasped_time_dict_per_run)
            
            if repeater_chain_success_noise:
                if not only_noise:
                    verify=verification(num_repeater,self.cfg.rgs.num_branches_half,data_noise["CRP_result"])
                    verify.start()
                    qrepr_veri=verify.get_expected_Bell_pair()
                    #print("qstate cal by verification",qrepr_veri)
                    qrepr_noise = data_noise["qrepr"]
                    
                    # Apply memory noise during measurement outcome anouncement
                    memory_a, memory_b = ns.qubits.create_qubits(2)
                    assign_qstate([memory_a, memory_b], qrepr=qrepr_noise)
                    node_distance = round(total_distance/(2*num_repeater+2), 5)
                    if self.cfg.emitter.memory_T2>0:
                        message_time = (total_distance-node_distance)/200000 *1E9  # From leftmost BSM node to the right node
                        dp = np.exp(-message_time / self.cfg.emitter.memory_T2)
                        probZ = (1 - dp) / 2
                        my_apply_pauli_noise(memory_a, (1-probZ, 0, 0, probZ), my_rng=self.rng_noise)
                        if not is_one_end_noise:
                            my_apply_pauli_noise(memory_b, (1-probZ, 0, 0, probZ), my_rng=self.rng_noise)
                    
                    try:
                        fidelity = qrepr_noise.fidelity(qrepr_veri, squared=True)
                        #fidelity = qrepr_noise.fidelity(qrepr_noiseless, squared=True)
                        fidelity_ls.append(fidelity)
                        successful_cnt += 1
                        # Plot the entangled state here
                        # plot_qubit_graph(data_noiseless["qubit"])
                        # pick_entangled_qubits(data_noise["qubit"])
                        if m_collector.is_meas_mismatch:
                            meas_mismatch_cnt += 1
                            # print("meas mismatch at seed",seed,"fidelity=",fidelity)
                            mismatch_dict[str(seed)] = fidelity
                    except TypeError as e:
                        print("TypeError when calculating fidelity")
                    
                else:
                    successful_cnt += 1
                    # if m_collector.is_meas_mismatch:
                    #    meas_mismatch_cnt+=1
                    #    mismatch_dict[str(seed)]=fidelity
            seed += 1
            cnt += 1
            if cnt % 10 == 0:
                log.info(f"\t\tcnt:{cnt},successful_cnt:{successful_cnt},meas_mismatch_cnt:{meas_mismatch_cnt}")
                mean_fidelity=np.average(fidelity_ls)
                log.info(f"\t\tfidelity: {mean_fidelity}")

        if not only_noise and successful_cnt > 0:
            mean_fidelity=np.average(fidelity_ls)
            fidelity_dict[num_repeater] = mean_fidelity
            #log.info(f"\t\tfidelity_dict: {fidelity_dict}")
        prob_dict[num_repeater] = (cnt, successful_cnt)
        #log.info(f"\t\tcnt: {cnt}, successful_cnt: {successful_cnt}, success_prob: {successful_cnt/cnt}, meas_mismatch_cnt: {meas_mismatch_cnt}")
        sim_rate,theo_rate= cal_rate_from_single_data(sim_prob=successful_cnt/cnt,total_distance=total_distance,num_repeater=num_repeater,
                                                      m=self.cfg.rgs.num_branches_half,b0=self.cfg.rgs.b0,b1=self.cfg.rgs.b1,
                                                      p_loss_length=self.cfg.network.photon_loss,QFC_loss=self.cfg.emitter.QFC_loss,
                                                      detector_eff=self.cfg.emitter.detector_eff,collection_eff=self.cfg.emitter.collection_eff,is_per_memory_qubit=True)
        self.final_data.append({
                'distance': total_distance,
                'num_repeaters':num_repeater,
                'success_prob': successful_cnt/cnt,
                'sim_rate': sim_rate,
                'theo_rate': theo_rate,
                'fidelity': mean_fidelity
                })

        # print("logical x prob",1-debug_noise[0]/debug_noise[1],"logical z prob",1-debug_noise[2]/debug_noise[3])
        return fidelity_dict, prob_dict, elasped_time_dict, elasped_time_dict_per_run

    def run_protocol_once(self, network, protocol, seed, num_repeater):
        """To run the protocol on the network once
        """
        # print(f"{ns.sim_time():.1f}: Inside run_protocol_once, network is {network}, protocol is {protocol},seed is {seed}")
        # Reseed all rng
        ns.set_random_state(seed)
        self.rng_noise.seed(seed)
        self.rng_measure.seed(seed)
        self.rng_loss.seed(seed)
        # XXX refactor this
        rng_measure_mem.seed(seed)
        # Run the protocol after reseeding the rng
        protocol.start()
        stats = ns.sim_run()
        elasped_time = stats.data["elapsed_wall_time"]
        protocol.stop()
        repeater_chain_success, data, logical_prob = self.collect_statistic(network, num_repeater, seed)
        return repeater_chain_success, data, logical_prob, elasped_time

    def cal_estimated_running_time(self, elasped_time_dict_per_run):
        """To estimate the total running time required
        """
        
        # read from varying_params instead of removed attributes
        num_rep_values = self.varying_params.get("num_repeaters", [])
        distances = self.varying_params.get("distances", [])
        for distance in distances:
            total_estimated_runtime = 0
            required_successful_cnt = 100  # per number of repeater
            for num_repeater in num_rep_values:
                prob_repeater_chain = cal_exact_prob_2level_tree(
                    tree_vec=[self.cfg.rgs.b0, self.cfg.rgs.b1],
                    total_distance=distance,
                    num_repeater=num_repeater,
                    m=self.cfg.rgs.num_branches_half,
                    QFC_loss=self.cfg.emitter.QFC_loss,
                    detector_eff=self.cfg.emitter.detector_eff,
                    collection_eff=self.cfg.emitter.collection_eff)
        #for num_repeater in self.num_repeaters:
        #    prob_repeater_chain = cal_exact_prob_2level_tree(
        #        tree_vec=[self.cfg.rgs.b0, self.cfg.rgs.b1], total_distance=self.distances[0], num_repeater=num_repeater, m=self.cfg.rgs.num_branches_half, 
        #        QFC_loss=self.cfg.emitter.QFC_loss,detector_eff=self.cfg.emitter.detector_eff,collection_eff=self.cfg.emitter.collection_eff)
                print("elasped_time_dict_per_run",elasped_time_dict_per_run)
                time_noise = elasped_time_dict_per_run[f'{distance}'][f'{num_repeater}_noise']
                # time_noiseless=elasped_time_dict_per_run[f'{num_repeater}_noiseless']
                # estimated_runtime+=time_noise*required_successful_cnt/prob_repeater_chain+time_noiseless*required_successful_cnt
                estimated_runtime = time_noise*required_successful_cnt/prob_repeater_chain
                total_estimated_runtime += estimated_runtime
                print(f'For {distance}km, {num_repeater} repeaters, prob_repeater_chain={prob_repeater_chain},estimated runtime: {estimated_runtime} second or {estimated_runtime/3600} hour')
        print(f'total time:{total_estimated_runtime/3600} hour')

if __name__ == "__main__":
    import sys
    config_file = Constants.DEFAULT_PARAM_FILE

    fixed_params = {
        "network": {"photon_loss": 0},
        "emitter":{"emitter_T2":3000,"memory_T2":20E6,"QFC_loss":0},
        "rgs":{"num_branches_half":6,"b0":1,"b1":1}
    }
    varying_params = {
        "num_repeaters": [1,2,3,4],
        "distance": [10],
    }
    sim = APESimulation(iterations= 10,
                        min_successful=0,
                        fixed_params=fixed_params,
                        varying_params=varying_params,
                        parameter_file=config_file,
                        output_dir="results",)
    data=sim.start()
    print('final_data',data)
    sim.plot(final_data=data, show_theo_rate=True, x_axis1="num_repeaters", y_axis1="sim_rate", xlabel1="Number of repeaters", ylabel1="Rate (Hz)",
         label_param1="distance", title1="Rate vs Number of repeaters",
         x_axis2="num_repeaters", y_axis2="fidelity", xlabel2="Number of repeaters", ylabel2="Fidelity",
         label_param2="distance", title2="Fidelity vs Number of repeaters"
         )
    sim.finalize()
