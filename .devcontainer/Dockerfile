# Fork of srl-labs/containerlab .devcontainer/slim.Dockerfile on Debian trixie.
# Omits dclab and vscode/zsh customization; this lab runs as root.
FROM mcr.microsoft.com/devcontainers/python:3.11-trixie

ARG CLAB_VERSION

RUN echo "deb [trusted=yes] https://netdevops.fury.site/apt/ /" | \
    tee -a /etc/apt/sources.list.d/netdevops.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    direnv \
    btop \
    iputils-ping \
    tcpdump \
    iproute2 \
    qemu-kvm \
    dnsutils \
    telnet \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN bash -c "$(curl -sL https://get.containerlab.dev)" -- -v ${CLAB_VERSION}

RUN bash -c 'ARCH=$(uname -m | sed "s/x86_64/amd64/" | sed "s/aarch64/arm64/") && \
    VERSION=$(curl -s https://api.github.com/repos/cli/cli/releases/latest | \
    grep -oP "\"tag_name\": \"\K[^\"]+") && \
    CLEAN_VERSION=${VERSION#v} && \
    DOWNLOAD_URL="https://github.com/cli/cli/releases/download/${VERSION}/gh_${CLEAN_VERSION}_linux_${ARCH}.tar.gz" && \
    curl -L "$DOWNLOAD_URL" | tar xz -C /tmp && \
    mv /tmp/gh_${CLEAN_VERSION}_linux_${ARCH}/bin/gh /usr/local/bin/ && \
    chmod +x /usr/local/bin/gh && \
    rm -rf /tmp/gh_${CLEAN_VERSION}_linux_${ARCH}'

# Inner DinD: skip credential helpers for Docker Hub (avoids macOS Keychain prompts on
# anonymous base-image pulls during make deploy; see docs/devcontainer.md).
RUN mkdir -p /root/.docker && cat > /root/.docker/config.json <<'EOF'
{
  "credHelpers": {
    "https://index.docker.io/v1/": "",
    "docker.io": ""
  }
}
EOF

RUN mkdir -p /etc/sudoers.d && echo 'Defaults env_keep += "SSH_AUTH_SOCK"' > /etc/sudoers.d/ssh_auth_sock

RUN ssh-keygen -t ecdsa -b 256 -N "" -f /root/.ssh/id_ecdsa
