import csv
import os
import aiohttp
import pytest
import asyncio
import secrets

from pathlib import Path
import json

from mpc_demo_infra.coordination_server.config import settings
from mpc_demo_infra.client_lib.lib import fetch_parties_certs, share_data, query_computation, add_user_to_queue, poll_queue_until_ready

FILE_DIR = Path(__file__).parent
proof_file_1 = FILE_DIR / f"proof_1.json"
proof_file_2 = FILE_DIR / f"proof_2.json"
proof_file_3 = FILE_DIR / f"proof_3.json"
proof_file_4 = FILE_DIR / f"proof_4.json"
proof_file_5 = FILE_DIR / f"proof_5.json"
secret_file_1 = FILE_DIR / f"secret_1.json"
secret_file_2 = FILE_DIR / f"secret_2.json"
secret_file_3 = FILE_DIR / f"secret_3.json"
secret_file_4 = FILE_DIR / f"secret_4.json"
secret_file_5 = FILE_DIR / f"secret_5.json"
def process_proof_file(proof_file):
    with open(proof_file, "r") as f:
        TLSN_PROOF = f.read()
        tlsn_proof = json.loads(TLSN_PROOF)
        private_openings = tlsn_proof["substrings"]["private_openings"]
        if len(private_openings) != 1:
            raise Exception(f"Expected 1 private opening, got {len(private_openings)}")
        commitment_index, openings = list(private_openings.items())[0]
        commitment_info, commitment = openings
        data_commitment_hash = bytes(commitment["hash"]).hex()
    return (TLSN_PROOF, data_commitment_hash)

def process_secret_file(secret_file):
    with open(secret_file, "r") as f_secret:
        secret_data = json.load(f_secret)
        value = float(secret_data["eth_free"])
        nonce = bytes(secret_data["nonce"]).hex()
    return (secret_data, value, nonce)

TLSN_PROOF_1, data_commitment_hash_1 = process_proof_file(proof_file_1)
TLSN_PROOF_2, data_commitment_hash_2 = process_proof_file(proof_file_2)
TLSN_PROOF_3, data_commitment_hash_3 = process_proof_file(proof_file_3)
TLSN_PROOF_4, data_commitment_hash_4 = process_proof_file(proof_file_4)
TLSN_PROOF_5, data_commitment_hash_5 = process_proof_file(proof_file_5)
secret_data_1, value_1, nonce_1 = process_secret_file(secret_file_1)
secret_data_2, value_2, nonce_2 = process_secret_file(secret_file_2)
secret_data_3, value_3, nonce_3 = process_secret_file(secret_file_3)
secret_data_4, value_4, nonce_4 = process_secret_file(secret_file_4)
secret_data_5, value_5, nonce_5 = process_secret_file(secret_file_5)


PROTOCOL = "http"
COMPUTATION_DB_URL_TEMPLATE = "sqlite:///./party_{party_id}.db"
NUM_PARTIES = 3
# Adjust these ports as needed
COORDINATION_PORT = 5565
DATA_CONSUMER_API_PORT = 5577
FREE_PORTS_START = 8010
FREE_PORTS_END = 8100
COMPUTATION_HOSTS = ["localhost"] * NUM_PARTIES
COMPUTATION_PARTY_PORTS = [COORDINATION_PORT + 1 + party_id for party_id in range(NUM_PARTIES)]
MPSPDZ_PROJECT_ROOT = Path(__file__).parent.parent.parent / "MP-SPDZ"
TLSN_PROJECT_ROOT = Path(__file__).parent.parent.parent / "tlsn"
CERTS_PATH = MPSPDZ_PROJECT_ROOT / "Player-Data"

TIMEOUT_MPC = 60

CMD_PREFIX_COORDINATION_SERVER = ["poetry", "run", "coord-run"]
CMD_PREFIX_GEN_VOUCHERS = ["poetry", "run", "coord-gen-vouchers"]
CMD_PREFIX_LIST_VOUCHERS = ["poetry", "run", "coord-list-vouchers"]
CMD_PREFIX_SHARE_DATA = ["poetry", "run", "client-share-data"]
CMD_PREFIX_QUERY_COMPUTATION = ["poetry", "run", "client-query-computation"]

CMD_PREFIX_COMPUTATION_PARTY_SERVER = ["poetry", "run", "party-run"]
CMD_PREFIX_DATA_CONSUMER_API = ["poetry", "run", "consumer-api-run"]

async def start_coordination_server(cmd: list[str], port: int, tlsn_proofs_dir: Path):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        env={
            **os.environ,
            "NUM_PARTIES": str(NUM_PARTIES),
            "PORT": str(port),
            "PARTY_HOSTS": '["' + '","'.join(COMPUTATION_HOSTS) + '"]',
            "PARTY_PORTS": '["' + '","'.join(map(str, COMPUTATION_PARTY_PORTS)) + '"]',
            "FREE_PORTS_START": str(FREE_PORTS_START),
            "FREE_PORTS_END": str(FREE_PORTS_END),
            "TLSN_PROOFS_DIR": str(tlsn_proofs_dir),
            "PARTY_WEB_PROTOCOL": "http",
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
            "COORDINATION_SERVER_URL": f"{PROTOCOL}://localhost:{COORDINATION_PORT}",
            "PARTY_HOSTS": '["' + '","'.join(COMPUTATION_HOSTS) + '"]',
            "PARTY_PORTS": '["' + '","'.join(map(str, COMPUTATION_PARTY_PORTS)) + '"]',
            "TLSN_PROJECT_ROOT": str(TLSN_PROJECT_ROOT),
            "MPSPDZ_PROJECT_ROOT": str(MPSPDZ_PROJECT_ROOT),
            "PARTY_WEB_PROTOCOL": "http",
        },
        # stdout=asyncio.subprocess.PIPE,
        # stderr=asyncio.subprocess.PIPE
    )
    return process

async def start_data_consumer_api_server(cmd: list[str], port: int):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        env={
            **os.environ,
            "PORT": str(port),
            "COORDINATION_SERVER_URL": f"{PROTOCOL}://localhost:{COORDINATION_PORT}",
            "TLSN_PROJECT_ROOT": str(TLSN_PROJECT_ROOT),
            "PARTY_HOSTS": '["' + '","'.join(COMPUTATION_HOSTS) + '"]',
            "PARTY_PORTS": '["' + '","'.join(map(str, COMPUTATION_PARTY_PORTS)) + '"]',
            "PARTY_WEB_PROTOCOL": "http",
        },
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

    for party_id in range(NUM_PARTIES):
        party_db_path = COMPUTATION_DB_URL_TEMPLATE.format(party_id=party_id).split(":///")[1]
        if os.path.exists(party_db_path):
            os.remove(party_db_path)

    start_tasks = [
        start_coordination_server(CMD_PREFIX_COORDINATION_SERVER, COORDINATION_PORT, tlsn_proofs_dir),
    ] + [
        start_computation_party_server(CMD_PREFIX_COMPUTATION_PARTY_SERVER, party_id, port)
        for party_id, port in enumerate(COMPUTATION_PARTY_PORTS)
    ] + [
        start_data_consumer_api_server(CMD_PREFIX_DATA_CONSUMER_API, DATA_CONSUMER_API_PORT)
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


async def gen_vouchers(num_vouchers: int):
    process = await asyncio.create_subprocess_exec(*CMD_PREFIX_GEN_VOUCHERS, str(num_vouchers))
    await process.wait()
    assert process.returncode == 0


async def get_vouchers():
    process = await asyncio.create_subprocess_exec(
        *CMD_PREFIX_LIST_VOUCHERS,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0

    # parse with csv
    reader = csv.reader(stdout.decode().splitlines())
    # [['id', 'voucher_code', 'is_used'], ['1', 'PEF2tZ5gqX4UkC6XwJ5LuA', 'False'], ['2', 'gOAn9Wvo7pydmTZlJibAAQ', 'False']]
    vouchers_rows = list(reader)
    without_header = vouchers_rows[1:]
    return [
        (row[1], row[2] == "True")
        for row in without_header
    ]


async def share_data_cli(voucher_code: str, api_key: str, api_secret: str):
    process = await asyncio.create_subprocess_exec(
        *CMD_PREFIX_SHARE_DATA,
        voucher_code,
        api_key,
        api_secret,
        env={
            **os.environ,
            "COORDINATION_SERVER_URL": f"{PROTOCOL}://localhost:{COORDINATION_PORT}",
            "PARTY_HOSTS": '["' + '","'.join(COMPUTATION_HOSTS) + '"]',
            "PARTY_PORTS": '["' + '","'.join(map(str, COMPUTATION_PARTY_PORTS)) + '"]',
        },
    )
    await process.wait()
    assert process.returncode == 0, f"Error running share_data_cli: process.returncode={process.returncode}"


async def query_computation_cli():
    process = await asyncio.create_subprocess_exec(
        *CMD_PREFIX_QUERY_COMPUTATION,
        str(0),
        env={
            **os.environ,
            "COORDINATION_SERVER_URL": f"{PROTOCOL}://localhost:{COORDINATION_PORT}",
            "PARTY_HOSTS": '["' + '","'.join(COMPUTATION_HOSTS) + '"]',
            "PARTY_PORTS": '["' + '","'.join(map(str, COMPUTATION_PARTY_PORTS)) + '"]',
        },
    )
    await process.wait()
    assert process.returncode == 0, f"Error running query_computation_cli: process.returncode={process.returncode}"


@pytest.mark.asyncio
async def test_basic_integration(servers, tlsn_proofs_dir: Path, tmp_path: Path):
    # Clean up the existing shares
    for party_id in range(NUM_PARTIES):
        (MPSPDZ_PROJECT_ROOT / "Persistence" /f"Transactions-P{party_id}.data").unlink(missing_ok=True)

    await fetch_parties_certs(PROTOCOL, CERTS_PATH, COMPUTATION_HOSTS, COMPUTATION_PARTY_PORTS)

    # Gen vouchers
    num_vouchers = 5
    await gen_vouchers(num_vouchers)

    # List vouchers
    vouchers = await get_vouchers()
    assert len(vouchers) == num_vouchers

    voucher_1, voucher_2, voucher_3, voucher_4, voucher_5 = [voucher for voucher, _ in vouchers]

    coordination_server_url = f"{PROTOCOL}://localhost:{COORDINATION_PORT}"

    # Add user to queue and get position to get the computation key
    await add_user_to_queue(coordination_server_url, voucher_1, 1)
    computation_key_1 = await poll_queue_until_ready(coordination_server_url, voucher_1, 1)
    await share_data(
        CERTS_PATH,
        coordination_server_url,
        COMPUTATION_HOSTS,
        voucher_1,
        TLSN_PROOF_5,
        value_5,
        nonce_5,
        computation_key_1,
    )

    # Get the vouchers again, voucher 1 should be used
    vouchers_after_sharing = await get_vouchers()
    voucher_1_after_sharing, is_used_1_after_sharing = vouchers_after_sharing[0]
    assert voucher_1_after_sharing == voucher_1, "Voucher 1 should not change"
    assert is_used_1_after_sharing, "Voucher 1 should be used"

    # get the computation key again
    access_key_3 = secrets.token_urlsafe(16)
    await add_user_to_queue(coordination_server_url, access_key_3, 1)
    computation_key_3 = await poll_queue_until_ready(coordination_server_url, access_key_3, 1)

    # Query computation concurrently
    num_queries = 1
    # computation_index = 1
    res_queries = await asyncio.gather(*[
        query_computation(
            CERTS_PATH,
            coordination_server_url,
            COMPUTATION_HOSTS,
            access_key_3,
            computation_key_3,
        ) for _ in range(num_queries)
        # query_computation_cli()
    ])

    assert len(res_queries) == num_queries
    results_0 = res_queries[0]

    # Query data consumer api
    data_consumer_api_url = f"{PROTOCOL}://localhost:{DATA_CONSUMER_API_PORT}"
    async def query_data_consumer_api():
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{data_consumer_api_url}/query-computation",
                json={},
            ) as resp:
                return await resp.json()

    res_data_consumer_api = await query_data_consumer_api()
    results_api = res_data_consumer_api["results"]
    assert results_api == list(map(float, results_0)), f"result mismatch from api and from computation party: {results_0=}, {results_api=}"

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
