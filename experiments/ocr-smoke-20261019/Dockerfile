FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/baseline && /opt/baseline/bin/pip install --no-cache-dir pypdf \
    && python -m venv /opt/candidate \
    && /opt/candidate/bin/pip install --no-cache-dir pymupdf pypdf reportlab pillow psutil
ENV OMP_THREAD_LIMIT=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /lab
# Required for native CJK PDFs; kept separate so the initial experiment is reproducible.
RUN apt-get update && apt-get install -y --no-install-recommends poppler-data \
    && rm -rf /var/lib/apt/lists/*
