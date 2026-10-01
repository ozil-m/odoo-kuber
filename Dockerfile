FROM odoo:18.0

USER root

# Install additional system packages if your custom modules need them
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        gcc \
        python3-dev \
        libldap2-dev \
        libsasl2-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements for custom modules
COPY requirements.txt /tmp/requirements.txt

RUN pip3 install --no-cache-dir --break-system-packages \
    -r /tmp/requirements.txt

# Copy custom Odoo modules
COPY --chown=odoo:odoo custom-addons/ /mnt/extra-addons/

# Copy Odoo configuration
COPY --chown=odoo:odoo config/odoo.conf /etc/odoo/odoo.conf

USER odoo
