# ETH Inequality @ DevCon 2024

Welcome to the [ETH Inequality Demo @ DevCon 2024](https://demo.mpcstats.org/). Join us in the [Telegram](https://t.me/mpcstats) to stay tuned for more updates!

This guide will help you participate in our survey of ETH distribution across Binance users at DevCon 2024. Don't worry - your data stays private and secure through [MPCStats](https://github.com/ZKStats/mpc-demo-infra) and [TLSNotary](https://tlsnotary.org/). You'll be eligible for an NFT from us and a chance to win $100 only if you complete the [share your balance](#share-your-binance-eth-balance-privately) step successfully.


## How it works
1. Participants prove their ETH balance on Binance using TLSNotary.

![alt text](./pics/prove-balance.png)

2. Participants share their masked balance to computation parties. People can query statistical results from the computation parties.

![alt text](./pics/demo-flow.png)


## Privacy & Security Details
- Your exact balance remains private throughout the whole data sharing process.
- The computing parties **MAY** learn the number of digits of your balance, but not the exact balance
- Security relies on the assumption that our 3 computing parties do not collude
- Your API keys are only used once to fetch your balance and only stay in your laptop.

## Share Your Binance ETH Balance Privately

### Before You Start
You'll need:
- Docker **installed and running** on your computer ([Get Docker here](https://docs.docker.com/get-docker/))
- A Binance account with some ETH holdings

### Step 1: Get Your Binance API Key
1. Log into [Binance.com](https://www.binance.com) and navigate to:
   - Click "Account"
   - Select "API Management"
   - [Direct link to API Management](https://www.binance.com/en/my/settings/api-management)
![alt text](pics/image.png)
![alt text](pics/image-1.png)

2. Create a new API key:
   - Click the yellow "Create API" button
   - Choose "System generated"
   - Enter a name for your API key (can be anything)
   - Complete any required verification steps
![alt text](pics/image-2.png)

3. Important Security Settings:
   - ✅ Make sure ONLY "Enable Reading" is selected
   - ❌ Please leave all other permissions disabled
   - Save both keys somewhere safe:
     - API Key (looks like: "aBc1234...")
     - Secret Key (looks like: "xYz5678...")
![alt text](pics/image-3.png)

🔒 Security Note: Keep your Secret Key private! Our demo only needs read-only access to check your ETH balance, and it's only kept

### Step 2: Run the script

First, make sure Docker is running on your computer!

Open a terminal/command prompt and get the docker image from the docker hub.

```bash
git clone https://github.com/ZKStats/mpc-demo-infra.git
cd mpc-demo-infra/mpc_demo_infra/client_cli/docker
./build.sh
```


Run the script with your details. The ETH address is **the one you want to receive the NFT and the lottery** if you win (**not the one you use for Binance**), so please double check if it's correct. It might take several minutes to run.
```bash
./share-data.sh <eth-address> <binance-api-key> <binance-api-secret>

# Example (DO NOT COPY, USE YOUR OWN VALUES):
# ./share-data.sh 0x123...abc aBc1234... xYz5678...
```

You'll see the following output:

```
Binance ETH balance data has been shared secretly to MPC parties.
```

If it took too much time because of the network to download the images, you can try build it locally instead.
```bash
docker build -t client_cli .
docker run -it client_cli client-share-data <eth-address> <binance-api-key> <binance-api-secret>
```

> ⚠️ **Warning**
> 1. Only 'Free' ETH in your spot account will be counted. This excludes:
>     - ETH in open orders
>     - ETH in locked staking
>     - ETH in savings products
>     - ETH used as collateral
>     - ETH in futures/margin accounts
> 2. If you have exact **0 ETH** it will fail due to the limitation of our implementation. You need to have at least some dust ETH (e.g. 0.00001 ETH) in your spot account.
> 3. We have only two decimals of precision. If you have less than 0.01 ETH, it will be rounded to 0.00 ETH.
> 4.

### Step 3:Query the Results
Visit https://demo.mpcstats.org/. It might take 5~10 minutes for results to be updated.

### Troubleshooting
Common issues:
1. Docker not running → Start Docker Desktop or Docker daemon
2. Script fails
    → Check your API key and secret are copied correctly.
    → Check if your ETH balance on Binance is not 0.
    → If it's timeout, try it again. If it didn't

## Need Help?
- Having trouble? Contact us on [Telegram](https://t.me/mpcstats)
