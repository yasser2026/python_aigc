# aigc_front — 短剧 AIGC 前端

Vue 3 + Vite，对话式界面：填写**短剧名称、集数、剧情** → 调用后端生成 → 预览与下载 MP4。

## 启动

1. 后端（项目根目录）：

```bash
python run.py
```

2. 前端：

```bash
cd aigc_front
npm install
npm run dev
```

浏览器打开：http://127.0.0.1:5173

开发环境通过 Vite 代理将 `/api` 转发到 `http://127.0.0.1:8000`。

## 生产构建

```bash
npm run build
```

可将 `dist/` 用任意静态服务器托管，并设置 `VITE_API_BASE` 指向后端地址。

## 必填字段

| 字段 | 对应 API |
|------|----------|
| 短剧名称 | `novel_name` |
| 集数 | `episode` |
| 剧情 | `text` |

存储目录：`data/{小说名}/第{集数}集/`
