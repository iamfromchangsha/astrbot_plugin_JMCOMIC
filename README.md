# jmcomic 插件说明文档

> 适用于 [AstrBot](https://github.com/Soulter/AstrBot) 的禁漫天堂（JMComic）插件，支持通过指令搜索和下载漫画。

---

## ✨ 功能特性

- **`/jm <漫画ID>`**：根据漫画 ID 下载整本漫画并逐张发送图片。
- **`/jms <关键词> [页码]`**：根据关键词搜索漫画，支持指定页码，默认为第 1 页。

---

## 📦 安装

1. 确保已安装 [AstrBot](https://github.com/Soulter/AstrBot)。
2. 将本插件文件夹放入 AstrBot 的 `plugins` 目录中。
3. 安装依赖：
   ```bash
   pip install jmcomic
   ```
4. 在插件目录下创建配置文件：
   ```
   ./data/plugins/astrbot_plugin_jmcomic/option.yml
   ```
   示例 `option.yml` 内容（请根据你的需求修改）：
   ```yaml
   dir: ./data/plugins/astrbot_plugin_jmcomic/download
   ```

---

## 🧩 使用说明

### 1. 下载漫画 `/jm`

**指令格式**：
```
/jm <漫画ID>
```

**示例**：
```
/jm 456789
```

**行为**：
- 插件会从消息中提取所有整数作为漫画 ID（支持多个 ID，但通常只用一个）。
- 自动下载漫画到指定目录。
- 按文件名中的数字顺序发送所有图片（每张间隔 1 秒）。
- 发送完成后自动清空下载目录。

---

### 2. 搜索漫画 `/jms`

**指令格式**：
```
/jms <关键词> [页码]
```

**示例**：
```
/jms 巨乳 2
```

**行为**：
- 从消息中提取第一个数字作为页码（若无则默认为 1）。
- 剩余文本作为搜索关键词。
- 返回该页的漫画列表，格式为 `[ID]: 标题`。

> ⚠️ 注意：关键词中不要包含数字，否则会被误认为页码。

---

## 📁 目录结构

插件运行时依赖以下目录结构：

```
astrbot/
└── data/
    └── plugins/
        └── astrbot_plugin_jmcomic/
            ├── option.yml          # jmcomic 配置文件
            └── download/           # 临时下载目录（自动创建/清空）
```

确保 `download` 目录有读写权限。

---

## 🔒 注意事项

- 本插件调用 `jmcomic` 库，需自行处理账号、Cookie 等认证信息（在 `option.yml` 中配置）。
- 请遵守当地法律法规，合理使用本插件。
- 频繁请求可能导致 IP 被封，请勿滥用搜索或下载功能。

---

## 🛠 开发者信息

- 插件名称：`jm`
- 作者：`iamfromchangsha`
- 版本：`1.0.0`

---

## 📜 依赖

- `astrbot` >= v4.0
- `jmcomic` >= 2.0
- Python >= 3.8

---

> 🌟 Enjoy your reading! 请合法合规使用本插件。