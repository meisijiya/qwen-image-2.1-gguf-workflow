# Repository Guidelines

## Project Overview

本仓库存放 **Qwen-Image-2.1 Uncensored（GGUF 量化版）在 ComfyUI 中的工作流产物**。

它**不是软件工程项目**：没有构建系统、没有包管理、没有单元测试、没有应用源码。唯一的产物类型是 ComfyUI 工作流 JSON。运行时（ComfyUI 内核、自定义节点、模型权重）全部在这台机器的 ComfyUI Desktop 安装目录里，不在版本控制内。

上游来源：
- 权重 `abenzerps/Qwen-Image-2.1-Uncensored-Quantized`（原始 base 为 `Qwen/Qwen-Image-2.1`）
- 工作流模板 `Comfy-Org/workflow_templates` → `templates/image_qwen_image_2_1_t2i.json`
- GGUF 加载节点 `leejet/ComfyUI-GGUF`（**必须**，不能用 city96 版）

> ⚠️ 该权重为 uncensored 版本，无内置安全检查器。本仓库的用途仅限在本地运行已下好的工作流；不要把它接到任何对外服务或自动化链路上。

## Architecture & Data Flow

```
image_qwen_image_2_1_t2i_gguf.json   ← 本仓库唯一的产物
        │  拖入 ComfyUI 画布
        ▼
ResolutionSelector (13) ──width/height──┐
                                        ▼
              子图 c291ceec… "Text to Image (Qwen Image 2.1)"
              ┌─────────────────────────────────────────────┐
              │ UnetLoaderGGUF (451) ──MODEL──┐             │
              │ CLIPLoader (453) ──CLIP──┐     │             │
              │   └→ TextEncodeQwenImage21 (452)           │
              │        ├ positive ─┐       │             │
              │        ├ negative ─┼→ KSampler (458)      │
              │        └ latent ───┘       │             │
              │ QwenImage21Cache (480) ────┘             │
              │ VAELoader (454) ──VAE──→ VAEDecode (457)  │
              │   ↑ refine_prompt=false 时，473/471/472   │
              │     经 ComfySwitchNode(474) 旁路，不执行   │
              └─────────────────────────────────────────────┘
                                        ▼
                        SaveImageAdvanced (461) → output/
```

三个必须理解的点：

1. **模型必须成套。** GGUF 只替换 diffusion model。文本编码器（`qwen3vl_8b_int8_convrot.safetensors`）和 VAE（`qwen_image_2.1_vae_bf16.safetensors`）仍走标准 safetensors 节点，不会因为换 GGUF 而省掉。
2. **`QwenImage21Cache` (480) 是 8 GB 显存的生死线。** 它把 20B 文本编码器的前缀缓存甩到内存，`device` 必须保持 `auto`；改 `off` 会每步重算前缀，慢一个量级。
3. **提示词增强器默认旁路。** `refine_prompt` / `thinking_mode` 默认 false，`ComfySwitchNode (474)` 走 on_false 分支，因此不需要 `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors`。一旦打开 refine_prompt 而模型缺失，运行时会直接报错。

## Key Directories

仓库内：

| 路径 | 用途 |
|---|---|
| `image_qwen_image_2_1_t2i_gguf.json` | 唯一产物。官方 t2i 模板 + `UNETLoader → UnetLoaderGGUF` 改造 |
| `AGENTS.md` | 本文件 |

仓库外（运行时，**不要提交，也不要在此建仓**）：

| 路径 | 用途 |
|---|---|
| `D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\` | ComfyUI 内核 0.39.2 |
| `D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\logs\` | 运行日志（排查第一现场） |
| `D:\Comfy-Desktop\ComfyUI-Shared\models\` | 模型根：`diffusion_models/` `text_encoders/` `vae/` |
| `D:\Comfy-Desktop\ComfyUI-Shared\input\` | 工作流 JSON 投放目录（`--input-directory`） |
| `D:\Comfy-Desktop\ComfyUI-Shared\output\` | 出图目录 |

## Development Commands

本仓库无构建/测试/lint。以下是**验证工作流改动是否有效**的实际命令。

```powershell
# 0) 权威解释器（Desktop 后端实际使用的那个，不要换）
$PY = "D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\.venv\Scripts\python.exe"

# 1) 语法自检：工作流必须是合法 JSON，且关键节点存在
$PY -c "import json;d=json.load(open('image_qwen_image_2_1_t2i_gguf.json',encoding='utf-8'));\
s=d['definitions']['subgraphs'][0];print([n['type'] for n in s['nodes'] if n['id']==451])"

# 2) 确认 GGUF 节点已被内核加载，且能看到权重
curl.exe --noproxy '*' http://127.0.0.1:8188/object_info | findstr UnetLoaderGGUF

# 3) 确认内核版本 / 内存
curl.exe --noproxy '*' http://127.0.0.1:8188/system_stats
```

**投放工作流**（改完 JSON 后复制一份到 input 目录，前端「工作流 → 打开」里才选得到）：

```powershell
Copy-Item image_qwen_image_2_1_t2i_gguf.json D:\Comfy-Desktop\ComfyUI-Shared\input\
```

## Code Conventions & Common Patterns

工作流 JSON 是手改产物，遵循这些约定：

**⚠️ 两套 link schema，不要混用**
- 顶层 `links`：数组的数组，`[link_id, origin_id, origin_slot, target_id, target_slot, type]`，共 3 条
- 子图 `links`：对象数组，`{id, origin_id, origin_slot, target_id, target_slot, type}`，共 34 条

**⚠️ `widgets_values_named` 必须随节点类型一起改**
大部分节点同时带 `widgets_values`（位置数组）和 `widgets_values_named`（键值字典）。改节点类型时必须**删除或重写** `widgets_values_named`，否则前端会用旧键名渲染出错的控件。当前 `UnetLoaderGGUF (451)` 已删除该字段，因为上游 `UNETLoader` 的 `weight_dtype` 在 GGUF 节点上不存在。

**`properties.models` 会过期**
`CLIPLoader (453)` 和 `VAELoader (454)` 带 `properties.models`，含 `name` / `url` / `directory`。这是给「缺模型时前端自动下载」用的。改模型文件时**必须同步更新**，否则前端会指向错误文件。注意节点 451 上该字段已被删除（GGUF 节点不提供自动下载）。

**⚠️ MarkdownNote 463 现在是错的**
`Note: Model links` 里 `diffusion_models` 一节仍写 `qwen_image_2.1_int8_convrot.safetensors` (6.76 GB)，而本工作流实际加载的是 `qwen-image-2.1-UC-Q4_K_M.gguf`。下同目录的 `Model Storage Location` 树状图也是错的（列的是 safetensors，且完全没提 GGUF）。**改模型时顺手修这里。**

**采样参数沿用官方推荐，不要动**
`cfg=1.0`（Qwen Image 2.1 固定）、`steps=25`、`sampler_name=euler`、`scheduler=simple`。`cfg` 调到 1 以上会明显劣化。

## Runtime / Tooling Preferences

| 项 | 值 | 说明 |
|---|---|---|
| 权威解释器 | `ComfyUI\.venv\Scripts\python.exe` | Python 3.13.12，uv 0.12.9 建的 venv，base 在 `..\standalone-env` |
| pip 装包形式 | `& $PY -m pip install <pkg>` | **必须绝对路径 + `&` 调用**。相对路径 `./ComfyUI/.venv/Scripts/python.exe` 在 bash 下报 `command not found` |
| 后端端口 | **8188** | 不是 8000 |
| 代理 | 全部本地请求需绕过 | `curl.exe --noproxy '*'`；Python 端必须用 `urllib.request.build_opener(urllib.request.ProxyHandler({}))`，默认 opener 会走系统代理导致 `WinError 10061` |
| 显卡 | RTX 4060 Laptop，8 GB | 配 31 GB 系统内存 |

**自定义节点依赖必须手动装。** ComfyUI Desktop **不会**执行 `custom_nodes/*/requirements.txt`。GGUF 节点装完默认是坏的：

```
ModuleNotFoundError: No module named 'gguf'
[WARNING] Cannot import ...\custom_nodes\ComfyUI-GGUF module for custom nodes: No module named 'gguf'
[INFO]    0.0 seconds (IMPORT FAILED): ...\custom_nodes\ComfyUI-GGUF
```

修复（当前已装：`gguf 0.19.0`、`protobuf 7.36.2`、`sentencepiece 0.2.2`）：

```powershell
& $PY -m pip install "gguf>=0.13.0" sentencepiece protobuf
```

**GGUF 节点必须是 leejet fork。** city96 老版遇到 Qwen-Image 2.1 会报 `Unknown model architecture!`。当前 checkout remote = `https://github.com/leejet/ComfyUI-GGUF`，其 `tools/convert.py` 含 `ModelQwenImage21`。改坏了就从 remote 重装。

**装完依赖必须重启后端，且要手动拉起。** 桌面端检测到 `requirements.txt` 有新依赖时会报错提示需要重启，按提示手动重启即可；后端不会自愈。重启后 `/object_info` 里才会出现 `UnetLoaderGGUF`。

## Important Files

| 文件 | 作用 |
|---|---|
| `image_qwen_image_2_1_t2i_gguf.json` | 工作流本体。`schema version 0.4`，`last_node_id 483`，`last_link_id 713` |
| `…\ComfyUI\logs\comfyui.log` | 当前日志；历史为 `comfyui.log_<ISO时间戳>.log` |
| `…\AppData\Roaming\Comfy Desktop\settings.json` | Desktop 全局配置（`installDir` / `modelsDirs` / `inputDir` / `outputDir` / `cacheDir`） |
| `…\AppData\Roaming\Comfy Desktop\instance-model-paths\inst-*.yaml` | 生成的模型路径映射，文件头写明「do not edit manually」 |
| `…\custom_nodes\ComfyUI-GGUF\nodes.py` | `UnetLoaderGGUF` 定义，`CATEGORY = "bootleg"`；第 32 行把 `diffusion_models` / `unet` 注册为 `unet_gguf` |

## Testing & QA

本仓库**没有测试框架，也不引入**。改动按下面顺序人工验证，最后一步不可省：

1. **JSON 合法性** —— 上节命令 1 能解析，且 `451` 打印 `['UnetLoaderGGUF']`。
2. **节点已注册** —— `/object_info` 里存在 `UnetLoaderGGUF`，且 `unet_name` 枚举包含目标 gguf 文件名。**若为空或缺节点，说明后端没重启或依赖没装全，先查日志，不要改 JSON。**
3. **端到端出图** —— 提交一次最小链路，确认 `status: success` 且 output 目录出现 PNG。

最小可跑链路（8 步，用于验通路而非出片质量）：

```json
{
  "1": {"class_type":"UnetLoaderGGUF","inputs":{"unet_name":"qwen-image-2.1-UC-Q4_K_M.gguf"}},
  "2": {"class_type":"CLIPLoader","inputs":{"clip_name":"qwen3vl_8b_int8_convrot.safetensors","type":"qwen_image","device":"default"}},
  "3": {"class_type":"VAELoader","inputs":{"vae_name":"qwen_image_2.1_vae_bf16.safetensors"}},
  "4": {"class_type":"TextEncodeQwenImage21","inputs":{"clip":["2",0],"prompt":"...","negative_prompt":"","resolution":1024}},
  "6": {"class_type":"KSampler","inputs":{"model":["1",0],"positive":["4",0],"negative":["4",1],"latent_image":["4",2],"seed":1,"steps":8,"cfg":1.0,"sampler_name":"euler","scheduler":"simple","denoise":1.0}},
  "7": {"class_type":"VAEDecode","inputs":{"samples":["6",0],"vae":["3",0]}},
  "8": {"class_type":"SaveImage","inputs":{"images":["7",0],"filename_prefix":"gguf_smoke"}}
}
```

`TextEncodeQwenImage21` 的输出顺序是 `[CONDITIONING(positive), CONDITIONING(negative), LATENT]` —— 三条都要接，漏接会在提交时被拒（`required_input_missing`）。`EmptyLatentImage` 在这条链路里用不到。

**验收标准**：8 GB 显存下 1024×1024 / 8 步不出 OOM，`status: success`，产出非空 PNG。已实测通过。

## Asset Inventory

| 文件 | 位置 | 字节 |
|---|---|---|
| `qwen-image-2.1-UC-Q4_K_M.gguf` | `models/diffusion_models/` | 4,604,558,112 |
| `qwen3vl_8b_int8_convrot.safetensors` | `models/text_encoders/` | 9,350,798,360 |
| `qwen_image_2.1_vae_bf16.safetensors` | `models/vae/` | 675,509,688 |

未下载：`qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors`（仅打开 refine_prompt 时需要）。