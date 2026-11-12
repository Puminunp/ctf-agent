# Solver sandbox: unprivileged user, no sudo, no Docker client, common CTF tooling.
# Build:  docker build -t ctf-solver:latest docker/solver
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev build-essential \
        file binutils xxd netcat-openbsd curl ca-certificates \
        unzip zip p7zip-full bsdmainutils libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

# Python packages pinned to the versions in the image used for both scored runs (built Nov 10, 2026;
# read with `pip3 list` inside ctf-solver:latest). apt packages follow Ubuntu 22.04 and are not pinned.
RUN pip3 install --no-cache-dir \
        pycryptodome==4.4.0 sympy==1.14.0 z3-solver==5.3.3.0 requests==2.34.2 beautifulsoup4==4.15.0 \
        numpy==2.2.6 pillow==12.3.0 gmpy2==2.3.2 pwntools==4.15.0

# uid 1000, no sudo, no password. /workspace is where the controller puts the contestant files.
RUN useradd -m -u 1000 -s /bin/bash solver \
    && mkdir /workspace && chown solver:solver /workspace
USER solver
WORKDIR /workspace
CMD ["sleep", "infinity"]
