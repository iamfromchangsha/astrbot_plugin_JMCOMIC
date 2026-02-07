# jmcomic 插件说明文档

> 适用于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的禁漫天堂（JMComic）插件，支持通过指令搜索、下载漫画、查看排行榜和标签。


## ✨ 功能特性

- **`/jm <漫画ID>`**：根据漫画 ID 下载整本漫画并逐张发送图片。
- **`/jms <关键词> [页码]`**：根据关键词搜索漫画，支持指定页码，默认为第 1 页。
- **`/jm 暂停`**：在下载或发送过程中，暂停当前任务并清除服务器上的临时文件。
- **`/jmtag <漫画ID>`**：查询指定漫画 ID 的详细标签信息。
- **`/jmmr [页码]`**：获取月度热门排行榜，默认第 1 页。
- **`/jmwr [页码]`**：获取周度热门排行榜，默认第 1 页。
- **`/jmhelp`**：显示插件的帮助信息。


## 📦 安装

1. 确保已安装 [AstrBot](https://github.com/AstrBotDevs/AstrBot)。
2. 将本插件文件夹放入 AstrBot 的 `plugins` 目录中。
3. 安装依赖：
   ```bash
   pip install jmcomic pyyaml
   ```
4. 在插件目录下创建配置文件：
   - `./data/plugins/astrbot_plugin_jmcomic/option.yml`

   示例 `option.yml` 内容（请根据你的需求修改，特别是 `base_dir`，但插件会动态覆盖它以实现用户隔离）：
   ```yaml
   dir_rule:
     base_dir: ./data/plugins/astrbot_plugin_jmcomic/download # 插件会忽略此项，使用用户专属目录
     album_dir_rule: '{id}'
   download:
     image_suffix: ''
     way: sequential
   cache:
     album_count: 5
   ```

---

## 🧩 使用说明

### 1. 下载漫画 `/jm`

- **指令格式**：
  ```
  /jm <漫画ID>
  ```
  或
  ```
  /jm 暂停
  ```
- **示例**：
  ```
  /jm 456789
  ```
- **行为**：
  - 插件会从消息中提取第一个整数作为漫画 ID。
  - 自动为用户创建独立的临时下载目录并下载漫画。
  - 按文件名中的数字顺序发送所有图片（每张间隔 1 秒）。
  - 发送完成后，会尝试将漫画打包成 CBZ 文件并保存到 `/opt/AstrBot/data/plugins_data/jmcomic/` 目录下（此路径硬编码在 `process_comics` 函数中）。
  - 无论成功与否，最后都会自动清空用户的临时下载目录。
  - 输入 `/jm 暂停` 可以中断当前的下载或发送流程。

### 2. 搜索漫画 `/jms`

- **指令格式**：
  ```
  /jms <关键词> [页码]
  ```
- **示例**：
  ```
  /jms 全彩 2
  ```
- **行为**：
  - 从消息中提取最后一个数字作为页码（若无则默认为 1）。
  - 剩余文本作为搜索关键词。
  - 返回该页的漫画列表，格式为 `[ID]: 标题`。

### 3. 查看标签 `/jmtag`

- **指令格式**：
  ```
  /jmtag <漫画ID>
  ```
- **示例**：
  ```
  /jmtag 456789
  ```
- **行为**：
  - 根据提供的漫画 ID 查询其标题和标签信息，并返回结果。

### 4. 月度排行榜 `/jmmr`

- **指令格式**：
  ```
  /jmmr [页码]
  ```
- **示例**：
  ```
  /jmmr 3
  ```
- **行为**：
  - 获取禁漫天堂的月度热门排行榜。
  - 支持指定页码，默认为第 1 页。
  - 返回该页的漫画列表，格式为 `[ID]: 标题`。

### 5. 周度排行榜 `/jmwr`

- **指令格式**：
  ```
  /jmwr [页码]
  ```
- **示例**：
  ```
  /jmwr 2
  ```
- **行为**：
  - 获取禁漫天堂的周度热门排行榜。
  - 支持指定页码，默认为第 1 页。
  - 返回该页的漫画列表，格式为 `[ID]: 标题`。

### 6. 帮助信息 `/jmhelp`

- **指令格式**：
  ```
  /jmhelp
  ```
- **行为**：
  - 显示所有可用命令及其简要说明。

---

## 📁 目录结构

插件运行时依赖以下目录结构：
```
astrbot/
├── data/
│   └── plugins/
│       └── astrbot_plugin_jmcomic/
│           ├── option.yml          # jmcomic 配置文件
│           └── download/           # 主下载目录
│               └── /      # 每个用户的独立临时下载目录（自动创建/清空）
└── /opt/AstrBot/data/plugins_data/jmcomic/ # CBZ文件最终保存位置（硬编码）
```
确保 `download` 目录及 `/opt/AstrBot/data/plugins_data/jmcomic/` 目录有读写权限。

---

## 🔒 注意事项

- 本插件调用 `jmcomic` 库，需自行处理账号、Cookie 等认证信息（在 `option.yml` 中配置）。
- 请遵守当地法律法规，合理使用本插件。
- 频繁请求可能导致 IP 被封，请勿滥用搜索或下载功能。
- **重要**：最终的 CBZ 文件是硬编码保存到 `/opt/AstrBot/data/plugins_data/jmcomic/` 的，如果您的 AstrBot 安装路径不同，请修改代码中的 `make_cbz` 函数内的路径。

---

## 🛠 开发者信息

- **插件名称**：jm
- **作者**：iamfromchangsha
- **版本**：1.1.0

---

## 📜 依赖

- `astrbot >= v4.0`
- `jmcomic >= 2.0`
- `pyyaml`
- `Python >= 3.8`

---

## 🌟 Enjoy your reading!

请合法合规使用本插件。
