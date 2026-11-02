FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu130
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
ENV CC=/usr/bin/gcc CXX=/usr/bin/g++
COPY requirements-runtime.txt /tmp/requirements-runtime.txt
RUN pip install --no-cache-dir -r /tmp/requirements-runtime.txt
COPY idle_release.py /opt/idle_release.py
WORKDIR /opt/ComfyUI
ENTRYPOINT ["python", "/opt/idle_release.py"]
