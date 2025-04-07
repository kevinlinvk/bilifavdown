import os
import re
import time
import json
import logging
import requests
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from http.cookies import SimpleCookie, CookieError
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def get_session_with_retries(timeout: int = 60, retries: int = 5) -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.request_timeout = timeout
    return session

# ===================== 配置类 =====================
@dataclass
class Config:
    cookies: str
    save_path: Path = Path("./downloads")
    ffmpeg_path: str = "ffmpeg"
    request_interval: float = 1.5
    max_retries: int = 3
    history_file: Path = Path("./config/download_history.json")
    temp_dir: Path = Path("./temp")
    max_title_length: int = 80
    max_filename_length: int = 240
    upname_max_length: int = 10
    auto_download: bool = False
    interval_hours: int = 6
    folder_history: bool = True  # 是否按收藏夹记录下载历史
    retry_412_max: int = 3  # 默认重试3次
    retry_412_delay: int = 120  # 默认等待120秒

    def __post_init__(self):
        self.save_path = self._resolve_path(self.save_path)
        self.history_file = self._resolve_path(self.history_file)
        self.temp_dir = self._resolve_path(self.temp_dir)
        
        self.save_path.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.history_file.exists():
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2, ensure_ascii=False)

    def _resolve_path(self, path: Path) -> Path:
        """Convert relative path to absolute based on project root"""
        if path.is_absolute():
            return path
        return Path(__file__).parent / path


# ===================== 核心下载器类 =====================
class BilibiliDownloader:
    def __init__(self, config: Config):
        self.config = config
        self.session = get_session_with_retries()
        self._init_session()
        self.logger = self._setup_logger()
        self.downloaded = self._load_download_history()

    def _init_session(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            "Referer": "https://www.bilibili.com",
            "Origin": "https://www.bilibili.com",
            "Cookie": self.config.cookies,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "X-Requested-With": "com.bilibili.app"  # 新增移动端标识
        }
        self.session.headers.update(headers)

    def _setup_logger(self):
        logger = logging.getLogger("BiliDownloader")
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        return logger

    # ------------------- 下载记录管理 -------------------
    def _load_download_history(self) -> Set[Tuple[str, int, int, str]]:
        """加载下载历史记录，添加收藏夹ID"""
        try:
            if self.config.history_file.exists():
                if self.config.history_file.stat().st_size == 0:
                    return set()
                with open(self.config.history_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
                    return {
                        (item["bvid"], item["cid"], item["quality"], item["folder_id"]) 
                        for item in records
                    }
            return set()
        except Exception as e:
            self.logger.error(f"加载历史记录失败: {str(e)}")
            return set()

    def _save_download_entry(self, bvid: str, cid: int, quality: int, title: str, up_name: str, folder_id: str):
        """保存下载记录，添加收藏夹ID"""
        try:
            records = []
            if self.config.history_file.exists():
                with open(self.config.history_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
            records.append({
                "bvid": bvid,
                "cid": cid,
                "quality": quality,
                "title": title,
                "up": up_name,
                "folder_id": folder_id,  # 新增字段
                "timestamp": int(time.time())
            })
            with open(self.config.history_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存记录失败: {str(e)}")
    # ------------------- 收藏夹获取 -------------------
    

    def get_user_folders(self) -> List[Dict]:
        try:
            cookies = SimpleCookie()
            cookies.load(self.config.cookies.strip())
            dede_userid = cookies.get("DedeUserID")
            
            params = {
                "up_mid": dede_userid.value,
                "platform": "web",
                "ts": int(time.time() * 1000)
            }

            created = self._get_paginated_data(
                "https://api.bilibili.com/x/v3/fav/folder/created/list",
                {**params, "type": 1},
                data_key="list"
            )
            
            collected = self._get_paginated_data(
                "https://api.bilibili.com/x/v3/fav/folder/collected/list",
                params,
                data_key="list"
            )
            
            return created + collected
        except Exception as e:
            self.logger.error(f"获取收藏夹失败: {str(e)}")
            return []


    def _get_paginated_data(self, url: str, params: dict = None, data_key: str = "medias") -> List[Dict]:
        results = []
        page = 1
        page_size = 20  # 使用B站API的标准分页大小
        
        while True:
            try:
                # 构造基础参数
                request_params = {
                    "pn": page,
                    "ps": page_size,
                    "platform": "web",
                    "ts": int(time.time() * 1000)
                }
                
                # 合并传入参数
                if params:
                    request_params.update(params)
                
                resp = self.session.get(
                    url,
                    params=request_params,
                    timeout=60
                )
                resp.raise_for_status()
                # data = resp.json()
                
                data = self._request_with_412_retry(url, params=request_params)
                
                if not data or data["code"] != 0:
                    break


                if data["code"] != 0:
                    self.logger.error(f"API错误[{url}]: {data.get('message')}")
                    break
                    
                # 获取数据项
                items = data["data"].get(data_key, [])
                results.extend(items)
                
                # 判断是否还有更多数据
                if len(items) < page_size:
                    break
                    
                page += 1
                time.sleep(self.config.request_interval)
                
            except Exception as e:
                self.logger.error(f"请求失败: {str(e)}")
                break
                
        return results

    # ------------------- 视频处理 -------------------
    def get_video_info(self, bvid: str) -> Optional[Dict]:
        try:
            resp = self.session.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != 0:
                self.logger.error(f"视频信息获取失败: {data.get('message')}")
                return None
            return data["data"]
        except Exception as e:
            self.logger.error(f"请求异常: {str(e)}")
            return None

    def get_available_qualities(self, bvid: str, cid: int) -> Dict[int, str]:
        """
        获取视频可选清晰度列表，支持4K、HDR、8K等
        """
        try:
            resp = self.session.get(
                "https://api.bilibili.com/x/player/playurl",
                params={
                    "bvid": bvid,
                    "cid": cid,
                    "qn": 0,
                    "fnval": 4048,
                    "fourk": 1,
                    "fnver": 0
                },
                timeout=60
            )
            resp.raise_for_status()
            # data = resp.json()

            params = {
                "bvid": bvid,
                "cid": cid,
                "qn": 0,
                "fnval": 4048,
                "fourk": 1,
                "fnver": 0
            }
            data = self._request_with_412_retry(
                "https://api.bilibili.com/x/player/playurl",
                params=params
            )
            
            if not data or data["code"] != 0:
                return {}
            

            if data["code"] != 0:
                self.logger.error(f"清晰度接口错误: {data.get('message')}")
                return {}
            qualities = {}
            for qn, desc in zip(data["data"]["accept_quality"], data["data"]["accept_description"]):
                if ":" in desc:
                    _, desc_part = desc.split(":", 1)
                    qualities[qn] = desc_part.strip()
                else:
                    qualities[qn] = desc.strip()
            return qualities
        except Exception as e:
            self.logger.error(f"清晰度获取失败: {str(e)}")
            return {}

    def _download_media(self, url: str, path: Path) -> bool:
        for retry in range(self.config.max_retries):
            try:
                with self.session.get(url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get("content-length", 0))
                    with open(path, "wb") as f, tqdm(
                        desc=f"下载 {path.name}",
                        total=total_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                    ) as bar:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                return True
            except Exception as e:
                self.logger.warning(f"下载失败（重试 {retry+1}/{self.config.max_retries}）: {str(e)}")
                if path.exists():
                    path.unlink()
                time.sleep(2)
        return False

    def _merge_files(self, video_path: Path, audio_path: Path, output_path: Path) -> bool:
        try:
            subprocess.run(
                [
                    self.config.ffmpeg_path,
                    "-y",
                    "-loglevel", "error",
                    "-i", str(video_path),
                    "-i", str(audio_path),
                    "-c", "copy",
                    str(output_path)
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"合并失败: {e.stderr.decode()}")
            return False
        except Exception as e:
            self.logger.error(f"FFmpeg异常: {str(e)}")
            return False


    def download_video(self, bvid: str, cid: int, quality: int, dest_dir: Path, folder_id: str, suffix: str = "") -> bool:
        try:
            if (bvid, cid, quality, folder_id) in self.downloaded:
                self.logger.info(f"跳过已下载内容: {bvid}-{cid} (收藏夹ID: {folder_id})")
                return True

            video_info = self.get_video_info(bvid)
            if not video_info:
                return False

            page_info = next((p for p in video_info["pages"] if p["cid"] == cid), None)
            if not page_info:
                self.logger.error(f"未找到分P信息: {bvid}-{cid}")
                return False

            # 生成优化后的文件名
            owner = video_info.get("owner", {})
            up_name = owner.get("name", "unknown").strip()
            base_filename = self._generate_filename(video_info, page_info, up_name, suffix)
            output_name = f"{base_filename}.mp4"

            # 处理保存路径和文件名冲突
            if dest_dir is None:
                dest_dir = self.config.save_path
            dest_dir.mkdir(parents=True, exist_ok=True)
            output_path = dest_dir / output_name

            # 处理文件名冲突
            counter = 1
            while output_path.exists():
                output_name = f"{base_filename}_{counter}.mp4"
                output_path = dest_dir / output_name
                counter += 1

            video_url, audio_url = self._get_media_urls(bvid, cid, quality)
            if not video_url or not audio_url:
                return False

            temp_video = self.config.temp_dir / f"{bvid}_{cid}_video.m4s"
            temp_audio = self.config.temp_dir / f"{bvid}_{cid}_audio.m4s"

            success = (
                self._download_media(video_url, temp_video) and
                self._download_media(audio_url, temp_audio) and
                self._merge_files(temp_video, temp_audio, output_path)
            )

            if success:
                self._save_download_entry(bvid, cid, quality, base_filename, up_name, folder_id)
                self.downloaded.add((bvid, cid, quality, folder_id))

            temp_video.unlink(missing_ok=True)
            temp_audio.unlink(missing_ok=True)
            return success
        except Exception as e:
            self.logger.error(f"下载流程异常: {str(e)}")
            return False

    def _get_media_urls(self, bvid: str, cid: int, quality: int) -> Tuple[Optional[str], Optional[str]]:
        """
        获取媒体文件地址，传入支持高画质参数，
        并优先选取 hi-res（id==30251）的音频
        """
        try:
            resp = self.session.get(
                "https://api.bilibili.com/x/player/playurl",
                params={
                    "bvid": bvid,
                    "cid": cid,
                    "qn": quality,
                    "fnval": 4048,
                    "fourk": 1,
                    "fnver": 0
                },
                timeout=60
            )
            resp.raise_for_status()
            # data = resp.json()

            params = {
                "bvid": bvid,
                "cid": cid,
                "qn": quality,
                "fnval": 4048,
                "fourk": 1,
                "fnver": 0
            }
            data = self._request_with_412_retry(
                "https://api.bilibili.com/x/player/playurl",
                params=params
            )
            
            if not data or data["code"] != 0:
                return None, None

            if data["code"] != 0:
                return None, None
            dash = data["data"].get("dash")
            if not dash:
                return None, None
            video_stream = max((v for v in dash["video"] if v["id"] == quality),
                               key=lambda x: x["bandwidth"],
                               default=None)
            hi_res_audio = next((a for a in dash["audio"] if a.get("id") == 30251), None)
            if hi_res_audio is not None:
                audio_stream = hi_res_audio
            else:
                audio_stream = max(dash["audio"], key=lambda x: x["bandwidth"], default=None)
            if video_stream and audio_stream:
                video_url = video_stream.get("baseUrl") or video_stream.get("base_url")
                audio_url = audio_stream.get("baseUrl") or audio_stream.get("base_url")
                return video_url, audio_url
            return None, None
        except Exception as e:
            self.logger.error(f"媒体地址获取失败: {str(e)}")
            return None, None

    def _generate_filename(self, video_info: Dict, page_info: Dict, up_name: str, suffix: str) -> str:
        """
        生成优化后的文件名
        参数:
            video_info: 视频信息字典
            page_info: 分P信息字典
            up_name: UP主名称
            suffix: 特殊后缀（如hdr）
        返回:
            优化后的文件名（不含扩展名）
        """
        # 清理基础标题
        raw_title = video_info["title"]
        base_title = re.sub(
            r'[\\/:*?"<>|【】()\[\]《》\s\U00010000-\U0010ffff]',  # 过滤特殊符号和表情
            " ", 
            raw_title
        ).strip()
        base_title = re.sub(r'\s+', ' ', base_title)[:self.config.max_title_length]

        # 处理分P信息
        page_num = page_info.get("page", 1)
        total_pages = len(video_info.get("pages", []))
        page_part = re.sub(r'[\\/:*?"<>|]', "", page_info['part']).strip()
        
        # 智能分P后缀处理
        page_suffix = ""
        if total_pages > 1:
            if page_part.lower() in raw_title.lower():  # 分P名已包含在标题中
                page_suffix = f"_P{page_num}"
            else:
                page_suffix = f"_{page_part[:20]}"  # 保留有区分度的部分

        # 处理UP主名称
        up_display = ""
        if up_name != "unknown":
            cleaned_up = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', up_name)  # 去除非中英文字符
            up_display = f"-{cleaned_up[:self.config.upname_max_length]}"

        # 组合各部分
        filename = f"{base_title}{page_suffix}{up_display}{suffix}"
        filename = re.sub(r'_{2,}', '_', filename)  # 清理连续下划线
        return filename[:self.config.max_filename_length]
    
    

    def process_folder(self, folder: Dict):
        folder_id = folder["id"]
        folder_title = re.sub(r'[\\/:*?"<>|]', "", folder["title"]).strip() or str(folder_id)
        folder_dir = self.config.save_path / folder_title
        folder_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"开始处理收藏夹: {folder_title} (ID: {folder_id})")
        
        medias = self._get_paginated_data(
            "https://api.bilibili.com/medialist/gateway/base/spaceDetail",
            {
                "media_id": folder_id,
                "platform": "web",
                "ts": int(time.time() * 1000)
            },
            data_key="medias"
        )

        for media in medias:
            bvid = media.get("bvid")
            if not bvid:
                continue
            
            # 传递收藏夹ID到处理流程
            self.process_video(bvid, folder_dir, folder_id)  # 新增第三个参数

    def _select_highest_quality(self, qualities: Dict[int, str]) -> int:
        allowed = {16, 32, 64, 80, 112, 116, 120, 125, 127}
        avail = allowed.intersection(set(qualities.keys()))
        return max(avail) if avail else max(qualities.keys())

    def _find_hdr_quality(self, qualities: Dict[int, str]) -> Optional[int]:
        hdr_candidates = [q for q, desc in qualities.items() if "HDR" in desc or "杜比视界" in desc]
        return max(hdr_candidates) if hdr_candidates else None
    
    def process_video(self, bvid: str, dest_dir: Path, folder_id: str):
        video_info = self.get_video_info(bvid)
        if not video_info:
            return

        for page in video_info.get("pages", []):
            cid = page.get("cid")
            if not cid:
                continue

            qualities = self.get_available_qualities(bvid, cid)
            if not qualities:
                continue

            # 下载主版本
            selected_quality = self._select_highest_quality(qualities)
            if not self._is_downloaded(bvid, cid, selected_quality, folder_id):
                if self.download_video(bvid, cid, selected_quality, dest_dir, folder_id):
                    self.logger.info(f"下载成功: {video_info['title']}")
                else:
                    self.logger.error(f"下载失败: {video_info['title']}")

            # 下载HDR版本
            hdr_quality = self._find_hdr_quality(qualities)
            if hdr_quality and not self._is_downloaded(bvid, cid, hdr_quality, folder_id):
                hdr_dir = dest_dir / "hdr"
                hdr_dir.mkdir(parents=True, exist_ok=True)
                self.download_video(bvid, cid, hdr_quality, hdr_dir, folder_id, "-hdr")

    def _is_downloaded(self, bvid: str, cid: int, quality: int, folder_id: str) -> bool:
        """添加 folder_id 检查"""
        return (bvid, cid, quality, folder_id) in self.downloaded
    
    def _request_with_412_retry(self, url: str, params: dict = None, method: str = 'GET') -> Optional[dict]:
        """带412错误重试的请求封装"""
        retry_count = 0
        params = params or {}
        while retry_count <= self.config.retry_412_max:
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    timeout=60
                )
                resp.raise_for_status()
                return resp.json()
                
            except requests.HTTPError as e:
                if resp.status_code == 412:
                    retry_count += 1
                    self.logger.warning(
                        f"遇到412错误，将在{self.config.retry_412_delay}秒后重试 "
                        f"({retry_count}/{self.config.retry_412_max})"
                    )
                    time.sleep(self.config.retry_412_delay)
                    continue
                raise e
            except Exception as e:
                raise e
                
        self.logger.error(f"412错误重试次数耗尽，放弃请求")
        return None

# ===================== 用户交互类 =====================
class InteractiveManager:
    @staticmethod
    def select_quality(qualities: Dict[int, str]) -> int:
        """交互式选择清晰度"""
        print("\n可用清晰度:")
        sorted_qn = sorted(qualities.items(), key=lambda x: x[0], reverse=True)
        for idx, (qn, desc) in enumerate(sorted_qn, 1):
            print(f"  {idx}. {qn} - {desc}")
        default_qn = sorted_qn[0][0]
        while True:
            choice = input(f"请输入清晰度（默认 {default_qn}）: ").strip()
            if not choice:
                return default_qn
            try:
                selected_idx = int(choice) - 1
                if 0 <= selected_idx < len(sorted_qn):
                    return sorted_qn[selected_idx][0]
                print(f"请输入1~{len(sorted_qn)}之间的数字")
            except ValueError:
                print("输入无效，请输入数字")

    @staticmethod
    def select_folders(folders: List[Dict]) -> List[str]:
        """选择收藏夹，返回收藏夹的 id 列表"""
        print("\n发现收藏夹:")
        for idx, folder in enumerate(folders, 1):
            print(f"  {idx}. {folder['title']} ({folder['media_count']}个视频)")
        while True:
            selection = input("\n请选择要下载的序号（多个用逗号分隔，q退出）: ").strip()
            if selection.lower() == "q":
                return []
            try:
                selected = [int(s.strip()) for s in selection.split(",")]
                if all(1 <= num <= len(folders) for num in selected):
                    return [folders[num-1]["id"] for num in selected]
                print(f"请输入1~{len(folders)}之间的有效数字")
            except ValueError:
                print("输入格式错误，示例：1,3")

# ===================== 主程序 =====================
def main():

    try:
        config_path = Path(__file__).parent / "config" / "config.json"
        with open(config_path, encoding="utf-8") as f:
            config_data = json.load(f)
    except FileNotFoundError:
        print(f"错误：配置文件不存在于 {config_path}")
        return
    except json.JSONDecodeError:
        print("错误：配置文件格式不正确")
        return


    config = Config(
            cookies=config_data.get("cookies", ""),
            save_path=Path(config_data.get("save_path", "./downloads")),
            ffmpeg_path=config_data.get("ffmpeg_path", "ffmpeg"),
            request_interval=config_data.get("request_interval", 1.5),
            max_retries=config_data.get("max_retries", 3),
            history_file=Path(config_data.get("history_file", "./config/download_history.json")),
            temp_dir=Path(config_data.get("temp_dir", "./temp")),
            max_title_length=config_data.get("max_title_length", 80),
            max_filename_length=config_data.get("max_filename_length", 240),
            upname_max_length=config_data.get("upname_max_length", 10),
            auto_download=config_data.get("auto_download", False),
            interval_hours=config_data.get("interval_hours", 6)
        )

    try:
        #config = Config(**config_data)
        downloader = BilibiliDownloader(config)

        if config.auto_download:
            folders = downloader.get_user_folders()
            if not folders:
                downloader.logger.error("无法获取收藏夹列表")
                return
            for folder in folders:
                downloader.process_folder(folder)
        else:
            print(f"已加载历史记录：{len(downloader.downloaded)} 条")

            use_highest_quality = False
            choice = input("是否以最高画质下载所有视频？(Y/n): ").strip().lower()
            if choice in ("", "y", "yes"):
                use_highest_quality = True

            folders = downloader.get_user_folders()
            if not folders:
                print("错误：无法获取收藏夹，请检查Cookie或网络连接")
                return

            selected_ids = InteractiveManager.select_folders(folders)
            if not selected_ids:
                print("下载已取消")
                return

            for folder_id in selected_ids:
                folder_info = next((f for f in folders if f["id"] == folder_id), None)
                if folder_info is None:
                    print(f"未找到收藏夹信息: {folder_id}")
                    continue

                folder_title = re.sub(r'[\\/:*?"<>|]', "", folder_info["title"]).strip() or folder_id
                folder_dir = config.save_path / folder_title
                folder_dir.mkdir(parents=True, exist_ok=True)
                print(f"\n正在处理收藏夹: {folder_title} (ID: {folder_id})")

                # medias = downloader._get_paginated_data(
                #     "https://api.bilibili.com/medialist/gateway/base/spaceDetail",
                #     {"media_id": folder_id, "keyword": "", "order": "mtime", "type": 0, "tid": 0, "jsonp": "jsonp"},
                #     data_key="medias"
                # )

                request_params = {
                    "media_id": folder_id,
                    "platform": "web",
                    "ts": int(time.time() * 1000),
                    "keyword": "",
                    "order": "mtime",
                    "type": 0,
                    "tid": 0,
                    "jsonp": "jsonp"
                }
                medias = downloader._get_paginated_data(
                    "https://api.bilibili.com/medialist/gateway/base/spaceDetail",
                    params=request_params,
                    data_key="medias"
                )

                for media in medias:
                    bvid = media.get("bvid")
                    if not bvid:
                        continue

                    video_info = downloader.get_video_info(bvid)
                    if not video_info:
                        print(f"跳过无效视频: {bvid}")
                        continue

                    for page in video_info.get("pages", []):
                        cid = page.get("cid")
                        if not cid:
                            continue

                        qualities = downloader.get_available_qualities(bvid, cid)
                        if not qualities:
                            print(f"视频可能受地区限制或需要登录: {video_info['title']}")
                            continue

                        if use_highest_quality:
                            allowed = {16, 32, 64, 80, 112, 116, 120, 125, 127}
                            avail = allowed.intersection(set(qualities.keys()))
                            if avail:
                                selected_quality = max(avail)
                            else:
                                selected_quality = max(qualities.keys())
                        else:
                            selected_quality = InteractiveManager.select_quality(qualities)

                        # 下载最高画质版本（下载结果放在收藏夹目录下）
                        if downloader.download_video(bvid, cid, selected_quality, folder_dir, folder_id):
                            print(f"✓ 成功下载: {video_info['title']} - {page['part']}")
                        else:
                            print(f"✗ 下载失败: {video_info['title']} - {page['part']}")

                        # 检查是否支持HDR：根据描述中包含 "HDR" 或 "杜比视界"
                        hdr_candidates = [q for q, desc in qualities.items() if "HDR" in desc or "杜比视界" in desc]
                        if hdr_candidates:
                            hdr_quality = max(hdr_candidates)
                            hdr_dir = folder_dir / "hdr"
                            hdr_dir.mkdir(parents=True, exist_ok=True)
                            #if downloader.download_video(bvid, cid, hdr_quality, dest_dir=hdr_dir, suffix="-hdr"):
                            if downloader.download_video(bvid, cid, hdr_quality, hdr_dir, folder_id, "-hdr"):
                                print(f"✓ HDR版本下载成功: {video_info['title']} - {page['part']}")
                            else:
                                print(f"✗ HDR版本下载失败: {video_info['title']} - {page['part']}")
            pass
    except Exception as e:
        logging.error(f"程序运行失败: {str(e)}")

if __name__ == "__main__":
    main()
