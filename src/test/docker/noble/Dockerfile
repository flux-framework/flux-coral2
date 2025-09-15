FROM fluxrm/flux-sched:noble

ARG USER=fluxuser
ARG UID=1000
ARG KUBECTL_VERSION=latest

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


USER $USER
WORKDIR /home/$USER
