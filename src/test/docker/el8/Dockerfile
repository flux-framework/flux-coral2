FROM fluxrm/flux-sched:el8

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

COPY ./kubectl.sh ./sync-kube-config.sh /usr/local/share/
RUN sudo chmod 755 /usr/local/share/kubectl.sh \
  && sudo chmod 755 /usr/local/share/sync-kube-config.sh \
  && sudo /usr/local/share/kubectl.sh \
  && echo "source /usr/local/share/sync-kube-config.sh" | sudo tee -a /etc/profile.d/99-sync-kube-config.sh \
  && sudo chmod 755 /etc/profile.d/99-sync-kube-config.sh

USER $USER
WORKDIR /home/$USER
