FROM ghcr.io/hassio-addons/base:21.0.0

COPY rootfs /

# Windows/Samba shares don't preserve the exec bit or LF endings
RUN sed -i 's/\r$//' /etc/s6-overlay/s6-rc.d/leapcard/run \
    && chmod +x /etc/s6-overlay/s6-rc.d/leapcard/run

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY leapcard_client.py main.py ./