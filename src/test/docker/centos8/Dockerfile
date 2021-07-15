FROM fluxrm/flux-sched:centos8

ARG USER=fluxuser
ARG UID=1000

RUN \
 if test "$USER" != "fluxuser"; then  \
      sudo groupadd -g $UID $USER \
   && sudo useradd -g $USER -u $UID -d /home/$USER -m $USER \
   && sudo sh -c "printf \"$USER ALL= NOPASSWD: ALL\\n\" >> /etc/sudoers" \
   && sudo usermod -G wheel $USER; \
 fi

RUN sudo yum install -y python3-pip \
    && sudo pip3 install kubernetes


USER $USER
WORKDIR /home/$USER
