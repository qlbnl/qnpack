#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>

void generate_s_values_P (
    int retries,
    int num_bsm_nodes,
    double* P_attempt_list,
    int* current_s_values,
    int depth,
    double* PL,
    int* max_svalues,
    int* index
) {
    if (depth == num_bsm_nodes) {
        double product = 1.0;
        int max_s = current_s_values[0];
        for (int i = 0; i < num_bsm_nodes; i++) {
            int s = current_s_values[i];
            product *= P_attempt_list[s - 1];  // s ∈ [1, retries+1]
            if (s > max_s) max_s = s;
        }
        PL[*index] = product;
        max_svalues[*index] = max_s;
        (*index)++;
        return;
    }

    for (int s = 1; s <= retries + 1; s++) {
        current_s_values[depth] = s;
        generate_s_values_P (
            retries, num_bsm_nodes, P_attempt_list,
            current_s_values, depth + 1,
            PL, max_svalues, index
        );
    }
}

int compute_P_c(
    int retries,
    int num_bsm_nodes,
    double P_base,
    double* PL,
    int* max_svalues) 
{
    double P_attempt_list[retries + 1];
    for (int s = 1; s <= retries + 1; s++) {
        P_attempt_list[s - 1] = pow(1 - P_base, s - 1) * P_base;
    }

    int num_combinations = pow(retries + 1, num_bsm_nodes);
    int *current_s_values = (int *)calloc(num_bsm_nodes, sizeof(int));
    int index = 0;

    // while (1) {
    //     double product = 1.0;
    //     int max_s = current_s_values[0];
    //     for (int i = 0; i < num_bsm_nodes + 1; i++) {
    //         int s = current_s_values[i];
    //         product *= P_attempt_list[s - 1];
    //         if (s > max_s) max_s = s;
    //     }
    //     PL[index] = product;
    //     max_svalues[index] = max_s;
    //     index++;

    //     // Increment like a base-N counter (repeat = num_bsm_nodes)
    //     int pos = num_bsm_nodes - 1;
    //     while (pos >= 0) {
    //         current_s_values[pos]++;
    //         if (current_s_values[pos] < retries + 1) {
    //             break;
    //         } else {
    //             current_s_values[pos] = 1;
    //             pos--;
    //         }
    //     }
    //     // If we carried out of the leftmost digit, we're done
    //     if (pos < 0) break;
    // }

    generate_s_values_P (
        retries, num_bsm_nodes, P_attempt_list,
        current_s_values, 0,
        PL, max_svalues, &index
    );

    return num_combinations;
}


double compute_repeater_rate(
    int retries, int num_repeaters,
    double P_L, double P_R, double P_base,
    double channel_loss, double ctrl_time, double T_retry,
    double BSM_time, double DBSM_time,
    double spin_echo_time, double init_time,
    int len_PL, int len_PR,
    double* PL, double* PR,
    int* max_svalues, int* max_svalues_R
) {
    double T_avg = 0.0;
    double T_avg1 = 0.0;
    double T_avg2 = 0.0;
    double T_avg3 = 0.0;
    double P_success=pow((1-pow((1-P_base),retries+1)),num_repeaters+1);

    for (int i = 0; i < len_PL; i++) {
        int max_s_L = max_svalues[i];
        for (int j = 0; j < len_PR; j++) {
            int max_s_R = max_svalues_R[j];

            double total_retry_time = T_retry * (max_s_L + max_s_R);
            double spin_echo_cost = ((int)(max_s_L / 5) + (int)(max_s_R / 5)) * spin_echo_time;
            
            T_avg1 += PL[i] * PR[j] * (
                total_retry_time + 2 * BSM_time + DBSM_time + 4 * ctrl_time + spin_echo_cost
                );
        }
    }

    T_avg2 = (1.0 - P_L) * ((T_retry * (retries + 1)) + ((int)((retries + 1.0) / 5.0) * spin_echo_time)); //changed from (retries + 1.0 / 5.0)

    for (int i = 0; i < len_PL; i++) {
        int max_s_L = max_svalues[i];
        T_avg3 += PL[i] * (1.0 - P_R) * (
            T_retry * (max_s_L + retries + 1) // BSM_time also need to multiply with number of attemtps
            + ((int)(max_s_L/5) + (int)((retries + 1.0) / 5)) * spin_echo_time //changed from (retries + 1.0/ 5.0)
            + 2 * ctrl_time
            + BSM_time
            );
    }
    T_avg +=T_avg1+T_avg2+T_avg3;
    T_avg += init_time + 4.5 * ctrl_time;
    T_avg *=1/P_success;
    
    //printf("T_avg1 %.8f T_avg2 %.8f T_avg3 %.8f T_avg %.8f init_time %.8f ctrl_time %.8f rate %.8f P_success %.8f",T_avg1,T_avg2,T_avg3,T_avg,init_time,ctrl_time,1/T_avg*P_success,P_success);
    return T_avg != 0 ? 1.0 / T_avg : 0.0;
}

