# 电影视频分析插件

面向 ChatGPT Work Mode / Codex 的私人插件市场，包含一个 `cinematic-video-analysis` 插件和三个独立技能：

- `analyze-shots`：切镜检测、时间码、关键帧、联系表和镜头清单。
- `analyze-cinematic-visuals`：景别、机位、构图、运镜、光影、色彩与人物调度。
- `check-continuity`：人物、服装、伤情、道具、轴线、空间和动作连续性。

## 安装

仓库发布后，在 Codex 中添加 Git 市场并安装插件：

```bash
codex plugin marketplace add littlefairy0206/Lian --ref main
codex plugin add cinematic-video-analysis@cinematic-tools
```

安装后新建 Work Mode 对话，输入 `@` 选择“电影视频分析”。

## 验证与更新

```bash
python3 scripts/release.py check
python3 scripts/release.py bump
```

需要自动保存并推送新版本时：

```bash
python3 scripts/release.py bump --push
```

更新已安装插件：

```bash
codex plugin marketplace upgrade cinematic-tools
codex plugin add cinematic-video-analysis@cinematic-tools
```

每次升级后使用新对话加载新版本。
