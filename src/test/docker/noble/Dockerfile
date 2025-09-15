FROM fluxrm/flux-sched:noble

ARG USER=fluxuser
ARG UID=1000
ARG KUBECTL_VERSION=latest
ARG SHS_CXI_DRIVER_BRANCH=release/shs-13.0
ARG SHS_LIBCXI_BRANCH=release/shs-13.0

ENV SHS_CXI_DRIVER_BRANCH=${SHS_CXI_DRIVER_BRANCH}
ENV SHS_LIBCXI_BRANCH=${SHS_LIBCXI_BRANCH}

# Copy scripts into image
COPY scripts/ /scripts

RUN \
 if test "$USER" != "fluxuser"; then  \
      sudo groupadd -g $UID $USER \
   && sudo useradd -g $USER -u $UID -d /home/$USER -m $USER \
   && sudo sh -c "printf \"$USER ALL= NOPASSWD: ALL\\n\" >> /etc/sudoers" \
   && sudo adduser $USER sudo ; \
 fi

RUN sudo apt-get update \
    && sudo apt install -y python3-pip curl python3-kubernetes

RUN sudo /scripts/kubectl.sh \
  && echo "source /scripts/sync-kube-config.sh" | sudo tee -a /etc/bash.bashrc \
  && sudo chmod 755 /etc/bash.bashrc

# Install libcxi prereqs
RUN sudo /scripts/install-libcxi-deps-deb.sh \
  && sudo apt clean \
  && sudo rm -rf /var/lib/apt/lists*

# Build/install libcxi
RUN cd /tmp \
  && /scripts/build-libcxi.sh \
  && sudo /scripts/install-libcxi.sh \
  && rm -rf shs-libcxi \
  && rm -rf shs-cxi-driver \
  && rm -rf shs-cassini-headers \
  && rm -rf cassini-headers

USER $USER
WORKDIR /home/$USER
