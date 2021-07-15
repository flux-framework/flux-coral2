FROM fluxrm/flux-sched:focal

ARG USER=fluxuser
ARG UID=1000

RUN \
 if test "$USER" != "fluxuser"; then  \
      sudo groupadd -g $UID $USER \
   && sudo useradd -g $USER -u $UID -d /home/$USER -m $USER \
   && sudo sh -c "printf \"$USER ALL= NOPASSWD: ALL\\n\" >> /etc/sudoers" \
   && sudo adduser $USER sudo ; \
 fi

RUN sudo apt-get update \
    && sudo apt-get install -y python3-pip \
    && sudo pip install kubernetes

USER $USER
WORKDIR /home/$USER
