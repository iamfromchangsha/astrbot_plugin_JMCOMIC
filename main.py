# astrbot_plugin_JMCOMIC —— AstrBot 4.x 新版 API 移植版
# 原作: iamfromchangsha (https://github.com/iamfromchangsha/astrbot_plugin_JMCOMIC)
# 本版: 适配 AstrBot 4.27.4 (star.Star + @filter.command + MessageEventResult + event.set_result)
# 功能: /jm /jmpdf /jms /jmtag /jmmr /jmwr /jmhelp
# 特色: 移除CBZ；/jmpdf 合成PDF发文件后删除；资源护栏；流式JPEG PDF合成(内存有界)；进度消息经 NapCat HTTP 即时送达
from astrbot.api import star
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.core.platform.message_type import MessageType

import jmcomic
from jmcomic import JmOption
from jmcomic.jm_downloader import JmDownloader
from jmcomic.jm_exception import PartialDownloadFailedException
import img2pdf
import requests
import re
import os
import shutil
import threading
import asyncio
import logging
import yaml
from PIL import Image as PILImage

logger = logging.getLogger("jmcomic_plugin")

# ===================== 安全护栏配置 =====================
MIN_FREE_DISK_MB = 50       # 下载前磁盘最低剩余(逐张压缩后磁盘需求小)
MAX_PAGES = 200             # 最大页数(所有章节合计)
MAX_CHAPTERS = 5            # 最大章节数(合集直接拒绝)
MAX_IMAGES_MB = 120         # 下载图片总体积上限(下载中监控+事后复查)
MAX_PDF_MB = 100            # 成品 PDF 体积上限
GUARD_MEM_MB = 60           # 下载中内存冻结线
GUARD_DISK_MB = 35          # 下载中磁盘冻结线
PDF_BUILD_TIMEOUT_SEC = 600 # PDF合成超时
DOWNLOAD_TIMEOUT_SEC = 900  # 下载超时(秒)
FALLBACK_IMG_DIM = 1200     # Pillow 兜底时页面最长边
# =======================================================

JM_PAUSE_FLAG = {}
_DOWNLOAD_BUSY = False

NAPCAT_HTTP = "http://127.0.0.1:5700"

# 插件数据目录(相对于运行目录 /root)
PLUGIN_DATA_DIR = "./data/plugins/astrbot_plugin_JMCOMIC"


class GuardError(Exception):
    """安全护栏拦截异常，message 可直接展示给用户。"""
    pass


def free_disk_mb(path="/"):
    try:
        return shutil.disk_usage(path).free / 1048576
    except Exception:
        return 99999


def available_mem_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 99999


def dir_size_mb(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1048576


class DownloadGuard:
    """下载中监控线程：内存/磁盘/目录体积超限时冻结下载目录，
    使 jmcomic 的下一次文件写入立即失败，从而干净地中止下载。"""

    def __init__(self, watch_dir):
        self.watch_dir = watch_dir
        self._stop = threading.Event()
        self._thread = None
        self.frozen = False
        self.reason = ""

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(3):
            try:
                mem = available_mem_mb()
                disk = free_disk_mb()
                size = dir_size_mb(self.watch_dir)
            except Exception:
                continue
            if mem < GUARD_MEM_MB:
                self.reason = f"可用内存过低（{mem:.0f}MB）"
            elif disk < GUARD_DISK_MB:
                self.reason = f"磁盘剩余过低（{disk:.0f}MB）"
            elif size > MAX_IMAGES_MB:
                self.reason = f"下载体积超限（{size:.0f}MB > {MAX_IMAGES_MB}MB）"
            else:
                continue
            self._freeze()
            return

    def _freeze(self):
        self.frozen = True
        try:
            for sub in os.listdir(self.watch_dir):
                p = os.path.join(self.watch_dir, sub)
                if os.path.isdir(p):
                    try:
                        os.chmod(p, 0o500)
                    except OSError:
                        pass
            logger.warning(f"DownloadGuard 冻结下载: {self.reason}")
        except Exception as e:
            logger.warning(f"DownloadGuard 冻结异常: {e}")

    def stop(self):
        self._stop.set()
        self.unfreeze()

    def unfreeze(self):
        try:
            if os.path.isdir(self.watch_dir):
                for sub in os.listdir(self.watch_dir):
                    p = os.path.join(self.watch_dir, sub)
                    if os.path.isdir(p):
                        try:
                            os.chmod(p, 0o755)
                        except OSError:
                            pass
        except Exception:
            pass
        self.frozen = False


def extract_numbers(text):
    pattern = r'-?\d+\.?\d*'
    matches = re.findall(pattern, text)
    numbers = []
    for match in matches:
        if '.' in match:
            numbers.append(float(match))
        else:
            numbers.append(int(match))
    return numbers


def find_images_os(folder_path, extensions=None):
    if extensions is None:
        extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
    extensions = {ext.lower() for ext in extensions}

    image_files = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if os.path.splitext(file)[1].lower() in extensions:
                full_path = os.path.join(root, file)
                image_files.append(full_path)

    def extract_number(filename):
        basename = os.path.basename(filename)
        numbers = re.findall(r'\d+', basename)
        if numbers:
            return int(numbers[0])
        return 0

    image_files.sort(key=extract_number)
    return image_files


def extract_integers(text):
    pattern = r'-?\b\d+\b'
    matches = re.findall(pattern, text)
    return [str(match) for match in matches]


def clear_folder(folder_path):
    if not os.path.exists(folder_path):
        return
    if not os.path.isdir(folder_path):
        raise ValueError(f"提供的路径不是文件夹: {folder_path}")
    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        except Exception as e:
            logger.warning(f"无法删除 {item_path}: {e}")


def get_user_download_dir(user_id):
    base_dir = PLUGIN_DATA_DIR
    user_dir = os.path.join(base_dir, "download", user_id)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


# ---- 韩漫识别与过滤 ----
HANGUL_RE = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')
KOREAN_MARKS = ('韩漫', '韓漫', '韩国', '韓國', 'korean')
KOREAN_SERIAL = ('连载中', '连载')  # 禁漫上日漫几乎全是完结单行本,"连载中"基本为韩漫特征


def _is_korean_album(album) -> bool:
    """三层检测韩漫：tag标记 / 韩文字符 / 连载中。宁可多滤。"""
    try:
        tags = [str(t) for t in (getattr(album, 'tags', None) or [])]
        tl = [t.lower() for t in tags]
        for m in KOREAN_MARKS:
            if any(m.lower() in t for t in tl):
                return True
        if any(t in KOREAN_SERIAL for t in tags):
            return True
        if HANGUL_RE.search(str(getattr(album, 'name', '') or '')):
            return True
        if HANGUL_RE.search(str(getattr(album, 'author', '') or '')):
            return True
    except Exception:
        pass
    return False


def _is_compilation(album) -> bool:
    """合集判定：一个 album 下含多个章节(episode_list>1)即视为合集，剔除。"""
    try:
        eps = list(getattr(album, 'episode_list', None) or [])
        return len(eps) > 1
    except Exception:
        return False


# 通用噪音tag：语言/状态/版式等非题材特征，相似推荐时忽略
NOISE_TAGS = frozenset({
    '中文', '日文', '韩文', '英文', '汉化', '禁漫书库', '连载', '连载中',
    '全彩', '彩色', '单行本', '短篇', '长篇', '无修', '有字', '生肉',
    '单章', '合集', '翻译', '未汉化', '全年龄', '成人', '原创',
})


def create_temp_option(option_file, user_download_dir):
    with open(option_file, 'r', encoding='utf-8') as f:
        option_data = yaml.safe_load(f)
    option_data['dir_rule']['base_dir'] = user_download_dir
    # 限制下载并发，防止小内存设备 OOM
    option_data.setdefault('download', {}).setdefault('threading', {})
    option_data['download']['threading']['photo'] = 1
    option_data['download']['threading']['image'] = 2
    temp_option_file = os.path.join(user_download_dir, "temp_option.yml")
    with open(temp_option_file, 'w', encoding='utf-8') as f:
        yaml.dump(option_data, f, allow_unicode=True)
    return temp_option_file


def _pil_pdf_fallback(image_files, pdf_path):
    """Pillow 兜底：仅在 img2pdf 失败时使用（逐页降采样重编码）。"""
    tmp_dir = pdf_path + "_tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        jpegs = []
        for i, p in enumerate(image_files):
            im = PILImage.open(p)
            if im.mode != 'RGB':
                im = im.convert('RGB')
            if max(im.size) > FALLBACK_IMG_DIM:
                sc = FALLBACK_IMG_DIM / float(max(im.size))
                im = im.resize((max(1, int(im.size[0] * sc)), max(1, int(im.size[1] * sc))), PILImage.BILINEAR)
            jp = os.path.join(tmp_dir, f"{i:05d}.jpg")
            im.save(jp, 'JPEG', quality=75)
            jpegs.append(jp)
        data = img2pdf.convert(jpegs)
        with open(pdf_path, 'wb') as f:
            f.write(data)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def compress_images(image_files, max_dim=1100, quality=80):
    """逐页压缩图片(原地转JPEG)：单页解码内存有界，总量缩小约90%，
    使后续PDF合成与QQ发送都在小内存设备的安全范围内。
    已在下载时压缩过的小JPEG(<1MB)直接跳过，避免重复重编码。"""
    out = []
    for p in image_files:
        try:
            if p.lower().endswith('.jpg') and os.path.getsize(p) < 1048576:
                out.append(p)
                continue
            im = PILImage.open(p)
            if im.mode != 'RGB':
                im = im.convert('RGB')
            if max(im.size) > max_dim:
                sc = max_dim / float(max(im.size))
                im = im.resize((max(1, int(im.size[0] * sc)), max(1, int(im.size[1] * sc))), PILImage.BILINEAR)
            jp = os.path.splitext(p)[0] + '.jpg'
            im.save(jp, 'JPEG', quality=quality)
            if os.path.abspath(jp) != os.path.abspath(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
            out.append(jp)
        except Exception as e:
            logger.warning(f"压缩失败，保留原图 {p}: {e}")
            out.append(p)
    return out


def _compress_single(path, max_dim=FALLBACK_IMG_DIM, quality=80):
    """单张图片原地压缩(降采样+重编码为JPEG)，成功后删除原文件，返回新路径。
    内存占用≈单张图，用于『每下载一张就压缩』，防止磁盘堆积原始大图导致溢出。"""
    try:
        im = PILImage.open(path)
        if im.mode != 'RGB':
            im = im.convert('RGB')
        if max(im.size) > max_dim:
            sc = max_dim / float(max(im.size))
            im = im.resize((max(1, int(im.size[0] * sc)), max(1, int(im.size[1] * sc))), PILImage.BILINEAR)
        jp = os.path.splitext(path)[0] + '.jpg'
        im.save(jp, 'JPEG', quality=quality)
        im.close()
        if os.path.abspath(jp) != os.path.abspath(path):
            try:
                os.remove(path)
            except OSError:
                pass
        return jp
    except Exception as e:
        logger.warning(f"单张压缩失败，保留原图 {path}: {e}")
        return path


class CompressOnDownload(JmDownloader):
    """自定义下载器：每张图片下载完成(after_image)后立即压缩，内存=单张，
    磁盘只保留压缩后小图，天然防溢出。下载并发线程数被 option 限制为 image=2/photo=1。"""

    def after_image(self, image, img_save_path):
        super().after_image(image, img_save_path)
        try:
            p = getattr(image, 'save_path', None)
            if p and os.path.exists(p):
                _compress_single(p)
        except Exception as e:
            logger.warning(f"下载后压缩失败: {e}")


def write_pdf_stream_jpeg(image_files, pdf_path):
    """极简流式 PDF 写入器：仅适用于 JPEG 页(压缩后的常态)。
    逐页读入文件数据直接追加到输出，内存占用≈单页，无需内存门槛。
    任一页非 JPEG 时返回 False，由调用方走 img2pdf 兜底。"""
    pages = []
    for p in image_files:
        try:
            im = PILImage.open(p)
            fmt, size = im.format, im.size
            im.close()
            if fmt != 'JPEG':
                return False
            pages.append((p, size))
        except Exception:
            return False
    n = len(pages)
    # 对象编号：1=catalog 2=pages 之后每页 3个对象(页/内容流/图片)
    with open(pdf_path, 'wb') as out:
        out.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        offsets = {1: out.tell()}
        out.write(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
        offsets[2] = out.tell()
        kids = b' '.join(('%d 0 R' % (3 + 3 * i)).encode() for i in range(n))
        out.write(b'2 0 obj\n<< /Type /Pages /Kids [' + kids + b'] /Count ' +
                  str(n).encode() + b' >>\nendobj\n')
        for i, (p, (w, h)) in enumerate(pages):
            page_num = 3 + 3 * i
            content_num = 4 + 3 * i
            img_num = 5 + 3 * i
            # 图片 XObject
            with open(p, 'rb') as f:
                data = f.read()
            offsets[img_num] = out.tell()
            out.write(('%d 0 obj\n' % img_num).encode())
            out.write(b'<< /Type /XObject /Subtype /Image /Width %d /Height %d '
                      b'/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode '
                      b'/Length %d >>\nstream\n' % (w, h, len(data)))
            out.write(data)
            out.write(b'\nendstream\nendobj\n')
            # 内容流：把图片画满整页
            content = b'q %d 0 0 %d 0 0 cm /Im0 Do Q' % (w, h)
            offsets[content_num] = out.tell()
            out.write(('%d 0 obj\n<< /Length %d >>\nstream\n' % (content_num, len(content))).encode())
            out.write(content)
            out.write(b'\nendstream\nendobj\n')
            # 页面对象
            offsets[page_num] = out.tell()
            out.write(('%d 0 obj\n' % page_num).encode())
            out.write(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] '
                      b'/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>\nendobj\n'
                      % (w, h, img_num, content_num))
        xref_pos = out.tell()
        total_objs = 2 + 3 * n
        out.write(('xref\n0 %d\n' % (total_objs + 1)).encode())
        out.write(b'0000000000 65535 f \n')
        for i in range(1, total_objs + 1):
            out.write(('%010d 00000 n \n' % offsets[i]).encode())
        out.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
                  % (total_objs + 1, xref_pos))
    return True


def build_pdf(image_files, pdf_path):
    """合成 PDF。优先流式写盘(JPEG页，内存有界、无门槛)；
    非JPEG页回退 img2pdf(需内存门槛保护)。"""
    if write_pdf_stream_jpeg(image_files, pdf_path):
        return os.path.getsize(pdf_path) / 1048576
    total_mb = sum(os.path.getsize(p) for p in image_files) / 1048576
    avail = available_mem_mb()
    if avail < max(total_mb * 2 + 25, 30):
        raise GuardError(
            f"内存不足以合成PDF（需约 {total_mb:.0f}MB，当前可用 {avail:.0f}MB）。建议改用 /jm 直接发图。")
    try:
        data = img2pdf.convert(image_files)
        with open(pdf_path, 'wb') as f:
            f.write(data)
        del data
    except Exception as e:
        logger.warning(f"img2pdf 合成失败({e})，改用 Pillow 兜底")
        _pil_pdf_fallback(image_files, pdf_path)
    size_mb = os.path.getsize(pdf_path) / 1048576
    if size_mb > MAX_PDF_MB:
        try:
            os.remove(pdf_path)
        except OSError:
            pass
        raise GuardError(f"PDF 体积 {size_mb:.0f}MB 超过上限 {MAX_PDF_MB}MB，已取消。建议改用 /jm 直接发图。")
    return size_mb


def napcat_send(is_group, target_id, message_arr, timeout=60):
    url = NAPCAT_HTTP + ("/send_group_msg" if is_group else "/send_private_msg")
    payload = {"message": message_arr}
    payload["group_id" if is_group else "user_id"] = int(target_id)
    resp = requests.post(url, json=payload, timeout=timeout)
    data = resp.json()
    ok = (data.get("status") == "ok") or (data.get("retcode") == 0)
    if not ok:
        logger.error(f"NapCat 发送消息失败: {data}")
    return ok


def napcat_upload_file(is_group, target_id, file_path, name):
    file_path = os.path.abspath(file_path)
    if is_group:
        url = NAPCAT_HTTP + "/upload_group_file"
        payload = {"group_id": int(target_id), "file": file_path, "name": name}
    else:
        url = NAPCAT_HTTP + "/upload_private_file"
        payload = {"user_id": int(target_id), "file": file_path, "name": name}
    resp = requests.post(url, json=payload, timeout=300)
    data = resp.json()
    ok = (data.get("status") == "ok") or (data.get("retcode") == 0)
    if not ok:
        logger.error(f"NapCat 发送文件失败: {data}")
    return ok


def download_album_to(album_id, user_download_dir, guard=None):
    """带前置页数检查的下载：先拉专辑详情，合集/页数超限直接拒绝（不落盘）。"""
    temp_option_file = create_temp_option(
        os.path.join(PLUGIN_DATA_DIR, "option.yml"),
        user_download_dir
    )
    option = jmcomic.create_option_by_file(temp_option_file)
    client = option.new_jm_client()
    album = client.get_album_detail(album_id)

    episodes = list(getattr(album, 'episode_list', None) or [])
    if len(episodes) > MAX_CHAPTERS:
        first = str(episodes[0][0]) if episodes else str(album_id)
        raise GuardError(
            f"该作品是合集，共 {len(episodes)} 章，超过服务器上限 {MAX_CHAPTERS} 章，"
            f"拒绝下载。提示：可用单章ID下载，例如 /jmpdf {first}"
        )

    photo_ids = [str(ep[0]) for ep in episodes] if episodes else [str(album_id)]
    total_pages = 0
    for pid in photo_ids:
        photo = client.get_photo_detail(pid)
        total_pages += len(getattr(photo, 'page_arr', None) or [])
    if total_pages > MAX_PAGES:
        raise GuardError(f"该作品共 {total_pages} 页，超过服务器上限 {MAX_PAGES} 页，拒绝下载。")

    logger.info(f"专辑 {album_id} 共 {len(photo_ids)} 章 / {total_pages} 页，通过前置检查，开始下载")
    if guard is not None:
        guard.start()
    failed = 0
    try:
        jmcomic.download_album(str(album_id), option, downloader=CompressOnDownload)
    except PartialDownloadFailedException as e:
        # 第一轮部分失败：cache机制下整体重试一次(已成功的图自动跳过，只补失败图)
        n = len(e.downloader.download_failed_image)
        logger.warning(f"第一轮下载部分失败({n} 张)，自动重试一轮...")
        try:
            jmcomic.download_album(str(album_id), option, downloader=CompressOnDownload)
        except PartialDownloadFailedException as e2:
            failed = len(e2.downloader.download_failed_image)
            logger.warning(f"重试后仍有 {failed} 张失败，跳过继续")
    return find_images_os(user_download_dir), failed


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        os.makedirs(PLUGIN_DATA_DIR, exist_ok=True)

    # ============ 通用工具 ============
    @staticmethod
    def _target(event):
        """返回 (is_group, target_id)。"""
        is_group = (event.get_message_type() == MessageType.GROUP_MESSAGE)
        target_id = event.get_group_id() if is_group else event.get_sender_id()
        return is_group, target_id

    def _precheck(self):
        """任务前置检查：并发锁 + 磁盘。返回 (ok, reason)。"""
        global _DOWNLOAD_BUSY
        if _DOWNLOAD_BUSY:
            return False, "⚠️ 已有下载任务在进行中，请等待其完成后再试。"
        free = free_disk_mb()
        if free < MIN_FREE_DISK_MB:
            return False, f"⚠️ 服务器磁盘空间不足（仅剩 {free:.0f}MB，需 ≥{MIN_FREE_DISK_MB}MB），任务取消。"
        _DOWNLOAD_BUSY = True
        return True, ""

    @staticmethod
    def _release():
        global _DOWNLOAD_BUSY
        _DOWNLOAD_BUSY = False

    async def _download_with_guard(self, album_id, user_download_dir):
        """在线程池中执行下载(不阻塞机器人)，带超时+下载中监控。异常类型化上抛。"""
        guard = DownloadGuard(user_download_dir)
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, download_album_to, album_id,
                                     user_download_dir, guard),
                timeout=DOWNLOAD_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            raise TimeoutError("download timeout")
        finally:
            guard.stop()

    # ============ /jm 下载并逐张发图 ============
    @filter.command("jm")
    async def jm(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        user_id = event.get_sender_id()
        is_group, target_id = self._target(event)
        message_str = event.get_message_str().strip()

        def now(t):
            try:
                napcat_send(is_group, target_id, [{"type": "text", "data": {"text": t}}])
            except Exception as e:
                logger.warning(f"即时消息失败: {e}")

        if re.search(r'暂停', message_str):
            JM_PAUSE_FLAG[user_id] = True
            clear_folder(get_user_download_dir(user_id))
            event.set_result(MessageEventResult().message(f"{user_name}，已暂停漫画发送并清除服务器下载文件！"))
            return

        JM_PAUSE_FLAG[user_id] = False

        album_ids_from_input = extract_integers(message_str)
        if not album_ids_from_input:
            event.set_result(MessageEventResult().message(f"{user_name}, 未找到有效的数字ID，请检查输入。例如：/jm 123456"))
            return

        album_id_to_search = album_ids_from_input[0]
        ok, reason = self._precheck()
        if not ok:
            event.set_result(MessageEventResult().message(reason))
            return

        now(f"{user_name}, 正在查找 [{album_id_to_search}] !")

        user_download_dir = get_user_download_dir(user_id)
        clear_folder(user_download_dir)
        try:
            images, failed_count = await self._download_with_guard(album_id_to_search, user_download_dir)

            if JM_PAUSE_FLAG.get(user_id, False):
                event.set_result(MessageEventResult().message(f"{user_name}，已触发暂停，取消图片发送并清除文件！"))
                return

            if not images:
                event.set_result(MessageEventResult().message(f"{user_name}，未下载到任何图片，请稍后再试。"))
                return

            now(f"共找到 {len(images)} 张图片，正在优化（压缩后发送更快）...")
            loop = asyncio.get_event_loop()
            images = await loop.run_in_executor(None, compress_images, images)

            now(f"开始逐张发送（共 {len(images)} 张）：")

            sent = 0
            fail = 0
            for i, img in enumerate(images, 1):
                if JM_PAUSE_FLAG.get(user_id, False):
                    event.set_result(MessageEventResult().message(
                        f"{user_name}，已暂停：已发 {sent} 张，剩余 {len(images) - i + 1} 张未发送。"))
                    return
                try:
                    if napcat_send(is_group, target_id,
                                   [{"type": "image", "data": {"file": "file:///" + os.path.abspath(img)}}]):
                        sent += 1
                    else:
                        fail += 1
                except Exception:
                    fail += 1
                await asyncio.sleep(1)

            if JM_PAUSE_FLAG.get(user_id, False):
                event.set_result(MessageEventResult().message(f"{user_name}，已暂停。已发 {sent} 张，缓存已清理。"))
                return
            tail = f"，{fail} 张发送失败" if fail else ""
            dl_tail = f"\n⚠️ 有 {failed_count} 张图因网络不稳定未能下载，已跳过" if failed_count else ""
            event.set_result(MessageEventResult().message(f"{user_name}，已全部发送完成！（共 {sent} 张{tail}）{dl_tail}"))
        except TimeoutError:
            event.set_result(MessageEventResult().message(
                f"⚠️ 下载超时（>{DOWNLOAD_TIMEOUT_SEC // 60} 分钟），任务已取消。"))
        except GuardError as ge:
            event.set_result(MessageEventResult().message(f"⚠️ {ge}"))
        except PermissionError:
            event.set_result(MessageEventResult().message("⚠️ 下载中途触发保护（内存/磁盘/体积），已中止并清理。"))
        except Exception as e:
            logger.error(f"用户{user_id}执行jm命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，操作出错：{str(e)}"))
        finally:
            clear_folder(user_download_dir)
            if user_id in JM_PAUSE_FLAG:
                del JM_PAUSE_FLAG[user_id]
            self._release()

    # ============ /jmpdf 下载并合成PDF发送 ============
    @filter.command("jmpdf")
    async def jmpdf(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        user_id = event.get_sender_id()
        is_group, target_id = self._target(event)
        message_str = event.get_message_str().strip()

        def now(t):
            try:
                napcat_send(is_group, target_id, [{"type": "text", "data": {"text": t}}])
            except Exception as e:
                logger.warning(f"即时消息失败: {e}")

        album_ids_from_input = extract_integers(message_str)
        if not album_ids_from_input:
            event.set_result(MessageEventResult().message(f"{user_name}, 未找到有效的数字ID，请检查输入。例如：/jmpdf 123456"))
            return

        album_id_to_search = album_ids_from_input[0]
        ok, reason = self._precheck()
        if not ok:
            event.set_result(MessageEventResult().message(reason))
            return

        now(f"{user_name}, 正在下载 [{album_id_to_search}] 并转换PDF，进度会随时播报，请耐心等待...")

        user_download_dir = get_user_download_dir(user_id)
        clear_folder(user_download_dir)
        try:
            images, failed_count = await self._download_with_guard(album_id_to_search, user_download_dir)
            if not images:
                event.set_result(MessageEventResult().message(f"{user_name}，未下载到任何图片，请稍后再试。"))
                return
            if failed_count:
                now(f"⚠️ 有 {failed_count} 张图因网络不稳定未能下载，将跳过（PDF 可能缺页）")
            if len(images) > MAX_PAGES:
                event.set_result(MessageEventResult().message(
                    f"⚠️ 页数超限（{len(images)} > {MAX_PAGES}），已取消。"))
                return

            total_mb = sum(os.path.getsize(p) for p in images) / 1048576
            now(f"下载完成：{len(images)} 页 / {total_mb:.0f}MB，正在压缩优化...")
            loop = asyncio.get_event_loop()
            images = await loop.run_in_executor(None, compress_images, images)
            compressed_mb = sum(os.path.getsize(p) for p in images) / 1048576
            now(f"压缩完成（{compressed_mb:.1f}MB），正在合成PDF...")

            # 漫画标题
            title = str(album_id_to_search)
            for subdir in os.listdir(user_download_dir):
                fp = os.path.join(user_download_dir, subdir)
                if os.path.isdir(fp):
                    title = subdir
                    break
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:60]

            pdf_path = os.path.join(user_download_dir, f"{safe_title}.pdf")
            loop = asyncio.get_event_loop()
            size_mb = await asyncio.wait_for(
                loop.run_in_executor(None, build_pdf, images, pdf_path),
                timeout=PDF_BUILD_TIMEOUT_SEC
            )

            now(f"PDF 已生成（{size_mb:.1f}MB），正在发送文件...")

            upload_ok = await loop.run_in_executor(
                None, napcat_upload_file, is_group, target_id, pdf_path, f"{safe_title}.pdf")

            if upload_ok:
                event.set_result(MessageEventResult().message(f"{user_name}，PDF 已发送！服务器缓存已清理。"))
                return
            event.set_result(MessageEventResult().message(f"{user_name}，PDF 发送失败，请稍后再试。"))
        except asyncio.TimeoutError:
            event.set_result(MessageEventResult().message(f"⚠️ PDF 合成超时（>{PDF_BUILD_TIMEOUT_SEC // 60} 分钟），已取消。"))
        except TimeoutError:
            event.set_result(MessageEventResult().message(
                f"⚠️ 下载超时（>{DOWNLOAD_TIMEOUT_SEC // 60} 分钟），任务已取消。"))
        except GuardError as ge:
            event.set_result(MessageEventResult().message(f"⚠️ {ge}"))
        except PermissionError:
            event.set_result(MessageEventResult().message("⚠️ 下载中途触发保护（内存/磁盘/体积），已中止并清理。"))
        except Exception as e:
            logger.error(f"用户{user_id}执行jmpdf命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，操作出错：{str(e)}"))
        finally:
            clear_folder(user_download_dir)
            self._release()

    # ============ /jms 搜索 ============
    @filter.command("jms")
    async def jms(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.get_message_str()
        logger.info(f"Received command from {user_name}: {message_str}")
        pages_list = extract_numbers(message_str)
        pages = int(pages_list[0]) if pages_list else 1
        query = re.sub(r'^\s*/?\s*jms\s*', '', message_str, flags=re.IGNORECASE)
        query = re.sub(r'\d', '', query).strip()
        if not query:
            event.set_result(MessageEventResult().message(f"{user_name}, 请输入要搜索的关键词。例如：/jms 姐姐"))
            return

        try:
            client = JmOption.default().new_jm_client()
            page = client.search_site(search_query=query, page=pages)
            result = ""
            for album_id, title in page:
                result += f'[{album_id}]: {title}\n'
            event.set_result(MessageEventResult().message(
                f"{user_name}, {query}这种题材实在是太涩啦!页面：{pages}\n\n" +
                (result.strip() if result else "未找到相关结果。")))
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jms命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，搜索出错：{str(e)}"))

    # ============ /jmmr 月度排行榜 ============
    @filter.command("jmmr")
    async def jm_monthly_ranking(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        page_num_list = extract_numbers(event.get_message_str())
        page_num = int(page_num_list[0]) if page_num_list and page_num_list[0] > 0 else 1
        try:
            client = JmOption.default().new_jm_client()
            page = client.month_ranking(page=page_num)
            if not page:
                event.set_result(MessageEventResult().message(f"{user_name}，未能获取到第 {page_num} 页的排行榜数据。"))
                return
            result = f"月度排行榜 第 {page_num} 页:\n"
            for album_id, title in page:
                result += f'[{album_id}]: {title}\n'
            event.set_result(MessageEventResult().message(result.strip()))
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmmr命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，获取月度排行榜时发生错误: {str(e)}"))

    # ============ /jmwr 周度排行榜 ============
    @filter.command("jmwr")
    async def jm_weekly_ranking(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        page_num_list = extract_numbers(event.get_message_str())
        page_num = int(page_num_list[0]) if page_num_list and page_num_list[0] > 0 else 1
        try:
            client = JmOption.default().new_jm_client()
            page = client.week_ranking(page=page_num)
            if not page:
                event.set_result(MessageEventResult().message(f"{user_name}，未能获取到第 {page_num} 页的排行榜数据。"))
                return
            result = f"周度排行榜 第 {page_num} 页:\n"
            for album_id, title in page:
                result += f'[{album_id}]: {title}\n'
            event.set_result(MessageEventResult().message(result.strip()))
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmwr命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，获取周度排行榜时发生错误: {str(e)}"))

    # ============ /jmhelp 帮助 ============
    @filter.command("jmhelp")
    async def jm_help(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        help_text = f"""
{user_name}，欢迎使用禁漫天堂插件！
以下是可用的命令列表：

/jm <ID>          - 下载指定ID的漫画，逐张发送图片。
/jm 暂停          - 暂停当前正在进行的漫画下载和发送，并清理缓存。
/jmpdf <ID>       - 下载指定ID的漫画，合成PDF以文件发送（发完自动清理）。
/jms <关键词> [页码] - 搜索指定关键词的漫画，默认第1页。
/jmrec [分类] [页码] - 🔥热门推荐（按观看数，已剔除韩漫和合集）。如：/jmrec 或 /jmrec 校园
/jmrec <本子ID>    - 🎯输入本子编号，推荐相同类型、题材的本子。如：/jmrec 394309
/jmday [页码]      - 日度热门排行榜（已剔除韩漫和合集）。
/jmmr [页码]      - 获取月度热门排行榜，默认第1页。
/jmwr [页码]      - 获取周度热门排行榜，默认第1页。
/jmtag <ID>       - 查询指定ID漫画的标签。
/jmauthor <ID>    - 👤输入本子编号，返回该作者的全部作品。
/jmhelp           - 显示此帮助信息。

⚠️ 服务器资源有限，已启用保护：
· 合集>{MAX_CHAPTERS}章 或 总页数>{MAX_PAGES}页 拒绝下载
· 图片总量>{MAX_IMAGES_MB}MB / PDF>{MAX_PDF_MB}MB 取消任务
· 同一时间仅允许一个下载任务；全程即时播报进度
        """.strip()
        event.set_result(MessageEventResult().message(help_text))

    # ============ /jmtag 查询标签 ============
    @filter.command("jmtag")
    async def jmtag(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        original_message_str = event.get_message_str()
        logger.info(f"Received command from {user_name}: {original_message_str}")
        album_ids = extract_integers(original_message_str)
        if not album_ids:
            event.set_result(MessageEventResult().message(f"{user_name}, 未找到有效的数字ID，请检查输入。例如：/jmtag 123456"))
            return

        album_id_to_search = album_ids[0]
        try:
            client = JmOption.default().new_jm_client()
            page = client.search_site(search_query=str(album_id_to_search))
            album = page.single_album
            if album is None:
                event.set_result(MessageEventResult().message(f"{user_name}, 未能找到ID为 [{album_id_to_search}] 的本子。"))
                return
            tags_str = ', '.join(album.tags) if album.tags else '无标签'
            event.set_result(MessageEventResult().message(f"{user_name}, 查询本子 [{album_id_to_search}] 的标签!\n\n"
                                                          f"[{album_id_to_search}]:\n{album.title}\n标签: {tags_str}"))
        except AttributeError as e:
            if "'JmSearchPage' object has no attribute 'single_album'" in str(e):
                event.set_result(MessageEventResult().message(f"{user_name}, 搜索结果不唯一或无效，无法获取详情。"))
                return
            logger.error(f"AttributeError in jmtag: {e}")
            event.set_result(MessageEventResult().message(f"{user_name}, 获取标签时发生错误 (AttributeError): {e}"))
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmtag命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}, 获取标签时发生错误: {str(e)}"))

    # ============ /jmrec 热门推荐 / 相似推荐(同类型题材) ============
    @filter.command("jmrec")
    async def jmrec(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        is_group, target_id = self._target(event)
        message_str = event.get_message_str()

        raw = re.sub(r'^\s*/?\s*jmrec\s*', '', message_str, flags=re.IGNORECASE).strip()

        def now(t):
            try:
                napcat_send(is_group, target_id, [{"type": "text", "data": {"text": t}}])
            except Exception as e:
                logger.warning(f"即时消息失败: {e}")

        # ---- 相似推荐模式: /jmrec <本子ID> ----
        if raw and re.fullmatch(r'\d+', raw.split()[0]):
            album_id = int(raw.split()[0])

            def _fetch_similar():
                client = JmOption.default().new_jm_client()
                album = client.get_album_detail(album_id)
                tags = [str(t) for t in (getattr(album, 'tags', None) or [])]
                topic_tags = [t for t in tags if t not in NOISE_TAGS][:3]
                album_name = str(getattr(album, 'name', '') or album_id)
                if not topic_tags:
                    return [], [], album_name
                score = {}
                titles = {}
                for tag in topic_tags:
                    try:
                        page = client.search_tag(tag, page=1, order_by='mv')
                        for i, (pid, title) in enumerate(page):
                            if i >= 20:
                                break
                            pid = str(pid)
                            if pid == str(album_id):
                                continue
                            score[pid] = score.get(pid, 0) + 1
                            titles[pid] = title
                    except Exception as e:
                        logger.warning(f"按tag[{tag}]搜索失败: {e}")
                cands = sorted(score.items(), key=lambda kv: -kv[1])
                out = []
                checked = 0
                for pid, hits in cands:
                    if len(out) >= 10 or checked >= 30:
                        break
                    checked += 1
                    try:
                        a = client.get_album_detail(pid)
                    except Exception:
                        continue
                    if _is_korean_album(a) or _is_compilation(a):
                        continue
                    out.append((pid, str(a.name or titles.get(pid, '')), hits))
                return out, topic_tags, album_name

            now(f"{user_name}, 正在分析 [{album_id}] 的题材并搜索相似本子，稍等...")
            loop = asyncio.get_event_loop()
            try:
                results, topic_tags, album_name = await asyncio.wait_for(
                    loop.run_in_executor(None, _fetch_similar), timeout=150)
                if not results:
                    event.set_result(MessageEventResult().message(
                        f"{user_name}，[{album_id}] 的题材标签太少，没能找到相似本子。\n"
                        f"标签: {', '.join(topic_tags) if topic_tags else '无'}"))
                    return
                result = f"🎯 与 [{album_id}]《{album_name[:40]}》题材相似的本子:\n"
                for i, (aid, title, hits) in enumerate(results, 1):
                    mark = '🔥' if hits >= 2 else '·'
                    result += f"{mark} [{aid}]: {title[:50]}\n"
                result += f"\n(题材: {', '.join(topic_tags[:3])} | 已剔除韩漫合集)"
                event.set_result(MessageEventResult().message(result.strip()))
            except asyncio.TimeoutError:
                event.set_result(MessageEventResult().message("⚠️ 相似推荐超时，请稍后再试。"))
            except Exception as e:
                logger.error(f"用户{event.get_sender_id()}执行jmrec相似推荐出错：{str(e)}")
                event.set_result(MessageEventResult().message(f"{user_name}，相似推荐出错: {str(e)}"))
            return

        # ---- 分类推荐模式: /jmrec <分类> [页码] ----
        page_list = extract_numbers(message_str)
        page = int(page_list[0]) if page_list and page_list[0] > 0 else 1
        q = re.sub(r'\b\d+\b', '', raw).strip()
        category = q or '全部'

        def _fetch():
            client = JmOption.default().new_jm_client()
            cpage = client.categories_filter(page=page, time='a', category=category, order_by='mv')
            out = []
            checked = 0
            for aid, title in cpage:
                if len(out) >= 10 or checked >= 30:
                    break
                checked += 1
                try:
                    album = client.get_album_detail(aid)
                except Exception:
                    continue
                if _is_korean_album(album) or _is_compilation(album):
                    continue
                out.append((str(aid), str(album.name or title)))
            return out, checked

        now(f"{user_name}, 正在获取 [{category}] 热门推荐（自动过滤韩漫和合集），稍等...")
        loop = asyncio.get_event_loop()
        try:
            results, checked = await asyncio.wait_for(loop.run_in_executor(None, _fetch), timeout=120)
            if not results:
                event.set_result(MessageEventResult().message(
                    f"{user_name}，[{category}] 第 {page} 页没能找到足够的非韩漫推荐，换个分类试试？\n"
                    f"示例：/jmrec 校园、/jmrec 后宫、/jmrec 纯爱；或 /jmrec <本子ID> 找相似"))
                return
            result = f"🔥 [{category}] 热门推荐 第{page}页（已剔除韩漫合集）:\n"
            for i, (aid, title) in enumerate(results, 1):
                result += f"{i}. [{aid}]: {title}\n"
            result += f"\n💡 发送 /jm <ID> 下载, /jms <关键词> 搜索, /jmrec <ID> 找同题材"
            event.set_result(MessageEventResult().message(result.strip()))
        except asyncio.TimeoutError:
            event.set_result(MessageEventResult().message(f"⚠️ 获取推荐超时，请稍后再试。"))
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmrec命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，获取推荐出错: {str(e)}"))

    # ============ /jmday 日度排行榜(自动过滤韩漫) ============
    @filter.command("jmday")
    async def jm_day_ranking(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        is_group, target_id = self._target(event)
        message_str = event.get_message_str()

        page_num_list = extract_numbers(message_str)
        page_num = int(page_num_list[0]) if page_num_list and page_num_list[0] > 0 else 1

        def _fetch():
            client = JmOption.default().new_jm_client()
            dpage = client.day_ranking(page=page_num)
            out = []
            checked = 0
            for aid, title in dpage:
                if len(out) >= 10 or checked >= 30:
                    break
                checked += 1
                try:
                    album = client.get_album_detail(aid)
                except Exception:
                    continue
                if _is_korean_album(album) or _is_compilation(album):
                    continue
                out.append((str(aid), str(album.name or title)))
            return out

        loop = asyncio.get_event_loop()
        try:
            results = await asyncio.wait_for(loop.run_in_executor(None, _fetch), timeout=120)
            if not results:
                event.set_result(MessageEventResult().message(f"{user_name}，未能获取到第 {page_num} 页的日榜数据。"))
                return
            result = f"日度排行榜 第 {page_num} 页（已剔除韩漫合集）:\n"
            for aid, title in results:
                result += f'[{aid}]: {title}\n'
            event.set_result(MessageEventResult().message(result.strip()))
        except asyncio.TimeoutError:
            event.set_result(MessageEventResult().message(f"⚠️ 获取日榜超时，请稍后再试。"))
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmday命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，获取日度排行榜时发生错误: {str(e)}"))

    # ============ /jmauthor 输入本子ID，返回作者全部作品 ============
    @filter.command("jmauthor")
    async def jmauthor(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        is_group, target_id = self._target(event)
        message_str = event.get_message_str()

        album_ids = extract_integers(message_str)
        if not album_ids:
            event.set_result(MessageEventResult().message(
                f"{user_name}, 未找到有效的本子ID，请检查输入。例如：/jmauthor 394309"))
            return
        aid = int(album_ids[0])

        def now(t):
            try:
                napcat_send(is_group, target_id, [{"type": "text", "data": {"text": t}}])
            except Exception as e:
                logger.warning(f"即时消息失败: {e}")

        def _fetch():
            client = JmOption.default().new_jm_client()
            album = client.get_album_detail(aid)
            author = str(getattr(album, 'author', '') or '').strip()
            src_name = str(getattr(album, 'name', '') or aid)
            if not author:
                return None, author, src_name
            page = client.search_author(author, page=1, order_by='mv')
            out = []
            checked = 0
            for pid, title in page:
                if len(out) >= 20 or checked >= 30:
                    break
                checked += 1
                try:
                    a = client.get_album_detail(pid)
                except Exception:
                    continue
                if _is_korean_album(a) or _is_compilation(a):
                    continue
                out.append((str(pid), str(a.name or title)))
            return out, author, src_name

        now(f"{user_name}, 正在查找本子 [{aid}] 的作者及其作品，稍等...")
        loop = asyncio.get_event_loop()
        try:
            results, author, src_name = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch), timeout=150)
            if results is None:
                event.set_result(MessageEventResult().message(
                    f"{user_name}，本子 [{aid}] 没有作者信息。"))
                return
            if not results:
                event.set_result(MessageEventResult().message(
                    f"{user_name}，没能获取到该作者的作品列表，稍后再试。"))
                return
            result = f"👤 作者「{author}」的作品（源自本子 [{aid}]《{src_name[:30]}》）:\n"
            for i, (pid, title) in enumerate(results, 1):
                mark = '📍' if pid == str(aid) else '-'
                result += f"{i}. {mark} [{pid}]: {title[:46]}\n"
            result += f"\n共 {len(results)} 本（已剔除韩漫合集）"
            event.set_result(MessageEventResult().message(result.strip()))
        except asyncio.TimeoutError:
            event.set_result(MessageEventResult().message("⚠️ 查询作者作品超时，请稍后再试。"))
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmauthor命令出错：{str(e)}")
            event.set_result(MessageEventResult().message(f"{user_name}，查询作者作品出错: {str(e)}"))

    async def terminate(self):
        JM_PAUSE_FLAG.clear()
