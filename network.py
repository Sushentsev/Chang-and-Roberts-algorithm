import math
import os
import sys
from enum import Enum
from itertools import tee
from random import sample
from random import choices

import matplotlib.pyplot as plt
import networkx as nx
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
number_of_communicators = comm.Get_size() - 1

ALGORITHM_TAG = 1
DRAWING_TAG = 2
DELAY_TIME = 0.5

# Process state.
class State(Enum):
    cand = 1
    sleep = 2
    leader = 3
    lost = 4


# Enum of errors during reading from file.
class Error(Enum):
    invalid_number_of_arguments = "invalid number of arguments \nformat of command: mpiexec -n {num_of_processes} python network.py [random | from_file {/path/to/file}]"
    invalid_number_of_communicators = "invalid number of communicators"
    invalid_mode = "invalid mode \nmode must be either random or from_file"
    file_not_found = "input file doesn't exist"
    ci_is_not_an_int = "%s is not an int"
    ci_duplication = "%s is already exists in the network"

# Returns iterators for generating edges.
def pairwise(iterable):
    a, b = tee(iterable)
    next(b, None)

    return zip(a, b)

# Generates edges between nodes.
def generate_edges(vxs):
    edges = [(v1,v2) for v1, v2 in pairwise(vxs)]
    edges.append((vxs[number_of_communicators - 1], vxs[0]))
    
    return edges


def finish(msg, *args):
    print(msg.value % args, flush=True)
    comm.Abort()
    exit(1)

# Returns nodes positions.
def get_pos(vxs):
    pos = {}
    radius = 20
    
    for i, v in enumerate(vxs):
        arc = 2 * math.pi * i / len(vxs)
        x = math.sin(arc) * radius
        y = math.cos(arc) * radius
        pos[v] = (x, y)

    return pos

def draw_network(vxs, pos, node_colors, labels):
    plt.clf()

    network = nx.DiGraph()
    network.add_edges_from(generate_edges(vxs))

    nx.draw_networkx_nodes(network, pos, node_color=node_colors, node_size=1000)
    nx.draw_networkx_labels(network, pos, labels=labels)
    nx.draw_networkx_edges(network, pos)

    plt.draw()
    plt.pause(DELAY_TIME)

# Returns next node.
def dst(rank, number_of_communicators):
    if rank == number_of_communicators:
        return 1

    return rank + 1

# Returns prev node.
def src(rank, number_of_communicators):
    if rank == 1:
        return number_of_communicators

    return rank - 1


def send_data_to_drawer(data):
    comm.send(data, dest=0, tag=DRAWING_TAG)


def send(next_node, algo_data, state_data):
    comm.send(algo_data, dest=next_node, tag=ALGORITHM_TAG)
    send_data_to_drawer(state_data)

# Returns vertex markers.
def get_vxs(argv):
    vxs = []

    if len(argv) < 1:
            finish(Error.invalid_number_of_arguments)
    
    if argv[0] == 'from_file':
        if len(argv) != 2:
            finish(Error.invalid_number_of_arguments)
        
        if not os.path.exists(argv[1]):
            finish(Error.file_not_found)
    
        for line in open(argv[1]):
            if not line[:-1].isdecimal():
                finish(Error.ci_is_not_an_int, line[:-1])
    
            ci = int(line)
            if ci in vxs:
                finish(Error.ci_duplication, ci)
    
            vxs.append(ci)
    
        if len(vxs) != number_of_communicators:
            finish(Error.invalid_number_of_communicators)
    elif argv[0] == 'random':
        if len(argv) != 1:
            finish(Error.invalid_number_of_arguments)
    
        vxs = sample(range(1, 100), number_of_communicators)
    else:
        finish(Error.invalid_mode)

    return vxs


def drawer_worker(argv):
    vxs = get_vxs(argv)
    comm.bcast(vxs, root=0)

    cand_node_color = "#ffff00" # Yellow
    sleep_node_color = "#787878" # Grey
    leader_node_color = "#ff4d4d" # Red
    lost_node_color =  "#0000ff" # Blue
    node_colors = [sleep_node_color for v in vxs]
    pos = get_pos(vxs)

    labels = {}
    for i, v in enumerate(vxs):
        labels[v] = "({0}, {1})".format(v, -1)
    
    is_running = number_of_communicators > 1
    
    while is_running:
        draw_network(vxs, pos, node_colors, labels)
    
        for i, v in enumerate(vxs):
            src_communicator = i + 1
            data = comm.recv(source=src_communicator, tag=DRAWING_TAG)
            
            if 'need_stop' in data:
                node_colors[i] = leader_node_color
                is_running = False
                break
            else:
                assert 'marker' in data
                assert 'state' in data
                assert 'tok' in data

                if data['state'] == State.cand:
                    node_colors[i] = cand_node_color
                if data['state'] == State.leader:
                    node_colors[i] = leader_node_color
                if data['state'] == State.lost:
                    node_colors[i] = lost_node_color

                tok = data['tok']
                labels[v] = "({0}, {1})".format(v, tok)
    
    draw_network(vxs, pos, node_colors, labels)
    plt.show()


def communicator_worker():
    prev_node = src(rank, number_of_communicators)
    next_node = dst(rank, number_of_communicators)

    vxs = comm.bcast(None, root=0)
    state_data = {'marker': vxs[rank - 1], 'state': State.sleep, 'tok': -1}
    if (True):
        state_data['state'] = State.cand 
        send(next_node, {'tok': state_data['marker']}, state_data)

        while (state_data['state'] != State.leader):
            data = comm.recv(source=prev_node, tag=ALGORITHM_TAG)
            assert 'tok' in data
            state_data['tok'] = data['tok']
            if (data['tok'] == state_data['marker']):
                state_data['state'] = State.leader
            else:
                if (data['tok'] < state_data['marker']):
                    if (state_data['state'] == State.cand):
                        state_data['state'] = State.lost
                    send(next_node, {'tok': data['tok']}, state_data)
    else:
        while True:
            data = comm.recv(source=prev_node, tag=ALGORITHM_TAG)
            assert 'tok' in data
            state_data['tok'] = data['tok']
            
            if (state_data['state'] == State.sleep):
                state_data['state'] = State.lost

            send(next_node, {'tok': data['tok']}, state_data)


    send_data_to_drawer(state_data)
    send_data_to_drawer({'need_stop': True})


# Process with rank = 0 is a drawer.
# Others are communicators.
def simulate(*argv):
    if rank == 0:
        drawer_worker(argv)
    else:
        communicator_worker()


if __name__ == '__main__':
    simulate(*sys.argv[1:])
