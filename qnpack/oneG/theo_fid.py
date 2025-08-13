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


class TheoFidSimulation(Simulation):
    def __init__(self, logfile=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        log.info(f"Configuration:\n{self.cfg}")

        self.F_em_single = self.cfg.ion_trap.emission_fidelity         # ion‑photon emission fidelity
        self.p_ms  = self.cfg.ion_trap.ms_depolar_prob                 # MS‑gate depolarising probability
        self.p_xz  = self.cfg.ion_trap.x_depolar_prob                  # depolarising probability for X and Z gates
        self.k_phase = 1                                               # dephasing factor (1 = independent phase)
        self.tau = self.cfg.ion_trap.coherence_time/1e9                # coherence time [s]
        self.MC_shots = 5000

        setup_logging(name=__name__,
                      level=logging.DEBUG if self.cfg.sim.debug else logging.INFO,
                      logfile=logfile)


    def plot(self, final_data, x_axis1, y_axis1, xlabel1, ylabel1, label_param1,
             title1="Simulation Results",
             filename="theo_fid_results.png"):
        # Save results
        rows = [[d['distance'], d['num_repeaters'], d['fidelity']] for d in final_data]

        # Save CSV with header once, then data rows only
        with open(f"{self.output_dir}/theo_fid_results.csv", mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["distance", "num_repeaters", "fidelity"])  # header
            writer.writerows(rows)  # data rows only
    
        # Load CSV into pandas DataFrame for plotting
        df = pandas.read_csv(f"{self.output_dir}/theo_fid_results.csv")

        # Plot the data with different lines for each unique 'distance'
        plt.figure(figsize=(10, 6))

        # Loop through each unique distance and plot corresponding data
        for distance in df['distance'].unique():
            subset = df[df['distance'] == distance]
            plt.plot(subset['num_repeaters'], subset['fidelity'], label=f'{distance} km')

        # Customize the plot
        plt.tight_layout() #
        plt.xlim(right=8)
        # plt.ylim(0, 1)
        plt.title('Theoretical Fidelity vs Number of Repeaters')
        plt.xlabel('Number of Repeaters')
        plt.ylabel('Total Fidelity')
        plt.legend(title='Distance')

        # Save the plot as PNG
        plt.savefig(f"{self.output_dir}/{filename}")

    def werner_fidelity(self, p, k):
        """F = (1 + (1-p)^k)/2"""
        return (1 + (1 - p) ** k) / 2

    def start(self):
        final_data = []
        param_names = list(self.varying_params.keys())  # List of parameter names to iterate

        log.info(f"Varying parameters: {self.varying_params}")
        log.info(f"Fixed parameters: {self.fixed_params}")

        # Generate all combinations of varying parameters
        for param_values in itertools.product(*self.varying_params.values()):
            param_dict = dict(zip(param_names, param_values))
            log.info(f"Running theoretical fidelity calculation with parameters: {param_dict}")
        
            # Merge varying parameters with fixed parameters
            sim_params = {**self.fixed_params, **param_dict}
        
            # Required params must be in varying_params
            if "distances" not in param_dict or "num_repeaters" not in param_dict:
                raise Exception("Both 'distances' and 'num_repeaters' must be in varying_params")
        
            # distance_list = param_dict["distances"]
            # repeater_list = param_dict["num_repeaters"]
            distance_list = self.varying_params["distances"]
            repeater_list = self.varying_params["num_repeaters"]

        
            # Get min and max from user-provided lists
            min_dist, max_dist = min(distance_list), max(distance_list)
            min_repeater, max_repeater = min(repeater_list), max(repeater_list)
        
            # Load and filter the data
            df = pandas.read_csv(f"{self.output_dir}/fixed_theo_rates.csv")
            mask = df["num_repeaters"].between(min_repeater, max_repeater) & df["distance"].between(min_dist, max_dist)
            rows = df.loc[mask].copy()
        
            results = []
            for _, row in rows.iterrows():
                n = int(row["num_repeaters"])
                d = float(row["distance"])
        
                # Optional: skip rows not in the exact lists (if you want exact matching instead of range)
                if n not in repeater_list or d not in distance_list:
                    continue
        
                T_avg = 1.0 / float(row["rate"])      # seconds
                sigma = T_avg / self.tau              # std‑dev of phase θ
            
                F_Z  = self.werner_fidelity(self.p_xz, n + 0.5)
                F_X  = self.werner_fidelity(self.p_xz, 1.5 * n + 1)
                F_MS = self.werner_fidelity(self.p_ms, n)
                F_gate = F_Z * F_X * F_MS
            
                F_em_chain = self.F_em_single ** (n)
            
                seg_vals = []
                for _ in range(self.MC_shots):
                    theta = np.random.normal(0.0, sigma)
                    F_seg = np.cos(self.k_phase * theta/2) ** 2          # one segment
                    seg_vals.append(F_seg ** (n + 1))             # across n+1 segments
                F_deph = np.mean(seg_vals)
            
                F_total = F_em_chain * F_gate * F_deph
            
                results.append(dict(distance=row["distance"],
                                    num_repeaters=n,
                                    # T_avg=T_avg,
                                    # F_em=F_em_chain,
                                    # F_gate=F_gate,
                                    # F_deph=F_deph,
                                    fidelity=F_total))

        return results

    def finalize(self):
        pass


if __name__ == "__main__":
    import sys
    config_file = Constants.DEFAULT_PARAM_FILE
    if len(sys.argv) > 1:
        config_file = sys.argv[1]

    fixed_params = {
        "ion_trap": {"coherence_time": 60000000}
    }

    varying_params = {
        "num_repeaters": [1, 2, 4, 6],
        "distances": [10, 50, 100],
    }
    sim = TheoFidSimulation(fixed_params=fixed_params,
                             varying_params=varying_params,
                             parameter_file="../../tutorial/1G_examples/parameters/noisy.yml",
                             output_dir="results",
                             #logfile="theo_fid.log"
                             )
    sim.start()
