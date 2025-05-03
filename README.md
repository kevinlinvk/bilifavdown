# bilifavdown

bilifavdown 是一个用于下载哔哩哔哩收藏夹内容的工具。支持自动下载、多收藏夹管理、最高画质下载等功能。

## 功能特点

- 支持下载哔哩哔哩收藏夹中的视频
- 自动选择最高画质版本
- 支持HDR视频下载
- 支持多收藏夹管理
- 自动跳过已下载内容
- 支持Docker部署
- 支持定时自动下载
- 智能文件名处理
- 自动重试机制
- 支持412错误处理

## 系统要求

- Python 3.9+
- FFmpeg
- 足够的磁盘空间

## 安装方法

### 1. 直接安装

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/bilifavdown.git
cd bilifavdown
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 安装FFmpeg：
- Windows: 下载 [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) 并添加到系统PATH
- Linux: `sudo apt install ffmpeg` 或 `sudo yum install ffmpeg`
- macOS: `brew install ffmpeg`

### 2. Docker安装

1. 构建Docker镜像：
```bash
docker build -t bilifavdown .
```

2. 运行容器：
```bash
# 自动下载模式
docker run -d \
  --name bilifavdown \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/downloads:/app/downloads \
  -e AUTO_DOWNLOAD=true \
  -e INTERVAL_HOURS=6 \
  bilifavdown

# 手动下载模式
docker run -d \
  --name bilifavdown \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/downloads:/app/downloads \
  -e AUTO_DOWNLOAD=false \
  bilifavdown
```

## 配置说明

在 `config/config.json` 中配置：

```json
{
    "cookies": "你的B站cookies",
    "save_path": "./downloads",
    "auto_download": true,
    "interval_hours": 6,
    "ffmpeg_path": "ffmpeg",
    "request_interval": 3,
    "max_retries": 3,
    "max_title_length": 100,
    "max_filename_length": 255,
    "upname_max_length": 15,
    "folder_history": true,
    "retry_412_max": 3,
    "retry_412_delay": 120,
    "download_hdr": true,
    "target_folders": []
}
```

### 配置项说明

- `cookies`: B站登录cookies（必填）
- `save_path`: 下载保存路径
- `auto_download`: 是否启用自动下载
- `interval_hours`: 自动下载间隔（小时）
- `request_interval`: 请求间隔（秒）
- `max_retries`: 下载失败重试次数
- `max_title_length`: 标题最大长度
- `max_filename_length`: 文件名最大长度
- `upname_max_length`: UP主名称最大长度
- `folder_history`: 是否按收藏夹记录下载历史
- `retry_412_max`: 412错误最大重试次数
- `retry_412_delay`: 412错误重试等待时间（秒）
- `download_hdr`: 是否下载HDR版本
- `target_folders`: 指定要下载的收藏夹ID列表

## 使用方法

### 1. 直接运行

```bash
python bili_downloader.py
```

### 2. Docker运行

```bash
# 自动下载模式
docker run -d \
  --name bilifavdown \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/downloads:/app/downloads \
  -e AUTO_DOWNLOAD=true \
  -e INTERVAL_HOURS=6 \
  bilifavdown

# 手动下载模式
docker run -d \
  --name bilifavdown \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/downloads:/app/downloads \
  -e AUTO_DOWNLOAD=false \
  bilifavdown
```

## 目录结构

```
bilifavdown/
├── bili_downloader.py    # 主程序
├── scheduler.py          # 定时任务
├── requirements.txt      # Python依赖
├── Dockerfile           # Docker配置
├── config/              # 配置目录
│   └── config.json      # 配置文件
└── downloads/           # 下载目录
```

## 注意事项

1. 请确保配置文件中的cookies有效
2. 下载目录需要有足够的磁盘空间
3. 建议适当设置请求间隔，避免被限制
4. 如果使用Docker，确保挂载目录有正确的权限
5. 文件名长度限制为240个字符
6. 建议定期清理临时文件

## 常见问题

1. 无法获取视频信息
   - 检查cookies是否有效
   - 检查网络连接
   - 适当增加请求间隔

2. 下载失败
   - 检查磁盘空间
   - 检查网络连接
   - 查看日志信息
   - 检查文件名长度

3. 视频无法播放
   - 确保FFmpeg正确安装
   - 检查视频文件完整性
   - 检查文件权限

4. 权限问题
   - 确保挂载目录有正确的权限
   - 检查目录所有权
   - 检查文件系统权限

## 更新日志

### v1.4 (2025-05-3)
- 优化文件名生成逻辑，解决文件名过长问题
- 改进错误处理和重试机制
- 添加412错误处理
- 优化Docker配置
- 改进日志记录

### v1.0 (2025-03-13)
- 初始版本发布
- 支持基本下载功能
- 支持Docker部署
- 支持自动下载
- 支持HDR视频下载

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request
