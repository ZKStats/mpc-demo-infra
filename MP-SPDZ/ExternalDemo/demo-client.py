#!/usr/bin/python3

import sys

sys.path.append('.')

from client import *
from domains import *

client_id = int(sys.argv[1])
n_parties = int(sys.argv[2])
isInput = int(sys.argv[3])
bonus = int(sys.argv[4])

client = Client(['localhost'] * n_parties, 14000, client_id)

for socket in client.sockets:
    os = octetStream()
    os.store(isInput)
    os.Send(socket)

def run(x):
    client.send_private_inputs([x])
    print("finish sending private inputs")
    # print('Winning client id is :', client.receive_outputs(1)[0])

# running two rounds
# first for sint, then for sfix
run(bonus)
# run(bonus * 2 ** 16)
