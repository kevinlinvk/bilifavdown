# 使用带有Python和FFmpeg的基础镜像
FROM python:3.9-slim-bullseye

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制代码文件
COPY bili_downloader.py scheduler.py ./

# 安装Python依赖
RUN pip install --no-cache-dir \
    requests>=2.31.0 \
    tqdm>=4.66.1 \
    urllib3>=2.1.0 \
    APScheduler==3.10.1

# 创建必要的目录结构
RUN mkdir -p \
    /app/downloads \
    /app/config \
    /app/temp \
    && chmod -R 777 /app/downloads \
    && chmod -R 777 /app/config \
    && chmod -R 777 /app/temp

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

# 设置卷映射
VOLUME ["/app/downloads", "/app/config"]

# 启动命令
CMD ["sh", "-c", \
    "if [ \"$AUTO_DOWNLOAD\" = \"true\" ]; then \
        python scheduler.py; \
    else \
        python bili_downloader.py; \
    fi"]