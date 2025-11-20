import os
import pydynaa as pd
import pandas
import logging
import numpy as np
import netsquid as ns
from matplotlib import pyplot as plt

from netsquid.qubits.qformalism import QFormalism
from netsquid.components import ClassicalChannel, QuantumChannel
from netsquid.protocols.protocol import Signals
from netsquid.components.clock import Clock
from netsquid.nodes.network import Network
from netsquid.util.datacollector import DataCollector
from netsquid.components.models.delaymodels import FibreDelayModel
from netsquid.components.models.qerrormodels import FibreLossModel
from netsquid.components.models.qerrormodels import DepolarNoiseModel
from netsquid.qubits.sparsedmtools import SparseDMRepr
from qnpack.common.config import Config
from qnpack.common.logging import setup_logging
from qnpack.common.simulation import Simulation
from qnpack.common.constants import Constants
from qnpack.common.utils import calculate_distances
from qnpack.oneG.advanced_ion_trap import Adv_Ion_Trap
from qnpack.oneG.lib.models import BSMGatedQuantumDetector
from qnpack.oneG.lib.protocols import RepeaterProtocol, DetectorStatus
from qnpack.oneG.lib.operators import create_meas_ops
import itertools



log = logging.getLogger(__name__)

class IonTrapSimulation(Simulation):
    def __init__(self, logfile=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        setup_logging(name=__name__,
                      level=logging.DEBUG if self.cfg.sim.debug else logging.INFO,
                      logfile=logfile)
        log.info(f"Configuration:\n{self.cfg}")

    def plot(self, final_data, x_axis1, y_axis1, xlabel1, ylabel1, label_param1, 
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
            else:
                ax1.errorbar((1-subset[x_axis1]), subset[y_axis1], label=f"{label_param1}={value}")
    
        ax1.set_xlabel(xlabel1)  # Format axis labels
        ax1.set_ylabel(ylabel1)
        ax1.set_title(title1)
        ax1.legend(title=label_param1.replace("_", " ").title())


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

        # Save the figures
        plt.tight_layout()
        plt.savefig(f"{self.output_dir}/{filename}")

    def start(self):
        ns.set_random_state()
        ns.set_qstate_formalism(QFormalism.SPARSEDM)

        final_data = []
        param_names = list(self.varying_params.keys())  # List of parameter names to iterate

        log.info(f"Running simulation with parameters: {self.varying_params}")
        log.info(f"Fixed parameters: {self.fixed_params}")
        log.info(f"Iterations: {self.cfg.sim.iterations}")

        # Generate all combinations of varying parameters
        for param_values in itertools.product(*self.varying_params.values()):
            param_dict = dict(zip(param_names, param_values))
            log.info(f"Running simulation with parameters: {param_dict}")
            
            fixed_params_values = self.fixed_params.values()
            fixed_params_unpacked = {}
            for d in fixed_params_values:
                for k, v in d.items():
                    fixed_params_unpacked[k] = v

            # Merge varying parameters with fixed parameters
            sim_params = {**fixed_params_unpacked, **param_dict}

            # Calculate node distances based on number of repeaters and total distance
            total_nodes = 3 + 2 * sim_params["num_repeaters"]
            sim_params["node_distance"] = sim_params["distance"] / (total_nodes - 1)

            # Set up the network and protocol
            network_params_init = {key: sim_params[key] for key in sim_params if key not in ["max_emission_retries", "retries", "distance", "proto_sched"]}
            network_param_keys = ['photon_loss', 'init_photon_loss', 'c_lightspeed', 'q_lightspeed', 'node_c_pos', 'coherence_time', 'z_gate_duration', 
                                  'x_gate_duration', 'ms_depolar_prob', 'x_depolar_prob', 'z_depolar_prob', 'measurement_duration', 'emission_duration', 
                                  'collection_efficiency', 'emission_fidelity', 'ms_pi_over_2_duration', 'retry_duration', 'channel_depolar_rate', 
                                  'coupling_efficiency', 'num_repeaters', 'node_distance']

            
            # Helper function to fetch parameters dynamically from the correct module
            def get_param_value(module_name, key):
                if module_name == 'network':
                    return getattr(self.cfg.network, key, None)
                elif module_name == 'ion_trap':
                    return getattr(self.cfg.ion_trap, key, None)
                else:
                    return getattr(self.cfg.bsm, key, None)
                # else:
                #     return self.cfg.bsm.max_emission_retries
            
            # Separate keys for network_params and those needing self.cfg
            network_params = {key: network_params_init[key] for key in network_params_init}
            
            # Parameters not in the list should be passed as self.cfg.<module>.<parameter>
            for key in network_param_keys:
                if key not in network_params_init:
                    # Identify the module the parameter belongs to
                    if key in self.cfg.network.__dict__:
                        module_name = 'network'
                    elif key in self.cfg.ion_trap.__dict__:
                        module_name = 'ion_trap'
                    # elif key in self.cfg.bsm.__dict__:
                    #     module_name = 'bsm'
                    else:
                        module_name = 'bsm'
            
                    # Get the value from the correct module
                    if module_name:
                        network_params[key] = get_param_value(module_name, key)
            
            # Now you can pass network_params to network_setup
            log.info(f"Final network params before building network: {network_params}")
            network, bsm_nodes, r_nodes, node_q1, node_q2, _ = self.network_setup(**network_params)
            # only relevant parameters for RepeaterProtocol
            repeater_param_keys = ['node_c_pos', 'z_gate_duration', 'x_gate_duration', 'node_distance',
                                   "max_emission_retries", "num_repeaters", "proto_sched"]
            repeater_params_init = {key: sim_params[key] for key in repeater_param_keys if key in sim_params}
            
            repeater_params = {key: repeater_params_init[key] for key in repeater_params_init}
            
            # Parameters not in the list should be passed as self.cfg.<module>.<parameter>
            for key in repeater_param_keys:
                if key not in repeater_params_init:
                    # Identify the module the parameter belongs to
                    if key in self.cfg.network.__dict__:
                        module_name = 'network'
                    elif key in self.cfg.ion_trap.__dict__:
                        module_name = 'ion_trap'
                    # elif key in self.cfg.bsm.__dict__:
                    #     module_name = 'bsm'
                    else:
                        module_name = 'bsm'
            
                    # Get the value from the correct module
                    if module_name:
                        repeater_params[key] = get_param_value(module_name, key)
            log.info(f"Final repeater params before repeater protocol: {repeater_params}")
            protocol = RepeaterProtocol(self.cfg, network, bsm_nodes, r_nodes, **repeater_params)

            dc = self.setup_datacollector(node_q1, node_q2, protocol)
            error_count = 0
            # Run trials
            fidelities, times, success_times, num_retries = [], [], [], []
            rows_added = False
            diff = 0
            for i in range(self.cfg.sim.iterations):
                log.info(
                    f"\t  Running iteration {i+1} of [{self.cfg.sim.iterations} total iters]")
                if not i:
                    try:
                        protocol.start()
                    except Exception as e:
                        print(e)
                        print("restarting protocol")
                        protocol.start()
                        print(protocol.subprotocols)
                else:
                    ns.set_random_state()
                    protocol.reset()
    
                    # Reinitialize quantum states
                    node_q1.subcomponents['ion_trap_quantum_communication_device'].resample()
                    node_q1.subcomponents['ion_trap_quantum_communication_device'].state_initialization(node_name="QNode_1")
                    node_q2.subcomponents['ion_trap_quantum_communication_device'].resample()
                    node_q2.subcomponents['ion_trap_quantum_communication_device'].state_initialization(node_name="QNode_2")
    
                    # Reset repeater nodes
                    for r_node_name in sorted(r_nodes):
                        r_node = network.get_node(r_node_name)
                        r_node.subcomponents['ion_trap_quantum_communication_device'].resample()
                        r_node.subcomponents['ion_trap_quantum_communication_device'].state_initialization(node_name=r_node_name, topo=[0, 1])
                ns.sim_run()
                try:
                    if len(dc.dataframe) != diff:
                        rows_added=True
                        diff = len(dc.dataframe)
                    if rows_added:
                        fid = dc.dataframe.loc[diff-1, 'fidelity']
                        if fid == -1:
                            log.info("-1 detected, filtering iteration data")
                            fidelities.append(-1)
                        else:
                            fidelities.append(fid)
                            retries_itr = protocol.subprotocols['node_c'].retries
                            avg_retries = round(sum(retries_itr) / len(retries_itr))
                            if fid > 0.2:
                                # for retry in retries_itr:
                                num_retries.append(avg_retries)
                    s_time = (protocol.subprotocols['node_c'].end_time - protocol.subprotocols['node_c'].start_time)/1e9
                    times.append(s_time)
                    success_times.append(s_time)
                    rows_added=False
                except KeyError as e:
                    log.info(f"Key error: {e}")
                    s_time = (protocol.subprotocols['node_c'].end_time - protocol.subprotocols['node_c'].start_time)/1e9
                    times.append(s_time)
                    error_count += 1
                    if error_count == self.cfg.sim.iterations:
                        # this means that all iterations had errors, so adding the fidelity value only for the last iteration
                        fidelities.append(-1)
                    log.warning(f"KeyError: Fidelity column missing, skipping iteration")
                    continue

            try:
                # Filter out -1 values and append valid fidelities once
                valid_fidelities = [f for f in fidelities if f != -1]
            except KeyError:
                log.warning("KeyError: No valid fidelities")
                valid_fidelities = None
                total_rate = 0
            if valid_fidelities:
                log.info(f"Valid fidelities: {valid_fidelities}")
                log.info(f"\t  Fidelities: {[round(x,2) for x in fidelities]}")
                if len(times) != 0:
                    total_time = sum(times)
                num_success = len(valid_fidelities)
                rate = num_success / total_time
                log.info(f"\t  Rate of Entanglement: {round(rate,2)} with total time: {total_time} and number of success: {num_success}")
            else:
                if len(times) != 0:
                    total_time = total_time + sum(times)
                num_success = 0
                total_rate = 0
                log.info(f"\t  Rate of Entanglement: {round(rate,2)}, with total time: {total_time} and number of success: {num_success}")
            # Store the mean and SEM of fidelities for each configuration
            if len(valid_fidelities) > 0:
                true_fidelities = [round(x,2) for x in valid_fidelities]
                mean_fidelity = np.mean(true_fidelities)
                mean_time = np.mean(success_times)
                mean_retries = np.mean(num_retries)
                log.info(f"\t  Mean Fidelity: {mean_fidelity}")
                if len(valid_fidelities) > 1:
                    sem_fidelity = np.std(valid_fidelities, ddof=1) / \
                        np.sqrt(len(valid_fidelities))
                else:
                    sem_fidelity = 0
            else:
                sem_fidelity = 0
                mean_fidelity = 0
            # Store results
            final_data.append({
                **param_dict,  # Store the varying parameters
                'fidelity': mean_fidelity,
                'sem': sem_fidelity,
                'rate': rate,
                'mean_retries': mean_retries,
                'num_success': num_success
            })
        return final_data


    def finalize(self):
        pass

    def network_setup(self, num_repeaters,
                      node_distance,
                      photon_loss,
                      init_photon_loss,
                      c_lightspeed,
                      q_lightspeed,
                      node_c_pos,
                      coherence_time,
                      z_gate_duration,
                      x_gate_duration,
                      ms_depolar_prob,
                      x_depolar_prob,
                      z_depolar_prob,
                      measurement_duration,
                      emission_duration,
                      collection_efficiency,
                      emission_fidelity,
                      ms_pi_over_2_duration,
                      retry_duration,
                      channel_depolar_rate,
                      coupling_efficiency):
        network = Network("Simple repeater experiment")
        # Create end nodes and add them to the network
        node_q1, node_q2, node_c = network.add_nodes(
            ["node_q1", "node_q2", "node_c"])

        q1_iontrap = Adv_Ion_Trap(self.cfg, num_positions=1, collection_efficiency=collection_efficiency,
                                  coherence_time=coherence_time,
                                  retry_duration=retry_duration,
                                  x_gate_duration=x_gate_duration,
                                  z_gate_duration=z_gate_duration,
                                  emission_duration=emission_duration,
                                  emission_fidelity=emission_fidelity,
                                  ms_pi_over_2_duration=ms_pi_over_2_duration,
                                  ms_depolar_prob=ms_depolar_prob,
                                  x_depolar_prob=x_depolar_prob,
                                  z_depolar_prob=z_depolar_prob,
                                  measurement_duration=measurement_duration,
                                  noise_model=self.cfg.ion_trap.noise_model)
        node_q1.add_subcomponent(q1_iontrap)
        q2_iontrap = Adv_Ion_Trap(self.cfg, num_positions=1, collection_efficiency=collection_efficiency,
                                  coherence_time=coherence_time,
                                  retry_duration=retry_duration,
                                  x_gate_duration=x_gate_duration,
                                  z_gate_duration=z_gate_duration,
                                  emission_duration=emission_duration,
                                  emission_fidelity=emission_fidelity,
                                  ms_pi_over_2_duration=ms_pi_over_2_duration,
                                  ms_depolar_prob=ms_depolar_prob,
                                  x_depolar_prob=x_depolar_prob,
                                  z_depolar_prob=z_depolar_prob,
                                  measurement_duration=measurement_duration,
                                  noise_model=self.cfg.ion_trap.noise_model)
        node_q2.add_subcomponent(q2_iontrap)

        bsm_nodes = set()
        r_nodes = set()
        if num_repeaters == 0:
            bsm_nodes.add("node_bsm1")
        else:
            for i in range(num_repeaters):
                bsm_nodes.add(f"node_bsm{i+1}")
                bsm_nodes.add(f"node_bsm{i+2}")
                r_nodes.add(f"node_r{i+1}")

        bsm_list = sorted(list(bsm_nodes))
        node_bsm_list = sorted(bsm_list, key=lambda x: int(x.split('node_bsm')[1]))
        r_list = sorted(list(r_nodes))
        node_r_list = sorted(r_list, key=lambda x: int(x.split('node_r')[1]))
        network.add_nodes(node_bsm_list)
        network.add_nodes(node_r_list)
        # log.debug(network.nodes)
        log.debug("Network successfully created")
        num_bsm = node_bsm_list[-1].split("node_bsm")[1]

        # loss model for Quantum Channels
        loss_model = FibreLossModel(
            p_loss_length=photon_loss, p_loss_init=init_photon_loss)

        # noise model for Quantum Channels
        noise = DepolarNoiseModel(
            depolar_rate=channel_depolar_rate, time_independent=True)

        # node_c_pos is the tosition of the control node [0, num_nodes-1]
        distances = calculate_distances(node_c_pos, num_repeaters, node_distance)
        log.debug(f"Distances from node_c: {distances}")
        # Setting up Classical and Quantum Channels for n repeaters
        conn_list = []
        for i in range(len(r_nodes)):
            left = node_bsm_list[i]
            middle = node_r_list[i]
            if i != len(r_nodes) - 1:
                next_repeater = node_r_list[i+1]
                next_node = network.get_node(f"{next_repeater}")
            right = node_bsm_list[i+1]
            left_node = network.get_node(f"{left}")
            middle_node = network.get_node(f"{middle}")
            right_node = network.get_node(f"{right}")
            # log.debug("Left", left_node)
            # log.debug("Right", right_node)
            # log.debug("Middle", middle_node)

            # Setup classical connections from BSMi to Repeateri on right
            conn_str = f"CChannel_BSM{i+1}->R{i+1}"
            if conn_str not in conn_list:
                conn_cfibre_br = ClassicalChannel(f"CChannel_BSM{i+1}->R{i+1}", length=node_distance,
                                                  models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                network.add_connection(left_node, middle_node, channel_to=conn_cfibre_br,
                                       port_name_node1="clock_to_right", port_name_node2="clock_from_left")
                conn_list.append(conn_str)

            conn_str = f"CChannel_res_BSM{i+1}->R{i+1}"
            if conn_str not in conn_list:
                cchannel_meas_bsmr = ClassicalChannel(f"CChannel_res_BSM{i+1}->R{i+1}", length=node_distance,
                                                      models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                network.add_connection(left_node, middle_node, channel_to=cchannel_meas_bsmr, label="BSM result",
                                       port_name_node1="BSM_res_to_right", port_name_node2="BSM_res_from_left")
                # cchannel_meas_bsm1q1.ports["send"].bind_input_handler(lambda msg: log.debug(msg,
                # "Sending a message to check the channel"))
                conn_list.append(conn_str)

            # Setup classical connections from BSMi+1 to Repeateri on left
            conn_str = f"CChannel_BSM{i+2}->R{i+1}"
            if conn_str not in conn_list:
                conn_cfibre_br = ClassicalChannel(f"CChannel_BSM{i+2}->R{i+1}", length=node_distance,
                                                  models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                network.add_connection(right_node, middle_node, channel_to=conn_cfibre_br,
                                       port_name_node1="clock_to_left", port_name_node2="clock_from_right")
                conn_list.append(conn_str)

            conn_str = f"CChannel_res_BSM{i+2}->R{i+1}"
            if conn_str not in conn_list:
                cchannel_meas_bsmr = ClassicalChannel(f"CChannel_res_BSM{i+2}->R{i+1}", length=node_distance,
                                                      models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                network.add_connection(right_node, middle_node, channel_to=cchannel_meas_bsmr, label="BSM result",
                                       port_name_node1="BSM_res_to_left", port_name_node2="BSM_res_from_right")
                conn_list.append(conn_str)

            # Setup quantum connections from Repeateri to BSMi on left
            conn_str = f"QChannel_{middle}->{left}"
            if conn_str not in conn_list:
                qchannel_rbsmleft = QuantumChannel(f"QChannel_{middle}->{left}", length=node_distance,
                                                   models={"quantum_loss_model": loss_model,
                                                           "delay_model": FibreDelayModel(c=q_lightspeed),
                                                           "noise_model": noise})
                network.add_connection(middle_node, left_node, channel_to=qchannel_rbsmleft, label="quantum",
                                       port_name_node1=f"qport_{middle}_{left}", port_name_node2=f"qport_{left}_{middle}")
                conn_list.append(conn_str)

            # Setup quantum connections from Repeateri to BSMi+1 on right
            conn_str = f"QChannel_{middle}->{right}"
            if conn_str not in conn_list:
                qchannel_rbsmright = QuantumChannel(f"QChannel_{middle}->{right}", length=node_distance,
                                                    models={"quantum_loss_model": loss_model,
                                                            "delay_model": FibreDelayModel(c=q_lightspeed),
                                                            "noise_model": noise})
                network.add_connection(middle_node, right_node, channel_to=qchannel_rbsmright, label="quantum",
                                       port_name_node1=f"qport_{middle}_{right}", port_name_node2=f"qport_{right}_{middle}")
                conn_list.append(conn_str)

            # Setup classical connections from BSMi+1 to Repeateri+1 on right
            if i != len(r_nodes) - 1:
                conn_str = f"CChannel_BSM{i+2}->R{i+2}"
                if conn_str not in conn_list:
                    conn_cfibre_br1 = ClassicalChannel(f"CChannel_BSM{i+2}->R{i+2}", length=node_distance,
                                                       models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                    network.add_connection(right_node, next_node, channel_to=conn_cfibre_br1,
                                           port_name_node1="clock_to_right", port_name_node2="clock_from_left")
                    conn_list.append(conn_str)

                conn_str = f"CChannel_res_BSM{i+2}->R{i+2}"
                if conn_str not in conn_list:
                    cchannel_meas_bsmr1 = ClassicalChannel(f"CChannel_res_BSM{i+2}->R{i+2}", length=node_distance,
                                                           models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                    network.add_connection(right_node, next_node, channel_to=cchannel_meas_bsmr1, label="BSM result",
                                           port_name_node1="BSM_res_to_right", port_name_node2="BSM_res_from_left")
                    conn_list.append(conn_str)

                # Setup quantum connections from Repeateri+1 to BSMi+1 on left
                conn_str = f"QChannel_{next_repeater}->{right}"
                if conn_str not in conn_list:
                    qchannel_r1bsm1 = QuantumChannel(f"QChannel_{next_repeater}->{right}", length=node_distance,
                                                     models={"quantum_loss_model": loss_model,
                                                             "delay_model": FibreDelayModel(c=q_lightspeed),
                                                             "noise_model": noise})
                    network.add_connection(next_node, right_node, channel_to=qchannel_r1bsm1, label="quantum",
                                           port_name_node1=f"qport_{next_repeater}_{right}",
                                           port_name_node2=f"qport_{right}_{next_repeater}")
                    conn_list.append(conn_str)

            # BSM Node Setup
            last_bsm_node = network.get_node(f"node_bsm{num_bsm}")

            if right_node != last_bsm_node:
                self.bsm_node_setup(right_node, qport_left_name=f"qport_{right}_{middle}",
                                    qport_right_name=f"qport_{right}_{next_repeater}",
                                    coupling_efficiency=coupling_efficiency)

            # add classical channel from all repeater nodes to the control node
            # print(f"Distance between node_c and {middle}", distances[f"{middle}"])
            conn_cfibre_rc = ClassicalChannel(f"CChannel_R{i+1}->C", length=distances[f"{middle}"],
                                              models={"delay_model": FibreDelayModel(c=c_lightspeed)})
            network.add_connection(middle_node, node_c, channel_to=conn_cfibre_rc,
                                   port_name_node1="to_control", port_name_node2=f"from_{middle}")

            # add classical channel from the control node to all repeater nodes
            # log.info(f"Distance to q_node1: {distances["node_q1"]}")
            conn_cfibre_init_ctrl = ClassicalChannel(f"CChannel_C->R{i+1}", length=distances[f"{middle}"],
                                                     models={"delay_model": FibreDelayModel(c=c_lightspeed)})
            network.add_connection(node_c, middle_node, channel_to=conn_cfibre_init_ctrl,
                                   port_name_node1=f"control_to_{middle}", port_name_node2="from_control")

            # Ion_Trap setup for n repeaters
            self.r_node_setup(middle_node, num_ions=2, qport_name1=f"qport_{middle}_{left}",
                              qport_name2=f"qport_{middle}_{right}", coherence_time=coherence_time,
                              z_gate_duration=z_gate_duration,
                              ms_pi_over_2_duration=ms_pi_over_2_duration,
                              x_gate_duration=x_gate_duration,
                              ms_depolar_prob=ms_depolar_prob,
                              x_depolar_prob=x_depolar_prob,
                              z_depolar_prob=z_depolar_prob,
                              measurement_duration=measurement_duration,
                              emission_duration=emission_duration,
                              collection_efficiency=collection_efficiency,
                              emission_fidelity=emission_fidelity,
                              retry_duration=retry_duration)
            # log.debug(f"{left}_node ports:", left_node.ports)
            # log.debug(f"{right}_node ports:", right_node.ports)
            # log.debug(f"{middle}_node ports:", middle_node.ports)
            log.debug("---------------------------------------")
        log.debug("Loop done")

        # add classical channel from the control node to qnodes for initialization sequence and sharing DBSM results
        conn_cfibre_init_q1 = ClassicalChannel(f"CChannel_Ctrl->Q1", length=distances["node_q1"],
                                               models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(node_c, node_q1, channel_to=conn_cfibre_init_q1,
                               port_name_node1=f"control_to_{node_q1}", port_name_node2="from_control")

        conn_cfibre_init_q2 = ClassicalChannel(f"CChannel_Ctrl->Q2", length=distances["node_q2"],
                                               models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(node_c, node_q2, channel_to=conn_cfibre_init_q2,
                               port_name_node1=f"control_to_{node_q2}", port_name_node2="from_control")

        # add classical channel from the qnodes to control node for entanglement success
        conn_cfibre_cq1 = ClassicalChannel(f"CChannel_Q1->C", length=distances["node_q1"],
                                           models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(node_q1, node_c, channel_to=conn_cfibre_cq1,
                               port_name_node1="from_qnode", port_name_node2="to_q1")

        conn_cfibre_cq2 = ClassicalChannel(f"CChannel_Q2->C", length=distances["node_q2"],
                                           models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(node_q2, node_c, channel_to=conn_cfibre_cq2,
                               port_name_node1="from_qnode", port_name_node2="to_q2")

        # Classical Channels from BSM1 to Q1
        node_bsm1 = network.get_node("node_bsm1")
        conn_cfibre_b1q1 = ClassicalChannel("CChannel_BSM1->Q1", length=node_distance,
                                            models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(node_bsm1, node_q1, channel_to=conn_cfibre_b1q1,
                               port_name_node1="clock_to_left", port_name_node2="clock_from_right")
        cchannel_meas_bsm1q1 = ClassicalChannel("CChannel_res_BSM1->Q1", length=node_distance,
                                                models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(node_bsm1, node_q1, channel_to=cchannel_meas_bsm1q1, label="BSM result",
                               port_name_node1="BSM_res_to_left", port_name_node2="BSM_res_from_right")

        # Classical Channels from last BSM to Q2
        if num_repeaters == 0:
            last_bsm_node = node_bsm1
        else:
            last_bsm_node = network.get_node(f"node_bsm{num_bsm}")
        conn_cfibre_bq2 = ClassicalChannel("CChannel_BSM->Q2", length=node_distance,
                                           models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(last_bsm_node, node_q2, channel_to=conn_cfibre_bq2,
                               port_name_node1="clock_to_right", port_name_node2="clock_from_left")
        cchannel_meas_bsmq2 = ClassicalChannel("CChannel_res_BSM->Q2", length=node_distance,
                                               models={"delay_model": FibreDelayModel(c=c_lightspeed)})
        network.add_connection(last_bsm_node, node_q2, channel_to=cchannel_meas_bsmq2, label="BSM result",
                               port_name_node1="BSM_res_to_right", port_name_node2="BSM_res_from_left")

        # Setup quantum channels from Q1 to BSM Node1
        qchannel_q1b1 = QuantumChannel(
            "QChannel_Q1->B1", length=node_distance,
            models={"quantum_loss_model": loss_model, "delay_model": FibreDelayModel(c=q_lightspeed),
                    "noise_model": noise})
        network.add_connection(node_q1, node_bsm1, channel_to=qchannel_q1b1, label="quantum",
                               port_name_node1="qport_node_q1_node_bsm1", port_name_node2="qport_node_bsm1_q1")

        # Setup quantum channels from Q2 to last BSM Node
        qchannel_q2b = QuantumChannel(
            "QChannel_Q2->B", length=node_distance,
            models={"quantum_loss_model": loss_model, "delay_model": FibreDelayModel(c=q_lightspeed),
                    "noise_model": noise})
        network.add_connection(node_q2, last_bsm_node, channel_to=qchannel_q2b, label="quantum",
                               port_name_node1=f"qport_node_q2_node_bsm{num_bsm}",
                               port_name_node2=f"qport_node_bsm{num_bsm}_q2")

        # add classical channels from control node to all BSM nodes
        if num_repeaters != 0:
            for i in range(len(node_bsm_list)):
                bsm = node_bsm_list[i]
                # print(f"Distance between node_c and {bsm}", distances[f"{bsm}"])
                node_bsm = network.get_node(f"{bsm}")
                conn_cfibre_cb = ClassicalChannel("CChannel_C->BSM", length=distances[f"{bsm}"],
                                                  models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                network.add_connection(node_c, node_bsm, channel_to=conn_cfibre_cb,
                                       port_name_node1=f"control_to_{bsm}", port_name_node2="to_bsm")
                conn_cfibre_bc = ClassicalChannel("CChannel_BSM->C", length=distances[f"{bsm}"],
                                                  models={"delay_model": FibreDelayModel(c=c_lightspeed)})
                network.add_connection(node_bsm, node_c, channel_to=conn_cfibre_bc,
                                       port_name_node1="to_control", port_name_node2=f"from_{bsm}")

        # Add Clock to the first BSM node
        clk = Clock("BSMCLK", self.cfg.clock.HZ, max_ticks=self.cfg.clock.max_ticks)
        node_bsm1.add_subcomponent(clk)

        # Add Clock to the last BSM node
        clk1 = Clock("BSMCLK", self.cfg.clock.HZ, max_ticks=self.cfg.clock.max_ticks)
        last_bsm_node.add_subcomponent(clk1)

        # Setup Quantum Detector for BSM1
        bsm_detector_1 = BSMGatedQuantumDetector('BSMDETECTOR', detection_window=self.cfg.bsm.detection_window,
                                                 system_delay=self.cfg.bsm.system_delay,
                                                 meas_operators=create_meas_ops(),
                                                 num_input_ports=2, num_output_ports=1,
                                                 coupling_efficiency=coupling_efficiency,
                                                 error_on_fail=False)
        node_bsm1.add_subcomponent(bsm_detector_1)

        # Setup Quantum Detector for last BSM
        if num_repeaters != 0:
            bsm_detector_last = BSMGatedQuantumDetector('BSMDETECTOR', detection_window=self.cfg.bsm.detection_window,
                                                        system_delay=self.cfg.bsm.system_delay,
                                                        meas_operators=create_meas_ops(),
                                                        num_input_ports=2, num_output_ports=1,
                                                        coupling_efficiency=coupling_efficiency,
                                                        error_on_fail=False)
            last_bsm_node.add_subcomponent(bsm_detector_last)

            # port connections for last BSM
            last_bsm_port_name = f"qport_node_bsm{num_bsm}_node_r{num_repeaters}"
            last_bsm_node.ports[last_bsm_port_name].forward_input(
                bsm_detector_last.ports["qin0"])
            last_bsm_node.ports[f"qport_node_bsm{num_bsm}_q2"].forward_input(
                bsm_detector_last.ports["qin1"])

        # port connections for BSM1
        if num_repeaters == 0:
            bsm1_port_name = "qport_node_bsm1_q2"
        else:
            bsm1_port_name = 'qport_node_bsm1_node_r1'
        node_bsm1.ports["qport_node_bsm1_q1"].forward_input(
            bsm_detector_1.ports["qin0"])
        node_bsm1.ports[bsm1_port_name].forward_input(
            bsm_detector_1.ports["qin1"])

        # port connections for end nodes
        node_q2.qmemory.ports["qout0"].forward_output(
            node_q2.ports[f"qport_node_q2_node_bsm{num_bsm}"])
        node_q1.qmemory.ports["qout0"].forward_output(
            node_q1.ports["qport_node_q1_node_bsm1"])

        # print(node_q1.ports, node_q2.ports)

        return network, node_bsm_list, node_r_list, node_q1, node_q2, num_repeaters

    def bsm_node_setup(self, node, qport_left_name, qport_right_name, coupling_efficiency):
        # Add Clock to the BSM nodes
        # log.debug(f"{node}, {qport_left_name}, {qport_right_name}")
        clk = Clock("BSMCLK", self.cfg.clock.HZ, max_ticks=self.cfg.clock.max_ticks)
        node.add_subcomponent(clk)
        # Set up BSM detector
        bsm_detector = BSMGatedQuantumDetector('BSMDETECTOR', detection_window=self.cfg.bsm.detection_window,
                                               system_delay=self.cfg.bsm.system_delay,
                                               meas_operators=create_meas_ops(),
                                               num_input_ports=2, num_output_ports=2,
                                               coupling_efficiency=coupling_efficiency,
                                               error_on_fail=False)
        node.add_subcomponent(bsm_detector)
        node.ports[qport_left_name].forward_input(
            bsm_detector.ports["qin0"])
        node.ports[qport_right_name].forward_input(
            bsm_detector.ports["qin1"])

    def r_node_setup(self, node, num_ions, qport_name1, qport_name2, coherence_time,
                     z_gate_duration=1, ms_pi_over_2_duration=1,
                     x_gate_duration=1, ms_depolar_prob=0, x_depolar_prob=0,
                     z_depolar_prob=0, measurement_duration=1, emission_duration=1,
                     collection_efficiency=1, emission_fidelity=1,
                     retry_duration=0):
        node_iontrap = Adv_Ion_Trap(self.cfg, num_positions=num_ions,
                                    collection_efficiency=collection_efficiency,
                                    coherence_time=coherence_time,
                                    retry_duration=retry_duration,
                                    x_gate_duration=x_gate_duration,
                                    z_gate_duration=z_gate_duration,
                                    emission_duration=emission_duration,
                                    emission_fidelity=emission_fidelity,
                                    ms_pi_over_2_duration=ms_pi_over_2_duration,
                                    ms_depolar_prob=ms_depolar_prob,
                                    x_depolar_prob=x_depolar_prob,
                                    z_depolar_prob=z_depolar_prob,
                                    measurement_duration=measurement_duration,
                                    noise_model=self.cfg.ion_trap.noise_model)
        node.add_subcomponent(node_iontrap)

        node.qmemory.ports["qout0"].forward_output(
            node.ports[qport_name1])
        node.qmemory.ports["qout1"].forward_output(
            node.ports[qport_name2])

    def setup_datacollector(self, node_q1, node_q2, setup_repeater_protocol):
        """Setup the datacollector to calculate the fidelity
        when the CorrectionProtocol has finished.
        """

        def calc_fidelity(evexpr):
            q_a, = node_q1.qmemory.peek(positions=[0])
            q_b, = node_q2.qmemory.peek(positions=[0])
            eigen_state1 = SparseDMRepr(
                dm=[[0.5, 0, 0, 0.5], [0, 0, 0, 0], [0, 0, 0, 0], [0.5, 0, 0, 0.5]])
            fidelity = ns.qubits.fidelity([q_a, q_b], SparseDMRepr(
                dm=[[1/2, 0, 0, 1/2], [0, 0, 0, 0], [0, 0, 0, 0], [1/2, 0, 0, 1/2]]), squared=True)
            for node in setup_repeater_protocol.subprotocols['node_c'].bsm_results:
                if setup_repeater_protocol.subprotocols['node_c'].bsm_results[node][0].status != DetectorStatus.SUCCESS:
                    log.info(f"Max retries exceeded for node {node}")
                    fidelity = -1
            start = setup_repeater_protocol.subprotocols['node_c'].start_time
            end = setup_repeater_protocol.subprotocols['node_c'].end_time
            sim_time = (end - start)/1e9
            log.debug(f"Simulation time: {sim_time}")
            log.debug(f"Fidelity value: {fidelity}")
            return {"fidelity": fidelity,
                    "time": sim_time
                    }

        dc = DataCollector(calc_fidelity, include_entity_name=False)
        dc.collect_on(pd.EventExpression(source=setup_repeater_protocol.subprotocols['node_c'],
                                         event_type=Signals.SUCCESS.value))
        return dc


if __name__ == "__main__":
    import sys
    config_file = Constants.DEFAULT_PARAM_FILE
    if len(sys.argv) > 1:
        config_file = sys.argv[1]

    fixed_params = {
        # "ion_trap": {"coherence_time": 60000000}
        # "bsm": {"max_emission_retries": 120}
    }

    varying_params = {
        "num_repeaters": [1, 4, 8],
        "distance": [50],
        # "init_photon_loss": [0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
        # "max_emission_retries": [30, 60, 90, 120]
        # "photon_loss": [0.3, 0.2, 0.1]
        # "collection_efficiency": [0.6, 0.7, 0.8, 0.9]
        # "proto_sched": [1, 3]
        # "emission_fidelity": [0.96, 0.97, 0.98, 0.99, 1]
        "coherence_time": [60000000, 100000000, 150000000, 200000000, 250000000]
        # "ms_depolar_prob": [0.1, 0.09, 0.08, 0.07, 0.06, 0.05]
    }
    directory = "results/fidelity"
    sim = IonTrapSimulation(fixed_params=fixed_params,
                             varying_params=varying_params,
                             parameter_file="parameters.yml",
                             output_dir=directory,
                             # logfile=""
                             )
    final_data = sim.start()
    data = pandas.DataFrame(final_data)
    data.to_csv(f"{directory}/ct9.csv", sep=',')