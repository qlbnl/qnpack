from netsquid.qubits.stabtools import StabRepr
from netsquid.qubits.qubitapi import *
from netsquid.qubits.qformalism import *
from netsquid.qubits.qstate import QState
from netsquid.qubits import operators as ops
from netsquid.qubits import Stabilizer
import netsquid as ns
import numpy as np
from netsquid.qubits import qubitapi as qapi
from netsquid.qubits.qubitapi import operate,measure,gmeasure
from netsquid.qubits import operators as ops
import networkx as nx 
import matplotlib.pyplot as plt
import numpy as np

def is_identity(matrix):
    # Get the size of the matrix
    size = matrix.shape[0]
    # Create the identity matrix of the same size
    identity = np.eye(size)
    # Check if the matrix is equal to the identity matrix using numpy.allclose
    return np.allclose(matrix, identity)

def is_symmetric(mat):
    transmat = np.array(mat).transpose()
    if np.array_equal(mat, transmat):
        return True
    return False
        
def plot_graph(check_mat,label=None):
    num_nodes = len(check_mat)
    #print("num_nodes",num_nodes)
    x_check=check_mat[:,:num_nodes]
    z_check=check_mat[:,num_nodes:]
    if is_identity(np.array(x_check)):
        if is_symmetric(np.array(z_check)):
            graph = nx.Graph() 
            graph.add_nodes_from(range(num_nodes))
            for i in range(num_nodes):
                for j in range(i + 1, num_nodes):
                    if z_check[i][j] == 1:
                        graph.add_edge(i, j)
            pos = nx.spring_layout(graph)
            nx.draw(graph, pos,with_labels=False, node_color='lightblue', node_size=500, font_weight='bold')
            
            #print("pos",pos)
            nx.draw_networkx_labels(graph, pos, label)
            plt.show()
        else:
            print("x_check is equal to identity but z_check is not symmetric.")
    else:
        print("x_check is not equal to identity.")
            
def is_qubit_in_product(qubit):
    num_qubits=qubit.qstate.num_qubits
    [index]=qubit.qstate.indices_of([qubit])
    qubit_x=np.array(qubit.qstate.qrepr.check_matrix[:,index])
    qubit_z=np.array(qubit.qstate.qrepr.check_matrix[:,num_qubits+index])
    qubit_y=qubit_x+qubit_z
    qubit_phase=qubit.qstate.qrepr.phases[index]
    #print(qubit,qubit_x,qubit_z,qubit_y)
    
    if (1 not in qubit_x) and (1 not in qubit_z):
        return True, ops.Y, qubit_phase
    if (1 not in qubit_x) and (2 not in qubit_y):
        return True, ops.Z, qubit_phase
    if (2 not in qubit_y) and (1 not in qubit_z):
        return True, ops.X, qubit_phase
    return False, None, None

def plot_qubit_graph_after_split(qubit,matter_qubits=None):
    qubit.qstate.qrepr.row_reduce()
    check_mat=qubit.qstate.qrepr.check_matrix
    graph_label={}
    for name,index in qubit.qstate.indices.items():
        #graph_label[index]=int(name[3:])
        graph_label[index]=name[3:]
    plot_graph(check_mat,graph_label)

def photonic_bsm(q1,q2,outcome,discard_qubits=True):
    #print("outcome inside photonic_bsm",outcome)
    if outcome==0 or outcome==1:
        #print("outcome 0")
        gmeasure([q1,q2], ops.X^ops.Z)
        gmeasure([q1,q2], ops.Z^ops.X) 
    elif outcome==2 or outcome==3:
        #print("outcome 2")
        gmeasure([q1,q2], ops.X^ops.Z)
        measure(q1,ops.X)
    else:
        print("undefined outcome")
    if discard_qubits:
        discard(q1)
        discard(q2)

def split_product_qubit(qubit):
    ##Check if the qubit is product state along its qstate. If so, separate it from the combined qstate.
    if len(qubit.qstate.qubits)<=1: #Already a product state
        #print(qubit,"has only one qubit in qstate")
        return
    else:
        is_product,observable,phase= is_qubit_in_product(qubit)
        if is_product:
            qubit.qstate.drop_qubit(qubit)
            QState([qubit], get_qstate_formalism().create_in_basis([(1-phase)/2], observable)) #(1-phase)/2
            print(qubit,"is a product state combined with other qubits in qstate")   
        else:
            #print(qubit,"is not in product state")
            pass

def plot_qubit_graph(qubit_to_plot):
    print(f"{ns.sim_time():.1f}:Print out graph state before splitting qubits in product:",qubit_to_plot.qstate)
    for qubit in qubit_to_plot.qstate.qubits:
        split_product_qubit(qubit)
    #print(qproc.peek([0,1,2]))
    qubit_to_plot.qstate.qrepr.row_reduce()
    print(qubit_to_plot.qstate.qrepr)
    print(qubit_to_plot.qstate)
    plot_qubit_graph_after_split(qubit_to_plot)
    print(f"{ns.sim_time():.1f}:Print out graph state after splitting qubits in product:",qubit_to_plot.qstate)

def plot_qubit_graph_without_split(qubit_to_plot):
    picked_stab,picked_qubits=pick_entangled_qubits(qubit_to_plot)
    graph_label={}
    for i in range(len(picked_qubits)):
        #graph_label[index]=int(name[3:])
        graph_label[i]=picked_qubits[i].name[3:]
    plot_graph(picked_stab.check_matrix,graph_label)


def pick_entangled_qubits(qubit):
    qubit.qstate.qrepr.row_reduce()
    [index]=qubit.qstate.indices_of([qubit])
    check_matrix=np.array(qubit.qstate.qrepr.check_matrix)
    num_qubits=check_matrix.shape[0]
    operators=np.bitwise_or(check_matrix[:,0:num_qubits],check_matrix[:,num_qubits:])
    #print("operators",operators)
    #print("index",index)
    entangled_qubits=np.array([index]) 
    mask = np.zeros(len(operators), dtype=bool) #True if the row has been checked
    
    def entangled_by_stab(operators,index_ls=[],entangled_qubits=[]):
    #new_entangled_ls=[]
        if len(index_ls)==0 or np.all(mask):
            return entangled_qubits
        else:
            for index in index_ls:
                if np.all(mask):
                    return entangled_qubits
                index_column=operators[:,index].astype(bool) ##index_column is the rows where column index is 1 
                row_sum=np.bitwise_or.reduce(operators[index_column],0)
                nonzero_indices = np.nonzero(row_sum)[0]
                #print("index_column",index_column)
                #print("operators[index_column]",operators[index_column])
                #print("nonzero_indices",nonzero_indices)
                #print("entangled_qubits",entangled_qubits)
                extra_entangled_qubits=nonzero_indices[np.isin(nonzero_indices,entangled_qubits,invert=True)]
                #print("extra_entangled_qubits",extra_entangled_qubits)
                mask[index_column]=True
                #print("mask",mask)
                entangled_qubits=np.append(entangled_qubits,extra_entangled_qubits)
                #print("entangled_qubits after append",entangled_qubits)
                operators[mask]=0
                #print("masked operators",operators)
                entangled_qubits=entangled_by_stab(operators,extra_entangled_qubits,entangled_qubits) ##Would operators in for loop not be masked if mask is modified during recursion?
                        
            #return new_entangled_ls+entangled_by_stab(operators,index_ls=new_entangled_ls,entangled_ls)
            return entangled_qubits
    
    
    all_entangled_index=entangled_by_stab(operators,[index],entangled_qubits)
    all_entangled_index=np.sort(all_entangled_index)
    #print("np.sort(all_entangled_index)",all_entangled_index)
    #print("np.append(all_entangled_index,all_entangled_index+num_qubits)",np.append(all_entangled_index,all_entangled_index+num_qubits))
    
    #picked_check_matrix=check_matrix[all_entangled_index][:,np.append(all_entangled_index,all_entangled_index+num_qubits)] ##the rows here are incorrect
    picked_check_matrix=check_matrix[mask][:,np.append(all_entangled_index,all_entangled_index+num_qubits)]
    
    picked_phases=qubit.qstate.qrepr.phases[mask]
    #print("mask",mask)
    #print("check_matrix",check_matrix)
    #print("picked_check_matrix",picked_check_matrix)
    #print("picked_phases",picked_phases)
    #print("all_entangled_index",all_entangled_index,all_entangled_index.tolist())
    #print("Correspond to qubits in qstate:",[qubit.qstate.qubits[i] for i in all_entangled_index])
    picked_stab = StabRepr(check_matrix=picked_check_matrix, phases=picked_phases)
    #print("qubit.qstate.qubits",np.array(qubit.qstate.qubits))
    picked_qubits=np.array(qubit.qstate.qubits)[all_entangled_index]
    return picked_stab,picked_qubits