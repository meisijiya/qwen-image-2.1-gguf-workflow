# Repository Guidelines

## Project Overview

本仓库存放 **Qwen-Image-2.1 Uncensored（GGUF 量化版）在 ComfyUI 中的工作流产物**。

它**不是软件工程项目**：没有构建系统、没有包管理、没有单元测试、没有应用源码。唯一的产物类型是 ComfyUI 工作流 JSON。运行时（ComfyUI 内核、自定义节点、模型权重）全部在这台机器的 ComfyUI Desktop 安装目录里，不在版本控制内。

上游来源：
- 权重 `abenzerps/Qwen-Image-2.1-Uncensored-Quantized`（原始 base 为 `Qwen/Qwen-Image-2.1`）
- 工作流模板 `Comfy-Org/workflow_templates` → `templates/image_qwen_image_2_1_t2i.json` 与 `templates/image_qwen_image_2_1_image_edit.json`
- turbo LoRA `Comfy-Org/Qwen-Image-2.1` → `loras/qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors`
- GGUF 加载节点 `leejet/ComfyUI-GGUF`（**必须**，不能用 city96 版）

**两个产物**：`image_qwen_image_2_1_t2i_gguf.json`（文生图）与 `image_qwen_image_2_1_i2i_gguf.json`（图生图 / 多参考图编辑）。两者都由上述官方模板派生，`build_i2i_workflow.py` 从模板重新生成 i2i 版，改模板约定时改脚本而不是手改 JSON。

> ⚠️ 该权重为 uncensored 版本，无内置安全检查器。本仓库的用途仅限在本地运行已下好的工作流；不要把它接到任何对外服务或自动化链路上。

## Architecture & Data Flow

```
image_qwen_image_2_1_t2i_gguf.json   ← 文生图产物
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
              │   ↓ 三级加速链（见「性能」）              │
              │ LoraLoaderModelOnly (484) Turbo 8 步      │
              │ ModelAttentionBackend (485) INT8 注意力   │
              │ EasyCache (486) 跳步复用                  │
              │ VAELoader (454) ──VAE──→ VAEDecode (457)  │
              │   ↑ refine_prompt=false 时，473/471/472   │
              │     经 ComfySwitchNode(474) 旁路，不执行   │
              └─────────────────────────────────────────────┘
                                        ▼
                        SaveImageAdvanced (461) → output/
```

```
image_qwen_image_2_1_i2i_gguf.json   ← 图生图产物
        │  拖入 ComfyUI 画布
        ▼
LoadImage (470) ──image_1──┐
LoadImage (475) ──image_2──┤   ┌─────────────────────────────────────────┐
             （image_3…10 留空）  │ 子图 bc1c967a… "Image Edit (Qwen Image 2.1)" │
                                  │ ┌───────────────────────────────────────┐ │
                                  │ │ UnetLoaderGGUF (451) ──MODEL──┐        │ │
                                  │ │ CLIPLoader (453) ──CLIP──┐    │        │ │
                                  │ │ VAELoader (454) ──VAE───┤    │        │ │
                                  │ │   └→ TextEncodeQwenImage21 (474)      │ │
                                  │ │        │ images.image_1…10          │ │
                                  │ │        ├ positive ─┐               │ │
                                  │ │        ├ negative ─┼→ KSampler(458)│ │
                                  │ │        └ latent ───┘  ↑ 468 旁路  │ │
                                  │ │ QwenImage21Cache (469) ─┘            │ │
                                  │ │   ↓ 四级加速链（见「性能」）         │ │
                                  │ │ LoraLoaderModelOnly (502) Turbo 8 步 │ │
                                  │ │ ModelAttentionBackend (503) INT8     │ │
                                  │ │ EasyCache (504) 跳步复用             │ │
                                  │ │        ↓→ VAEDecode (457)           │ │
                                  │ └───────────────────────────────────────┘ │
                                  └─────────────────────────────────────────┘
                                        ▼
              SaveImageAdvanced (461) + ImageCompare (472) → output/
```

图生图与文生图的差异，四个必须理解的点：

1. **编码节点换成了吃参考图的形态。** `TextEncodeQwenImage21 (474)` 有 `images.image_1` 到 `image_10` 十个可选输入，参考图既进文本编码器（作为上下文），也以 VAE latent 拼进序列。它的第三个输出就是 latent，`KSampler` 的 `latent_image` 直接接它，**不需要 `VAEEncode`**。不要用 `TextEncodeQwenImageEdit` / `TextEncodeQwenImageEditPlus`——那两个只输出 conditioning，不产 latent，是给另一个 pipeline 用的。
2. **`resolution` 是像素预算不是边长，默认给 1024。** 填 0 表示输出跟随 `image_1` 的尺寸（按 32 取整）——**小参考图配 0 会让输出缩到同样小，画质直接崩**。实测：101×120 参考图 + `resolution=0` → 96×128 糊成一团；同一张图 + `resolution=1024` → 928×1120 干净完整。官方模板默认 0，那只对已经很大的原图成立。填具体值会强行改画布比例导致编辑走形，所以别拿它当边长用。
3. **`image_1` 是编辑目标，其余是参考图。** prompt 里用 `<image1>` `<image2>` 指名引用。**prompt 与 image_1 内容不匹配时模型会重画全图**——实测拿人像图配「改厨房柜子」的 prompt，背景被整个重做成厨房，只有人物勉强保留。编辑 prompt 必须描述图里真有的东西。
4. **PE 模型的 combo 被置空。** `qwen3.5_9b_qwen_image_2.1_pe_i2i` 本机没下载。填一个不存在的文件名会让前端弹「missing a required model file」红框，即使 `refine_prompt=false` 时该分支根本不执行。置空即可消除误报，功能保留 —— 哪天下了模型，把子图节点 477 和顶层 `clip_name_1` 一起填回去。

以下三点对**两个**工作流都成立：

1. **模型必须成套。** GGUF 只替换 diffusion model。文本编码器（`qwen3vl_8b_int8_convrot.safetensors`）和 VAE（`qwen_image_2.1_vae_bf16.safetensors`）仍走标准 safetensors 节点，不会因为换 GGUF 而省掉。
2. **`QwenImage21Cache` (480) 是 8 GB 显存的生死线。** 它把 20B 文本编码器的前缀缓存甩到内存，`device` 必须保持 `auto`；改 `off` 会每步重算前缀，慢一个量级。
3. **提示词增强器默认旁路。** `refine_prompt` / `thinking_mode` 默认 false，`ComfySwitchNode (474)` 走 on_false 分支，因此不需要 `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors`。一旦打开 refine_prompt 而模型缺失，运行时会直接报错。

## 性能（RTX 4060 Laptop 8 GB 实测）

MODEL 链上串了三级加速，都在 `QwenImage21Cache (480)` 之后、`KSampler (458)` 之前：

| 节点 | id | 作用 | 单独效果（1024²） |
|---|---|---|---|
| `LoraLoaderModelOnly` | 484 | 官方 turbo LoRA，蒸馏成 8 步 | **大头**：25→8 步，105.7s → 44.7s |
| `EasyCache` | 486 | latent 变化小时复用前一步 | **约 50%**（步数越多省得越多） |
| `ModelAttentionBackend` | 485 | 切 comfy-kitchen INT8 注意力 | **约 4%**，接近噪声 |

前两个是大头。485 收益很小：干净环境下 5 轮交替 A/B（16 步 + turbo + EasyCache）测得 36.5s → 35.0s。**曾有一轮测出 10%，但那轮混入了后台负载，不要引用。**

**三级叠加：8 步 turbo + INT8 + EasyCache = 27.5s**，相对原始 25 步基线 105.7s 约 **3.8 倍**。

必须知道的约束：

- **`steps` 可以往上加，8 步不是上限。** turbo LoRA 的设计值是 8，但加步数**仍有画质收益**，只是收益递减。实测（1024²，全链路）：6 步 24.1s 面部明显畸变 → 8 步 26.5s 可用 → 12 步 29.3s 干净 → 16 步 36.3s / 20 步 42.2s / 25 步 48.6s 与 12 步差距已不明显。**日常出图用 8–12；要细节上 16。**要完全回退基础模型的完整调度，Bypass 掉 484 并把 steps 提到 40–50（25 步不加速约 105s）。
- **加步数时 EasyCache 收益会被放大**，因为跳掉的步更多：实测 25 步时 EasyCache 省约 50%，8 步时省得少（8 步全链路 26.5s 已含 EasyCache）。
- **INT8 注意力不需要额外依赖。** 它走 comfy-kitchen 的 **cuda backend**，启动日志里 `backend cuda` 自带 `int8_linear` capability。本机 sm_89 有 INT8 tensor core，实测 `torch._int_mm` 比 bf16 matmul 快 3.5–4 倍。
- **triton-windows 已装但默认不启用。** `comfy/quant_ops.py` 在启动时无条件执行 `ck.registry.disable("triton")`，除非显式加 `--enable-triton_backend`。所以日志里会看到 `Found comfy_kitchen backend triton: {'available': True, 'disabled': True}` —— **这是正常状态，不是故障**。triton 只被 `TorchCompileModel`（inductor）需要，而该节点在本机 Windows 上编译 20B 模型收益小且不稳，不建议加 flag 启用。
- **`EasyCache` 参数别贪。** `reuse_threshold` 0.2 是安全值；0.35 观感仍干净；再高细节会漂。
- **`torch.compile` 类节点一律先看日志再上机。** ComfyUI 的执行缓存会让「重复跑同一图」秒回，计时必须换 seed 交替 A/B，否则会被 0.5s 的假数据带偏。

### 内存与缓存行为（实测，非推断）

连续 8 轮换 prompt + seed 出图，耗时 25.6–32.5s，显存稳定在 5091–5238 MiB **无单调增长**。

- **GPU 上确实留缓存**，这是设计使然：`QwenImage21Cache (480)` 把 20B 文本编码器的前缀缓存常驻，`device=auto` 会尽量占显存。稳态显存约 5.1–5.2 GB / 8 GB，留 3 GB 余量。出图之间不卸载，所以后续都是热启动。
- **首次运行慢**是因为要从磁盘加载 GGUF + 文本编码器（约 14 GB）并初始化，之后常驻不再重复加载。
- **不存在显存泄漏。** 唯一的累积点是 `EasyCacheHolder.uuid_cache_diffs`（按 conditioning UUID 索引，换 prompt 不覆盖旧条目，且 `reset()` 只在 tensor 形状/dtype/device 变化时触发）。但每条 diff 经 `subsample_factor=8` 二次降采样后仅 **16 KiB**，跑 1000 张不同 prompt 也只有约 16 MiB，可忽略。`ModelPatcher.clone()` 里的 `deepcopy_list_dict` 只深拷 dict/list、叶子对象原样返回，所以 holder 确实跨次共享，但增长的是这个小字典。
- 显存读数波动属正常（CUDA caching allocator 行为），**看趋势不看单次值**。

### 图生图实测（同一台机器，1024²，单参考图）

3 轮交替 A/B，每轮换 seed 绕开执行缓存：

| 配置 | 第 1 轮 | 第 2 轮 | 第 3 轮 |
|---|---|---|---|
| 官方模板原样（25 步，无加速） | 108.4s | 96.4s | 96.2s |
| 本工作流（8 步 + 三级加速） | 27.3s | 26.4s | 26.4s |

约 **3.7×**。同 seed 下两张图并排看，姿态、发型、墨镜、背景涂鸦、镜头角度全部一致，画质无可辨差异。

单节点收益（2 轮，seed 各不相同，均稳定复现）：

| 变体 | 耗时 | 相对全链 |
|---|---|---|
| 全链（8 步 + turbo + INT8 + EasyCache） | 25.3 / 25.2s | — |
| 去掉 EasyCache | 36.5 / 36.5s | **+45%** |
| 去掉 INT8 | 27.4 / 27.3s | +8% |

**EasyCache 在编辑模式下收益比文生图更大**（+45% vs +31%），因为编辑的 latent 序列变化更平缓，跳步更容易命中阈值。

**编辑对步数远不如生成敏感。** 4 步 17–18s、8 步 25–27s、12 步 29s、25 步 96–108s。4 步就已经可用（耳部结构略有瑕疵），8 步干净，12 步与 8 步肉眼几乎无差别。这跟文生图「6 步面部畸变」的情况不同 —— 编辑任务本身把构图和身份锁死在参考图上，多步的边际收益更低。

参考图数量直接翻倍耗时。单参考图 25s，双参考图 48.6s。参考图与参考图上下文都进序列长度。

测速用的脚本是 `i2i_bench.py`（`smoke` / `ab` / `matrix` / `tworef` 四个模式），参考图是 `input/ref_test_a.png`（黑白人像）和 `input/ref_test_b.png`。

### 分辨率与参考图尺寸的关系（实测，非推断）

同一个中文双主体合成 prompt（「让 <image1> 的棕色小熊和 <image2> 的白色熊猫紧紧拥抱在一起…」）、同一 seed、同一对 101×120 / 105×118 的参考图，只改 `resolution`：

| resolution | 输出尺寸 | 耗时 | 画质 |
|---|---|---|---|
| 0 | 96×128 | 16.2s | **糊成一团**，五官糊、肢体粘连 |
| 1024 | 928×1120 | 36.3 / 52.9s | 干净完整，角色特征与服装都对 |
| 2048 | 1888×2240 | 350.5 / 342.6s | 更精细，但慢 7 倍 |

**结论：决定输出质量的是 `resolution`，不是参考图本身的像素数。** 把 101×120 的参考图用 Lanczos 放大到 606×720 再喂，画质与直接喂 101×120 **无可见差异**。所以拿到低分辨率参考图时不要去放大，改 `resolution` 就行。

**`resolution=0` 是官方模板埋的坑。** 它的语义是「跟随 image_1 原尺寸」，只对已经 1K+ 的原图成立。用户拿手机截图、素材站小图、网页缩略图当参考图时必然踩中，输出会缩到同样小。工作流默认值已改成 1024。

## Key Directories

仓库内：

| 路径 | 用途 |
|---|---|
| `image_qwen_image_2_1_t2i_gguf.json` | 文生图产物。官方 t2i 模板 + `UNETLoader → UnetLoaderGGUF` 改造 |
| `image_qwen_image_2_1_i2i_gguf.json` | 图生图产物。官方 image_edit 模板 + GGUF + 四级加速链 |
| `build_i2i_workflow.py` | 从官方 image_edit 模板生成 i2i JSON。**改 i2i 工作流要改这个脚本再重跑**，别手改 JSON |
| `i2i_bench.py` | 图生图测速脚本（`smoke`/`ab`/`matrix`/`tworef`） |
| `参数配置说明手册.md` | 两个工作流逐节点逐参数的取值范围、建议与踩坑。改参数前先查这里，改完参数同步更新这里 |
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

**投放工作流**（改完 JSON 后复制一份，前端才选得到）：

```powershell
Copy-Item image_qwen_image_2_1_t2i_gguf.json D:\Comfy-Desktop\ComfyUI-Shared\input\
Copy-Item image_qwen_image_2_1_i2i_gguf.json D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\user\default\workflows\
```

两个目录作用不同：input 目录让文件在「加载」菜单里出现；后端 `user\default\workflows` 目录让工作流出现在前端的**工作流标签页**列表里（保存过的工作流都在这）。想两个入口都有就两处都放。

## Code Conventions & Common Patterns

工作流 JSON 是手改产物，遵循这些约定：

**⚠️ 两套 link schema，不要混用**
- 顶层 `links`：数组的数组，`[link_id, origin_id, origin_slot, target_id, target_slot, type]`，t2i 共 3 条，i2i 共 5 条
- 子图 `links`：对象数组，`{id, origin_id, origin_slot, target_id, target_slot, type}`，t2i 共 37 条，i2i 共 63 条

**⚠️ `widgets_values_named` 必须随节点类型一起改**
大部分节点同时带 `widgets_values`（位置数组）和 `widgets_values_named`（键值字典）。改节点类型时必须**删除或重写** `widgets_values_named`，否则前端会用旧键名渲染出错的控件。当前 `UnetLoaderGGUF (451)` 已删除该字段，因为上游 `UNETLoader` 的 `weight_dtype` 在 GGUF 节点上不存在。

**⚠️ 顶层子图节点的 widget 值有三处副本**
子图节点（如 i2i 的 459）有一长串 `widgets_values` 位置数组、`widgets_values_named` 键值字典，以及子图内部节点自己的 widget。改任何一项都要三处同步。位置数组的下标靠顺序猜很容易错位——`build_i2i_workflow.py` 用**下标硬编码**（如 `top["widgets_values"][7]` 是 steps、`[14]` 是 unet_name、`[19]` 是 PE 模型）。改模板结构时先打印 `widgets_values_named` 对照下标，别照抄旧下标。

**`properties.models` 会过期**
`CLIPLoader (453)` 和 `VAELoader (454)` 带 `properties.models`，含 `name` / `url` / `directory`。这是给「缺模型时前端自动下载」用的。改模型文件时**必须同步更新**，否则前端会指向错误文件。注意节点 451 上该字段已被删除（GGUF 节点不提供自动下载）。

**⚠️ MarkdownNote 是易腐化的**
t2i 的 `Note: Model links`（463）列模型文件与目录树，`Note: Usage`（468）写 steps 用法。i2i 的 463 写尺寸与参数、476 写模型与加速链、501 写提示词增强器。改模型或步数时**必须同步对应 Note**，否则前端会显示过期的文件名与参数建议。

**⚠️ 不存在的模型文件名会让前端弹红框**
combo 里填一个磁盘上没有的文件名，前端立刻标红「missing a required model file」，即使该分支因开关关闭而根本不会执行。本机没下载的 PE 模型（t2i 是 `pe_t2i`，i2i 是 `pe_i2i`）在 i2i 里一律置空字符串。**判断依据是磁盘上有没有，不是开关关没关。**

**⚠️ Note 类节点有两份文本，改一处等于改两处**
`widgets_values[0]`（位置数组）与 `widgets_values_named.text`（键值字典）内容必须一致，只改其一会导致前端渲染出旧文本。

**采样参数**
`cfg=1.0`（Qwen Image 2.1 固定，调到 1 以上明显劣化）、`sampler_name=euler`、`scheduler=simple` 这三项沿用官方推荐，不要动。`steps` 与 turbo LoRA 联动，见「性能」一节。

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
| `image_qwen_image_2_1_t2i_gguf.json` | 文生图工作流本体。`schema version 0.4`，`last_node_id 486`，`last_link_id 723`，子图 16 节点 / 37 link |
| `image_qwen_image_2_1_i2i_gguf.json` | 图生图工作流本体。`schema version 0.4`，`last_node_id 504`，`last_link_id 906`，顶层 8 节点 / 5 link，子图 18 节点 / 63 link |
| `…\ComfyUI\logs\comfyui.log` | 当前日志；历史为 `comfyui.log_<ISO时间戳>.log` |
| `…\AppData\Roaming\Comfy Desktop\settings.json` | Desktop 全局配置（`installDir` / `modelsDirs` / `inputDir` / `outputDir` / `cacheDir`） |
| `…\AppData\Roaming\Comfy Desktop\instance-model-paths\inst-*.yaml` | 生成的模型路径映射，文件头写明「do not edit manually」 |
| `…\ComfyUI\user\default\workflows\` | 后端 `user` 目录（见日志 `** User directory:`）。放进去的工作流出现在前端「工作流」列表。注意单文件 GET 需把斜杠 URL 编码：`/api/userdata/workflows%2F<name>.json` |
| `…\custom_nodes\ComfyUI-GGUF\nodes.py` | `UnetLoaderGGUF` 定义，`CATEGORY = "bootleg"`；第 32 行把 `diffusion_models` / `unet` 注册为 `unet_gguf` |

## Testing & QA

本仓库**没有测试框架，也不引入**。改动按下面顺序人工验证，最后一步不可省：

1. **JSON 合法性** —— 上节命令 1 能解析，且 `451` 打印 `['UnetLoaderGGUF']`。
2. **节点已注册** —— `/object_info` 里存在 `UnetLoaderGGUF`，且 `unet_name` 枚举包含目标 gguf 文件名。**若为空或缺节点，说明后端没重启或依赖没装全，先查日志，不要改 JSON。**
3. **端到端出图** —— 提交一次最小链路，确认 `status: success` 且 output 目录出现 PNG。

最小可跑链路（与工作流实际链路一致，含三级加速，用于验通路）：

```json
{
  "1": {"class_type":"UnetLoaderGGUF","inputs":{"unet_name":"qwen-image-2.1-UC-Q4_K_M.gguf"}},
  "2": {"class_type":"CLIPLoader","inputs":{"clip_name":"qwen3vl_8b_int8_convrot.safetensors","type":"qwen_image","device":"default"}},
  "3": {"class_type":"VAELoader","inputs":{"vae_name":"qwen_image_2.1_vae_bf16.safetensors"}},
  "4": {"class_type":"TextEncodeQwenImage21","inputs":{"clip":["2",0],"prompt":"...","negative_prompt":"","resolution":1024}},
  "80": {"class_type":"QwenImage21Cache","inputs":{"model":["1",0],"device":"auto","dtype":"default"}},
  "84": {"class_type":"LoraLoaderModelOnly","inputs":{"model":["80",0],"lora_name":"qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors","strength_model":1.0}},
  "85": {"class_type":"ModelAttentionBackend","inputs":{"model":["84",0],"attention":"comfy kitchen attention"}},
  "86": {"class_type":"EasyCache","inputs":{"model":["85",0],"reuse_threshold":0.2,"start_percent":0.15,"end_percent":0.95,"verbose":false}},
  "6": {"class_type":"KSampler","inputs":{"model":["86",0],"positive":["4",0],"negative":["4",1],"latent_image":["4",2],"seed":1,"steps":8,"cfg":1.0,"sampler_name":"euler","scheduler":"simple","denoise":1.0}},
  "7": {"class_type":"VAEDecode","inputs":{"samples":["6",0],"vae":["3",0]}},
  "8": {"class_type":"SaveImage","inputs":{"images":["7",0],"filename_prefix":"gguf_smoke"}}
}
```

`TextEncodeQwenImage21` 的输出顺序是 `[CONDITIONING(positive), CONDITIONING(negative), LATENT]` —— 三条都要接，漏接会在提交时被拒（`required_input_missing`）。

**`QwenImage21Cache` (80) 不能省。** 20B 文本编码器的前缀缓存靠它甩到内存；绕过它会 OOM。

**`EasyCache` (86) 三个参数必须显式传全。** 省略任何一项提交即被拒（`required_input_missing`），节点不会用默认值兜底。同理 `ModelAttentionBackend` 的 `attention` 必填。

**验收标准**：8 GB 显存下 1024×1024 / 8 步不出 OOM，`status: success`，产出非空 PNG，耗时 30–40s。已实测通过（34.4s）。

### 图生图的验收链路

在上面的图上多一个 `LoadImage`，并给编码节点喂参考图。**`TextEncodeQwenImage21` 的 `images.image_1` 输入名带点号**，不是 `image_1`：

```json
{
  "10": {"class_type":"LoadImage","inputs":{"image":"ref_test_a.png"}},
  "4": {"class_type":"TextEncodeQwenImage21","inputs":{"clip":["2",0],"images.image_1":["10",0],"vae":["3",0],"prompt":"...","negative_prompt":"","resolution":1024}}
}
```

其余节点与文生图链路完全相同。`latent_image` 仍接 `["4",2]`（编码节点输出的 latent），**不要加 `VAEEncode`**。第二张参考图用 `"images.image_2": ["11",0]`。

**图生图的实测验收标准**：1024² / 8 步 / 单参考图 25–28s（首次冷启动更慢），产出 PNG。已实测通过。

### 前端渲染验证

JSON 解析成功不等于前端能渲染。**改完必须过一遍真实前端**，步骤：

1. 复制到后端 user 目录：`Copy-Item <wf>.json "D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\user\default\workflows\"`。注意后端 `user` 目录在 `ComfyUI\ComfyUI\user` 下（从日志 `** User directory:` 确认），不是 input 目录。
2. 打开 `http://127.0.0.1:8188`，用 DevTools 跑 `fetch('/api/userdata/workflows%2F<文件名>.json')` 再 `window.app.loadGraphData(json)`。**斜杠必须 URL 编码**，不编码返回 404（列表接口却能列出文件，容易误判成没投放成功）。
3. 检查 `window.app.lastNodeErrors.length` 为 0，并 `window.app.graph.subgraphs.values().next().value._nodes` 确认子图节点数与类型都解析出来。
4. 截图看有没有红框告警 —— 见「不存在的模型文件名会让前端弹红框」。

**`window.app.loadGraphData` 在未 ready 时会静默失败**：返回 `true` 但 `app.graph._nodes` 不变，连官方模板也一样。必须先 `await window.app.vueAppReady` 或 reload 后等 10s 以上再调。

## Asset Inventory

| 文件 | 位置 | 字节 |
|---|---|---|
| `qwen-image-2.1-UC-Q4_K_M.gguf` | `models/diffusion_models/` | 4,604,558,112 |
| `qwen3vl_8b_int8_convrot.safetensors` | `models/text_encoders/` | 9,350,798,360 |
| `qwen_image_2.1_vae_bf16.safetensors` | `models/vae/` | 675,509,688 |
| `qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors` | `models/loras/` | 913,314,512 |

Python 侧依赖（venv 内，非模型）：`triton-windows==3.8.0.post29`（INT8 attention 与 inductor 的前提，缺了报 `Cannot find a working triton installation`）。

未下载：`qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors`（t2i 的 PE）、`qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors`（i2i 的 PE），都只在打开 refine_prompt 时需要。**i2i 工作流里的 `pe_i2i` combo 已置空**（子图节点 477 + 顶层 `clip_name_1`），不会误报；t2i 工作流里的 `pe_t2i` 仍保留原文件名，打开时会看到红框告警。