FROM docker.m.daocloud.io/library/python:3.10-slim

ENV PYTHONUNBUFFERED=1

# 更换 apt 源以国内加速镜像 (针对 Debian)
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources || true && \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list || true

RUN apt-get update && apt-get install -y \
    gcc \
    alsa-utils \
    libasound2-dev \
    libportaudio2 \
    portaudio19-dev \
    libsndfile1 \
    ffmpeg \
    sox \
    libsox-fmt-all \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# 更换 pip 源加速依赖安装
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY . .

# Default sleep to allow docker-compose to override commands
CMD ["tail", "-f", "/dev/null"]
