from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
import astrbot.api.message_components as Comp
import jmcomic
from jmcomic import *
import re
import os
import asyncio
import shutil
from pathlib import Path


def extract_numbers(text):
    # 正则表达式匹配整数、浮点数、负数
    pattern = r'-?\d+\.?\d*'
    matches = re.findall(pattern, text)
    # 转换为数字类型（int 或 float）
    numbers = []
    for match in matches:
        if '.' in match:
            numbers.append(float(match))
        else:
            numbers.append(int(match))
    return numbers

def find_images_os(folder_path: str, extensions=None):
    if extensions is None:
        extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
    extensions = {ext.lower() for ext in extensions}
    
    image_files = []
    if not os.path.exists(folder_path):
        logger.warning(f"路径不存在: {folder_path}")
        return image_files
        
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if os.path.splitext(file)[1].lower() in extensions:
                full_path = os.path.join(root, file)
                image_files.append(full_path)
    
    # 按文件名中的数字排序
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

def clear_folder(folder_path: str):
    if not os.path.exists(folder_path):
        logger.warning(f"警告: 路径不存在 - {folder_path}")
        return

    if not os.path.isdir(folder_path):
        logger.error(f"提供的路径不是文件夹: {folder_path}")
        return

    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        except Exception as e:
            logger.error(f"无法删除 {item_path}: {e}")

@register("jm", "iamfromchangsha", "一个简单的插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_dir: Path = StarTools.get_data_dir()

    async def initialize(self):
        """可选择实现异步的插件初始化方法"""
        # 确保下载目录存在
        download_dir = self.data_dir / "download"
        download_dir.mkdir(parents=True, exist_ok=True)

    @filter.command("jm")
    async def helloworld(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(f"Received command from {user_name}: {message_str}")
        yield event.plain_result(f"{user_name}, 正在查找 {message_str}!")

        album_ids = extract_integers(message_str)
        if not album_ids:
            yield event.plain_result("未检测到有效的本子ID，请输入数字。")
            return

        option_file = self.data_dir / "option.yml"
        if not option_file.exists():
            yield event.plain_result("配置文件 option.yml 不存在，请先配置。")
            return

        option = jmcomic.create_option_by_file(str(option_file))

        download_dir = self.data_dir / "download"
        # 清空下载目录前先清理
        clear_folder(str(download_dir))

        # 使用 asyncio.to_thread 避免阻塞事件循环
        try:
            await asyncio.to_thread(jmcomic.download_album, album_ids, option)
        except Exception as e:
            logger.exception("下载过程中发生错误")
            yield event.plain_result(f"下载失败: {e}")
            return

        images = find_images_os(str(download_dir))
        yield event.plain_result(f"共找到 {len(images)} 张图片，按顺序发送：")

        for i, img in enumerate(images, 1):
            yield event.image_result(img)
            await asyncio.sleep(1)  # 非阻塞等待

        clear_folder(str(download_dir))
    
    @filter.command("jms")
    async def helloworld2(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        pages = extract_numbers(message_str)
        message_str = re.sub(r'\d', '', message_str)
        logger.info(f"Received command from {user_name}: {message_str}page: {pages}")
        yield event.plain_result(f"{user_name}, {message_str}这种题材实在是太涩啦!页面：{pages}")
        client = JmOption.default().new_jm_client()
        page: JmSearchPage = client.search_site(search_query=message_str, page=pages)
        result = ""
        for album_id, title in page:
            result += f'[{album_id}]: {title}\n'
        yield event.plain_result(result)

    async def terminate(self):
        """插件销毁时清理资源"""
        pass