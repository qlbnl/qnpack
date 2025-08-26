from netsquid.qubits.stabtools import StabRepr
from netsquid.qubits.qubitapi import *
from netsquid.qubits.qformalism import *
from netsquid.qubits.qstate import QState
from netsquid.qubits import operators as ops
from netsquid.qubits import Stabilizer
import netsquid as ns
import numpy as np
from netsquid.qubits import qubitapi as qapi
#from netsquid.qubits.qubitapi import operate,measure,gmeasure
from netsquid.qubits import operators as ops
from qnpack.APE.lib.drawGS import plot_qubit_graph, pick_entangled_qubits
from qnpack.APE.lib.custom_qubitapi import (
    my_measure,
    my_gmeasure
)
from qnpack.common.utils import ForcedRNG
# Used in ancilla qubit for performing local complementation of graph state
Rx = ops.create_rotation_op(np.pi/2, (1, 0, 0))
# Used in CorePhotonicProcessing for performing local complementation of graph state
Rz = ops.create_rotation_op(-np.pi/2, (0, 0, 1))

class verification():

    def __init__(self,num_repeaters,num_branches_half,result):
        self.num_repeaters=num_repeaters
        self.num_branches_half=num_branches_half
        self.num_qubits_rgs=num_branches_half*4
        self.num_end_qubits=num_branches_half*2
        self.result=result
        self.reset()
                 
    def photonic_bsm(self, q1,q2,outcome,discard_qubits=False):
        #print(q1,q2)
        #print("outcome inside photonic_bsm",outcome)
        if outcome==0 or outcome==1:
            #print("outcome 0")
            self.forced_my_gmeasure([q1,q2], ops.X^ops.Z, 0)
            if outcome==0:
                self.forced_my_gmeasure([q1,q2], ops.Z^ops.X, 0) 
            else:
                self.forced_my_gmeasure([q1,q2], ops.Z^ops.X, 1) 
        elif outcome==2 or outcome==3:
            self.forced_my_gmeasure([q1,q2], ops.X^ops.Z,1)
            if outcome==2:
                self.forced_my_measure(q1,ops.X,0)
            else:
                self.forced_my_measure(q1,ops.X,1)
        elif outcome==4: 
            self.forced_my_measure(q1,ops.X,0)
        elif outcome==5:
            self.forced_my_measure(q1,ops.X,1)
        elif outcome==6: 
            self.forced_my_measure(q2,ops.Z,0)
        elif outcome==7:
            self.forced_my_measure(q2,ops.Z,1)
        elif outcome=="No photon detected in BSM":
            pass
        else:
            raise ValueError
        #if discard_qubits:
        #    discard(q1)
        #    discard(q2)
    
    def forced_my_gmeasure(self, qubits, meas_operators,forced_outcome):
            # Do forced outcome here
            m, prob = my_gmeasure(qubits, meas_operators, rng_measure=ForcedRNG(forced_outcome))
            # print("forced_my_gmeasure m",m,"prob",prob,"forced_outcome",forced_outcome,"qubits",qubits,"m_collector.bsm_cnt",m_collector.bsm_cnt-1)
            assert m == forced_outcome, f"Forced outcome {forced_outcome} is different than actual outcome {m}"
            return m, prob
    
    def forced_my_measure(self, qubit, observable,forced_outcome,is_assert=True):
        # Do forced outcome here
        m, prob = my_measure(qubit, observable, rng_measure=ForcedRNG(forced_outcome))
        # print("forced_my_measure m",m,"prob",prob,"forced_outcome",forced_outcome,"qubit",qubit,"m_collector.bsm_cnt",m_collector.bsm_cnt-1)
        if is_assert:
            assert m == forced_outcome, f"Forced outcome {forced_outcome} is different than actual outcome {m}"
        else:
            if m != forced_outcome:
                print(qubit,f"Forced outcome {forced_outcome} is different than actual outcome {m}")
        return m, prob
    
    def edge_to_check_mat(self, edge_list):
        num_vertices=max([val for edge in edge_list for val in edge])+1
        adj_mat=np.zeros([num_vertices,num_vertices],dtype=int)
        for edge in edge_list:
            adj_mat[edge]=1
            adj_mat[edge[::-1]]=1
        
        x_stab=np.diagflat([1 for i in range(num_vertices)])    
        check_mat=np.concatenate((x_stab, adj_mat), axis=1)
        return check_mat
    
    ##Test the method pick_entangled_qubits
    
    
    
    
    def get_rgs_check_mat(self):
        core_list=[2*i+1 for i in range(2*self.num_branches_half)]
        leaf_list=[2*i for i in range(2*self.num_branches_half)]
        edge_list=[(i,j) for i in core_list for j in core_list if i<j]
        edge_list2=[(i,i+1) for i in leaf_list]
        edge_list=edge_list+edge_list2
        check_mat=self.edge_to_check_mat(edge_list)
        return check_mat
    
    def get_end_check_mat(self):
        edge_list=[(2*i,2*i+1) for i in range(self.num_branches_half)]
        check_mat=self.edge_to_check_mat(edge_list)
        return check_mat

    def reset(self):
        self.ape_dict={}
        end_stab=StabRepr(check_matrix=self.get_end_check_mat(), phases=[1 for i in range(self.num_end_qubits)])
        self.end_left = create_qubits(num_qubits=self.num_end_qubits, system_name=f"end_left",no_state=True)
        assign_qstate(self.end_left,qrepr=end_stab)
        self.end_left_photons_idx=list(range(0,self.num_end_qubits,2))
        self.end_right= create_qubits(num_qubits=self.num_end_qubits, system_name=f"end_right",no_state=True)
        assign_qstate(self.end_right, qrepr=end_stab)
        self.end_right_photons_idx=list(range(0,self.num_end_qubits,2))
    
        rgs_stab = StabRepr(check_matrix=self.get_rgs_check_mat(), phases=[1 for i in range(self.num_qubits_rgs)])
        for n in range(self.num_repeaters):
            self.ape_dict[n] = create_qubits(num_qubits=self.num_qubits_rgs, system_name=f"ape{n}_",no_state=True)
            assign_qstate(self.ape_dict[n],qrepr=rgs_stab)
        #print(self.ape_dict)
        #qubit=self.ape_dict[0][0]
        #plot_qubit_graph(qubit)
        #print(pick_entangled_qubits(qubit))
    
    def start(self):
        for i in range(self.num_qubits_rgs): #i=photon index
            for n in reversed(range(self.num_repeaters)): #n=repeater index
                
                if n % 2 == 0:
                    dir_to=["right", "right", "left", "left"]*int(self.num_branches_half)
                else:
                    dir_to=["left","left", "right", "right"]*int(self.num_branches_half)
            
                if dir_to[i]=="right":
                    dir_receive="L"
                    bsm_node=n+1
                else:
                    dir_receive="R"
                    bsm_node=n
                protocol_name=f"CRP{dir_receive}_bsm{bsm_node}"
                if i%2==0: #leaf qubit
                    basis=None
                    #print(self.result[protocol_name],i//4)
                    meas_outcome=self.result[protocol_name][1][i//4]
            
                    #Here, for BSM, we always count the right emitting photon to prevent overcounting
                    if dir_to[i]=="right":
                        if n==self.num_repeaters-1:
                            
                            self.photonic_bsm(self.ape_dict[n][i],self.end_right[self.end_right_photons_idx.pop(0)],meas_outcome)
                        else:
                            self.photonic_bsm(self.ape_dict[n][i],self.ape_dict[n+1][i],meas_outcome)
                    else:
                        if n==0:
                            self.photonic_bsm(self.end_left[self.end_left_photons_idx.pop(0)],self.ape_dict[n][i],meas_outcome)
                else: #core qubit
                    basis,meas_outcome=self.result[protocol_name][3][i//4]
                    if basis=='x':
                        operator=ops.X
                    elif basis=='z':
                        operator=ops.Z
                    else:
                        raise ValueError("Measurement basis other than x or z is performed")
                    self.forced_my_measure(self.ape_dict[n][i],operator,meas_outcome)
    
    def get_expected_Bell_pair(self):
        _, bsm_outcomes, _, _ = self.result['CRPR_bsm0']
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
        _, bsm_outcomes, _, _ = self.result[f'CRPL_bsm{self.num_repeaters}']
        for i in range(len(bsm_outcomes)):
            if bsm_outcomes[i] == 0 or bsm_outcomes[i] == 1:
                node_b_1st_successful_index = i
                verify_b_successful = True
                break
        assert verify_a_successful & verify_b_successful, "All_bsm_success is True but could not find sucessful bsm outcome in end nodes"
        # print("node_a_1st_successful_index",node_a_1st_successful_index,"node_b_1st_successful_index",node_b_1st_successful_index)
        a_matter_qubits = self.end_left[1::2]
        b_matter_qubits = self.end_right[1::2]
        a_successful_qubit = a_matter_qubits[node_a_1st_successful_index]
        b_successful_qubit = b_matter_qubits[node_b_1st_successful_index]
        #print("all matter qubits in node a:",a_matter_qubits)
        # for qubit in a_matter_qubits:
        #    print(qubit,pick_entangled_qubits(qubit))
        #print("all matter qubits in node b:",b_matter_qubits)
        # for qubit in b_matter_qubits:
        #    print(qubit,pick_entangled_qubits(qubit))
        # Assert that the first successful matter qubit in node a is only entangled with the first successful matter in node b
        picked_qstate_a, picked_qubits_a = pick_entangled_qubits(a_successful_qubit)
        try:
            assert picked_qstate_a.num_qubits == 2, f"First successful matter qubit in node a is entangled with >1 qubit"
            assert picked_qubits_a[1] == b_successful_qubit, f"First successful matter qubits in node a and b are not entangled"
        except AssertionError as e:
            print(f'Assertion failed')
            print(f'picked_qstate_a: {picked_qstate_a}')
            print(f'picked_qubits_a: {picked_qubits_a}')
        return picked_qstate_a
        
    def get_meas_outcome(self,i,n): #i=photon meas num, n=ape_node number
        if n % 2 == 0:
            dir_to=["right", "right", "left", "left"]*int(self.num_branches_half)
        else:
            dir_to=["left","left", "right", "right"]*int(self.num_branches_half)
    
        if dir_to[i]=="right":
            dir_receive="L"
            bsm_node=i+1
        else:
            dir_receive="R"
            bsm_node=i
        protocol_name=f"CRP{dir_receive}_bsm{bsm_node}"
        if i%2==0: #leaf qubit
            basis=None
            meas_outcome=self.result[protocol_name][1][i//2]
    
            #Here, for BSM, we always count the right emitting photon to prevent overcounting
            if dir_to[i]=="right":
                if n==self.num_repeaters-1:
                    
                    self.photonic_bsm(self.ape_dict[n][i],self.end_right[self.end_right_photons_idx.pop(0)],meas_outcome)
                else:
                    self.photonic_bsm(self.ape_dict[n][i],self.ape_dict[n+1][i],meas_outcome)
            else:
                if n==0:
                    self.photonic_bsm(self.end_left[self.end_left_photons_idx.pop(0)],self.ape_dict[n+1][i],meas_outcome)
        else: #core qubit
            basis,meas_outcome=self.result[protocol_name][3][i//2]
            if basis=='x':
                operator=ops.X
            elif basis=='z':
                operator=ops.Z
            else:
                raise ValueError("Measurement basis other than x or z is performed")
            self.forced_my_measure(self.ape_dict[n][i],operator,meas_outcome)
        return 
        
    def create_rgs_1_3_1(self):
        print("inside create rgs 131")
        edge_list=[(0,2),(0,4),(0,6),(1,2),(2,9),(2,11),(2,13),(3,4),(4,9),(4,11),(4,13),(5,6),(6,9),(6,11),(6,13),(7,9),(7,11),(7,13),(8,9),(10,11),(12,13)]
        check_mat=self.edge_to_check_mat(edge_list)
        print(check_mat)
        rgs_stab=StabRepr(check_matrix=check_mat, phases=[1 for i in range(14)])
        ape = create_qubits(num_qubits=14, system_name=f"ape0_",no_state=True)
        assign_qstate(ape,qrepr=rgs_stab)
        
        end_stab=StabRepr(check_matrix=self.edge_to_check_mat([(0,1)]), phases=[1 for i in range(2)])
        end_left=create_qubits(num_qubits=2, system_name=f"end_left",no_state=True)
        assign_qstate(end_left,qrepr=end_stab)
        operate(ape[8],ops.X) #X error
        
        #logical Mx of left subtree
        self.forced_my_measure(ape[8],ops.Z,0,False)
        self.forced_my_measure(ape[9],ops.X,0,False)
        self.forced_my_measure(ape[10],ops.Z,0,False)
        self.forced_my_measure(ape[11],ops.X,0,False)
        self.forced_my_measure(ape[12],ops.Z,0,False)
        self.forced_my_measure(ape[13],ops.X,0,False)
        #BSM
        self.photonic_bsm(end_left[0],ape[0],0)
        #logical Mx of Right subtree
        self.forced_my_measure(ape[1],ops.Z,0,False)
        self.forced_my_measure(ape[2],ops.X,0,False)
        self.forced_my_measure(ape[3],ops.Z,0,False)
        self.forced_my_measure(ape[4],ops.X,0,False)
        self.forced_my_measure(ape[5],ops.Z,0,False)
        self.forced_my_measure(ape[6],ops.X,0,False)
        
        #[index]=ape[0].qstate.indices_of([ape[0]])
        #print(index,ape[0].qstate.qrepr)
        #ape[0].qstate.qrepr.row_reduce()
        #[index]=ape[0].qstate.indices_of([ape[0]])
        #print(index,ape[0].qstate.qrepr)
        [index]=end_left[1].qstate.indices_of([end_left[1]])
        print(index,end_left[1].qstate.qrepr)
        end_left[1].qstate.qrepr.row_reduce()
        [index]=end_left[1].qstate.indices_of([end_left[1]])
        print(index,end_left[1].qstate.qrepr)

        picked_qstate_a, picked_qubits_a = pick_entangled_qubits(end_left[1])
        print(picked_qstate_a, picked_qubits_a)
        print("complete create rgs 131")

    def operate_first_level_core(self,qubit):
        operate(qubit, ops.S.inv)
        operate(qubit, Rz)

    def create_rgs_1_3_1_from_ancilla(self):
        edge_list=[(0,2),(0,4),(0,6),(1,2),(2,14),(3,4),(4,14),(5,6),(6,14),(7,9),(7,11),(7,13),(8,9),(9,14),(10,11),(11,14),(12,13),(13,14)]
        check_mat=self.edge_to_check_mat(edge_list)
        print(check_mat)
        rgs_stab=StabRepr(check_matrix=check_mat, phases=[1 for i in range(15)])
        ape = create_qubits(num_qubits=15, system_name=f"ape0_",no_state=True)
        assign_qstate(ape,qrepr=rgs_stab)
        
        end_stab=StabRepr(check_matrix=self.edge_to_check_mat([(0,1)]), phases=[1 for i in range(2)])
        end_left=create_qubits(num_qubits=2, system_name=f"end_left",no_state=True)
        assign_qstate(end_left,qrepr=end_stab)
        end_right=create_qubits(num_qubits=2, system_name=f"end_right",no_state=True)
        assign_qstate(end_right,qrepr=end_stab)
        operate(ape[8],ops.X) #X error
        
        picked_qstate_a, picked_qubits_a = pick_entangled_qubits(ape[14])
        print(picked_qstate_a, picked_qubits_a)
        self.forced_my_measure(ape[14],ops.Y,0,False)
        #BSM1
        operate(ape[7], Rx)
        self.photonic_bsm(ape[7],end_right[0],0)
        #logical Mx of left subtree
        self.forced_my_measure(ape[8],ops.Z,0,False)
        self.operate_first_level_core(ape[9])
        self.forced_my_measure(ape[9],ops.X,0,False)
        self.forced_my_measure(ape[10],ops.Z,0,False)
        self.operate_first_level_core(ape[11])
        self.forced_my_measure(ape[11],ops.X,0,False)
        self.forced_my_measure(ape[12],ops.Z,0,False)
        self.operate_first_level_core(ape[13])
        self.forced_my_measure(ape[13],ops.X,0,False)
        #BSM0
        operate(ape[0], Rx)
        self.photonic_bsm(end_left[0],ape[0],0)
        #logical Mx of Right subtree
        self.forced_my_measure(ape[1],ops.Z,0,False)
        self.operate_first_level_core(ape[2])
        self.forced_my_measure(ape[2],ops.X,0,False)
        self.forced_my_measure(ape[3],ops.Z,0,False)
        self.operate_first_level_core(ape[4])
        self.forced_my_measure(ape[4],ops.X,0,False)
        self.forced_my_measure(ape[5],ops.Z,0,False)
        self.operate_first_level_core(ape[6])
        self.forced_my_measure(ape[6],ops.X,0,False)

        [index]=end_left[1].qstate.indices_of([end_left[1]])
        print(index,end_left[1].qstate.qrepr)
        end_left[1].qstate.qrepr.row_reduce()
        [index]=end_left[1].qstate.indices_of([end_left[1]])
        print(index,end_left[1].qstate.qrepr)

        picked_qstate_a, picked_qubits_a = pick_entangled_qubits(end_left[1])
        print(picked_qstate_a, picked_qubits_a)


        

#set_qstate_formalism(QFormalism.STAB)
#
##veri=verification(1,1,None)
##veri.create_rgs_1_3_1()
#print("hi")
#hi=verification(1,1,[0])
#hi.create_rgs_1_3_1_from_ancilla()
