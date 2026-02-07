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
    async def jm(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        user_id = event.get_sender_id()
        message_str = event.message_str.strip()
        message_chain = event.get_messages()
        logger.info(message_chain)

        if re.match(r'^jm\s*暂停$', message_str, re.IGNORECASE):
            JM_PAUSE_FLAG[user_id] = True
            user_download_dir = get_user_download_dir(user_id)
            clear_folder(user_download_dir)
            yield event.plain_result(f"{user_name}，已暂停漫画发送并清除服务器下载文件！")
            return

        JM_PAUSE_FLAG[user_id] = False
        
        # --- 修改开始：参考上次建议 ---
        original_message_for_display = message_str # 保存原始字符串用于显示
        album_ids_from_input = extract_integers(message_str) # 提取ID列表

        if not album_ids_from_input:
            yield event.plain_result(f"{user_name}, 未找到有效的数字ID，请检查输入。例如：/jm 123456")
            return # 如果没有找到ID，直接返回
        
        album_id_to_search = album_ids_from_input[0] # 取第一个ID用于下载和后续查询
        # --- 修改结束 ---

        yield event.plain_result(f"{user_name}, 正在查找 [{album_id_to_search}] !") # 显示要下载的ID

        # 为每个用户创建独立的下载目录
        user_download_dir = get_user_download_dir(user_id)
        clear_folder(user_download_dir)
        try:
            temp_option_file = create_temp_option(
                "./data/plugins/astrbot_plugin_jmcomic/option.yml", 
                user_download_dir
            )
            
            option = jmcomic.create_option_by_file(temp_option_file)
            # --- 修改：使用提取到的ID ---
            jmcomic.download_album(album_id_to_search, option) 
            
            images = find_images_os(user_download_dir)

            if JM_PAUSE_FLAG.get(user_id, False):
                clear_folder(user_download_dir)
                yield event.plain_result(f"{user_name}，已触发暂停，取消图片发送并清除文件！")
                return
            
            yield event.plain_result(f"共找到 {len(images)} 张图片，按顺序发送：")
            
            for i, img in enumerate(images, 1):
                if JM_PAUSE_FLAG.get(user_id, False):
                    yield event.plain_result(f"{user_name}，已暂停图片发送，剩余{len(images)-i+1}张未发送！")
                    break
                yield event.image_result(img)
                await asyncio.sleep(1)

            if JM_PAUSE_FLAG.get(user_id, False):
                yield event.plain_result(f"{user_name}，未保存到komaga")
            else:
                # 现在 album_id_to_search 已经在函数作用域内定义了
                subdir = os.listdir(user_download_dir)[0]
                for subdir in os.listdir(user_download_dir):
                    folder_path = os.path.join(user_download_dir, subdir)
                    if os.path.isdir(folder_path):
                        title = subdir 

                yield event.plain_result(f"{user_name}，正在保存,{title}")
                
                client = JmOption.default().new_jm_client()
                # --- 使用定义好的 album_id_to_search ---
                page = client.search_site(search_query=album_id_to_search) 
                album: JmAlbumDetail = page.single_album 
                
                if album is None:
                    # 现在这一行不会报 NameError 了
                    yield event.plain_result(f"{user_name}, 未能找到ID为 [{album_id_to_search}] 的本子。")
                    return # 添加return，否则会继续执行下面的代码

                # 注意：这里获取到的 tags 是一个列表，而 process_comics 期望的是一个列表
                # 但您传入的是 join 后的字符串。需要调整。
                album_tags_list = album.tags if album.tags else ['No Tags Found']
                album_author_str = album.author if album.author else 'Unknown Author'

                yield event.plain_result(f"{user_name}，正在保存,{title}")
                # --- 传入标签列表和作者字符串 ---
                process_comics(user_download_dir, album_tags_list, album_author_str) # 传入列表

                yield event.plain_result(f"{user_name}，已保存到komaga")
        except Exception as e:
            logger.error(f"用户{user_id}执行jm命令出错：{str(e)}")
            yield event.plain_result(f"{user_name}，操作出错：{str(e)}")
        finally:
            clear_folder(user_download_dir)
            if user_id in JM_PAUSE_FLAG:
                del JM_PAUSE_FLAG[user_id]

    @filter.command("jms")
    async def jms(self, event: AstrMessageEvent):
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

    # --- 新增：月排行榜 ---
    @filter.command("jmmr")
    async def jm_monthly_ranking(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(f"Received monthly ranking request from {user_name}: {message_str}")
        
        # 尝试从消息中提取页码，默认为1
        page_num_list = extract_numbers(message_str)
        page_num = int(page_num_list[0]) if page_num_list and page_num_list[0] > 0 else 1

        yield event.plain_result(f"{user_name}，正在获取月度排行榜第 {page_num} 页...")

        try:
            client = JmOption.default().new_jm_client()
            # 调用月排行榜API
            page: JmCategoryPage = client.month_ranking(page=page_num)
            
            if not page:
                 yield event.plain_result(f"{user_name}，未能获取到第 {page_num} 页的排行榜数据。")
                 return

            result = f"月度排行榜 第 {page_num} 页:\n"
            for album_id, title in page:
                result += f'[{album_id}]: {title}\n'
            
            yield event.plain_result(result.strip())

        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmmr命令出错：{str(e)}")
            yield event.plain_result(f"{user_name}，获取月度排行榜时发生错误: {str(e)}")
    # --- 新增结束 ---

    # --- 新增：周排行榜 ---
    @filter.command("jmwr")
    async def jm_weekly_ranking(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(f"Received weekly ranking request from {user_name}: {message_str}")
        
        # 尝试从消息中提取页码，默认为1
        page_num_list = extract_numbers(message_str)
        page_num = int(page_num_list[0]) if page_num_list and page_num_list[0] > 0 else 1

        yield event.plain_result(f"{user_name}，正在获取周度排行榜第 {page_num} 页...")

        try:
            client = JmOption.default().new_jm_client()
            # 调用周排行榜API
            page: JmCategoryPage = client.week_ranking(page=page_num)
            
            if not page:
                 yield event.plain_result(f"{user_name}，未能获取到第 {page_num} 页的排行榜数据。")
                 return

            result = f"周度排行榜 第 {page_num} 页:\n"
            for album_id, title in page:
                result += f'[{album_id}]: {title}\n'
            
            yield event.plain_result(result.strip())

        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmwr命令出错：{str(e)}")
            yield event.plain_result(f"{user_name}，获取周度排行榜时发生错误: {str(e)}")
    # --- 新增结束 ---

    # --- 新增：帮助命令 ---
    @filter.command("jmhelp")
    async def jm_help(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        help_text = f"""
{user_name}，欢迎使用禁漫天堂插件！
以下是可用的命令列表：

/jm <ID>          - 下载指定ID的漫画，并发送图片。
/jm 暂停          - 暂停当前正在进行的漫画下载和发送，并清理缓存。
/jms <关键词> [页码] - 搜索指定关键词的漫画，默认第1页。
/jmtag <ID>       - 查询指定ID漫画的标签。
/jmmr [页码]      - 获取月度热门排行榜，默认第1页。
/jmwr [页码]      - 获取周度热门排行榜，默认第1页。
/jmhelp           - 显示此帮助信息。

注意：[] 表示可选参数。
        """.strip()
        yield event.plain_result(help_text)
    # --- 新增结束 ---

    @filter.command("jmtag")
    async def jmtag(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        original_message_str = event.message_str # 保存原始消息字符串
        logger.info(f"Received command from {user_name}: {original_message_str}")
        
        # 提取数字，假设第一个数字就是要查询的album ID
        album_ids = extract_integers(original_message_str)
        
        if not album_ids:
            yield event.plain_result(f"{user_name}, 未找到有效的数字ID，请检查输入。例如：/jmtag 123456")
            return
            
        album_id_to_search = album_ids[0] # 取第一个找到的数字作为ID
        
        # 不再修改原始message_str用于显示
        yield event.plain_result(f"{user_name}, 查询本子 [{album_id_to_search}] 的标签!")

        try:
            client = JmOption.default().new_jm_client()
            # 直接使用提取到的数字ID进行搜索
            page = client.search_site(search_query=str(album_id_to_search)) # 确保传入字符串
            # 使用正确的属性名 .single_album
            album: JmAlbumDetail = page.single_album 

            # 检查是否成功获取到album对象 (虽然按理说查ID应该能找到，但以防万一)
            if album is None:
                yield event.plain_result(f"{user_name}, 未能找到ID为 [{album_id_to_search}] 的本子。")
                return

            tags_str = ', '.join(album.tags) if album.tags else '无标签' # 将标签列表转为字符串
            yield event.plain_result(f"[{album_id_to_search}]:\n{album.title}\n标签: {tags_str}") # 显示ID, 标题和标签
            
        except AttributeError as e:
            if "'JmSearchPage' object has no attribute 'single_album'" in str(e):
                # 这种情况理论上不应该发生在查ID时，除非ID无效
                yield event.plain_result(f"{user_name}, 搜索结果不唯一或无效，无法获取详情。")
            else:
                logger.error(f"AttributeError in jmtag: {e}")
                yield event.plain_result(f"{user_name}, 获取标签时发生错误 (AttributeError): {e}")
        except Exception as e:
            logger.error(f"用户{event.get_sender_id()}执行jmtag命令出错：{str(e)}")
            yield event.plain_result(f"{user_name}, 获取标签时发生错误: {str(e)}")   
    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # 插件销毁时清空所有暂停标识
        JM_PAUSE_FLAG.clear()