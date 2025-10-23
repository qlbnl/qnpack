import os
import pandas
import logging
import numpy as np
from matplotlib import pyplot as plt

from qnpack.common.simulation import Simulation
from qnpack.common.constants import Constants
from qnpack.common.utils import calculate_distances
from qnpack.common.logging import setup_logging
import itertools
import csv
import ctypes


log = logging.getLogger(__name__)


class TheoRateSimulation(Simulation):
    def __init__(self, logfile=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        log.info(f"Configuration:\n{self.cfg}")

        self._col_eff = self.cfg.network.col_eff
        self._QFC_loss = self.cfg.network.QFC_loss
        self._channel_loss = self.cfg.network.channel_loss
        self._init_loss = self.cfg.network.init_loss
        self._coupling_bsm_loss = self.cfg.network.coupling_bsm_loss
        self._retries = self.cfg.ion_trap.retries
        self._retry_time = self.cfg.ion_trap.retry_time
        self._init_time = self.cfg.ion_trap.init_time
        self._DBSM_time = self.cfg.ion_trap.DBSM_time
        self._BSM_time = self.cfg.ion_trap.BSM_time
        self._spin_echo_time = self.cfg.ion_trap.spin_echo_time
        self._node_pos = self.cfg.network.node_pos

        setup_logging(name=__name__,
                      level=logging.DEBUG if self.cfg.sim.debug else logging.INFO,
                      logfile=logfile)

        self._PL = []
        self._PR = []
        self._max_svalues = []
        self._max_svalues_R = []
        self._s_values_L_list = []
        self._s_values_R_list = []
        # Load the compiled shared library
        this_dir = os.path.dirname(os.path.abspath(__file__))
        lib_path = os.path.join(this_dir, "librepeater.so")
        self._c_lib = ctypes.CDLL(lib_path)

        # Set argument and return types
        self._c_lib.compute_repeater_rate.argtypes = [
            ctypes.c_int, ctypes.c_int,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
        ]
        self._c_lib.compute_repeater_rate.restype = ctypes.c_double

    def plot(self, final_data, x_axis1, y_axis1, xlabel1, ylabel1, label_param1,
             title1="Simulation Results",
             filename="theo_rate_results.png"):
        # Save results
        with open(f"{self.output_dir}/theo_rate_results.csv", mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["distance", "num_repeaters", "rate"])
            writer.writerows(final_data)

        df = pandas.read_csv(f"{self.output_dir}/theo_rate_results.csv")

        # Ensure columns are correctly named
        df.columns = ['distance', 'num_repeaters', 'rate']

        # Plot the data with different lines for each unique 'distance'
        plt.figure(figsize=(10, 6))

        # Loop through each unique distance and plot corresponding data
        for distance in df['distance'].unique():
            subset = df[df['distance'] == distance]
            plt.plot(subset['num_repeaters'], subset['rate'], label=f'{distance} km')

        # Customize the plot
        plt.xticks(range(0, 21, 2))  #
        plt.title('Theoretical Rate vs Number of Repeaters')
        plt.xlabel('Number of Repeaters')
        plt.ylabel('Total Rate')
        plt.legend(title='Distance')

        # Save the plot as PNG
        plt.savefig(f"{self.output_dir}/{filename}")

    def calc_node_dist(self, num_repeaters, distance):
        total_nodes = 3 + 2 * num_repeaters
        node_distance = distance / (total_nodes - 1)
        return node_distance

    # def P_L_i(self, s, channel_loss):
    #     col_eff=self._col_eff
    #     QFC_loss=self._QFC_loss
    #     coupling_bsm_loss = self._coupling_bsm_loss
    #     total_photon_loss = (1 - col_eff) + (col_eff * QFC_loss) + (col_eff * (1 - QFC_loss) * channel_loss) + (col_eff * (1 - QFC_loss) * (1 - channel_loss) * coupling_bsm_loss)
    #     # Compute P l
    #     P = ((1 - total_photon_loss) ** 2) / 2
    #     # fail_prob = (1 - P) ** (self._retries + 1)
    #     return ((1 - P) ** (s - 1)) * P

    # def P_R_j(self, s, channel_loss):
    #     col_eff=self._col_eff
    #     QFC_loss=self._QFC_loss
    #     coupling_bsm_loss = self._coupling_bsm_loss
    #     total_photon_loss = (1 - col_eff) + (col_eff * QFC_loss) + (col_eff * (1 - QFC_loss) * channel_loss) + (col_eff * (1 - QFC_loss) * (1 - channel_loss) * coupling_bsm_loss)
    #     # Compute P
    #     P = ((1 - total_photon_loss) ** 2) / 2
    #     # fail_prob = (1 - P) ** (self._retries + 1)
    #     return ((1 - P) ** (s - 1)) * P

    def compute_per_attempt_success(self, channel_loss):
        col_eff = self._col_eff
        QFC_loss = self._QFC_loss
        coupling_bsm_loss = self._coupling_bsm_loss

        total_photon_loss = (
            (1 - col_eff)
            + (col_eff * QFC_loss)
            + (col_eff * (1 - QFC_loss) * channel_loss)
            + (col_eff * (1 - QFC_loss) * (1 - channel_loss) * coupling_bsm_loss)
        )

        P = ((1 - total_photon_loss) ** 2) / 2
        return P

    def compute_attempt_prob_list(self, retries, P_base):

        return [((1 - P_base) ** (s - 1)) * P_base for s in range(1, retries + 2)]

    def num_odd_bsm(self, num_repeaters):
        if num_repeaters % 2 == 0:
            num_odd_bsm_nodes = (num_repeaters + 1) // 2 + 1
        else:
            num_odd_bsm_nodes = (num_repeaters + 1) // 2
        # print("Number of odd bsm nodes", num_odd_bsm_nlodes)
        return num_odd_bsm_nodes

    def num_even_bsm(self, num_repeaters):
        if num_repeaters % 2 == 0:
            num_even_bsm_nodes = num_repeaters // 2  # Count of even BSM nodes
        else:
            num_even_bsm_nodes = num_repeaters // 2 + 1  # Count of even BSM nodes
        # print("Number of even bsm nodes", num_even_bsm_nodes)
        return num_even_bsm_nodes

    # def compute_P_L(self, retries, num_repeaters, channel_loss):
    #     P_L = 0
    #     # Compute only for odd-numbered BSM nodes (1, 3, 5, ..., up to N+1)
    #     self._s_values_L_list = list(itertools.product(range(1, retries + 2), repeat=self.num_odd_bsm(num_repeaters) + 1))
    #     for s_values in self._s_values_L_list:
    #         # print(s_values)  # Print the values being used
    #         product = np.prod([self.P_L_i(s, channel_loss) for s in s_values])
    #         P_L += product
    #         self._PL.append(product)
    #         self._max_svalues.append(max(s_values, default=0))
    #     return P_L

    # # Compute P_R
    # def compute_P_R(self, retries, num_repeaters, channel_loss):
    #     P_R = 0
    #     self._s_values_R_list = list(itertools.product(range(1, retries + 2), repeat=self.num_even_bsm(num_repeaters) + 1))
    #     for s_values in self._s_values_R_list:
    #         # print("R", s_values)  # Print the values being used
    #         product = np.prod([self.P_R_j(s, channel_loss) for s in s_values])
    #         P_R += product
    #         self._PR.append(product)
    #         self._max_svalues_R.append(max(s_values, default=0))
    #     return P_R

    # def compute_P_L(self, retries, num_repeaters, channel_loss):
    #     P_L = 0
    #     P_base = self.compute_per_attempt_success(channel_loss)
    #     P_attempt_list = self.compute_attempt_prob_list(retries, P_base)

    #     self._s_values_L_list = list(itertools.product(
    #         range(1, retries + 2), repeat=self.num_odd_bsm(num_repeaters) + 1))

    #     for s_values in self._s_values_L_list:
    #         product = np.prod([P_attempt_list[s - 1] for s in s_values])
    #         P_L += product
    #         self._PL.append(product)
    #         self._max_svalues.append(max(s_values))
    #     return P_L

    def compute_P_L_c(self, retries, num_repeaters, channel_loss):
        P_base = self.compute_per_attempt_success(channel_loss)
        num_bsm_nodes = self.num_odd_bsm(num_repeaters) + 1
        num_combinations = int((retries + 1) ** num_bsm_nodes)

        # Allocate memory
        PL = np.zeros(num_combinations, dtype=np.float64)
        max_svalues = np.zeros(num_combinations, dtype=np.int32)

        # Call C function
        self._c_lib.compute_P_c.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int)
        ]
        self._c_lib.compute_P_c.restype = ctypes.c_int

        count = self._c_lib.compute_P_c(
            retries,
            num_bsm_nodes,
            P_base,
            PL.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            max_svalues.ctypes.data_as(ctypes.POINTER(ctypes.c_int))
        )

        # Store results
        self._PL = PL.tolist()
        self._max_svalues = max_svalues.tolist()

        return sum(self._PL)

    # def compute_P_R(self, retries, num_repeaters, channel_loss):
    #     P_R = 0
    #     P_base = self.compute_per_attempt_success(channel_loss)
    #     P_attempt_list = self.compute_attempt_prob_list(retries, P_base)

    #     self._s_values_R_list = list(itertools.product(
    #         range(1, retries + 2), repeat=self.num_even_bsm(num_repeaters) + 1))

    #     for s_values in self._s_values_R_list:
    #         product = np.prod([P_attempt_list[s - 1] for s in s_values])
    #         P_R += product
    #         self._PR.append(product)
    #         self._max_svalues_R.append(max(s_values))
    #     return P_R

    def compute_P_R_c(self, retries, num_repeaters, channel_loss):
        num_bsm_nodes = self.num_even_bsm(num_repeaters) + 1
        num_combinations = (retries + 1) ** num_bsm_nodes

        PR = np.zeros(num_combinations, dtype=np.float64)
        max_svalues = np.zeros(num_combinations, dtype=np.int32)

        self._c_lib.compute_P_c.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int)
        ]
        self._c_lib.compute_P_c.restype = ctypes.c_int

        count = self._c_lib.compute_P_c(
            retries,
            num_bsm_nodes,
            self.compute_per_attempt_success(channel_loss),
            PR.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            max_svalues.ctypes.data_as(ctypes.POINTER(ctypes.c_int))
        )

        self._PR = list(PR[:count])
        self._max_svalues_R = list(max_svalues[:count])

        return sum(self._PR)

    # Compute T_avg
    # def compute_repeater_rate(self, retries, num_repeaters, P_L, P_R, channel_loss, ctrl_time, T_retry):
    #     BSM_time = self._BSM_time
    #     DBSM_time = self._DBSM_time
    #     spin_echo_time = self._spin_echo_time
    #     T_avg = 0

    #     for i, product_PL in enumerate(self._PL):
    #         max_s_L = self._max_svalues[i]
    #         for j, product_PR in enumerate(self._PR):
    #             max_s_R = self._max_svalues_R[j]

    #             total_retry_time = T_retry * (max_s_L + max_s_R)
    #             spin_echo_cost = (max_s_L // 5 + max_s_R // 5) * spin_echo_time

    #             T_avg += product_PL * product_PR * (
    #                 total_retry_time + 2 * BSM_time + DBSM_time + 4 * ctrl_time + spin_echo_cost
    #             )
    #     # print(T_avg)
    #     T_avg += (1 - P_L) * ((T_retry * (retries + 1)) +  ((retries+1/5)*spin_echo_time))
    #     # print(T_avg)
    #     for i, product_PL in enumerate(self._PL):
    #         max_s_L = self._max_svalues[i]
    #         T_avg += product_PL * (1 - P_R) * (
    #             T_retry * (max_s_L + retries + 1)
    #             + DBSM_time
    #             +  ((retries+1/5)*spin_echo_time)
    #             + 2 * ctrl_time
    #         )

    #     T_avg = T_avg + self._init_time + (4.5 * ctrl_time)
    #     # print(T_avg)
    #     return 1 / T_avg if T_avg != 0 else 0

    def compute_repeater_rate_c(self, retries, num_repeaters, P_L, P_R, channel_loss, ctrl_time, T_retry):
        PL = np.ascontiguousarray(self._PL, dtype=np.float64)
        PR = np.ascontiguousarray(self._PR, dtype=np.float64)
        max_svalues = np.ascontiguousarray(self._max_svalues, dtype=np.int32)
        max_svalues_R = np.ascontiguousarray(self._max_svalues_R, dtype=np.int32)

        return self._c_lib.compute_repeater_rate(
            retries,
            num_repeaters,
            P_L, P_R,
            channel_loss, ctrl_time, T_retry,
            self._BSM_time, self._DBSM_time,
            self._spin_echo_time, self._init_time,
            len(PL), len(PR),
            PL.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            PR.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            max_svalues.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
            max_svalues_R.ctypes.data_as(ctypes.POINTER(ctypes.c_int))
        )

    def start(self):
        final_data = []
        param_names = list(self.varying_params.keys())  # List of parameter names to iterate

        log.info(f"Running theoretical rate calculation with parameters: {self.varying_params}")
        log.info(f"Fixed parameters: {self.fixed_params}")

        # Generate all combinations of varying parameters
        for param_values in itertools.product(*self.varying_params.values()):
            param_dict = dict(zip(param_names, param_values))
            log.info(f"Running theoretical rate calculation with parameters: {param_dict}")

            # Merge varying parameters with fixed parameters
            sim_params = {**self.fixed_params, **param_dict}

            # Required params must be in varying_params
            if "distances" not in param_dict or "num_repeaters" not in param_dict:
                raise Exception("Both 'distances' and 'num_repeaters' must be in varying_params")

            distance = param_dict["distances"]
            num_repeaters = param_dict["num_repeaters"]

            node_distance = self.calc_node_dist(num_repeaters, distance)
            dist = calculate_distances(self._node_pos, num_repeaters, node_distance)
            channel_loss = 1 - (1 - self._QFC_loss) * np.power(10, - node_distance * self._init_loss / 10)
            max_value = max(dist.values())
            ctrl_time = max_value / 200000
            T_retry = 2 * (node_distance / 200000) + self._retry_time
            P_L_value = self.compute_P_L_c(self._retries, num_repeaters, channel_loss)
            P_R_value = self.compute_P_R_c(self._retries, num_repeaters, channel_loss)
            # print(P_L_value)
            # print(P_R_value)
            # print(self._max_svalues)
            # print(self._max_svalues_R)
            # print(self._PL)
            # print(self._PR)
            # rate = self.compute_repeater_rate(self._retries, num_repeaters, P_L_value, P_R_value, channel_loss, ctrl_time, T_retry)
            rate = self.compute_repeater_rate_c(self._retries, num_repeaters, P_L_value,
                                                P_R_value, channel_loss, ctrl_time, T_retry)
            print(f"Rate for {distance} with {num_repeaters} repeaters is: {rate}")
            final_data.append([distance, num_repeaters, rate])

        return final_data

    def finalize(self):
        pass


if __name__ == "__main__":
    import sys
    config_file = Constants.DEFAULT_PARAM_FILE
    if len(sys.argv) > 1:
        config_file = sys.argv[1]

    fixed_params = {
        "ion_trap": {"retries": 90}
    }

    varying_params = {
        "num_repeaters": [1, 2, 3, 4, 5, 6, 7, 8],
        "distances": [20, 50, 80],
    }
    sim = TheoRateSimulation(fixed_params=fixed_params,
                             varying_params=varying_params,
                             parameter_file="theo_rate.yml",
                             output_dir="results/rate",
                             #logfile="theo_rate.log"
                             )
    final_data = sim.start()
    data = pandas.DataFrame(final_data)
    data.to_csv(f"{self.output_dir}/theo_rate.csv", sep=',')