# astrbot_plugin_JMCOMIC

> 适用于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) **4.x** 的禁漫天堂（JMComic）插件。
> 本分支 `feature/astrbot4-rewrite` 为面向 AstrBot 4.x 的移植重构版，在原版基础上加入了大量增强特性。

## ✨ 本分支新增 / 增强

- **AstrBot 4.x API 完整移植**：基于 `star.Star` / `star.Context` / `filter.command` 新接口重写。
- **自动剔除韩漫与合集**：三层韩漫识别（标签 / 谚文字符 / 连载状态）+ 多章节合集检测，搜索、推荐、排行、相似结果全部过滤。
- **逐张压缩发送**：下载过程中每张图片即时压缩（JPEG q80 / 最长边 1200px），节省流量、防止内存与磁盘溢出。
- **`/jmrec <本子ID>` 相似推荐**：分析目标本子的题材标签，按多标签命中度排序推荐同类型作品。
- **`/jmauthor <本子ID>` 作者作品**：输入任意本子编号，返回该作者的全部作品列表。
- **下载容错加固**：部分图片下载失败时自动补下重试一轮（利用 cache 机制只补失败图）；仍失败则跳过继续，不再整体中断。
- **资源安全护栏**：合集章节数 / 总页数 / 磁盘剩余 / 内存水位 / 图片总体积 / PDF 体积 / 下载与合成超时多重护栏，超限直接拒绝或暂停，防止低配服务器被拖垮。

## 📋 命令一览

| 命令 | 说明 |
|------|------|
| `/jm <漫画ID>` | 下载整本漫画并逐张发送图片（下载中逐张压缩） |
| `/jm 暂停` | 暂停当前下载/发送任务并清理临时文件 |
| `/jmpdf <漫画ID>` | 下载漫画并合成 PDF 以文件形式发送 |
| `/jms <关键词> [页码]` | 关键词搜索漫画（自动过滤韩漫与合集） |
| `/jmrec [分类] [页码]` | 分类热门推荐（按观看数排序） |
| `/jmrec <本子ID>` | 🎯 相似推荐：分析题材，推荐同类型本子 |
| `/jmday` | 日 / 周 / 月三榜热门排行 |
| `/jmmr [页码]` | 月榜热门排行 |
| `/jmwr [页码]` | 周榜热门排行 |
| `/jmtag <漫画ID>` | 查询指定漫画的标签信息 |
| `/jmauthor <漫画ID>` | 👤 查询该作者的全部作品 |
| `/jmhelp` | 查看帮助 |

## 🔧 安装

将本仓库克隆到 AstrBot 的 `data/plugins/` 目录下（或通过 WebUI 填写插件仓库地址安装）：

```bash
cd AstrBot/data/plugins
git clone -b feature/astrbot4-rewrite https://github.com/iamfromchangsha/astrbot_plugin_JMCOMIC.git astrbot_plugin_JMCOMIC
```

依赖（jmcomic / Pillow / img2pdf 等）会在 AstrBot 载入插件时自动安装。

## ⚙️ 配置

`option.yml` 为 jmcomic 的下载配置，其中 `dir_rule.base_dir` 指定下载缓存目录；插件会在每次下载时基于它生成临时配置（并发 photo=1 / image=2，按需覆盖）。如需账号登录（部分漫画需要），在 `plugins.after_init` 的 `login` 段填写 jmcomic 账号。

插件数据目录默认为 `./data/plugins/astrbot_plugin_JMCOMIC`，用户下载缓存位于其下 `download/<user_id>/`，每次任务开始前自动清空。

## 🛡️ 安全护栏默认值

| 护栏项 | 阈值 |
|--------|------|
| 合集章节数上限 | 5 章 |
| 总页数上限 | 200 页 |
| 磁盘剩余下限 | 50 MB（下载前检查 + 下载中监控） |
| 内存可用下限 | 60 MB |
| 图片总体积上限 | 120 MB |
| PDF 体积上限 | 100 MB |
| 下载超时 | 900 秒 |
| PDF 合成超时 | 600 秒 |

## 📄 License

GPL-2.0（见 LICENSE）
