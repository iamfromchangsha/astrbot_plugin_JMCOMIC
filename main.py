from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import jmcomic
import re
import os
import time

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
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    @filter.command("jm")
    async def helloworld(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
        logger.info(message_chain)
        yield event.plain_result(f"{user_name}, 正在查找 {message_str}!") # 发送一条纯文本消息
        message_str = extract_integers(message_str)
        option = jmcomic.create_option_by_file("./data/plugins/astrbot_plugin_jmcomic/option.yml")
        jmcomic.download_album(message_str, option)
        images = find_images_os("./data/plugins/astrbot_plugin_jmcomic/download")
        for img in  images:
            yield event.image_result(img)
            time.sleep(1)
    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""