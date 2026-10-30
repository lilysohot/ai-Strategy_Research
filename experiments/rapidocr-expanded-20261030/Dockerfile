FROM public.ecr.aws/docker/library/python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
COPY requirements.txt /opt/requirements.txt
RUN python -m venv /opt/baseline && /opt/baseline/bin/pip install --no-cache-dir pypdf==6.21.1 \
    && python -m venv /opt/rapid && /opt/rapid/bin/pip install --no-cache-dir -r /opt/requirements.txt
COPY config.py prepare.py /opt/prep/
RUN /opt/rapid/bin/python /opt/prep/prepare.py
ENV HOME=/tmp OMP_THREAD_LIMIT=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /lab
