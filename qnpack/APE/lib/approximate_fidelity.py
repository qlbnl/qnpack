import numpy as np
from math import comb
from lib.repeater_rate import cal_rgs_time,cal_two_tree_RGS_size,total_prob_survival

def cal_fidelity(e_x,e_z,e_meas,n,m):
    Ex=1/4-1/4*(1-2*e_meas)**(2*(n+1))*(1-2*e_x)**(2*n)
    Ez=Ex
    Ey=1/4+1/4*(1-2*e_meas)**(2*(n+1))*(1-2*e_x)**(2*n)\
    -1/2*(1-2*e_meas)**(2*(n+1))*(1-2*e_x)**n*(1-2*e_z)**((2*m-2)*n)
    F=1-Ex-Ey-Ez
    return Ex,Ey,Ez,F

def cal_fidelity_modified(e_x,e_z,e_meas,n,m):
    """Assume no error on leaf qubits i.e. e_meas=0. 
    Also, assume e_z=0 because Z error on emitter can be shown not to affect logical Mz of core qubits.
    Hence from the two major events of error, first error is taken into account by e_x passed in argument,
    second error gives an extra error prob in e_x=(1-np.exp(-200/3000))/2 for the 2 CZ gates before Mx.
    """
    e_z=0 #Assume no logical z error on core qubit
    print("e_x in cal_fidelity_modified",e_x,(1-np.exp(-200/3000))/2)
    e_x=e_x+(1-np.exp(-243/3000))/2
    Ex=1/4-1/4*(1-2*0)**(2*(n+1))*(1-2*e_x)**(2*n)
    Ez=Ex
    Ey=1/4+1/4*(1-2*0)**(2*(n+1))*(1-2*e_x)**(2*n)\
    -1/2*(1-2*0)**(2*(n+1))*(1-2*e_x)**n*(1-2*e_z)**((2*m-2)*n)
    F=1-Ex-Ey-Ez
    return Ex,Ey,Ez,F

def cal_eI_m(k,m,eI_B):
    #General for n-level tree
    sum=0
    if m%2==1: #m is odd
        for j in range(m//2+1,m+1):
            #print("m",m,"j",j)
            sum+=comb(m,j)*eI_B[k]**j*(1-eI_B[k])**(m-j)
    else: #m is even
        for j in range(m//2+1,m+1):
            #print("m",m,"j",j)
            sum+=comb(m,j)*eI_B[k]**j*(1-eI_B[k])**(m-j) #use this instead of supp Eq10 which seems wrong. Check again later
        #for j in range(m//2,m):
        #    sum+=comb(m-1,j)*eI_B[k]**j*(1-eI_B[k])**(m-1-j)
    return sum

def T(k,m,tree_vec,s):
    return comb(tree_vec[k],m)*s[k]**m*(1-s[k])**(tree_vec[k]-m)

def cal_eI(k,eI_B,tree_vec,r,s): 
    #General for n-level tree
    sum=0
    for m in range(1,tree_vec[k]+1):
        sum+=T(k,m,tree_vec,s)*cal_eI_m(k,m,eI_B)
    return sum/r[k]

def cal_e_z(tree_vec,r,Mz,e_meas,eI):
    #General for n-level tree
    sum=0
    b0=tree_vec[0]
    for l in range(b0+1):
        sum+=comb(b0,l)*(1-r[1]/Mz[1])**l*(r[1]/Mz[1])**(b0-l)*(1-(1-2*e_meas)**l*(1-2*eI[1])**(b0-l))/2
    return sum

def cal_eI_B(k,tree_vec,r,Mz,e_meas,eI):
    #Only for k<tree_depth-3
    sum=0
    b=tree_vec[k+1]
    for l in range(b+1):
        #print(l)
        sum+=comb(b,l)*(1-r[k+2]/Mz[k+2])**l*(r[k+2]/Mz[k+2])**(b-l)*(1-(1-2*e_meas)**(1+l)*(1-2*eI[k+2])**(b-l))/2
    return sum

def cal_avg_error_2level_tree(tree_vec,total_distance,num_repeater,m,QFC_loss,detector_eff,collection_eff,e_depolarize):
    tree_depth=3
    qchannel_length=total_distance/(2*(num_repeater+1))
    prob_ph=total_prob_survival(qchannel_length,QFC_loss,detector_eff,collection_eff)
    #prob_ph=np.exp(-qchannel_length/attenuation_length) #Survival prob
    prob_loss_qchannel=1-prob_ph
    prob_bsm=(1-prob_loss_qchannel)**2/2
    prob_measX=prob_ph
    prob_measZ=prob_ph
    e_meas=2/3*e_depolarize
    r=[None for _ in range(tree_depth)] #prob of at least one successful indirect Z meas of a qubit at level k
    s=[None for _ in range(tree_depth)] #Success prob of single indirect Z meas of a qubit at level k
    Mz=[None for _ in range(tree_depth)] #Success prob of indirect+direct Z meas of a qubit at level k
    Mx=[None for _ in range(tree_depth)]
    eI_B=[None for _ in range(tree_depth)]
    eI=[None for _ in range(tree_depth)]
    
    for k in reversed(range(tree_depth)):
        
        if k==tree_depth-1: #level 2
            Mz[k]=prob_ph
        if k==tree_depth-2: #level 1
            s[k]=prob_measX
            r[k]=1-(1-s[k])**tree_vec[k]
            Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
            eI_B[k]=e_meas
            eI[k]=cal_eI(k,eI_B,tree_vec,r,s)
        if k<tree_depth-2: #level 0
            s[k]=prob_measX*Mz[k+2]**tree_vec[k+1] ##Need to use Mx here for deeper tree?
            r[k]=1-(1-s[k])**tree_vec[k]
            #Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
            eI_B[k]=(1-(1-2*e_meas)**(1+tree_vec[k+1]))/2
            eI[k]=cal_eI(k,eI_B,tree_vec,r,s)
    Mx_logical=r[0]
    Mz_logical=Mz[1]**tree_vec[0]
    e_x=eI[0]
    e_z=cal_e_z(tree_vec,r,Mz,e_meas,eI)
    prob_two_repeaters=(1-(1-prob_bsm)**m)*(Mx_logical**2)*(Mz_logical**(2*m-2))
    prob_repeater_end_node=(1-(1-prob_bsm)**m)*Mx_logical*(Mz_logical**(m-1))
    prob_repeater_chain=(prob_repeater_end_node**2)*prob_two_repeaters**(num_repeater-1)
    return prob_repeater_chain,e_x,e_z

def cal_avg_error_2level_tree_modified(tree_vec,total_distance,num_repeater,m,QFC_loss,detector_eff,collection_eff,e_depolarize):
    tree_depth=3
    qchannel_length=total_distance/(2*(num_repeater+1))
    prob_ph=total_prob_survival(qchannel_length,QFC_loss,detector_eff,collection_eff)
    #prob_ph=np.exp(-qchannel_length/attenuation_length) #Survival prob
    prob_loss_qchannel=1-prob_ph
    prob_bsm=(1-prob_loss_qchannel)**2/2
    prob_measX=prob_ph
    prob_measZ=prob_ph
    e_meas=2/3*e_depolarize
    r=[None for _ in range(tree_depth)] #prob of at least one successful indirect Z meas of a qubit at level k
    s=[None for _ in range(tree_depth)] #Success prob of single indirect Z meas of a qubit at level k
    Mz=[None for _ in range(tree_depth)] #Success prob of indirect+direct Z meas of a qubit at level k
    Mx=[None for _ in range(tree_depth)]
    eI_B=[None for _ in range(tree_depth)]
    eI=[None for _ in range(tree_depth)]
    
    for k in reversed(range(tree_depth)):
        
        if k==tree_depth-1: #level 2
            Mz[k]=prob_ph
        if k==tree_depth-2: #level 1
            s[k]=prob_measX
            r[k]=1-(1-s[k])**tree_vec[k]
            Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
            eI_B[k]=e_meas
            eI[k]=cal_eI(k,eI_B,tree_vec,r,s)
        if k<tree_depth-2: #level 0
            s[k]=prob_measX*Mz[k+2]**tree_vec[k+1] ##Need to use Mx here for deeper tree?
            r[k]=1-(1-s[k])**tree_vec[k]
            #Mz[k]=prob_measZ+(1-prob_measZ)*r[k]
            eI_B[k]=(1-(1-2*e_meas)**(1+tree_vec[k+1]))/2
            print("original eI_B[0]",eI_B[k])
            eI_B[k]=(1-np.exp(-112/3000))/2 #directly use the prob of X error on one of the level 2 photons=Z error on emitter during generation before H_p 
            print("eI_B[0]",eI_B[k])
            eI[k]=cal_eI(k,eI_B,tree_vec,r,s)
    Mx_logical=r[0]
    Mz_logical=Mz[1]**tree_vec[0]
    e_x=eI[0]
    e_z=cal_e_z(tree_vec,r,Mz,e_meas,eI)
    prob_two_repeaters=(1-(1-prob_bsm)**m)*(Mx_logical**2)*(Mz_logical**(2*m-2))
    prob_repeater_end_node=(1-(1-prob_bsm)**m)*Mx_logical*(Mz_logical**(m-1))
    prob_repeater_chain=(prob_repeater_end_node**2)*prob_two_repeaters**(num_repeater-1)
    return prob_repeater_chain,e_x,e_z

def cal_avg_error_2level_tree_multiple(repeater_ls,total_distance,b0,b1,m,QFC_loss,detector_eff,collection_eff,t_coh):
    fidelity_ls=[]
    T_graph=cal_rgs_time(b0,b1,m)
    photon_per_rgs=cal_two_tree_RGS_size(b0,b1,m)
    #e_depolarize=np.exp(-3*T_graph/t_coh)
    e_depolarize=3/4*(1-np.exp(-(T_graph/photon_per_rgs)/t_coh))
    print("T_graph",T_graph,"photon_per_rgs",photon_per_rgs,"e_depolarize",e_depolarize)
    e_meas=2/3*e_depolarize
    
    for n in repeater_ls:
        prob_repeater_chain,e_x,e_z=cal_avg_error_2level_tree(tree_vec=[b0,b1],total_distance=total_distance,num_repeater=n,m=m,QFC_loss=QFC_loss,detector_eff=detector_eff,collection_eff=collection_eff,e_depolarize=e_depolarize)
        #Ex,Ey,Ez,F=cal_fidelity(e_x,e_z,e_meas,n=n,m=m)
        Ex,Ey,Ez,F=cal_fidelity(e_x,e_z,e_meas,n=n,m=m)
        fidelity_ls.append(F)
        print(f"n{n},prob_repeater_chain{prob_repeater_chain},e_x{e_x},e_z{e_z},Ex{Ex},Ey{Ey},Ez{Ez},F{F}")
    return fidelity_ls

def cal_avg_error_2level_tree_multiple_modified(repeater_ls,total_distance,b0,b1,m,QFC_loss,detector_eff,collection_eff,t_coh):
    fidelity_ls=[]
    T_graph=cal_rgs_time(b0,b1,m)
    photon_per_rgs=cal_two_tree_RGS_size(b0,b1,m)
    #e_depolarize=np.exp(-3*T_graph/t_coh)
    e_depolarize=3/4*(1-np.exp(-(T_graph/photon_per_rgs)/t_coh))
    #print("T_graph",T_graph,"photon_per_rgs",photon_per_rgs,"e_depolarize",e_depolarize)
    e_meas=2/3*e_depolarize
    e_meas=(1-np.exp(-100/3000))/2 #prob of one of the level 2 photons has X error #formula used in NetSquid T2 model
    for n in repeater_ls:
        prob_repeater_chain,e_x,e_z=cal_avg_error_2level_tree_modified(tree_vec=[b0,b1],total_distance=total_distance,num_repeater=n,m=m,QFC_loss=QFC_loss,detector_eff=detector_eff,collection_eff=collection_eff,e_depolarize=e_depolarize)
        #Ex,Ey,Ez,F=cal_fidelity(e_x,e_z,e_meas,n=n,m=m)
        Ex,Ey,Ez,F=cal_fidelity_modified(e_x,e_z,e_meas,n=n,m=m)
        fidelity_ls.append(F)
        print(f"n{n},prob_repeater_chain{prob_repeater_chain},e_x{e_x},e_z{e_z},Ex{Ex},Ey{Ey},Ez{Ez},F{F}")
    return fidelity_ls