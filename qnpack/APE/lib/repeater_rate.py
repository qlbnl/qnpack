import numpy as np
from matplotlib import pyplot as plt
from matplotlib import rc
from math import ceil,floor

"""bsm_detection_window = 5
spd_detection_window = 5
emitter_INIT_duration = 1
emitter_H_duration = 1  # 0.1?
emitter_EMIT_PHOTON_duration = 2
emitter_CZ_duration = 20  # 100
emitter_MEASURE_duration = 10  # 10
apeqr_clock_period = 40E-9
core_photon_delay = 10
leaf_photon_clock_time = emitter_INIT_duration+emitter_H_duration+emitter_CZ_duration + \
    emitter_EMIT_PHOTON_duration-emitter_INIT_duration-emitter_H_duration  # =22
attenuation_length = 22  # unit in km
emitter_T1=0
emitter_T2=1000
num_rgs_branches_half=3 #Number of branches in repeater graph states=2*num_rgs_branches_half"""

emitter_INIT_duration = 1
emitter_H_duration = 1  # 0.1?
emitter_EMIT_PHOTON_duration = 2
photon_emission_buffer=1
emitter_CZ_duration = 100  # 100
emitter_MEASURE_duration = 20  # 10

#collection_eff=0.997
#QFC_loss=0.05
#p_loss_length=0.2
#detector_eff=1
c=2E5/1E9 #km/ns


def cal_rgs_time(b0,b1,m):
    emitter_init_prog_period=emitter_INIT_duration+emitter_H_duration+emitter_CZ_duration #22
    level1_subtree_duration=emitter_init_prog_period+(emitter_EMIT_PHOTON_duration+photon_emission_buffer)*(b1+1)+emitter_H_duration+emitter_MEASURE_duration #45
    apeqr_clock_period = level1_subtree_duration*(b0+1)+emitter_CZ_duration+emitter_MEASURE_duration
    return apeqr_clock_period*2*m

def cal_exact_prob(total_distance,num_repeater,m=3,attenuation_length=22):
    qchannel_length=total_distance/(2*(num_repeater+1))
    prob_loss_qchannel=1-np.exp(-qchannel_length/attenuation_length)
    prob_bsm=(1-prob_loss_qchannel)**2/2
    prob_measX=1-prob_loss_qchannel
    prob_measZ=1-prob_loss_qchannel
    prob_two_repeaters=(1-(1-prob_bsm)**m)*(prob_measX**2)*(prob_measZ**(2*m-2))
    prob_repeater_end_node=(1-(1-prob_bsm)**m)*prob_measX*(prob_measZ**(m-1))
    prob_repeater_chain=(prob_repeater_end_node**2)*prob_two_repeaters**(num_repeater-1)
    return prob_repeater_chain

def cal_exact_prob_tree(tree_vec=[2,3],total_distance=1000,num_repeater=1,m=3,attenuation_length=22):
    tree_depth=len(tree_vec)+1
    qchannel_length=total_distance/(2*(num_repeater+1))
    prob_ph=np.exp(-qchannel_length/attenuation_length)
    prob_loss_qchannel=1-prob_ph
    prob_bsm=(1-prob_loss_qchannel)**2/2
    prob_measX=prob_ph
    prob_measZ=prob_ph
    r=[None for _ in range(tree_depth)]
    s=[None for _ in range(tree_depth)]
    Mz=[None for _ in range(tree_depth)]
    
    for k in reversed(range(tree_depth)):
        if k==tree_depth-1:
            Mz[k]=prob_ph
        if k==tree_depth-2:
            s[k]=prob_measX
            r[k]=1-(1-s[k])**tree_vec[k]
            Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
        if k<tree_depth-2:
            s[k]=prob_measX*Mz[k+2]**tree_vec[k+1] ##Need to use Mx here for deeper tree?
            r[k]=1-(1-s[k])**tree_vec[k]
            Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
    Mx_logical=r[0]
    Mz_logical=Mz[1]**tree_depth[0]
    prob_two_repeaters=(1-(1-prob_bsm)**m)*(Mx_logical**2)*(Mz_logical**(2*m-2))
    prob_repeater_end_node=(1-(1-prob_bsm)**m)*Mx_logical*(Mz_logical**(m-1))
    prob_repeater_chain=(prob_repeater_end_node**2)*prob_two_repeaters**(num_repeater-1)
    return prob_repeater_chain

def total_prob_survival(length,p_loss_length,QFC_loss,detector_eff,collection_eff):
    fiber_prob_loss = 1 - (1 - QFC_loss) * np.power(10, - length * p_loss_length / 10)
    return collection_eff*(1-fiber_prob_loss)*detector_eff

def cal_exact_prob_2level_tree(tree_vec,m,total_distance,num_repeater,p_loss_length,QFC_loss,detector_eff,collection_eff):
    #How to exclude tie case here?
    #print("inside cal_exact_prob_2level_tree",QFC_loss,detector_eff,collection_eff)
    tree_depth=3
    qchannel_length=total_distance/(2*(num_repeater+1))
    #prob_ph=np.exp(-qchannel_length/attenuation_length) #Survival prob
    prob_ph=total_prob_survival(qchannel_length,p_loss_length,QFC_loss,detector_eff,collection_eff)
    #print("prob_ph",prob_ph)
    prob_loss_qchannel=1-prob_ph
    prob_bsm=(1-prob_loss_qchannel)**2/2
    prob_measX=prob_ph
    prob_measZ=prob_ph
    r=[None for _ in range(tree_depth)] #prob of at least one successful indirect Z meas of a qubit at level k
    s=[None for _ in range(tree_depth)] #Success prob of single indirect Z meas of a qubit at level k
    Mz=[None for _ in range(tree_depth)] #Success prob of indirect+direct Z meas of a qubit at level k
    
    for k in reversed(range(tree_depth)):
        if k==tree_depth-1: #level 2
            Mz[k]=prob_ph
        if k==tree_depth-2: #level 1
            s[k]=prob_measX
            r[k]=1-(1-s[k])**tree_vec[k]
            Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
        if k<tree_depth-2: #level 0
            s[k]=prob_measX*Mz[k+2]**tree_vec[k+1] ##Need to use Mx here for deeper tree?
            r[k]=1-(1-s[k])**tree_vec[k]
            #Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
    Mx_logical=r[0]
    Mz_logical=Mz[1]**tree_vec[0]
    #print("prob_loss_qchannel",prob_loss_qchannel,"Mx_logical",Mx_logical,"Mz_logical",Mz_logical)
    prob_two_repeaters=(1-(1-prob_bsm)**m)*(Mx_logical**2)*(Mz_logical**(2*m-2))
    prob_repeater_end_node=(1-(1-prob_bsm)**m)*Mx_logical*(Mz_logical**(m-1))
    prob_repeater_chain=(prob_repeater_end_node**2)*prob_two_repeaters**(num_repeater-1)
    return prob_repeater_chain


def cal_exact_prob_nlevel_tree(tree_vec=[8,4,1],total_distance=200,num_repeater=24,m=11):
    tree_depth=len(tree_vec)+1
    qchannel_length=total_distance/(2*(num_repeater+1))
    #prob_ph=np.exp(-qchannel_length/attenuation_length) #Survival prob
    prob_ph=total_prob_survival(qchannel_length)
    prob_loss_qchannel=1-prob_ph
    prob_bsm=(1-prob_loss_qchannel)**2/2
    prob_measX=prob_ph
    prob_measZ=prob_ph
    r=[None for _ in range(tree_depth)] #prob of at least one successful indirect Z meas of a qubit at level k
    s=[None for _ in range(tree_depth)] #Success prob of single indirect Z meas of a qubit at level k
    Mz=[None for _ in range(tree_depth)] #Success prob of indirect+direct Z meas of a qubit at level k
    
    for k in reversed(range(tree_depth)):
        
        if k==tree_depth-1: #level 3
            s[k]=0
            r[k]=0
            Mz[k]=prob_measZ
        if k==tree_depth-2: #level 2
            s[k]=prob_measX #At second to last level, indirect Z=direct X of one child qubit
            r[k]=1-(1-s[k])**tree_vec[k]
            Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
        if k<tree_depth-2: #level 0,1
            s[k]=prob_measX*Mz[k+2]**tree_vec[k+1] 
            r[k]=1-(1-s[k])**tree_vec[k]
            Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
    Mx_logical=r[0]
    Mz_logical=Mz[1]**tree_vec[0]
    print(1-Mx_logical,1-Mz_logical)
    prob_two_repeaters=(1-(1-prob_bsm)**m)*(Mx_logical**2)*(Mz_logical**(2*m-2))
    prob_repeater_end_node=(1-(1-prob_bsm)**m)*Mx_logical*(Mz_logical**(m-1))
    prob_repeater_chain=(prob_repeater_end_node**2)*prob_two_repeaters**(num_repeater-1)
    return prob_repeater_chain

def cal_two_tree_RGS_size(b0,b1,m):
    return (b0+b0*b1)*2*m+2*m
#
#def cal_benefit_over_dft():
    max_rgs_size=300
    m_ls=range(1,20)
    b0_ls=range(1,20)
    b1_ls=range(1,20)
    num_repeater_ls=range(1,11)
    best_dict={}
    min_dict={}
    min_repeater_dict={}
    
    #To find min number of repeaters to have benefit over direct fibre transmission
    #To find the (m,b0,b1) that could give the best repeater rate/matter qubit 
    total_distance=1000
    attenuation_length = 22
    #dft_rate=np.exp(-total_distance/attenuation_length)
    dft_rate=np.exp(-total_distance/attenuation_length)*emitter_CZ_duration
    
    print(cal_exact_prob_2level_tree())
    
    for m in m_ls:
        for b0 in b0_ls:
            for b1 in b1_ls:
                photon_per_rgs=cal_two_tree_RGS_size(b0,b1,m)
                if photon_per_rgs<=max_rgs_size:
                    rates=[]
                    benefit_over_dft=False
                    min_repeater_required=None
                    min_entangled_qubit_netsquid=None
                    for num_repeater in num_repeater_ls:
                        T_rgs=cal_rgs_time(b0,b1,m)/emitter_CZ_duration
                        #print("new",T_rgs,"old",2*m*(2+b0))
                        #T_rgs=2*m*(2+b0)
                        prob_repeater_chain=cal_exact_prob_2level_tree(tree_vec=[b0,b1],m=m,total_distance=total_distance,num_repeater=num_repeater,attenuation_length=attenuation_length)
                        #print(prob_repeater_chain)
                        
                        matter_qubit=3*num_repeater
                        #print(matter_qubit)
                        #repeater_rate_per_qubit=prob_repeater_chain/T_rgs/matter_qubit
                        repeater_rate_per_qubit=prob_repeater_chain/T_rgs
                        if not benefit_over_dft:
                            #if repeater_rate_per_qubit>dft_rate and prob_repeater_chain>0.01:
                            if repeater_rate_per_qubit>dft_rate:
                                min_repeater_required=num_repeater
                                min_entangled_qubit_netsquid=photon_per_rgs*num_repeater
                                benefit_over_dft=True
                        rates.append(repeater_rate_per_qubit)
                        max_rate = max(rates)
                        idx_max = rates.index(max_rate)
                    best_dict[f"{m}_{b0}_{b1}"]=(max_rate,idx_max+1)
                    if benefit_over_dft:
                        min_dict[f"{m}_{b0}_{b1}"]=(min_repeater_required,min_entangled_qubit_netsquid,photon_per_rgs)
                    
    
    #print("best_dict",best_dict)
    #print("min_photon_dict",min_dict)
    
    print("max rate:",max(best_dict.items(),key=lambda x: x[1][0]))
    print("dft rate",dft_rate)
    print("min entangled photons:",min(min_dict.items(),key=lambda x: x[1][1]))
    print("min repeaters:",min(min_dict.items(),key=lambda x: x[1][0]))

def cal_repeater_rate(prob_repeater_chain,m,b0,b1,num_repeater,total_distance):
    T_rgs=cal_rgs_time(b0,b1,m) #in nanosecond
    L0=total_distance/(num_repeater+1)
    qubits_per_end=m+ceil(L0/c/T_rgs)*m+ceil((total_distance-L0)/c/T_rgs)
    #print("T_rgs",T_rgs,'m',m,'num_repeater',num_repeater,'total_distance',total_distance)
    #print(m+ceil(L0/c/T_rgs)*m,ceil((total_distance-L0)/c/T_rgs))
    #print("max need",ceil((total_distance)/c/T_rgs)*m)
    matter_qubit=qubits_per_end
    #matter_qubit=2*qubits_per_end+3*num_repeater
    repeater_rate=prob_repeater_chain/T_rgs #in ns^-1=1e9 Hz
    repeater_rate=repeater_rate*1E9 #in Hz
    
    T_transmission=(L0+total_distance/2-L0+total_distance/2)/c #Control at middle
    T_transmission_max=(L0+total_distance-L0+total_distance)/c #Control at one end
    new_repeater_rate=prob_repeater_chain*floor((1E9-T_transmission)/T_rgs)
    new_repeater_rate_min=prob_repeater_chain*floor((1E9-T_transmission_max)/T_rgs)
    #print("ceil(L0/c/T_rgs)",ceil(L0/c/T_rgs),"ceil(total_distance/c/T_rgs)",ceil(total_distance/c/T_rgs))
    #print("T_rgs",T_rgs,"T_transmission",T_transmission,"T_transmission_max",T_transmission_max)
    #print("qubits_per_end",qubits_per_end)
    #print("prob_repeater_chain",prob_repeater_chain)
    #print("repeater_rate",repeater_rate/matter_qubit, "new_repeater_rate", new_repeater_rate/matter_qubit,"new_repeater_rate_min", new_repeater_rate_min/matter_qubit)
    return repeater_rate, matter_qubit

def cal_theoretical_repeater_rate(m,b0,b1,num_repeater,total_distance,QFC_loss,detector_eff,collection_eff):
    prob_repeater_chain=cal_exact_prob_2level_tree(tree_vec=[b0,b1],m=m,total_distance=total_distance,num_repeater=num_repeater,QFC_loss=QFC_loss,detector_eff=detector_eff,collection_eff=collection_eff)    
    repeater_rate, matter_qubit= cal_repeater_rate(prob_repeater_chain,m,b0,b1,num_repeater,total_distance)
    return repeater_rate, matter_qubit

def cal_max_rate(max_rgs_size,m_ls,b0_ls,b1_ls,num_repeater_ls,total_distance_ls,is_per_matter_qubit,QFC_loss,detector_eff,collection_eff):
    
    best_dict={}
    best_tree_dict={}
    for total_distance in total_distance_ls:
        max_rate_ls=[]
        rgs_size_ls=[]
        max_rate_memory_number_ls=[]
        for num_repeater in num_repeater_ls:
            max_repeater_rate=0
            for m in m_ls:
                for b0 in b0_ls:
                    for b1 in b1_ls:
                        photon_per_rgs=cal_two_tree_RGS_size(b0,b1,m)

                        if photon_per_rgs<=max_rgs_size:  
                            prob_repeater_chain=cal_exact_prob_2level_tree(tree_vec=[b0,b1],m=m,total_distance=total_distance,num_repeater=num_repeater,QFC_loss=QFC_loss,detector_eff=detector_eff,collection_eff=collection_eff)               
                            repeater_rate, matter_qubit=cal_repeater_rate(prob_repeater_chain,m,b0,b1,num_repeater,total_distance)
                            #if m==5 and b0==4 and b1==2:
                            #    print("542 rate",prob_repeater_chain,repeater_rate, matter_qubit)
                            #if m==6 and b0==6 and b1==3:
                            #    print("663 rate",prob_repeater_chain,repeater_rate, matter_qubit)
                            if is_per_matter_qubit:                                
                                repeater_rate=repeater_rate/matter_qubit
                            
                            if repeater_rate>max_repeater_rate:
                                max_repeater_rate=repeater_rate
                                rgs_size=(m,b0,b1)
                                max_rate_memory_number=matter_qubit
                                
            max_rate_ls.append(max_repeater_rate) #in Hz
            rgs_size_ls.append(rgs_size)
            #print("max_rate_memory_number",max_rate_memory_number)
            max_rate_memory_number_ls.append(max_rate_memory_number)
        best_dict[total_distance]=max_rate_ls
        best_tree_dict[total_distance]=rgs_size_ls
    return best_dict, best_tree_dict

def plot_max_rate_against_n(is_per_matter_qubit,QFC_loss,detector_eff,collection_eff):
    max_rgs_size=300
    m_ls=range(1,100)
    b0_ls=range(1,150)
    b1_ls=range(1,100)
    num_repeater_ls=range(1,13)
    total_distance_ls=[10,50,100]
    #To find the (m,b0,b1) that could give the best repeater rate/matter qubit 
    #attenuation_length = 22
    #dft_rate_pmq=np.exp(-total_distance/attenuation_length)/2/(total_distance/c)/2*1E-6 #in kHz
    #dft_rate=np.exp(-total_distance/attenuation_length)*T_CZ
    
    best_dict, best_tree_dict=cal_max_rate(max_rgs_size,m_ls,b0_ls,b1_ls,num_repeater_ls,total_distance_ls,is_per_matter_qubit)
    #font = {'family' : 'normal',
    #    'size'   : 15}
    # Set global plot formatting
    plt.rc('axes', labelsize=20)       # Axis label font size
    plt.rc('lines', linewidth=3.0)     # Line width
    plt.rc('xtick', labelsize=15)      # X-axis tick label size
    plt.rc('ytick', labelsize=15)      # Y-axis tick label size
    plt.rc('font', size=10)  
    plt.rc('axes', titlesize=20)     # fontsize of the axes title
    #plt.rc('legend', fontsize=20) 
    #fig, ax = plt.subplots()
    fig = plt.figure(figsize=(12, 6))
    ax = fig.add_subplot(1, 1, 1) 
    colors=['b','g','r']
    for cnt,total_distance in enumerate(total_distance_ls):
        
        max_rate_ls=best_dict[total_distance]
        rgs_size_ls=best_tree_dict[total_distance]
        #plt.plot(keys, values, label=f"{dist} km")
        #dft_rate=np.exp(-total_distance/attenuation_length)/2/(total_distance*2/c)*(1E-12) #in kHz
        dft_rate=total_prob_survival(total_distance/2,QFC_loss,detector_eff,collection_eff)**2/2/(total_distance/c)*(1E9) #in Hz, assume a bsm node in the middle
        print(total_distance,dft_rate)
        if is_per_matter_qubit:
            ax.plot(range(1,len(max_rate_ls)+1), max_rate_ls, color=colors[cnt], label=f"{total_distance} km")
            ax.hlines(dft_rate,linestyle='dashed', xmin=1, xmax=len(max_rate_ls),color=colors[cnt],label=f"Repeaterless rate={round(dft_rate,2)}Hz")
        else:
            ax.plot(range(1,len(max_rate_ls)+1), max_rate_ls, color=colors[cnt],label=f"{total_distance} km")
            ax.hlines(dft_rate,linestyle='dashed', xmin=1, xmax=len(max_rate_ls),color=colors[cnt],label=f"Repeaterless rate={round(dft_rate,2)}Hz")
        
        for x, y in enumerate(max_rate_ls):
            if total_distance==100:
                plt.text(x+0.5, y+0.6, f"{rgs_size_ls[x]}" , horizontalalignment="left")
            elif total_distance==50:
                plt.text(x+0.5, y+30, f"{rgs_size_ls[x]}" , horizontalalignment="left")
            elif total_distance==10:
                plt.text(x+0.5, y-1500, f"{rgs_size_ls[x]}" , horizontalalignment="left")
            else:
                plt.text(x+0.5, y+30, f"{rgs_size_ls[x]}" , horizontalalignment="left")
        
    plt.xticks(range(1,len(max_rate_ls)+1))
    plt.xlabel("Number of repeaters")
    if is_per_matter_qubit:
        plt.ylabel(f"Entanglement Rate (Hz)")
    else:
        plt.ylabel(f"Entanglement Rate (Hz)")
    plt.yscale("log")   
    plt.subplots_adjust(bottom=0.15)
    #plt.title("Repeater chain with different total lengths")
    #plt.title(f"All-photonic repeater chain, optimized over RGS size<={max_rgs_size} photons, \nwith RGS parameter=(m,b0,b1), QFC_eff={1-QFC_loss}, detector_eff={detector_eff} and perfect emitter")
    plt.legend(loc="best", prop={'size': 10},handlelength=3.9)
    plt.savefig('qnpack/APE/plot_Sigcomm/sigcomm_figures/optimized_rgs.pdf', dpi=1200) 
    plt.show()

def cal_rate_from_data(data,m,b0,b1,p_loss_length,QFC_loss,detector_eff,collection_eff,is_per_memory_qubit):
    for dist, item in data.items():
        total_distance=float(dist)
        keys = list(item.keys())
        values = list(item.values())
        #print("keys",keys,"item.values()",item.values())
        #print(list(item.values())[0])
        sim_prob_list=[]
        sim_rate_list=[]
        exact_rate_list=[]
        exact_prob_list=[]
        for i in range(len(values)):
            num_repeater=int(keys[i])
            (cnt,successful_cnt)=values[i]
            #print(dist,int(keys[i]))
            sim_prob=successful_cnt/cnt
            exact_prob=cal_exact_prob_2level_tree(tree_vec=[b0,b1],total_distance=total_distance,num_repeater=num_repeater,
                                            m=m,p_loss_length=p_loss_length,QFC_loss=QFC_loss,detector_eff=detector_eff,collection_eff=collection_eff)
            sim_rate,matter_qubit=cal_repeater_rate(sim_prob,m,b0,b1,num_repeater=num_repeater,total_distance=total_distance)
            if is_per_memory_qubit:
                sim_rate=sim_rate/matter_qubit
            exact_rate,_=cal_repeater_rate(exact_prob,m,b0,b1,num_repeater=num_repeater,total_distance=total_distance)
            if is_per_memory_qubit:
                exact_rate=exact_rate/matter_qubit
            sim_prob_list.append(sim_prob)
            exact_prob_list.append(exact_prob)
            sim_rate_list.append(sim_rate)
            exact_rate_list.append(exact_rate)
        print(dist,"sim_prob_list",sim_prob_list)
        print(dist,"exact_prob_list",exact_prob_list)
    return keys,sim_rate_list,exact_rate_list
    #return keys,sim_prob_list,exact_prob_list

def cal_rate_from_single_data(sim_prob,total_distance,num_repeater,m,b0,b1,p_loss_length,QFC_loss,detector_eff,collection_eff,is_per_memory_qubit):       
            
    exact_prob=cal_exact_prob_2level_tree(tree_vec=[b0,b1],total_distance=total_distance,num_repeater=num_repeater,
                                    m=m,p_loss_length=p_loss_length, QFC_loss=QFC_loss,detector_eff=detector_eff,collection_eff=collection_eff)
    sim_rate,matter_qubit=cal_repeater_rate(sim_prob,m,b0,b1,num_repeater=num_repeater,total_distance=total_distance)
    if is_per_memory_qubit:
        sim_rate=sim_rate/matter_qubit
    exact_rate,_=cal_repeater_rate(exact_prob,m,b0,b1,num_repeater=num_repeater,total_distance=total_distance)
    if is_per_memory_qubit:
        exact_rate=exact_rate/matter_qubit        
    return sim_rate,exact_rate

def cal_sem(avg_fidelity,total_count):
    n1=avg_fidelity*total_count
    n0=total_count-n1
    unbiased_sd=np.sqrt(((1-avg_fidelity)**2*n1+avg_fidelity**2*n0)/(total_count-1))
    sem=unbiased_sd/np.sqrt(total_count)
    #print("n1",n1,"unbiased_sd",unbiased_sd,"sem",sem)
    return sem

#main()
#print(cal_exact_prob_nlevel_tree(tree_vec=[17,28],total_distance=200,num_repeater=24,m=11,attenuation_length=22))
#print(cal_avg_error_nlevel_tree(tree_vec=[17,28,2],total_distance=200,num_repeater=24,m=11,attenuation_length=22,e_meas=5.6e-5))
#plot_max_rate_against_n(is_per_matter_qubit=True) 
#print(cal_theoretical_repeater_rate(m=5,b0=4,b1=2,num_repeater=1,total_distance=50,QFC_loss=0.65,detector_eff=0.9,collection_eff=0.997))