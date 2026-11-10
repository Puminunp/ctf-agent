# Solver sandbox: unprivileged user, no sudo, no Docker client, common CTF tooling.
# Build:  docker build -t ctf-solver:latest docker/solver
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev build-essential \
        file binutils xxd netcat-openbsd curl ca-certificates \
        unzip zip p7zip-full bsdmainutils libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
        pycryptodome sympy z3-solver requests beautifulsoup4 numpy pillow gmpy2 pwntools

# uid 1000, no sudo, no password. /workspace is where the controller puts the contestant files.
RUN useradd -m -u 1000 -s /bin/bash solver \
    && mkdir /workspace && chown solver:solver /workspace
USER solver
WORKDIR /workspace
CMD ["sleep", "infinity"]
