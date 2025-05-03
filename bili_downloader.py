import os
import re
import time
import json
import logging
import requests
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
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
    download_hdr: bool = True  # 是否下载HDR版本
    target_folders: List[str] = field(default_factory=list)  # 指定要下载的收藏夹ID列表

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
    def _load_download_history(self) -> Set[Tuple[str, int, str]]:
        """加载下载历史记录，记录bvid、cid和folder_id"""
        try:
            if self.config.history_file.exists():
                if self.config.history_file.stat().st_size == 0:
                    return set()
                with open(self.config.history_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
                    return {
                        (item["bvid"], item["cid"], item["folder_id"]) 
                        for item in records
                    }
            return set()
        except Exception as e:
            self.logger.error(f"加载历史记录失败: {str(e)}")
            return set()

    def _save_download_entry(self, bvid: str, cid: int, quality: int, title: str, up_name: str, folder_id: str):
        """保存下载记录"""
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
                "folder_id": folder_id,
                "timestamp": int(time.time())
            })
            with open(self.config.history_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存记录失败: {str(e)}")

    def _is_downloaded(self, bvid: str, cid: int, folder_id: str) -> bool:
        """检查视频在指定收藏夹中是否已下载"""
        return (bvid, cid, folder_id) in self.downloaded

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
                    
                    # 检查响应内容是否为空
                    if total_size == 0:
                        self.logger.warning(f"响应内容为空，重试中... ({retry+1}/{self.config.max_retries})")
                        time.sleep(2)
                        continue
                        
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
                                
                    # 验证下载的文件大小
                    if path.stat().st_size == 0:
                        self.logger.warning(f"下载的文件大小为0，重试中... ({retry+1}/{self.config.max_retries})")
                        path.unlink()
                        time.sleep(2)
                        continue
                        
                    return True
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"下载失败（重试 {retry+1}/{self.config.max_retries}）: {str(e)}")
                if path.exists():
                    path.unlink()
                time.sleep(2)
            except Exception as e:
                self.logger.error(f"下载过程发生未知错误: {str(e)}")
                if path.exists():
                    path.unlink()
                time.sleep(2)
        return False

    def _merge_files(self, video_path: Path, audio_path: Path, output_path: Path) -> bool:
        try:
            # 检查输入文件是否存在且大小不为0
            if not video_path.exists() or not audio_path.exists():
                self.logger.error("视频或音频文件不存在")
                return False
                
            if video_path.stat().st_size == 0 or audio_path.stat().st_size == 0:
                self.logger.error("视频或音频文件大小为0")
                return False

            # 使用更详细的FFmpeg命令
            cmd = [
                self.config.ffmpeg_path,
                "-y",
                "-loglevel", "error",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-c:a", "copy",
                "-strict", "experimental",
                str(output_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # 验证输出文件
            if not output_path.exists() or output_path.stat().st_size == 0:
                self.logger.error("合并后的文件无效")
                return False
                
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"FFmpeg合并失败: {e.stderr}")
            return False
        except Exception as e:
            self.logger.error(f"合并过程发生未知错误: {str(e)}")
            return False


    def download_video(self, bvid: str, cid: int, quality: int, dest_dir: Path, folder_id: str, suffix: str = "") -> bool:
        try:
            if (bvid, cid, folder_id) in self.downloaded:
                self.logger.info(f"跳过已下载内容: {bvid}-{cid} (收藏夹ID: {folder_id})")
                return True

            video_info = self.get_video_info(bvid)
            if not video_info:
                self.logger.error(f"无法获取视频信息: {bvid}")
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

            # 获取媒体URL
            video_url, audio_url = self._get_media_urls(bvid, cid, quality)
            if not video_url or not audio_url:
                self.logger.error(f"无法获取媒体URL: {bvid}-{cid}")
                return False

            # 创建临时文件，使用简短的命名方式
            temp_prefix = f"{bvid}_{cid}"
            temp_video = self.config.temp_dir / f"{temp_prefix}_v.m4s"
            temp_audio = self.config.temp_dir / f"{temp_prefix}_a.m4s"

            # 下载视频和音频
            video_success = self._download_media(video_url, temp_video)
            if not video_success:
                self.logger.error(f"视频下载失败: {bvid}-{cid}")
                return False

            audio_success = self._download_media(audio_url, temp_audio)
            if not audio_success:
                self.logger.error(f"音频下载失败: {bvid}-{cid}")
                temp_video.unlink(missing_ok=True)
                return False

            # 合并文件
            merge_success = self._merge_files(temp_video, temp_audio, output_path)
            if not merge_success:
                self.logger.error(f"文件合并失败: {bvid}-{cid}")
                temp_video.unlink(missing_ok=True)
                temp_audio.unlink(missing_ok=True)
                return False

            # 清理临时文件
            temp_video.unlink(missing_ok=True)
            temp_audio.unlink(missing_ok=True)

            # 保存下载记录
            self._save_download_entry(bvid, cid, quality, base_filename, up_name, folder_id)
            self.downloaded.add((bvid, cid, folder_id))
            
            self.logger.info(f"下载成功: {output_name}")
            return True

        except Exception as e:
            self.logger.error(f"下载流程异常: {str(e)}")
            # 清理临时文件
            if 'temp_video' in locals():
                temp_video.unlink(missing_ok=True)
            if 'temp_audio' in locals():
                temp_audio.unlink(missing_ok=True)
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
        
        # 限制标题长度，考虑路径长度限制
        # 假设路径前缀长度为50（包括目录名和扩展名）
        max_title_length = min(self.config.max_title_length, 150)
        base_title = re.sub(r'\s+', ' ', base_title)[:max_title_length]

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
                # 限制分P名称长度
                page_suffix = f"_{page_part[:15]}"  # 保留有区分度的部分

        # 处理UP主名称
        up_display = ""
        if up_name != "unknown":
            cleaned_up = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', up_name)  # 去除非中英文字符
            up_display = f"-{cleaned_up[:self.config.upname_max_length]}"

        # 组合各部分
        filename = f"{base_title}{page_suffix}{up_display}{suffix}"
        filename = re.sub(r'_{2,}', '_', filename)  # 清理连续下划线
        
        # 确保最终文件名不超过系统限制
        max_length = min(self.config.max_filename_length, 240)  # 考虑路径长度限制
        return filename[:max_length]
    
    

    def process_video(self, bvid: str, dest_dir: Path, folder_id: str):
        video_info = self.get_video_info(bvid)
        if not video_info:
            return

        # 获取所有分P的清晰度信息
        qualities_cache = {}
        for page in video_info.get("pages", []):
            cid = page.get("cid")
            if not cid:
                continue

            # 检查是否已下载
            if self._is_downloaded(bvid, cid, folder_id):
                self.logger.info(f"跳过已下载内容: {video_info['title']} - {page['part']}")
                continue

            # 获取清晰度信息
            qualities = self.get_available_qualities(bvid, cid)
            if not qualities:
                self.logger.error(f"无法获取清晰度信息: {video_info['title']} - {page['part']}")
                continue

            # 下载主版本
            selected_quality = self._select_highest_quality(qualities)
            if self.download_video(bvid, cid, selected_quality, dest_dir, folder_id):
                self.logger.info(f"下载成功: {video_info['title']} - {page['part']}")
            else:
                self.logger.error(f"下载失败: {video_info['title']} - {page['part']}")

            # 检查是否支持HDR
            if self.config.download_hdr:
                hdr_quality = self._find_hdr_quality(qualities)
                if hdr_quality:
                    hdr_dir = dest_dir / "hdr"
                    hdr_dir.mkdir(parents=True, exist_ok=True)
                    if self.download_video(bvid, cid, hdr_quality, hdr_dir, folder_id, "-hdr"):
                        self.logger.info(f"HDR版本下载成功: {video_info['title']} - {page['part']}")
                    else:
                        self.logger.error(f"HDR版本下载失败: {video_info['title']} - {page['part']}")

            # 添加请求间隔，避免频繁请求
            time.sleep(self.config.request_interval)

    def process_folder(self, folder: Dict):
        folder_id = folder["id"]
        folder_title = re.sub(r'[\\/:*?"<>|]', "", folder["title"]).strip() or str(folder_id)
        folder_dir = self.config.save_path / folder_title
        folder_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"开始处理收藏夹: {folder_title} (ID: {folder_id})")
        
        # 获取收藏夹中的所有视频
        medias = self._get_paginated_data(
            "https://api.bilibili.com/medialist/gateway/base/spaceDetail",
            {
                "media_id": folder_id,
                "platform": "web",
                "ts": int(time.time() * 1000)
            },
            data_key="medias"
        )

        # 批量处理视频
        for media in medias:
            bvid = media.get("bvid")
            if not bvid:
                continue
            
            # 处理视频
            self.process_video(bvid, folder_dir, folder_id)
            
            # 添加请求间隔，避免频繁请求
            time.sleep(self.config.request_interval)

    def _select_highest_quality(self, qualities: Dict[int, str]) -> int:
        allowed = {16, 32, 64, 80, 112, 116, 120, 125, 127}
        avail = allowed.intersection(set(qualities.keys()))
        return max(avail) if avail else max(qualities.keys())

    def _find_hdr_quality(self, qualities: Dict[int, str]) -> Optional[int]:
        hdr_candidates = [q for q, desc in qualities.items() if "HDR" in desc or "杜比视界" in desc]
        return max(hdr_candidates) if hdr_candidates else None
    
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
        interval_hours=config_data.get("interval_hours", 6),
        download_hdr=config_data.get("download_hdr", True),
        target_folders=config_data.get("target_folders", [])
    )

    try:
        downloader = BilibiliDownloader(config)
        folders = downloader.get_user_folders()
        
        if not folders:
            downloader.logger.error("无法获取收藏夹列表")
            return

        # 如果配置了目标收藏夹，只处理指定的收藏夹
        target_folders = config.target_folders
        if target_folders:
            folders = [f for f in folders if f["id"] in target_folders]
            if not folders:
                downloader.logger.error("未找到指定的收藏夹")
                return

        # 处理所有收藏夹
        for folder in folders:
            downloader.process_folder(folder)

    except Exception as e:
        logging.error(f"程序运行失败: {str(e)}")

if __name__ == "__main__":
    main()
