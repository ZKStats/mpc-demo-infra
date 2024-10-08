import asyncio
import time
import threading
import tempfile
from pathlib import Path
from dataclasses import dataclass
import logging
from threading import Lock, Event

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from .schemas import (
    NegotiateShareDataRequest, NegotiateShareDataResponse,
    RegisterDataProviderRequest, RegisterDataProviderResponse,
    VerifyRegistrationRequest, VerifyRegistrationResponse,
    MPCStatus, CheckShareDataStatusResponse,
    SetShareDataCompleteRequest,
    RequestSharingDataRequest, RequestSharingDataResponse,
)
from .database import DataProvider, Voucher, get_db
from .config import settings

router = APIRouter()

#
# Public APIs
#

@router.post("/register", response_model=RegisterDataProviderResponse)
def register(request: RegisterDataProviderRequest, db: Session = Depends(get_db)):
    logger.info(f"Attempting to register provider with identity: {request.identity}")
    # Check if voucher is valid
    voucher: Voucher | None = db.query(Voucher).filter(Voucher.code == request.voucher_code).first()
    if not voucher:
        raise HTTPException(status_code=400, detail="Invalid voucher code")
    if voucher.data_provider:
        raise HTTPException(status_code=400, detail="Voucher already used")

    # Check if identity has existed, raise error
    if db.query(DataProvider).filter(DataProvider.identity == request.identity).first():
        raise HTTPException(status_code=400, detail="Identity already exists")

    # Create a new data provider and associate it with the voucher
    new_provider = DataProvider(voucher=voucher, identity=request.identity)
    db.add(new_provider)
    db.commit()
    db.refresh(new_provider)
    logger.info(f"Successfully registered provider with id: {new_provider.id}")
    return {"provider_id": new_provider.id}


@router.post("/verify_registration", response_model=VerifyRegistrationResponse)
def verify_registration(request: VerifyRegistrationRequest, db: Session = Depends(get_db)):
    logger.info(f"Verifying registration for identity: {request.identity}")
    # Check if identity has not registered, raise error
    data_provider: DataProvider | None = db.query(DataProvider).filter(DataProvider.identity == request.identity).first()
    if not data_provider:
        raise HTTPException(status_code=400, detail="Identity not registered")

    # TODO: more checks
    logger.info(f"Registration verified for identity: {request.identity}")
    return {"client_id": data_provider.id}


#
# Party Server APIs: callable by parties
#

@dataclass(frozen=True)
class Session:
    identity: str
    time: int

# Global lock and session tracking
global_lock = Lock()
indicated_joining_mpc: dict[int, Session] = {}
indicated_mpc_complete: dict[int, Session] = {}
sharing_data_lock = asyncio.Lock()



# async def long_running_task(param: str):
#     # This is an async function that will run in the background
#     await asyncio.sleep(2)  # Simulating a long-running operation
#     print(f"Completed async task with param: {param}")

# @router.post("/start-task")
# async def start_task(background_tasks: BackgroundTasks):
#     # Add the async task to background tasks
#     # background_tasks.add_task(long_running_task, "some_param")
#     asyncio.create_task(long_running_task("some_param"))
#     return {"message": "Async task started"}

def long_running_task(param: str):
    # This function will run in a separate thread
    time.sleep(2)  # Simulating a long-running operation
    print(f"Completed threaded task with param: {param}")

@router.post("/start-task")
def start_task():
    # Start the task in a new thread
    thread = threading.Thread(target=long_running_task, args=("some_param",))
    thread.start()
    return {"message": "Threaded task started"}


@router.post("/share_data", response_model=RequestSharingDataResponse)
async def share_data(request: RequestSharingDataRequest, db: Session = Depends(get_db)):
    print(f"!@# share_data: {settings.party_ips=}, {type(settings.party_ips)=}")
    logger.info(f"Acquiring lock for sharing data for {request.identity=}")
    await sharing_data_lock.acquire()

    try:
        logger.info(f"Acquired lock for sharing data for {request.identity=}")
        identity = request.identity
        tlsn_proof = request.tlsn_proof

        logger.info(f"Verifying registration for identity: {request.identity}")
        # Check if identity has not registered, raise error
        data_provider: DataProvider | None = db.query(DataProvider).filter(DataProvider.identity == request.identity).first()
        if not data_provider:
            raise HTTPException(status_code=400, detail="Identity not registered")
        logger.info(f"Registration verified for identity: {request.identity}")
        client_id = data_provider.id

        # with tempfile.NamedTemporaryFile() as temp_file:
        #     # Store TLSN proof in temporary file.
        #     temp_file.write(request.tlsn_proof.encode('utf-8'))

        #     # Run TLSN proof verifier
        #     try:
        #         process = await asyncio.create_subprocess_shell(
        #             f"cd {str(TLSN_VERIFIER_PATH)} && {CMD_VERIFYTLSN_PROOF} {temp_file.name}",
        #             stdout=asyncio.subprocess.PIPE,
        #             stderr=asyncio.subprocess.PIPE
        #         )
        #         stdout, stderr = await process.communicate()
        #         if process.returncode != 0:
        #             raise asyncio.subprocess.CalledProcessError(process.returncode, process.args, stdout, stderr)
        #     except asyncio.subprocess.CalledProcessError as e:
        #         logger.error(f"Failed to verify TLSN proof: {str(e)}")
        #         raise HTTPException(status_code=400, detail="Failed when verifying TLSN proof")

        #     # Proof is valid, copy to tlsn_proofs_dir and delete the temp file.
        #     tlsn_proofs_dir = Path(settings.tlsn_proofs_dir)
        #     tlsn_proofs_dir.mkdir(parents=True, exist_ok=True)
        #     tlsn_proof_path = tlsn_proofs_dir / f"proof_{client_id}.json"
        #     tlsn_proof_path.write_text(request.tlsn_proof)

        # Request computation parties servers to run MPC
        mpc_ports = [settings.mpc_port_base + party_id for party_id in range(settings.num_parties)]
        l = asyncio.Event()
        async def request_sharing_data_all_parties():
            try:
                logger.info(f"Requesting sharing data MPC for {identity=}")
                async with aiohttp.ClientSession() as session:
                    tasks = []
                    for party_ip in settings.party_ips:
                        url = f"http://{party_ip}/request_sharing_data_mpc"
                        task = session.post(url, json={"client_id": client_id, "mpc_ports": mpc_ports, "tlsn_proof": tlsn_proof})
                        tasks.append(task)
                    l.set()
                    responses = await asyncio.gather(*tasks)
                logger.info(f"Received responses for sharing data MPC for {identity=}")
                for party_id, response in enumerate(responses):
                    if response.status != 200:
                        logger.error(f"Failed to request sharing data MPC from {party_id}: {response.status}")
                        raise HTTPException(status_code=400, detail="Failed to request sharing data MPC from all parties")
            finally:
                sharing_data_lock.release()
        asyncio.create_task(request_sharing_data_all_parties())
        # Wait until `gather` called
        await l.wait()
        # Return ports for computation parties servers to run MPC so that user can run client to connect
        return RequestSharingDataResponse(mpc_ports=mpc_ports)
    except Exception as e:
        logger.error(f"Failed to share data: {str(e)}")
        sharing_data_lock.release()
        raise HTTPException(status_code=400, detail="Failed to share data")



@router.post("/negotiate_share_data", response_model=NegotiateShareDataResponse)
def negotiate_share_data(request: NegotiateShareDataRequest, db: Session = Depends(get_db)):
    party_id = request.party_id
    identity = request.identity
    logger.info(f"Negotiating share data for {party_id=} from {identity=}")

    with global_lock:
        state = get_current_state()
        if state == MPCStatus.MPC_IN_PROGRESS:
            logger.error(f"Cannot negotiate share data: MPC is in progress. Current state: {state}")
            raise HTTPException(status_code=400, detail="Cannot negotiate share data: MPC is in progress")
        if party_id in indicated_joining_mpc:
            logger.error(f"Party {party_id} already waiting for MPC")
            raise HTTPException(status_code=400, detail="Party already waiting")
        # Check if every party is running for the same identity
        if any(indicated_joining_mpc[id].identity != identity for id in indicated_joining_mpc):
            logger.error(f"Party {party_id} is running for different identity")
            raise HTTPException(status_code=400, detail="Party is running for different identity")
        # Add the party to the indicated joining MPC for the given identity
        indicated_joining_mpc[party_id] = Session(identity=identity, time=time.time())
        logger.info(f"Party {party_id} joined MPC. Total parties: {len(indicated_joining_mpc)}")
        current_state = get_current_state()
        if current_state == MPCStatus.MPC_IN_PROGRESS:
            logger.info("All parties joined. MPC is now in progress.")
        elif current_state == MPCStatus.WAITING_FOR_ALL_PARTIES:
            logger.info(f"Waiting for more parties. Current count: {len(indicated_joining_mpc)}, required: {settings.num_parties}")
        else:
            raise HTTPException(status_code=400, detail=f"Invalid state: {current_state}")
        # Every party should have different ports, just for convenience
        ports = [settings.mpc_port_base + party_id for party_id in range(settings.num_parties)]
        return NegotiateShareDataResponse(
            ports=ports,
            status=current_state.value,
        )


@router.post("/set_share_data_complete", status_code=status.HTTP_204_NO_CONTENT)
def set_share_data_complete(request: SetShareDataCompleteRequest):
    party_id = request.party_id
    identity = request.identity
    logger.info(f"Setting share data complete for {party_id=}")
    with global_lock:
        state = get_current_state()
        if state != MPCStatus.MPC_IN_PROGRESS:
            logger.error(f"Cannot set share data complete: MPC is not in progress. Current state: {state}")
            raise HTTPException(status_code=400, detail="Cannot set share data complete: MPC is not in progress")
        if party_id not in indicated_joining_mpc:
            logger.error(f"Party {party_id} not waiting in MPC")
            raise HTTPException(status_code=400, detail="Party not waiting")
        # Check if every party is running for the same identity
        if any(indicated_mpc_complete[id].identity != identity for id in indicated_mpc_complete):
            logger.error(f"Party {party_id} is running for different identity")
            raise HTTPException(status_code=400, detail="Party is running for different identity")
        indicated_mpc_complete[party_id] = Session(identity=identity, time=time.time())
        logger.info(f"Party {party_id} completed MPC. Total completed: {len(indicated_mpc_complete)}")
        if len(indicated_mpc_complete) == settings.num_parties:
            logger.info("All parties completed MPC. Cleaning up states.")
            cleanup_states()


@router.get("/check_share_data_status", response_model=CheckShareDataStatusResponse)
def check_share_data_status():
    logger.info("Checking share data status")
    with global_lock:
        state = get_current_state()
    logger.info(f"Current share data status: {state}")
    return {"status": state.value}


#
# Admin APIs: callable by admin
#

@router.post("/cleanup_sessions", status_code=status.HTTP_204_NO_CONTENT)
def cleanup_sessions():
    logger.info("Cleaning up stale sessions")
    with global_lock:
        cleanup_states()
    logger.info("Stale sessions cleaned up")



def get_current_state() -> MPCStatus:
    # no lock is acquired here, the caller should acquire the lock
    num_parties_indicated_joining = len(indicated_joining_mpc)
    num_parties_indicated_complete = len(indicated_mpc_complete)
    logger.debug(f"Current state: Parties joined: {num_parties_indicated_joining}, Parties completed: {num_parties_indicated_complete}")

    # initial: both num_parties_indicated_complete and num_parties_indicated_joining are 0
    # waiting for all parties: num_parties_indicated_joining == settings.num_parties, num_parties_indicated_complete == 0
    # mpc in progress: num_parties_indicated_joining == settings.num_parties
    if num_parties_indicated_joining == 0:
        if num_parties_indicated_complete != 0:
            raise HTTPException(status_code=400, detail="Invalid state: should be no one indicating complete when no one has joined")
        return MPCStatus.INITIAL
    elif num_parties_indicated_joining < settings.num_parties:
        if num_parties_indicated_complete > 0:
            raise HTTPException(status_code=400, detail="Invalid state: should be no one indicating complete when not all parties have joined")
        return MPCStatus.WAITING_FOR_ALL_PARTIES
    elif num_parties_indicated_joining == settings.num_parties:
        return MPCStatus.MPC_IN_PROGRESS
    else:
        raise HTTPException(status_code=400, detail=f"Invalid state: num_parties_indicated_joining = {num_parties_indicated_joining}, num_parties_indicated_complete = {num_parties_indicated_complete}")


def cleanup_states():
    logger.info("Cleaning up MPC states")
    indicated_joining_mpc.clear()
    indicated_mpc_complete.clear()
    logger.info("MPC states cleaned up")
