FROM ubuntu:24.04

SHELL ["/bin/bash", "-c"]
ENV PATH="/root/.cargo/bin:/root/.local/bin:${PATH}"
ARG PORT=8006
ENV PORT=${PORT}
ARG PARTY_ID=0
ENV PARTY_ID=${PARTY_ID}
ARG NUM_PARTIES=3
ENV NUM_PARTIES=${NUM_PARTIES}

ENV DOCKERFILE_DIR="./mpc_demo_infra/computation_party_server/docker"

RUN apt-get update && apt-get install -y python3 python3-venv python3-pip curl pipx git automake build-essential clang cmake git libboost-dev libboost-iostreams-dev libboost-thread-dev libgmp-dev libntl-dev libsodium-dev libssl-dev libtool pkg-config libmpfr-dev libmpc-dev libboost-filesystem-dev \
    && apt-get clean \
    && pipx install poetry \
    && pipx ensurepath

WORKDIR /root

# Install mpc-demo-infra
COPY . mpc-demo-infra/
RUN cd mpc-demo-infra && \
    PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring poetry install

# Install rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# Install binance_verifier
COPY tlsn /root/tlsn/
RUN cd tlsn/tlsn \
    && cargo build --release --example binance_verifier

# Install MP-SPDZ and generate party cert files
COPY MP-SPDZ /root/MP-SPDZ/
COPY $DOCKERFILE_DIR/CONFIG.mine /root/MP-SPDZ
RUN cd MP-SPDZ \
    && make -j$(nproc) malicious-rep-ring-party.x

COPY $DOCKERFILE_DIR/.env.party /root/mpc-demo-infra/
COPY $DOCKERFILE_DIR/ssl_certs/ /root/mpc-demo-infra/ssl_certs/

RUN cd /root/MP-SPDZ \
    && ./Scripts/setup-ssl.sh ${NUM_PARTIES}

RUN sed -i "s/^PORT=.*/PORT=${PORT}/" /root/mpc-demo-infra/.env.party \
    && sed -i "s/^PARTY_ID=.*/PARTY_ID=${PARTY_ID}/" /root/mpc-demo-infra/.env.party

ENV LD_LIBRARY_PATH="/root/MP-SPDZ"
WORKDIR /root/mpc-demo-infra
EXPOSE 8000-9000

ENTRYPOINT ["poetry", "run"]
CMD ["party-run"]

