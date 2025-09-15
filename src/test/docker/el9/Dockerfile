FROM fluxrm/flux-sched:el9

ARG USER=fluxuser
ARG UID=1000

# Copy scripts into image
COPY scripts/ /scripts

RUN \
 if test "$USER" != "fluxuser"; then  \
      sudo groupadd -g $UID $USER \
   && sudo useradd -g $USER -u $UID -d /home/$USER -m $USER \
   && sudo sh -c "printf \"$USER ALL= NOPASSWD: ALL\\n\" >> /etc/sudoers" \
   && sudo usermod -G wheel $USER; \
 fi

RUN sudo pip3 install kubernetes

RUN sudo /scripts/kubectl.sh \
  && echo "source /scripts/sync-kube-config.sh" | sudo tee -a /etc/profile.d/99-sync-kube-config.sh \
  && sudo chmod 755 /etc/profile.d/99-sync-kube-config.sh

USER $USER
WORKDIR /home/$USER
