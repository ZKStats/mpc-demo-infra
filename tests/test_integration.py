import os
import requests
import pytest
import asyncio
import aiohttp
from pathlib import Path

from mpc_demo_infra.coordination_server.config import settings
from mpc_demo_infra.coordination_server.database import SessionLocal, Voucher, DataProvider

from .common import TLSN_PROOF


COMPUTATION_DB_URL_TEMPLATE = "sqlite:///./party_{party_id}.db"
NUM_PARTIES = 3
# Adjust these ports as needed
COORDINATION_PORT = 5565
MPC_PORT_BASE = 8010
CLIENT_PORT = 14000
COMPUTATION_HOSTS = ["localhost"] * NUM_PARTIES
COMPUTATION_PARTY_PORTS = [5566 + party_id for party_id in range(NUM_PARTIES)]

TIMEOUT_MPC = 60

CMD_PREFIX_COORDINATION_SERVER = ["poetry", "run", "coordination-server-run"]
CMD_PREFIX_COMPUTATION_PARTY_SERVER = ["poetry", "run", "computation-party-server-run"]

async def start_coordination_server(cmd: list[str], port: int, tlsn_proofs_dir: Path):
    party_ips = [f"{host}:{port}" for host, port in zip(COMPUTATION_HOSTS, COMPUTATION_PARTY_PORTS)]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        env={
            **os.environ,
            "NUM_PARTIES": str(NUM_PARTIES),
            "PORT": str(port),
            "PARTY_IPS": '["' + '","'.join(party_ips) + '"]',
            "MPC_PORT_BASE": str(MPC_PORT_BASE),
            "CLIENT_PORT": str(CLIENT_PORT),
            "TLSN_PROOFS_DIR": str(tlsn_proofs_dir),
        },
        # stdout=asyncio.subprocess.PIPE,
        # stderr=asyncio.subprocess.PIPE
    )
    return process

async def start_computation_party_server(cmd: list[str], party_id: int, port: int):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        env={
            **os.environ,
            "PORT": str(port),
            "PARTY_ID": str(party_id),
            "DATABASE_URL": COMPUTATION_DB_URL_TEMPLATE.format(party_id=party_id),
            "COORDINATION_SERVER_URL": f"http://localhost:{COORDINATION_PORT}",
        },
        # stdout=asyncio.subprocess.PIPE,
        # stderr=asyncio.subprocess.PIPE
    )
    return process


@pytest.fixture
def tlsn_proofs_dir(tmp_path):
    p = tmp_path / "tlsn_proofs"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
@pytest.mark.asyncio
async def servers(tlsn_proofs_dir):
    print(f"Setting up servers")
    # Remove the existing coordination.db file
    # Extract the coordination.db path from the database URL
    coordination_db_path = settings.database_url.split(":///")[1]

    if os.path.exists(coordination_db_path):
        os.remove(coordination_db_path)

    for party_id in range(settings.num_parties):
        party_db_path = COMPUTATION_DB_URL_TEMPLATE.format(party_id=party_id).split(":///")[1]
        if os.path.exists(party_db_path):
            os.remove(party_db_path)

    start_tasks = [
        start_coordination_server(CMD_PREFIX_COORDINATION_SERVER, COORDINATION_PORT, tlsn_proofs_dir),
    ] + [
        start_computation_party_server(CMD_PREFIX_COMPUTATION_PARTY_SERVER, party_id, port)
        for party_id, port in enumerate(COMPUTATION_PARTY_PORTS)
    ]

    processes = await asyncio.gather(*start_tasks)

    print("!@# All servers started concurrently")

    await asyncio.sleep(2)

    yield

    # Graceful shutdown attempt
    for process in processes:
        process.terminate()

    # Ensure all processes are terminated
    await asyncio.gather(*[process.wait() for process in processes])
    print("All servers terminated")

    # Additional wait to allow OS to release resources
    await asyncio.sleep(1)


# def run_save_data_client(client_port: int, client_id: int, value: int):
#     import sys
#     sys.path.append(settings.mpspdz_project_root)

#     from ExternalDemo.client import Client, octetStream
#     from ExternalDemo.domains import *

#     isInput = 1

#     # client id should be assigned by our server
#     client = Client(COMPUTATION_HOSTS, client_port, client_id)

#     for socket in client.sockets:
#         os = octetStream()
#         os.store(isInput)
#         os.Send(socket)


#     def run(x):
#         client.send_private_inputs([x])
#         print("finish sending private inputs")
#         # print('Winning client id is :', client.receive_outputs(1)[0])

#     # running two rounds
#     # first for sint, then for sfix
#     run(value)


@pytest.mark.asyncio
async def test_basic_integration(servers, tlsn_proofs_dir: Path):
    voucher1 = "1234567890"
    voucher2 = "0987654321"
    identity1 = "test_identity1"
    identity2 = "test_identity2"
    with SessionLocal() as db:
        voucher_1 = Voucher(code=voucher1)
        db.add(voucher_1)
        voucher_2 = Voucher(code=voucher2)
        db.add(voucher_2)
        db.commit()
        db.refresh(voucher_1)
        db.refresh(voucher_2)

    # Register the user
    response1 = requests.post(f"http://localhost:{COORDINATION_PORT}/register", json={
        "voucher_code": voucher1,
        "identity": identity1
    })
    assert response1.status_code == 200

    response2 = requests.post(f"http://localhost:{COORDINATION_PORT}/register", json={
        "voucher_code": voucher2,
        "identity": identity2
    })
    assert response2.status_code == 200

    # Request the data
    # for party_id in range(settings.num_parties):
    # asynchronously request /share_data for all parties
    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://localhost:{COORDINATION_PORT}/share_data", json={
            "identity": identity1,
            "tlsn_proof": TLSN_PROOF
        }) as response:
            assert response.status == 200
            data = await response.json()
            client_port_1 = data["client_port"]
            client_id_1 = data["client_id"]

    # Wait until all computation parties started their MPC servers.
    await asyncio.sleep(2)

    value_1 = 3
    value_2 = value_1

    # Clean up the existing shares
    for party_id in range(settings.num_parties):
        (Path(settings.mpspdz_project_root) / f"Persistence/Transactions-P{party_id}.data").unlink(missing_ok=True)

    print(f"!@# Requesting share data for {identity1}")
    # await asyncio.sleep(10000)
    await asyncio.create_subprocess_shell(
        f"cd {settings.mpspdz_project_root} && python ExternalDemo/save_data_client.py {client_port_1} {settings.num_parties} {client_id_1} {value_1}",
        # stdout=asyncio.subprocess.PIPE,
        # stderr=asyncio.subprocess.PIPE
    )

    await asyncio.sleep(1)

    print(f"!@# Requesting share data for {identity2}")

    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://localhost:{COORDINATION_PORT}/share_data", json={
            "identity": identity2,
        "tlsn_proof": TLSN_PROOF
    }) as response:
            assert response.status == 200
            data = await response.json()
            client_port_2 = data["client_port"]
            client_id_2 = data["client_id"]
    await asyncio.create_subprocess_shell(
        f"cd {settings.mpspdz_project_root} && python ExternalDemo/save_data_client.py {client_port_2} {settings.num_parties} {client_id_2} {value_2}",
        # stdout=asyncio.subprocess.PIPE,
        # stderr=asyncio.subprocess.PIPE
    )


    # async def wait_until_request_fulfilled():
    #     # Poll if tlsn_proof is saved, which means the background task running MPC finished.
    #     tlsn_proof_path = tlsn_proofs_dir / f"proof_{client_id}.json"
    #     while not tlsn_proof_path.exists():
    #         await asyncio.sleep(1)

    # await asyncio.wait_for(
    #     asyncio.gather(
    #         task,
    #         wait_until_request_fulfilled()
    #     ),
    #     timeout=TIMEOUT_MPC,
    # )

    print("Test finished")
