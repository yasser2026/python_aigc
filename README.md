# 小说转短视频 (Novel to Short Video)

基于 **FastAPI + JSON 配置** 的 AIGC 流水线 MVP：通义千问（DashScope）分镜、ComfyUI / Mock 生图、Edge TTS 配音、FFmpeg Ken Burns 与成片合成。

## 技术栈

| 环节 | 技术 |
|------|------|
| API | FastAPI + Uvicorn |
| 配置 | `config/*.json` + `.env` 密钥 |
| 分镜 | 通义千问 DashScope API（OpenAI 兼容） |
| 图像 | ComfyUI HTTP API + IP-Adapter（可 `mock`） |
| 配音 | edge-tts |
| 视频 | FFmpeg（Ken Burns、concat、字幕烧录） |

## 环境要求

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) 已加入 `PATH`（含 `ffprobe`）
- （可选）本地 [ComfyUI](https://github.com/comfyanonymous/ComfyUI)，默认 `http://127.0.0.1:8188`
- 阿里云 DashScope API Key（通义千问）

## 快速开始

```bash
cd python_agic
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # 填入 DASHSCOPE_API_KEY
python run.py
```

服务默认：`http://127.0.0.1:8000`  
文档：`http://127.0.0.1:8000/docs`

### Web 前端（Vue）

```bash
cd aigc_front && npm install && npm run dev
```

打开 http://127.0.0.1:5173 ，填写短剧名称、集数、剧情后生成并下载。侧栏 **作品集** 可浏览 `data/` 下已完成的成片并预览下载。

### 作品集 API

```bash
curl http://127.0.0.1:8000/portfolio
```

返回所有含 `output/final.mp4` 的项目；封面图：`GET /portfolio/{小说名/第01集}/poster`。

### 健康检查

```bash
curl http://127.0.0.1:8000/health
```

返回 FFmpeg / ComfyUI 是否可用；`comfyui_mock: true` 表示使用占位图（见 `config/comfyui.json` 的 `"mock": true`）。

### 创建项目

```bash
curl -X POST http://127.0.0.1:8000/projects ^
  -H "Content-Type: application/json" ^
  -d "{\"novel_name\": \"盘龙\", \"episode\": 1, \"text\": \"夜色如墨，少年推门而入……\"}"
```

响应示例：

```json
{"project_id": "盘龙/第01集", "novel_name": "盘龙", "episode": 1, "work_dir": "...", "status": "pending"}
```

### 查询进度

```bash
curl "http://127.0.0.1:8000/projects/盘龙/第01集"
```

状态流转：`pending` → `parsing` → `imaging` → `audio` → `motion` → `subtitles` → `assembling` → `done`

### 下载成片

```bash
curl -O -J "http://127.0.0.1:8000/projects/盘龙/第01集/download"

curl.exe -s http://127.0.0.1:8000/projects/9f66d69e-1652-44f4-b604-e3fbc183f258
```

产物目录：`data/{小说名}/第{集数}集/`

```
data/盘龙/第01集/
├── meta.json        # 小说名、集数
├── scenes.json      # 分镜与角色
├── images/          # 场景图
├── audio/           # TTS mp3
├── clips/           # 分镜视频
├── subs/full.ass    # 字幕
└── output/final.mp4 # 成片
```

## 配置说明

所有业务参数在 `config/` 下 JSON 文件中，密钥通过 `${ENV_VAR}` 引用：

| 文件 | 作用 |
|------|------|
| `app.json` | 端口、数据目录、`image_provider`（qwen / comfyui / mock） |
| `image.json` | 千问生图模型、尺寸、`rate_limit_rpm`（默认 2）、`request_interval_sec`、429 重试 |
| `llm.json` | 千问 DashScope 地址、模型、分镜 system prompt |
| `comfyui.json` | ComfyUI 地址、`mock`、节点字段映射 |
| `tts.json` | edge-tts 音色 |
| `ffmpeg.json` | 分辨率 1080×1920、Ken Burns、字幕样式 |
| `pipeline.json` | 场景数上限、阶段列表、重试次数 |

### 生图方式（`config/app.json` → `image_provider`）

| 值 | 说明 |
|----|------|
| **`qwen`**（默认） | 阿里百炼 **Qwen-Image**，模型见 `config/image.json` |
| **`comfyui`** | 本地 ComfyUI + IP-Adapter（需 NVIDIA GPU） |
| **`mock`** | 本地占位图（大号中文旁白，无 API 费用） |

```json
"image_provider": "qwen"
```

千问生图 `qwen-image-2.0-pro-2026-04-22` 任务派发约 **2 次/分钟**，默认串行且场景间隔 **32s**（`request_interval_sec`），遇 **429** 按 `retry.backoff_sec`（35s / 45s / 60s / 90s）退避，最多 6 次。分镜较多时整段生图会较慢，属正常限流。

### 角色 / 场所一致性（Milvus + ref_image）

- **向量库**：`config/milvus.json`（默认 `enabled: true`，`uri: http://127.0.0.1:19530`）。分镜后把主角、配角、场所的文本设定写入 **Milvus**（DashScope `text-embedding-v3`）；新集按语义检索合并历史 `appearance` / `description`。Milvus 不可用时自动降级到 `data/milvus_fallback.json`。
- **参考图**：`data/{小说名}/characters/{char_id}/ref.png`；`characters.json` / `locations.json` 与向量库同步。
- **生图**：先补角色立绘参考图，场景图带参考图调用 Qwen（`use_character_ref`）或 ComfyUI IP-Adapter；场景 prompt 注入向量库检索到的角色与场所描述。
- 启动 Milvus（Docker 示例）：`docker run -d --name milvus -p 19530:19530 milvusdb/milvus:latest`

全片画风在 `config/image.json` 的 `style_prefix` / `style_suffix` 统一（默认：手绘动漫、宫崎骏相似风格）。想换风格只改这两项和 `llm.json` 里的画风说明即可。

### 接入 ComfyUI（仅 `image_provider: "comfyui"`）

1. 启动 ComfyUI：`python main.py --listen`
2. 导出工作流到 `workflows/ipadapter_scene.json`，更新 `config/comfyui.json` 的 `input_mappings`
3. `config/comfyui.json` 设 `"mock": false`

### 无 API Key 本地调试

在 `config/llm.json` 中设置 `"mock": true`，将使用内置示例分镜，无需 DashScope 密钥。

### 环境变量（`.env`）

```
DASHSCOPE_API_KEY=sk-...
COMFYUI_HOST=http://127.0.0.1:8188
```

创建任务时 **`novel_name`、`episode`（第几集）、`text`（正文）均为必填**。

## 流水线阶段

```mermaid
flowchart LR
  A[parse_scenes] --> B[generate_images]
  B --> C[tts]
  C --> D[motion_clips]
  D --> E[subtitles]
  E --> F[assemble]
```

TTS 在动效之前执行，以便按旁白时长生成镜头，避免音画不同步。

## 二期扩展（未实现）

- Celery + Redis 任务队列
- Kling / Runway 图生视频（`pipeline.json` → `motion.mode: i2v`）
- 对象存储 OSS、质量评分过滤

## 常见问题

**`DASHSCOPE_API_KEY not set`**  
复制 `.env.example` 为 `.env` 并填写阿里云百炼 / DashScope 密钥。

**`ffmpeg not found`**  
安装 FFmpeg 并确保 `ffmpeg`、`ffprobe` 在 PATH 中。

**ComfyUI 超时**  
检查 GPU 服务是否运行；开发阶段可保持 `"mock": true` 用占位图跑通全流程。

**字幕未显示**  
Windows 需安装 `config/ffmpeg.json` 中指定的字体（默认微软雅黑），或修改 `subtitle.font_name`。
