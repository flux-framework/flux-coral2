FROM fluxrm/flux-sched:noble

ARG USER=fluxuser
ARG UID=1000
ARG KUBECTL_VERSION=latest

RUN \
 if test "$USER" != "fluxuser"; then  \
      sudo groupadd -g $UID $USER \
   && sudo useradd -g $USER -u $UID -d /home/$USER -m $USER \
   && sudo sh -c "printf \"$USER ALL= NOPASSWD: ALL\\n\" >> /etc/sudoers" \
   && sudo adduser $USER sudo ; \
 fi

RUN sudo apt-get update \
    && sudo apt install -y python3-pip curl python3-kubernetes

COPY ./kubectl.sh ./sync-kube-config.sh /usr/local/share/
RUN sudo chmod 755 /usr/local/share/kubectl.sh \
  && sudo chmod 755 /usr/local/share/sync-kube-config.sh \
  && sudo /usr/local/share/kubectl.sh \
  && echo "source /usr/local/share/sync-kube-config.sh" | sudo tee -a /etc/bash.bashrc \
  && sudo chmod 755 /etc/bash.bashrc


USER $USER
WORKDIR /home/$USER
