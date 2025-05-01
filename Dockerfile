# 使用带有Python和FFmpeg的基础镜像
FROM python:3.9-slim-bullseye

# 设置工作目录
WORKDIR /app

# 安装系统依赖和Python依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
    requests>=2.31.0 \
    tqdm>=4.66.1 \
    urllib3>=2.1.0 \
    APScheduler==3.10.1

# 复制应用代码
COPY bili_downloader.py scheduler.py ./

# 创建必要的目录
RUN mkdir -p \
    /app/downloads \
    /app/config \
    /app/temp \
    && chmod -R 755 /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    AUTO_DOWNLOAD=true \
    INTERVAL_HOURS=6 \
    REQUEST_INTERVAL=3 \
    MAX_RETRIES=3 \
    RETRY_412_MAX=3 \
    RETRY_412_DELAY=120

# 设置卷
VOLUME ["/app/downloads", "/app/config"]

# 设置非root用户
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# 启动命令
CMD ["sh", "-c", \
    "if [ \"$AUTO_DOWNLOAD\" = \"true\" ]; then \
        python scheduler.py; \
    else \
        python bili_downloader.py; \
    fi"]