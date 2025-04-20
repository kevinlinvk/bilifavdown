# bilifavdown

bilifavdown 是一个用于下载哔哩哔哩收藏夹内容的工具。

## 功能

- 下载哔哩哔哩收藏夹中的视频。
- 支持批量下载。
- 自定义下载路径。

## 安装

1. 克隆此仓库：
    ```bash
    git clone https://github.com/kevin/bilifavdown.git
    ```
2. 安装依赖：
    ```bash
    cd bilifavdown
    pip install -r requirements.txt
    ```

## 使用方法

1. 配置哔哩哔哩账号 Cookies：  
    在项目目录下的 `config` 文件夹中找到 `config.json` 文件，并添加以下内容：  
    ```json
    {
        "cookies": "你的Cookies"
    }
    ```

2. 使用 Docker 构建并运行：  
    如果需要使用 Docker，可以按照以下步骤操作：  
    - 构建 Docker 镜像：  
        ```bash
        docker build -t bilifavdown .
        ```
    - 运行容器并挂载配置文件和下载目录：  
        ```bash
        docker run -v $(pwd)/config:/app/config -v $(pwd)/downloads:/app/downloads bilifavdown
            ```  
              默认情况下，Docker 容器会每 6 小时自动运行一次下载任务。

              请确保 `config` 文件夹中的 `config.json` 文件已正确配置，例如：  
              ```json
              {
                "cookies": "",
                "save_path": "./downloads",
                "auto_download": true,
              }
              ```
这三个是最关键的配置，cookies是用于验证下载，save_path用于配置下载目录，auto_downlanded用于配置是否启用最高画质自动下载,具体其他配置可以参考config文件夹下的文件,如果使用docker部署的话则下载目录默认使用dockerloads就可以了
注意如果您发现有段时间不能下载了那就请更新cookies文件
