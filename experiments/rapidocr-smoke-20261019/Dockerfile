FROM frontier-ocr-smoke:20261019-5db5
RUN python -m venv /opt/rapid && /opt/rapid/bin/pip install --no-cache-dir rapidocr==3.10.0 onnxruntime==1.31.0 psutil==7.2.2 pymupdf==1.28.2 pypdf==6.21.1 pillow==13.0.0
ENV HOME=/tmp OMP_THREAD_LIMIT=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /lab
