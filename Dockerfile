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
    requests \
    apscheduler \
    tqdm \
    python-dotenv

# 创建必要的目录结构（不再持久化temp目录）
RUN mkdir -p \
    /app/downloads \
    /app/config \
    /app/temp  # 临时目录仅在容器内部使用

# 设置卷映射（仅保留需要持久化的目录）
VOLUME ["/app/downloads", "/app/config"]

# 设置默认环境变量
ENV AUTO_DOWNLOAD=true
ENV INTERVAL_HOURS=6

# 启动命令（根据环境变量选择模式）
CMD ["sh", "-c", \
    "if [ \"$AUTO_DOWNLOAD\" = \"true\" ]; then \
        python scheduler.py; \
    else \
        python bili_downloader.py; \
    fi"]