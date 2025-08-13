// compute_rate.c
#include <stddef.h>

double compute_repeater_rate(
    int retries, int num_repeaters,
    double P_L, double P_R,
    double channel_loss, double ctrl_time, double T_retry,
    double BSM_time, double DBSM_time,
    double spin_echo_time, double init_time,
    int len_PL, int len_PR,
    double* PL, double* PR,
    int* max_svalues, int* max_svalues_R
) {
    double T_avg = 0.0;

    for (int i = 0; i < len_PL; i++) {
        int max_s_L = max_svalues[i];
        for (int j = 0; j < len_PR; j++) {
            int max_s_R = max_svalues_R[j];

            double total_retry_time = T_retry * (max_s_L + max_s_R);
            double spin_echo_cost = ((max_s_L / 5) + (max_s_R / 5)) * spin_echo_time;

            T_avg += PL[i] * PR[j] * (
                total_retry_time + 2 * BSM_time + DBSM_time + 4 * ctrl_time + spin_echo_cost
            );
        }
    }

    T_avg += (1.0 - P_L) * ((T_retry * (retries + 1)) + ((retries + 1.0/5.0) * spin_echo_time));

    for (int i = 0; i < len_PL; i++) {
        int max_s_L = max_svalues[i];
        T_avg += PL[i] * (1.0 - P_R) * (
            T_retry * (max_s_L + retries + 1)
            + DBSM_time
            + ((retries + 1.0/5.0) * spin_echo_time)
            + 2 * ctrl_time
        );
    }

    T_avg += init_time + 4.5 * ctrl_time;

    return T_avg != 0 ? 1.0 / T_avg : 0.0;
}
