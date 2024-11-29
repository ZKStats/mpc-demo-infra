#!/bin/bash

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <eth-address> <binance-api-key> <binance-api-secret>"
    exit 1
fi

export github_artifacts_url=https://api.github.com/repos/ZKStats/tlsn/actions/artifacts

# check if required environment variables are set
if [ -z "$github_access_token" ]; then
    echo 'github_access_token environment variable is required'
    exit 1
fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ "$(uname -m)" == "x86_64" ]]; then
        export binary_suffix=macos_sonoma
    elif [[ "$(uname -m)" == "arm64" ]]; then
        export binary_suffix=macos_sonoma_arm64
    else
        echo "Unsupported architecture: $OSTYPE"
        exit 1
    fi
    
    if ! command -v brew &> /dev/null; then
        echo "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    for cmd in jq curl unzip python3; do
        if ! command -v $cmd &> /dev/null; then
            echo "Installing $cmd..."
            brew install $cmd
        fi
    done

elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if command -v lsb_release &> /dev/null; then
        version=$(lsb_release -rs)
    elif [[ -f /etc/os-release ]]; then
        version=$(grep "^VERSION_ID=" /etc/os-release | cut -d'"' -f2)
    else
        echo "Failed to determine Ubuntu version."
        exit 1
    fi

    if [[ "$version" == "24.04" ]]; then
        export binary_suffix=ubuntu_noble
    else
        echo "Unsupported Ubuntu version: $ubuntu_version"
        exit 1
    fi

    for cmd in curl jq unzip python3; do
        if ! command -v $cmd &> /dev/null; then
            echo "Installing $cmd..."
            sudo apt-get install -y $cmd || {
                echo "Failed to install $cmd. Try running: sudo apt-get update";
                exit 1;
            }
        fi
    done
fi

binary_url=$(curl -sL \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $github_access_token" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  $github_artifacts_url \
  | jq -r '.artifacts[] | select(.name == ("binance_prover_" + env.binary_suffix)) | .archive_download_url' | head -n1)

echo "Downloading binance_prover from $binary_url..."
curl -L \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $github_access_token" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -o binance_prover.zip \
  $binary_url

unzip -o -q binance_prover.zip
rm -f binance_prover.zip

binary_dir=../../../../tlsn/tlsn/target/release/examples
mkdir -p $binanry_dir

mv binance_prover_* $binary_dir/binance_prover
echo "copied binance_prover to $binary_dir"

echo 'Install poetry...'
VENV_PATH=./mpc-demo-venv
mkdir -p $VENV_PATH

python3 -m venv $VENV_PATH
source $VENV_PATH/bin/activate

$VENV_PATH/bin/pip install -U pip setuptools
$VENV_PATH/bin/pip install poetry

# move to repository root and run client-share-data
cd ../../..
poetry install
poetry run client-share-data $1 $2 $3

