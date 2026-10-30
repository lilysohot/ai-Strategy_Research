FROM frontier-rapidocr-expanded:20261030-5db5@sha256:7b9dce41dbd71a8a1b5a5e1b269075004def90965f02468223b203df7f3f8880
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && dpkg-query -W poppler-utils libpoppler147 > /opt/poppler-packages.txt \
    && rm -rf /var/lib/apt/lists/*
