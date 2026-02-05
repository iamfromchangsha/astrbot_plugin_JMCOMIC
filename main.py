from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import jmcomic
from jmcomic import *
import re
import os
import time
import shutil
import asyncio
import logging
import yaml  # 提前导入，避免函数内重复导入
import zipfile
import random
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString


logger = logging.getLogger("jmcomic_plugin")

# 全局暂停标识字典：key=用户ID，value=是否暂停（bool），实现多用户隔离
JM_PAUSE_FLAG = {}

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

def get_user_download_dir(user_id):
    """
    为每个用户生成独立的下载目录路径
    """
    base_dir = "./data/plugins/astrbot_plugin_jmcomic"
    user_dir = os.path.join(base_dir, "download", user_id)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def create_comic_info_xml(title="Default Title", author="Unknown", tags=None):
    """
    创建包含标签的ComicInfo.xml字符串
    """
    comicinfo = Element('ComicInfo')
    title_elem = SubElement(comicinfo, 'Title')
    title_elem.text = title
    author_elem = SubElement(comicinfo, 'Writer')
    author_elem.text = author
    
    if tags:
        tags_elem = SubElement(comicinfo, 'Tags')  # 使用'Tags'元素来存储标签
        tags_elem.text = ", ".join(tags)
    
    rough_string = tostring(comicinfo, 'utf-8')
    reparsed = parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

def add_comic_info_to_folder(folder_path, title="Default Title", author="Unknown", tags=None):
    """
    在指定漫画文件夹中添加ComicInfo.xml
    """
    xml_content = create_comic_info_xml(title=title, author=author, tags=tags)
    with open(os.path.join(folder_path, 'ComicInfo.xml'), 'w', encoding='utf-8') as f:
        f.write(xml_content)
    print(f"Added ComicInfo.xml to {folder_path}")
def make_cbz(folder_path, output_filename):
    """
    将漫画文件夹压缩为CBZ文件
    """
    with zipfile.ZipFile(output_filename, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, start=folder_path)
                zf.write(full_path, arcname=arcname)
    print(f"Created {output_filename}")

def process_comics(main_folder,albumtags,albumauthor):
    """
    遍历主文件夹中的所有漫画文件夹，并为每个文件夹创建CBZ文件
    """
    for subdir in os.listdir(main_folder):
        folder_path = os.path.join(main_folder, subdir)
        if os.path.isdir(folder_path):
            title = subdir  # 使用文件夹名称作为漫画标题
            author = albumauthor
            tags = albumtags  # 根据需要修改标签
            
            add_comic_info_to_folder(folder_path, title=title, author=author, tags=tags)
            make_cbz(folder_path,  f"/opt/AstrBot/data/plugins_data/jmcomic/{subdir}.cbz")

def create_temp_option(option_file, user_download_dir):
    """
    创建临时配置文件，将下载目录指向用户的独立目录
    """
    # 读取原始配置
    with open(option_file, 'r', encoding='utf-8') as f:
        option_data = yaml.safe_load(f)
    
    # 修改下载目录
    option_data['dir_rule']['base_dir'] = user_download_dir
    
    # 创建临时配置文件
    temp_option_file = os.path.join(user_download_dir, "temp_option.yml")
    with open(temp_option_file, 'w', encoding='utf-8') as f:
        yaml.dump(option_data, f, allow_unicode=True)
    
    return temp_option_file

@register("jm", "iamfromchangsha", "一个简单的插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    @filter.command("jm")
    async def helloworld(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        user_id = event.get_sender_id()  # 获取用户ID以区分不同用户
        message_str = event.message_str.strip() # 去除首尾空格，避免匹配问题
        message_chain = event.get_messages()
        logger.info(message_chain)

        # 1. 暂停指令判断：匹配/jm 暂停（忽略空格）
        if re.match(r'^jm\s*暂停$', message_str, re.IGNORECASE):
            JM_PAUSE_FLAG[user_id] = True  # 设置当前用户暂停标识为True
            # 清除该用户下载目录并提示
            user_download_dir = get_user_download_dir(user_id)
            clear_folder(user_download_dir)
            yield event.plain_result(f"{user_name}，已暂停漫画发送并清除服务器下载文件！")
            return  # 直接返回，终止后续逻辑

        # 2. 非暂停指令：重置当前用户的暂停标识为False（开始新的下载/发送）
        JM_PAUSE_FLAG[user_id] = False
        yield event.plain_result(f"{user_name}, 正在查找 {message_str}!")
        message_str = extract_integers(message_str)
        
        # 为每个用户创建独立的下载目录
        user_download_dir = get_user_download_dir(user_id)
        # 先清空目录，避免残留旧文件
        clear_folder(user_download_dir)
        try:
            temp_option_file = create_temp_option(
                "./data/plugins/astrbot_plugin_jmcomic/option.yml", 
                user_download_dir
            )
            
            option = jmcomic.create_option_by_file(temp_option_file)
            jmcomic.download_album(message_str, option)
            images = find_images_os(user_download_dir)
            
            # 检查是否在下载后被暂停
            if JM_PAUSE_FLAG.get(user_id, False):
                clear_folder(user_download_dir)
                yield event.plain_result(f"{user_name}，已触发暂停，取消图片发送并清除文件！")
                return
            
            yield event.plain_result(f"共找到 {len(images)} 张图片，按顺序发送：")
            
            # 3. 图片发送循环：每次发送前检查暂停标识
            for i, img in enumerate(images, 1):
                # 暂停标识为True时，立即终止循环
                if JM_PAUSE_FLAG.get(user_id, False):
                    yield event.plain_result(f"{user_name}，已暂停图片发送，剩余{len(images)-i+1}张未发送！")
                    break
                yield event.image_result(img)  # 发送图片
                await asyncio.sleep(1)


            if JM_PAUSE_FLAG.get(user_id, False):
                yield event.plain_result(f"{user_name}，未保存到komaga")
            else:
                # client = JmOption.default().new_jm_client()
                subdir = os.listdir(user_download_dir)[0]  # 假设只有一个下载的漫画文件夹
                for subdir in os.listdir(user_download_dir):
                    folder_path = os.path.join(user_download_dir, subdir)
                    if os.path.isdir(folder_path):
                        title = subdir 
             # 使用文件夹名称作为漫画标题
                # page = client.search_site(search_query=str(message_str))
                # album: JmAlbumDetail = page.single_album
                yield event.plain_result(f"{user_name}，正在保存,{title}")
                process_comics(user_download_dir,'None','None')

                yield event.plain_result(f"{user_name}，已保存到komaga")
        except Exception as e:
            logger.error(f"用户{user_id}执行jm命令出错：{str(e)}")
            yield event.plain_result(f"{user_name}，操作出错：{str(e)}")

        finally:
            
            # 4. 最终清理：无论是否暂停，结束后清空下载目录
            clear_folder(user_download_dir)
            # 重置暂停标识，避免影响下次操作
            if user_id in JM_PAUSE_FLAG:
                del JM_PAUSE_FLAG[user_id]

    @filter.command("jms")
    async def helloworld2(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(f"Received command from {user_name}: {message_str}")
        pages = int(extract_numbers(message_str)[0]) if extract_numbers(message_str) else 1
        message_str = re.sub(r'\d', '', message_str)
        yield event.plain_result(f"{user_name}, {message_str}这种题材实在是太涩啦!页面：{pages}")
        client = JmOption.default().new_jm_client()
        page: JmSearchPage = client.search_site(search_query=message_str, page=pages)
        result = ""
        for album_id, title in page:
            result += f'[{album_id}]: {title}\n'
        yield event.plain_result(result)
            
    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # 插件销毁时清空所有暂停标识
        JM_PAUSE_FLAG.clear()