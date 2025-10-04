from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import re
import os
import time
import pathlib
import asyncio


# 将jmcomic导入放在try-except中，避免导入错误导致插件无法加载
try:
    import jmcomic
    JMCOMIC_AVAILABLE = True
except ImportError:
    JMCOMIC_AVAILABLE = False
    logger.warning("jmcomic模块未安装，相关功能将无法使用")

def find_images_os(folder_path, extensions=None):
    if extensions is None:
        extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
    extensions = {ext.lower() for ext in extensions}
    
    image_files = []
    # 检查文件夹是否存在
    if not os.path.exists(folder_path):
        logger.warning(f"文件夹 {folder_path} 不存在")
        return image_files
        
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if os.path.splitext(file)[1].lower() in extensions:
                full_path = os.path.join(root, file)
                image_files.append(full_path)
    return image_files

def extract_integers(text):
    pattern = r'-?\b\d+\b'
    matches = re.findall(pattern, text)
    return [str(match) for match in matches]

@register("jm", "iamfromchangsha", "一个简单的插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        if not JMCOMIC_AVAILABLE:
            logger.error("jmcomic模块不可用，插件功能受限")
    
    @filter.command("jm")
    async def jm(self, event: AstrMessageEvent):
        if not JMCOMIC_AVAILABLE:
            yield event.plain_result("错误：jmcomic模块未安装，无法使用此功能")
            return
            
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(f"用户 {user_name} 请求: {message_str}")
        yield event.plain_result(f"{user_name}, 正在查找 {message_str}!")

        try:
            ids = extract_integers(message_str)
            if not ids:
                yield event.plain_result("错误：未能从消息中提取到有效的数字ID")
                return

            option_path = pathlib.Path(__file__).parent.resolve() / "option.yml"
            if not option_path.exists():
                yield event.plain_result(f"错误：配置文件不存在: {option_path}")
                return

            option = jmcomic.create_option_by_file(str(option_path))
            jmcomic.download_albums(ids, option)

            download_dir = pathlib.Path(__file__).parent.resolve() / "download"
            images = find_images_os(str(download_dir))
            if not images:
                yield event.plain_result("未找到下载的图片")
                return

            for img in images:
                if os.path.exists(img):
                    yield event.image_result(img)
                    await asyncio.sleep(1)  
                else:
                    logger.warning(f"图片文件不存在: {img}")

        except Exception as e:
            logger.exception("处理请求时出错")
            yield event.plain_result(f"处理请求时出错: {str(e)}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        pass  