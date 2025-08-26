from qnpack.APE.allphotonic import APESimulation
from qnpack.oneG.theo_rate import TheoRateSimulation
from qnpack.oneG.iontrap import IonTrapSimulation
import argparse
import os


def run_simulation(sim_type, output_dir, parameter_file, theo_mode):
    if sim_type == "1G":
        if theo_mode:
            sim = TheoRateSimulation(
                fixed_params={},
                varying_params={
                    "num_repeaters": [1, 3, 5],
                    "distance": [5, 10, 15]
                },
                parameter_file=parameter_file,
                output_dir=output_dir,
            )
        else:
            sim = IonTrapSimulation(
                fixed_params={},
                varying_params={
                    "num_repeaters": [1, 3, 5],
                    "distance": [5, 10, 15]
                },
                iterations=10,
                parameter_file=parameter_file,
                output_dir=output_dir,
            )
    elif sim_type == "APE":
        sim = APESimulation(
            fixed_params={},
            varying_params={
                "num_repeaters": [1, 3, 5],
                "distance": [10]
            },
            iterations=1,
            min_successful=10,
            parameter_file=parameter_file,
            output_dir=output_dir,
        )
    else:
        raise ValueError("Invalid simulation type. Use '1G' or 'APE'.")

    print(f"Running simulation: {sim_type}{' (Theoretical)' if theo_mode else ''}")
    final_data = sim.start()

    if theo_mode and sim_type == "1G":
        sim.plot(
            final_data=final_data,
            x_axis1="num_repeaters",
            y_axis1="rate",
            xlabel1="Repeaters",
            ylabel1="Rate",
            label_param1="num_repeaters"
        )
        print(f"Plot saved in {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Run simulations for Ion Trap or All-Photonic networks")
    parser.add_argument("--type", choices=["1G", "APE"], required=True,
                        help="Simulation type: '1G' for ion-trap, 'APE' for all-photonic")
    parser.add_argument("--theo", action="store_true",
                        help="Run the theoretical rate simulation for 1G (ignored for APE)")
    parser.add_argument("--output", type=str, default="results",
                        help="Directory to save outputs (default: results)")
    parser.add_argument("--param", type=str, default=None,
                        help="Path to the parameter YAML file")
    parser.add_argument("--noisy", action="store_true", help="Use noisy parameters (only for 1G non-theoretical)")

    args = parser.parse_args()

    param_file = args.param
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    run_simulation(args.type, output_dir, param_file, args.theo)


if __name__ == "__main__":
    main()
