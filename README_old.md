# mpc-demo-infra

A demonstration infrastructure for Multi-Party Computation (MPC) using TLSN and MP-SPDZ.

## Table of Contents
- [Dependencies](#dependencies)
- [Getting Started](#getting-started)
  - [Run it locally](#run-it-locally)
- [Configurations](#configurations)
- [Troubleshooting](#troubleshooting)


## DevCon 2024

To participate in our demo [ETH Inequality @ DevCon 2024](https://demo.mpcstats.org/) and win some prizes, please refer to the [README](mpc_demo_infra/client_cli/docker/README.md) for the entire process.

## Dependencies

- python 3
- poetry
- cargo
- [TLSN](https://github.com/ZKStats/tlsn)
  - branch: `mpspdz-compat`
  - clone it as `../tlsn`
- [MP-SPDZ](https://github.com/ZKStats/MP-SPDZ) (only required for computation party server)
  - branch: `demo_client`
  - clone it as `../MP-SPDZ`
  - need to add `MOD = -DGFP_MOD_SZ=5 -DRING_SIZE=257` to `CONFIG.mine`
  - install: `make setup`
  - build vm: `make replicated-ring-party.x`

## Getting Started

### Run it using tests folder

- Here, we already prepopulate corresponding proof and secret file for two input providers from https://github.com/ZKStats/tlsn/tree/mpspdz-compat.

```
poetry run pytest -s tests/test_integration.py
```

### Run it locally

**Note**: This section is for running the MPC demo locally. For cloud deployment, you'll need to adjust network configurations.

The demo consists of three main components:

1. Coordination Server: Coordinates the MPC process.
2. Computation Party Servers: Run by 3 trusted parties and perform the actual MPC computations.
3. Client CLI: Used by data provider to share data and query results.

Install dependencies:

```bash
./setup_env.sh --setup-mpspdz
```

Default ports:
- 8005: coordination server
- 8006~8008: computation party server 0~2
- 8010~8100: ports used by MPC servers during sharing data and querying results

Please make sure these ports are not used by other services.

#### Setup coordination server:

In a terminal, run coordination server:

```bash
poetry run coord-run
```

#### Setup computation party server:

In a terminal, run party 0:

```bash
PORT=8006 PARTY_ID=0 poetry run party-run
```

In another terminal, run party 1:

```bash
PORT=8007 PARTY_ID=1 poetry run party-run
```

In another terminal, run party 2:

```bash
PORT=8008 PARTY_ID=2 poetry run party-run
```

#### Data provider share data with a generated voucher.

```bash
poetry run client-share-data <eth_address> <binance_api_key> <binance_api_secret>
```

#### Query computation result

```bash
poetry run client-query
```

## Configurations

See available configs in
- coordination server: [mpc_demo_infra/coordination_server/config.py](mpc_demo_infra/coordination_server/config.py)
- computation party server: [mpc_demo_infra/computation_party_server/config.py](mpc_demo_infra/computation_party_server/config.py)
- client CLI: [mpc_demo_infra/client_cli/config.py](mpc_demo_infra/client_cli/config.py)

You can use `.env.xxx` to override the default configs.
- `.env.coord`: coordination server. Example in [.env.coord.example](.env.coord.example)
- `.env.party`: computation party server. Example in [.env.party.example](.env.party.example)
- `.env.client_cli`: client CLI. Example in [.env.client_cli.example](.env.client_cli.example)

## Troubleshooting

If you encounter issues:
1. Ensure all dependencies are correctly installed.
2. Check that the required ports (8005-8008, 8010-8100) are not in use.
3. Verify that TLSN and MP-SPDZ are cloned in the correct locations (`../tlsn` and `../MP-SPDZ`).
4. For MP-SPDZ issues, ensure
  - you've added `MOD = -DGFP_MOD_SZ=5` to `CONFIG.mine`.
  - you've generated certificates for computation parties. If not, run `Scripts/setup-ssl.sh` under `../MP-SPDZ`.
  - you've rebuilt the VM. If not, run `make replicated-ring-party.x` under `../MP-SPDZ`.
