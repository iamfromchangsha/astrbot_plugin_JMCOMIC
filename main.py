from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import re
import os
import time

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
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        if not JMCOMIC_AVAILABLE:
            logger.error("jmcomic模块不可用，插件功能受限")
    
    # 注册指令的装饰器。指令名为 jm。注册成功后，发送 `/jm` 就会触发这个指令
    @filter.command("jm")
    async def jm(self, event: AstrMessageEvent):
        # 检查jmcomic是否可用
        if not JMCOMIC_AVAILABLE:
            yield event.plain_result("错误：jmcomic模块未安装，无法使用此功能")
            return
            
        user_name = event.get_sender_name()
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链
        logger.info(f"用户 {user_name} 请求: {message_str}")
        yield event.plain_result(f"{user_name}, 正在查找 {message_str}!") # 发送一条纯文本消息
        
        try:
            message_str = extract_integers(message_str)
            if not message_str:
                yield event.plain_result("错误：未能从消息中提取到有效的数字ID")
                return
                
            # 直接使用配置文件路径（使用绝对路径避免工作目录问题）
                
            option = jmcomic.create_option_by_file("/opt/AstrBot/data/plugins/astrbot_plugin_jmcomic/option.yml")
            jmcomic.download_albums(message_str, option)
            
            # 确保download目录存在并包含图片
            images = find_images_os("/opt/AstrBot/data/plugins/astrbot_plugin_jmcomic/download")
            if not images:
                yield event.plain_result("未找到下载的图片")
                return
                
            for img in images:
                # 检查文件是否存在
                if os.path.exists(img):
                    yield event.image_result(img)
                    time.sleep(1)  # 控制发送频率，避免过快
                else:
                    logger.warning(f"图片文件不存在: {img}")
                    
        except Exception as e:
            logger.error(f"处理请求时出错: {e}")
            yield event.plain_result(f"处理请求时出错: {str(e)}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""