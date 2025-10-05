from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import jmcomic
import re
import os
import time
import shutil

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
    
    # 按文件名中的数字排序
    def extract_number(filename):
        # 提取文件名中的数字部分
        basename = os.path.basename(filename)
        numbers = re.findall(r'\d+', basename)
        if numbers:
            return int(numbers[0])  # 返回第一个数字
        return 0  # 如果没有找到数字，则返回0
    
    image_files.sort(key=extract_number)
    return image_files

def extract_integers(text):
    pattern = r'-?\b\d+\b'
    matches = re.findall(pattern, text)
    return [str(match) for match in matches]

def clear_folder(folder_path):
    if not os.path.exists(folder_path):
        print(f"警告: 路径不存在 - {folder_path}")
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
            print(f"无法删除 {item_path}: {e}")

@register("jm", "iamfromchangsha", "一个简单的插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    @filter.command("jm")
    async def helloworld(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链
        logger.info(message_chain)
        yield event.plain_result(f"{user_name}, 正在查找 {message_str}!") # 发送一条纯文本消息
        message_str = extract_integers(message_str)
        option = jmcomic.create_option_by_file("./data/plugins/astrbot_plugin_jmcomic/option.yml")
        jmcomic.download_album(message_str, option)
        images = find_images_os("./data/plugins/astrbot_plugin_jmcomic/download")
        yield event.plain_result(f"共找到 {len(images)} 张图片，按顺序发送：")
        
        for i, img in enumerate(images, 1):
            yield event.image_result(img)  # 发送图片
            time.sleep(1) 
        clear_folder("./data/plugins/astrbot_plugin_jmcomic/download")

            
    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""