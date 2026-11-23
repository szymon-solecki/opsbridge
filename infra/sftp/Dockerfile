FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash \
        ca-certificates \
        openssh-server \
        openssl \
        passwd \
        python3 \
        util-linux \
    && rm -f /etc/ssh/ssh_host_* \
    && rm -rf /var/lib/apt/lists/*

COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /usr/local/sbin/opsbridge-sftp-entrypoint

RUN chmod 0755 /usr/local/sbin/opsbridge-sftp-entrypoint \
    && sed -i 's/\r$//' /etc/ssh/sshd_config /usr/local/sbin/opsbridge-sftp-entrypoint \
    && mkdir -p /run/sshd /etc/ssh/authorized_keys /srv/opsbridge-sftp /var/lib/ssh-host-keys \
    && chmod 0755 /srv/opsbridge-sftp \
    && chmod 0700 /var/lib/ssh-host-keys \
    && chmod 0755 /etc/ssh/authorized_keys

EXPOSE 22
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/sbin/opsbridge-sftp-entrypoint"]
CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"]
