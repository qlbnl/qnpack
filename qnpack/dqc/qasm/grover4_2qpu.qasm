OPENQASM 3.0;
include "stdgates.inc";
gate entanglement _gate_q_0, _gate_q_1 {
  h _gate_q_0;
  cx _gate_q_0, _gate_q_1;
}
bit[4] m;
bit[1] _clbit_comm_qubit1_1;
bit[1] _clbit_comm_qubit2_1;
bit[1] _clbit_comm_qubit1_2;
bit[1] _clbit_comm_qubit2_2;
bit[1] _clbit_comm_qubit1_3;
bit[1] _clbit_comm_qubit2_3;
bit[1] _clbit_comm_qubit1_4;
bit[1] _clbit_comm_qubit2_4;
bit[1] _clbit_comm_qubit1_5;
bit[1] _clbit_comm_qubit2_5;
bit[1] _clbit_comm_qubit1_6;
bit[1] _clbit_comm_qubit2_6;
bit[1] _clbit_comm_qubit1_7;
bit[1] _clbit_comm_qubit2_7;
bit[1] _clbit_comm_qubit1_8;
bit[1] _clbit_comm_qubit2_8;
bit[1] _clbit_comm_qubit1_9;
bit[1] _clbit_comm_qubit2_9;
bit[1] _clbit_comm_qubit1_10;
bit[1] _clbit_comm_qubit2_10;
qubit[1] _qubit1_2;
qubit[1] _qubit1_1;
qubit[1] _qubit2_2;
qubit[1] _comm_qubit1_1;
qubit[1] _comm_qubit2_1;
qubit[1] _comm_qubit1_2;
qubit[1] _comm_qubit2_2;
qubit[1] _comm_qubit1_3;
qubit[1] _comm_qubit2_3;
qubit[1] _comm_qubit1_4;
qubit[1] _comm_qubit2_4;
qubit[1] _qubit2_1;
qubit[1] _comm_qubit1_5;
qubit[1] _comm_qubit2_5;
qubit[1] _comm_qubit1_6;
qubit[1] _comm_qubit2_6;
qubit[1] _comm_qubit1_7;
qubit[1] _comm_qubit2_7;
qubit[1] _comm_qubit1_8;
qubit[1] _comm_qubit2_8;
qubit[1] _comm_qubit1_9;
qubit[1] _comm_qubit2_9;
qubit[1] _comm_qubit1_10;
qubit[1] _comm_qubit2_10;
rz(pi/2) _qubit1_2[0];
sx _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
rz(pi/8) _qubit1_2[0];
rz(pi/2) _qubit1_1[0];
sx _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
rz(pi/8) _qubit1_1[0];
cx _qubit1_2[0], _qubit1_1[0];
rz(-pi/8) _qubit1_1[0];
cx _qubit1_2[0], _qubit1_1[0];
rz(pi/2) _qubit2_2[0];
sx _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
entanglement _comm_qubit1_1[0], _comm_qubit2_1[0];
cx _qubit1_1[0], _comm_qubit1_1[0];
entanglement _comm_qubit1_2[0], _comm_qubit2_2[0];
cx _qubit1_2[0], _comm_qubit1_2[0];
entanglement _comm_qubit1_3[0], _comm_qubit2_3[0];
entanglement _comm_qubit1_4[0], _comm_qubit2_4[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
entanglement _comm_qubit1_5[0], _comm_qubit2_5[0];
entanglement _comm_qubit1_6[0], _comm_qubit2_6[0];
entanglement _comm_qubit1_7[0], _comm_qubit2_7[0];
entanglement _comm_qubit1_8[0], _comm_qubit2_8[0];
entanglement _comm_qubit1_9[0], _comm_qubit2_9[0];
entanglement _comm_qubit1_10[0], _comm_qubit2_10[0];
_clbit_comm_qubit1_1[0] = measure _comm_qubit1_1[0];
reset _comm_qubit1_1[0];
if (_clbit_comm_qubit1_1[0]) {
  x _comm_qubit2_1[0];
}
cx _comm_qubit2_1[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_1[0];
_clbit_comm_qubit2_1[0] = measure _comm_qubit2_1[0];
if (_clbit_comm_qubit2_1[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_3[0];
reset _comm_qubit2_1[0];
entanglement _comm_qubit1_1[0], _comm_qubit2_1[0];
_clbit_comm_qubit1_2[0] = measure _comm_qubit1_2[0];
reset _comm_qubit1_2[0];
if (_clbit_comm_qubit1_2[0]) {
  x _comm_qubit2_2[0];
}
cx _comm_qubit2_2[0], _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
h _comm_qubit2_2[0];
_clbit_comm_qubit2_2[0] = measure _comm_qubit2_2[0];
if (_clbit_comm_qubit2_2[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_4[0];
reset _comm_qubit2_2[0];
entanglement _comm_qubit1_2[0], _comm_qubit2_2[0];
_clbit_comm_qubit1_3[0] = measure _comm_qubit1_3[0];
reset _comm_qubit1_3[0];
if (_clbit_comm_qubit1_3[0]) {
  x _comm_qubit2_3[0];
}
cx _comm_qubit2_3[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_3[0];
_clbit_comm_qubit2_3[0] = measure _comm_qubit2_3[0];
if (_clbit_comm_qubit2_3[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_5[0];
reset _comm_qubit2_3[0];
entanglement _comm_qubit1_3[0], _comm_qubit2_3[0];
_clbit_comm_qubit1_4[0] = measure _comm_qubit1_4[0];
reset _comm_qubit1_4[0];
if (_clbit_comm_qubit1_4[0]) {
  x _comm_qubit2_4[0];
}
cx _comm_qubit2_4[0], _qubit2_2[0];
cx _qubit2_2[0], _qubit2_1[0];
h _comm_qubit2_4[0];
rz(-pi/8) _qubit2_1[0];
_clbit_comm_qubit2_4[0] = measure _comm_qubit2_4[0];
if (_clbit_comm_qubit2_4[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_6[0];
reset _comm_qubit2_4[0];
entanglement _comm_qubit1_4[0], _comm_qubit2_4[0];
_clbit_comm_qubit1_5[0] = measure _comm_qubit1_5[0];
reset _comm_qubit1_5[0];
if (_clbit_comm_qubit1_5[0]) {
  x _comm_qubit2_5[0];
}
cx _comm_qubit2_5[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_5[0];
_clbit_comm_qubit2_5[0] = measure _comm_qubit2_5[0];
if (_clbit_comm_qubit2_5[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_7[0];
reset _comm_qubit2_5[0];
entanglement _comm_qubit1_5[0], _comm_qubit2_5[0];
_clbit_comm_qubit1_6[0] = measure _comm_qubit1_6[0];
reset _comm_qubit1_6[0];
if (_clbit_comm_qubit1_6[0]) {
  x _comm_qubit2_6[0];
}
cx _comm_qubit2_6[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_6[0];
_clbit_comm_qubit2_6[0] = measure _comm_qubit2_6[0];
if (_clbit_comm_qubit2_6[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_8[0];
reset _comm_qubit2_6[0];
entanglement _comm_qubit1_6[0], _comm_qubit2_6[0];
_clbit_comm_qubit1_7[0] = measure _comm_qubit1_7[0];
reset _comm_qubit1_7[0];
if (_clbit_comm_qubit1_7[0]) {
  x _comm_qubit2_7[0];
}
cx _comm_qubit2_7[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
sx _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_7[0];
_clbit_comm_qubit2_7[0] = measure _comm_qubit2_7[0];
if (_clbit_comm_qubit2_7[0]) {
  z _qubit1_1[0];
}
rz(pi/2) _qubit1_1[0];
sx _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
rz(pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(2*pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(3*pi) _qubit1_1[0];
rz(pi/8) _qubit1_1[0];
reset _comm_qubit2_7[0];
entanglement _comm_qubit1_7[0], _comm_qubit2_7[0];
_clbit_comm_qubit1_8[0] = measure _comm_qubit1_8[0];
reset _comm_qubit1_8[0];
if (_clbit_comm_qubit1_8[0]) {
  x _comm_qubit2_8[0];
}
cx _comm_qubit2_8[0], _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(2*pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(3*pi) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
h _comm_qubit2_8[0];
_clbit_comm_qubit2_8[0] = measure _comm_qubit2_8[0];
if (_clbit_comm_qubit2_8[0]) {
  z _qubit1_2[0];
}
rz(pi/2) _qubit1_2[0];
sx _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
rz(pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(2*pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(3*pi) _qubit1_2[0];
rz(pi/8) _qubit1_2[0];
cx _qubit1_2[0], _qubit1_1[0];
rz(-pi/8) _qubit1_1[0];
cx _qubit1_2[0], _qubit1_1[0];
cx _qubit1_2[0], _comm_qubit1_10[0];
cx _qubit1_1[0], _comm_qubit1_9[0];
reset _comm_qubit2_8[0];
entanglement _comm_qubit1_8[0], _comm_qubit2_8[0];
_clbit_comm_qubit1_9[0] = measure _comm_qubit1_9[0];
reset _comm_qubit1_9[0];
if (_clbit_comm_qubit1_9[0]) {
  x _comm_qubit2_9[0];
}
cx _comm_qubit2_9[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_9[0];
_clbit_comm_qubit2_9[0] = measure _comm_qubit2_9[0];
if (_clbit_comm_qubit2_9[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_1[0];
_clbit_comm_qubit1_1[0] = measure _comm_qubit1_1[0];
reset _comm_qubit1_1[0];
if (_clbit_comm_qubit1_1[0]) {
  x _comm_qubit2_1[0];
}
reset _comm_qubit2_9[0];
entanglement _comm_qubit1_9[0], _comm_qubit2_9[0];
_clbit_comm_qubit1_10[0] = measure _comm_qubit1_10[0];
reset _comm_qubit1_10[0];
if (_clbit_comm_qubit1_10[0]) {
  x _comm_qubit2_10[0];
}
cx _comm_qubit2_10[0], _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
cx _comm_qubit2_1[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_1[0];
_clbit_comm_qubit2_1[0] = measure _comm_qubit2_1[0];
if (_clbit_comm_qubit2_1[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_3[0];
reset _comm_qubit2_1[0];
entanglement _comm_qubit1_1[0], _comm_qubit2_1[0];
_clbit_comm_qubit1_3[0] = measure _comm_qubit1_3[0];
reset _comm_qubit1_3[0];
if (_clbit_comm_qubit1_3[0]) {
  x _comm_qubit2_3[0];
}
h _comm_qubit2_10[0];
_clbit_comm_qubit2_10[0] = measure _comm_qubit2_10[0];
if (_clbit_comm_qubit2_10[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_2[0];
_clbit_comm_qubit1_2[0] = measure _comm_qubit1_2[0];
reset _comm_qubit1_2[0];
if (_clbit_comm_qubit1_2[0]) {
  x _comm_qubit2_2[0];
}
cx _comm_qubit2_2[0], _qubit2_2[0];
cx _qubit2_2[0], _qubit2_1[0];
h _comm_qubit2_2[0];
_clbit_comm_qubit2_2[0] = measure _comm_qubit2_2[0];
if (_clbit_comm_qubit2_2[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_4[0];
reset _comm_qubit2_2[0];
entanglement _comm_qubit1_2[0], _comm_qubit2_2[0];
_clbit_comm_qubit1_4[0] = measure _comm_qubit1_4[0];
reset _comm_qubit1_4[0];
if (_clbit_comm_qubit1_4[0]) {
  x _comm_qubit2_4[0];
}
rz(-pi/8) _qubit2_1[0];
cx _comm_qubit2_3[0], _qubit2_1[0];
h _comm_qubit2_3[0];
_clbit_comm_qubit2_3[0] = measure _comm_qubit2_3[0];
if (_clbit_comm_qubit2_3[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_5[0];
reset _comm_qubit2_3[0];
entanglement _comm_qubit1_3[0], _comm_qubit2_3[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
cx _comm_qubit2_4[0], _qubit2_1[0];
h _comm_qubit2_4[0];
_clbit_comm_qubit2_4[0] = measure _comm_qubit2_4[0];
if (_clbit_comm_qubit2_4[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_6[0];
reset _comm_qubit2_4[0];
entanglement _comm_qubit1_4[0], _comm_qubit2_4[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
_clbit_comm_qubit1_5[0] = measure _comm_qubit1_5[0];
reset _comm_qubit1_5[0];
if (_clbit_comm_qubit1_5[0]) {
  x _comm_qubit2_5[0];
}
cx _comm_qubit2_5[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
sx _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_5[0];
_clbit_comm_qubit2_5[0] = measure _comm_qubit2_5[0];
if (_clbit_comm_qubit2_5[0]) {
  z _qubit1_1[0];
}
rz(pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(2*pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(3*pi) _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
sx _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
rz(pi/8) _qubit1_1[0];
reset _comm_qubit2_5[0];
entanglement _comm_qubit1_5[0], _comm_qubit2_5[0];
_clbit_comm_qubit1_6[0] = measure _comm_qubit1_6[0];
reset _comm_qubit1_6[0];
if (_clbit_comm_qubit1_6[0]) {
  x _comm_qubit2_6[0];
}
cx _comm_qubit2_6[0], _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(2*pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(3*pi) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
h _comm_qubit2_6[0];
_clbit_comm_qubit2_6[0] = measure _comm_qubit2_6[0];
if (_clbit_comm_qubit2_6[0]) {
  z _qubit1_2[0];
}
rz(pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(2*pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(3*pi) _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
sx _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
rz(pi/8) _qubit1_2[0];
cx _qubit1_2[0], _qubit1_1[0];
rz(-pi/8) _qubit1_1[0];
cx _qubit1_2[0], _qubit1_1[0];
cx _qubit1_2[0], _comm_qubit1_8[0];
cx _qubit1_1[0], _comm_qubit1_7[0];
reset _comm_qubit2_6[0];
entanglement _comm_qubit1_6[0], _comm_qubit2_6[0];
_clbit_comm_qubit1_7[0] = measure _comm_qubit1_7[0];
reset _comm_qubit1_7[0];
if (_clbit_comm_qubit1_7[0]) {
  x _comm_qubit2_7[0];
}
cx _comm_qubit2_7[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_7[0];
_clbit_comm_qubit2_7[0] = measure _comm_qubit2_7[0];
if (_clbit_comm_qubit2_7[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_9[0];
reset _comm_qubit2_7[0];
entanglement _comm_qubit1_7[0], _comm_qubit2_7[0];
_clbit_comm_qubit1_8[0] = measure _comm_qubit1_8[0];
reset _comm_qubit1_8[0];
if (_clbit_comm_qubit1_8[0]) {
  x _comm_qubit2_8[0];
}
cx _comm_qubit2_8[0], _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
h _comm_qubit2_8[0];
_clbit_comm_qubit2_8[0] = measure _comm_qubit2_8[0];
if (_clbit_comm_qubit2_8[0]) {
  z _qubit1_2[0];
}
reset _comm_qubit2_8[0];
entanglement _comm_qubit1_8[0], _comm_qubit2_8[0];
_clbit_comm_qubit1_9[0] = measure _comm_qubit1_9[0];
reset _comm_qubit1_9[0];
if (_clbit_comm_qubit1_9[0]) {
  x _comm_qubit2_9[0];
}
cx _comm_qubit2_9[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_9[0];
_clbit_comm_qubit2_9[0] = measure _comm_qubit2_9[0];
if (_clbit_comm_qubit2_9[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_1[0];
_clbit_comm_qubit1_1[0] = measure _comm_qubit1_1[0];
reset _comm_qubit1_1[0];
if (_clbit_comm_qubit1_1[0]) {
  x _comm_qubit2_1[0];
}
reset _comm_qubit2_9[0];
entanglement _comm_qubit1_9[0], _comm_qubit2_9[0];
reset _comm_qubit2_10[0];
entanglement _comm_qubit1_10[0], _comm_qubit2_10[0];
cx _qubit1_2[0], _comm_qubit1_10[0];
_clbit_comm_qubit1_10[0] = measure _comm_qubit1_10[0];
reset _comm_qubit1_10[0];
if (_clbit_comm_qubit1_10[0]) {
  x _comm_qubit2_10[0];
}
cx _comm_qubit2_10[0], _qubit2_2[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
cx _comm_qubit2_1[0], _qubit2_1[0];
h _comm_qubit2_1[0];
_clbit_comm_qubit2_1[0] = measure _comm_qubit2_1[0];
if (_clbit_comm_qubit2_1[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_3[0];
reset _comm_qubit2_1[0];
entanglement _comm_qubit1_1[0], _comm_qubit2_1[0];
_clbit_comm_qubit1_3[0] = measure _comm_qubit1_3[0];
reset _comm_qubit1_3[0];
if (_clbit_comm_qubit1_3[0]) {
  x _comm_qubit2_3[0];
}
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_10[0];
_clbit_comm_qubit2_10[0] = measure _comm_qubit2_10[0];
if (_clbit_comm_qubit2_10[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_2[0];
_clbit_comm_qubit1_2[0] = measure _comm_qubit1_2[0];
reset _comm_qubit1_2[0];
if (_clbit_comm_qubit1_2[0]) {
  x _comm_qubit2_2[0];
}
cx _comm_qubit2_2[0], _qubit2_1[0];
h _comm_qubit2_2[0];
_clbit_comm_qubit2_2[0] = measure _comm_qubit2_2[0];
if (_clbit_comm_qubit2_2[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_4[0];
reset _comm_qubit2_2[0];
entanglement _comm_qubit1_2[0], _comm_qubit2_2[0];
_clbit_comm_qubit1_4[0] = measure _comm_qubit1_4[0];
reset _comm_qubit1_4[0];
if (_clbit_comm_qubit1_4[0]) {
  x _comm_qubit2_4[0];
}
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
cx _comm_qubit2_3[0], _qubit2_1[0];
h _comm_qubit2_3[0];
_clbit_comm_qubit2_3[0] = measure _comm_qubit2_3[0];
if (_clbit_comm_qubit2_3[0]) {
  z _qubit1_1[0];
}
rz(pi/2) _qubit1_1[0];
sx _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
rz(pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(2*pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(3*pi) _qubit1_1[0];
rz(pi/8) _qubit1_1[0];
reset _comm_qubit2_3[0];
entanglement _comm_qubit1_3[0], _comm_qubit2_3[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
sx _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
rz(-pi/8) _qubit2_1[0];
cx _comm_qubit2_4[0], _qubit2_1[0];
h _comm_qubit2_4[0];
_clbit_comm_qubit2_4[0] = measure _comm_qubit2_4[0];
if (_clbit_comm_qubit2_4[0]) {
  z _qubit1_2[0];
}
rz(pi/2) _qubit1_2[0];
sx _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
rz(pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(2*pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(3*pi) _qubit1_2[0];
rz(pi/8) _qubit1_2[0];
cx _qubit1_2[0], _qubit1_1[0];
rz(-pi/8) _qubit1_1[0];
cx _qubit1_2[0], _qubit1_1[0];
cx _qubit1_2[0], _comm_qubit1_6[0];
cx _qubit1_1[0], _comm_qubit1_5[0];
reset _comm_qubit2_4[0];
entanglement _comm_qubit1_4[0], _comm_qubit2_4[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(2*pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(3*pi) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
_clbit_comm_qubit1_5[0] = measure _comm_qubit1_5[0];
reset _comm_qubit1_5[0];
if (_clbit_comm_qubit1_5[0]) {
  x _comm_qubit2_5[0];
}
cx _comm_qubit2_5[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_5[0];
_clbit_comm_qubit2_5[0] = measure _comm_qubit2_5[0];
if (_clbit_comm_qubit2_5[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_7[0];
reset _comm_qubit2_5[0];
entanglement _comm_qubit1_5[0], _comm_qubit2_5[0];
_clbit_comm_qubit1_6[0] = measure _comm_qubit1_6[0];
reset _comm_qubit1_6[0];
if (_clbit_comm_qubit1_6[0]) {
  x _comm_qubit2_6[0];
}
cx _comm_qubit2_6[0], _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
h _comm_qubit2_6[0];
_clbit_comm_qubit2_6[0] = measure _comm_qubit2_6[0];
if (_clbit_comm_qubit2_6[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_8[0];
reset _comm_qubit2_6[0];
entanglement _comm_qubit1_6[0], _comm_qubit2_6[0];
_clbit_comm_qubit1_7[0] = measure _comm_qubit1_7[0];
reset _comm_qubit1_7[0];
if (_clbit_comm_qubit1_7[0]) {
  x _comm_qubit2_7[0];
}
cx _comm_qubit2_7[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_7[0];
_clbit_comm_qubit2_7[0] = measure _comm_qubit2_7[0];
if (_clbit_comm_qubit2_7[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_9[0];
reset _comm_qubit2_7[0];
entanglement _comm_qubit1_7[0], _comm_qubit2_7[0];
_clbit_comm_qubit1_8[0] = measure _comm_qubit1_8[0];
reset _comm_qubit1_8[0];
if (_clbit_comm_qubit1_8[0]) {
  x _comm_qubit2_8[0];
}
cx _comm_qubit2_8[0], _qubit2_2[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_8[0];
_clbit_comm_qubit2_8[0] = measure _comm_qubit2_8[0];
if (_clbit_comm_qubit2_8[0]) {
  z _qubit1_2[0];
}
reset _comm_qubit2_8[0];
entanglement _comm_qubit1_8[0], _comm_qubit2_8[0];
_clbit_comm_qubit1_9[0] = measure _comm_qubit1_9[0];
reset _comm_qubit1_9[0];
if (_clbit_comm_qubit1_9[0]) {
  x _comm_qubit2_9[0];
}
cx _comm_qubit2_9[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_9[0];
_clbit_comm_qubit2_9[0] = measure _comm_qubit2_9[0];
if (_clbit_comm_qubit2_9[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_1[0];
_clbit_comm_qubit1_1[0] = measure _comm_qubit1_1[0];
reset _comm_qubit1_1[0];
if (_clbit_comm_qubit1_1[0]) {
  x _comm_qubit2_1[0];
}
reset _comm_qubit2_9[0];
entanglement _comm_qubit1_9[0], _comm_qubit2_9[0];
reset _comm_qubit2_10[0];
entanglement _comm_qubit1_10[0], _comm_qubit2_10[0];
cx _qubit1_2[0], _comm_qubit1_10[0];
_clbit_comm_qubit1_10[0] = measure _comm_qubit1_10[0];
reset _comm_qubit1_10[0];
if (_clbit_comm_qubit1_10[0]) {
  x _comm_qubit2_10[0];
}
cx _comm_qubit2_10[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
cx _comm_qubit2_1[0], _qubit2_1[0];
h _comm_qubit2_1[0];
_clbit_comm_qubit2_1[0] = measure _comm_qubit2_1[0];
if (_clbit_comm_qubit2_1[0]) {
  z _qubit1_1[0];
}
rz(pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(2*pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(3*pi) _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
sx _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
rz(pi/8) _qubit1_1[0];
reset _comm_qubit2_1[0];
entanglement _comm_qubit1_1[0], _comm_qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
sx _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_10[0];
_clbit_comm_qubit2_10[0] = measure _comm_qubit2_10[0];
if (_clbit_comm_qubit2_10[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_2[0];
_clbit_comm_qubit1_2[0] = measure _comm_qubit1_2[0];
reset _comm_qubit1_2[0];
if (_clbit_comm_qubit1_2[0]) {
  x _comm_qubit2_2[0];
}
cx _comm_qubit2_2[0], _qubit2_1[0];
h _comm_qubit2_2[0];
_clbit_comm_qubit2_2[0] = measure _comm_qubit2_2[0];
if (_clbit_comm_qubit2_2[0]) {
  z _qubit1_2[0];
}
rz(pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(2*pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(3*pi) _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
sx _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
rz(pi/8) _qubit1_2[0];
cx _qubit1_2[0], _qubit1_1[0];
rz(-pi/8) _qubit1_1[0];
cx _qubit1_2[0], _qubit1_1[0];
cx _qubit1_2[0], _comm_qubit1_4[0];
cx _qubit1_1[0], _comm_qubit1_3[0];
reset _comm_qubit2_2[0];
entanglement _comm_qubit1_2[0], _comm_qubit2_2[0];
_clbit_comm_qubit1_3[0] = measure _comm_qubit1_3[0];
reset _comm_qubit1_3[0];
if (_clbit_comm_qubit1_3[0]) {
  x _comm_qubit2_3[0];
}
cx _comm_qubit2_3[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_3[0];
_clbit_comm_qubit2_3[0] = measure _comm_qubit2_3[0];
if (_clbit_comm_qubit2_3[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_5[0];
reset _comm_qubit2_3[0];
entanglement _comm_qubit1_3[0], _comm_qubit2_3[0];
_clbit_comm_qubit1_4[0] = measure _comm_qubit1_4[0];
reset _comm_qubit1_4[0];
if (_clbit_comm_qubit1_4[0]) {
  x _comm_qubit2_4[0];
}
cx _comm_qubit2_4[0], _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
h _comm_qubit2_4[0];
_clbit_comm_qubit2_4[0] = measure _comm_qubit2_4[0];
if (_clbit_comm_qubit2_4[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_6[0];
reset _comm_qubit2_4[0];
entanglement _comm_qubit1_4[0], _comm_qubit2_4[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(2*pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(3*pi) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
_clbit_comm_qubit1_5[0] = measure _comm_qubit1_5[0];
reset _comm_qubit1_5[0];
if (_clbit_comm_qubit1_5[0]) {
  x _comm_qubit2_5[0];
}
cx _comm_qubit2_5[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_5[0];
_clbit_comm_qubit2_5[0] = measure _comm_qubit2_5[0];
if (_clbit_comm_qubit2_5[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_7[0];
reset _comm_qubit2_5[0];
entanglement _comm_qubit1_5[0], _comm_qubit2_5[0];
_clbit_comm_qubit1_6[0] = measure _comm_qubit1_6[0];
reset _comm_qubit1_6[0];
if (_clbit_comm_qubit1_6[0]) {
  x _comm_qubit2_6[0];
}
cx _comm_qubit2_6[0], _qubit2_2[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_6[0];
_clbit_comm_qubit2_6[0] = measure _comm_qubit2_6[0];
if (_clbit_comm_qubit2_6[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_8[0];
reset _comm_qubit2_6[0];
entanglement _comm_qubit1_6[0], _comm_qubit2_6[0];
_clbit_comm_qubit1_7[0] = measure _comm_qubit1_7[0];
reset _comm_qubit1_7[0];
if (_clbit_comm_qubit1_7[0]) {
  x _comm_qubit2_7[0];
}
cx _comm_qubit2_7[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_7[0];
_clbit_comm_qubit2_7[0] = measure _comm_qubit2_7[0];
if (_clbit_comm_qubit2_7[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_9[0];
reset _comm_qubit2_7[0];
entanglement _comm_qubit1_7[0], _comm_qubit2_7[0];
_clbit_comm_qubit1_8[0] = measure _comm_qubit1_8[0];
reset _comm_qubit1_8[0];
if (_clbit_comm_qubit1_8[0]) {
  x _comm_qubit2_8[0];
}
cx _comm_qubit2_8[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_8[0];
_clbit_comm_qubit2_8[0] = measure _comm_qubit2_8[0];
if (_clbit_comm_qubit2_8[0]) {
  z _qubit1_2[0];
}
reset _comm_qubit2_8[0];
entanglement _comm_qubit1_8[0], _comm_qubit2_8[0];
_clbit_comm_qubit1_9[0] = measure _comm_qubit1_9[0];
reset _comm_qubit1_9[0];
if (_clbit_comm_qubit1_9[0]) {
  x _comm_qubit2_9[0];
}
cx _comm_qubit2_9[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
sx _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_9[0];
_clbit_comm_qubit2_9[0] = measure _comm_qubit2_9[0];
if (_clbit_comm_qubit2_9[0]) {
  z _qubit1_1[0];
}
rz(pi/2) _qubit1_1[0];
sx _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
rz(pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(2*pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(3*pi) _qubit1_1[0];
rz(pi/8) _qubit1_1[0];
reset _comm_qubit2_9[0];
reset _comm_qubit2_10[0];
entanglement _comm_qubit1_10[0], _comm_qubit2_10[0];
cx _qubit1_2[0], _comm_qubit1_10[0];
_clbit_comm_qubit1_10[0] = measure _comm_qubit1_10[0];
reset _comm_qubit1_10[0];
if (_clbit_comm_qubit1_10[0]) {
  x _comm_qubit2_10[0];
}
cx _comm_qubit2_10[0], _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(2*pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(3*pi) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
h _comm_qubit2_10[0];
_clbit_comm_qubit2_10[0] = measure _comm_qubit2_10[0];
if (_clbit_comm_qubit2_10[0]) {
  z _qubit1_2[0];
}
rz(pi/2) _qubit1_2[0];
sx _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
rz(pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(2*pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(3*pi) _qubit1_2[0];
rz(pi/8) _qubit1_2[0];
cx _qubit1_2[0], _qubit1_1[0];
rz(-pi/8) _qubit1_1[0];
cx _qubit1_2[0], _qubit1_1[0];
cx _qubit1_2[0], _comm_qubit1_2[0];
cx _qubit1_1[0], _comm_qubit1_1[0];
_clbit_comm_qubit1_1[0] = measure _comm_qubit1_1[0];
reset _comm_qubit1_1[0];
if (_clbit_comm_qubit1_1[0]) {
  x _comm_qubit2_1[0];
}
cx _comm_qubit2_1[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_1[0];
_clbit_comm_qubit2_1[0] = measure _comm_qubit2_1[0];
if (_clbit_comm_qubit2_1[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_3[0];
reset _comm_qubit2_1[0];
_clbit_comm_qubit1_2[0] = measure _comm_qubit1_2[0];
reset _comm_qubit1_2[0];
if (_clbit_comm_qubit1_2[0]) {
  x _comm_qubit2_2[0];
}
cx _comm_qubit2_2[0], _qubit2_2[0];
rz(pi/8) _qubit2_2[0];
h _comm_qubit2_2[0];
_clbit_comm_qubit2_2[0] = measure _comm_qubit2_2[0];
if (_clbit_comm_qubit2_2[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_4[0];
reset _comm_qubit2_2[0];
_clbit_comm_qubit1_3[0] = measure _comm_qubit1_3[0];
reset _comm_qubit1_3[0];
if (_clbit_comm_qubit1_3[0]) {
  x _comm_qubit2_3[0];
}
cx _comm_qubit2_3[0], _qubit2_2[0];
rz(-pi/8) _qubit2_2[0];
h _comm_qubit2_3[0];
_clbit_comm_qubit2_3[0] = measure _comm_qubit2_3[0];
if (_clbit_comm_qubit2_3[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_5[0];
reset _comm_qubit2_3[0];
_clbit_comm_qubit1_4[0] = measure _comm_qubit1_4[0];
reset _comm_qubit1_4[0];
if (_clbit_comm_qubit1_4[0]) {
  x _comm_qubit2_4[0];
}
cx _comm_qubit2_4[0], _qubit2_2[0];
cx _qubit2_2[0], _qubit2_1[0];
h _comm_qubit2_4[0];
_clbit_comm_qubit2_4[0] = measure _comm_qubit2_4[0];
if (_clbit_comm_qubit2_4[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_6[0];
reset _comm_qubit2_4[0];
rz(-pi/8) _qubit2_1[0];
_clbit_comm_qubit1_5[0] = measure _comm_qubit1_5[0];
reset _comm_qubit1_5[0];
if (_clbit_comm_qubit1_5[0]) {
  x _comm_qubit2_5[0];
}
cx _comm_qubit2_5[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_5[0];
_clbit_comm_qubit2_5[0] = measure _comm_qubit2_5[0];
if (_clbit_comm_qubit2_5[0]) {
  z _qubit1_1[0];
}
cx _qubit1_1[0], _comm_qubit1_7[0];
reset _comm_qubit2_5[0];
_clbit_comm_qubit1_6[0] = measure _comm_qubit1_6[0];
reset _comm_qubit1_6[0];
if (_clbit_comm_qubit1_6[0]) {
  x _comm_qubit2_6[0];
}
cx _comm_qubit2_6[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_6[0];
_clbit_comm_qubit2_6[0] = measure _comm_qubit2_6[0];
if (_clbit_comm_qubit2_6[0]) {
  z _qubit1_2[0];
}
cx _qubit1_2[0], _comm_qubit1_8[0];
reset _comm_qubit2_6[0];
_clbit_comm_qubit1_7[0] = measure _comm_qubit1_7[0];
reset _comm_qubit1_7[0];
if (_clbit_comm_qubit1_7[0]) {
  x _comm_qubit2_7[0];
}
cx _comm_qubit2_7[0], _qubit2_1[0];
rz(pi/8) _qubit2_1[0];
cx _qubit2_2[0], _qubit2_1[0];
rz(pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(2*pi) _qubit2_2[0];
sx _qubit2_2[0];
rz(3*pi) _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
sx _qubit2_2[0];
rz(pi/2) _qubit2_2[0];
m[2] = measure _qubit2_2[0];
rz(-pi/8) _qubit2_1[0];
h _comm_qubit2_7[0];
_clbit_comm_qubit2_7[0] = measure _comm_qubit2_7[0];
if (_clbit_comm_qubit2_7[0]) {
  z _qubit1_1[0];
}
rz(pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(2*pi) _qubit1_1[0];
sx _qubit1_1[0];
rz(3*pi) _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
sx _qubit1_1[0];
rz(pi/2) _qubit1_1[0];
m[1] = measure _qubit1_1[0];
reset _comm_qubit2_7[0];
_clbit_comm_qubit1_8[0] = measure _comm_qubit1_8[0];
reset _comm_qubit1_8[0];
if (_clbit_comm_qubit1_8[0]) {
  x _comm_qubit2_8[0];
}
cx _comm_qubit2_8[0], _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
rz(pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(2*pi) _qubit2_1[0];
sx _qubit2_1[0];
rz(3*pi) _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
sx _qubit2_1[0];
rz(pi/2) _qubit2_1[0];
m[3] = measure _qubit2_1[0];
h _comm_qubit2_8[0];
_clbit_comm_qubit2_8[0] = measure _comm_qubit2_8[0];
if (_clbit_comm_qubit2_8[0]) {
  z _qubit1_2[0];
}
rz(pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(2*pi) _qubit1_2[0];
sx _qubit1_2[0];
rz(3*pi) _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
sx _qubit1_2[0];
rz(pi/2) _qubit1_2[0];
m[0] = measure _qubit1_2[0];
reset _comm_qubit2_8[0];
reset _comm_qubit2_10[0];

