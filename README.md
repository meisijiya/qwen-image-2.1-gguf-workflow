# Qwen-Image-2.1 GGUF 工作流

在 8 GB 显存笔记本上跑 [Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) 的 ComfyUI 工作流。

两个产物，拖进 ComfyUI 画布即可用：

| 文件 | 用途 |
|---|---|
| [`image_qwen_image_2_1_t2i_gguf.json`](image_qwen_image_2_1_t2i_gguf.json) | 文生图 |
| [`image_qwen_image_2_1_i2i_gguf.json`](image_qwen_image_2_1_i2i_gguf.json) | 图生图 / 多参考图编辑 |

两者都由官方模板派生：`image_qwen_image_2_1_t2i.json` 与 `image_qwen_image_2_1_image_edit.json`，把 `UNETLoader` 换成 `UnetLoaderGGUF`，并在采样链上串 turbo LoRA + INT8 注意力 + EasyCache，采样步数从 25 降到 8。

## 实测效果

RTX 4060 Laptop 8 GB / 1024×1024，接默认 `euler` + `simple`：

| 场景 | 官方模板原样 | 本仓库工作流 |
|---|---|---|
| 文生图 | 105.7s（25 步） | **约 27s** |
| 图生图（编辑 1 张参考图） | 96–108s（25 步） | **26–27s** |

图生图数据是 3 轮交替 A/B、每轮换 seed 实测的均值区间：基线 108.4 / 96.4 / 96.2s，加速后 27.3 / 26.4 / 26.4s，约 **3.7×**。同 seed 下两张图肉眼对比，画质无可辨差异。

文生图连续 20 轮实测 24.3–30.3s，显存稳定 5.1 GB，无泄漏。

## 三级加速

官方模板的采样链路是裸的 `KSampler`，这里在 `QwenImage21Cache` 之后串了三层：

| 节点 | 作用 | 单独收益 |
|---|---|---|
| `LoraLoaderModelOnly` | 官方 turbo LoRA，蒸馏到 8 步 | **大头**：25→8 步，105.7s → 44.7s |
| `EasyCache` | latent 变化小时复用前一步 | **约 50%**（步数越多省得越多） |
| `ModelAttentionBackend` | comfy-kitchen INT8 注意力 | **约 4%**，接近噪声，锦上添花 |

turbo LoRA 和 EasyCache 是两个大头，INT8 那层收益很小。叠加后约 3.8×，出图对比无可见劣化。

## 图生图怎么用

顶层节点 `Image Edit (Qwen Image 2.1)` 有 `image_1` 到 `image_10` 十个参考图入口：

1. `image_1` 接 `LoadImage`，放要编辑的目标图。
2. 其余的接风格 / 服装 / 材质参考图，可以留空。
3. 在 prompt 里用 `<image1>` `<image2>` 指名道姓地引用，例如 `give it the color grading of <image2>, keep the pose of <image1>`。
4. `refine_prompt` 保持关闭。本机没下 `qwen3.5_9b_qwen_image_2.1_pe_i2i` 这个提示词增强器模型，打开会直接报错。
5. **`resolution` 保持 1024，别填 0。** 它是像素预算不是边长，0 表示「跟随 `image_1` 的原始尺寸」。参考图只有几百像素时，0 会让输出缩到同样小 —— 实测 101×120 的参考图配 `resolution=0`，输出 96×128 糊成一团；同一张图改成 1024，输出 928×1120 干净完整。参考图本身分辨率低**不是问题**，不用去放大。

`custom_size` 打开时改用 `ResolutionSelector` 的宽高，值要贴近 `image_1` 缩放后的尺寸。

分辨率实测（同一 prompt、同一 seed、同一参考图，只改 `resolution`）：

| resolution | 输出尺寸 | 耗时 |
|---|---|---|
| 0（跟随参考图原尺寸） | 96×128 | 16s |
| **1024（默认）** | **928×1120** | **36–53s** |
| 2048 | 1888×2240 | 350s |

把 101×120 的参考图用 Lanczos 放大到 606×720 再喂，画质**没有可见变化** —— 决定输出质量的是 `resolution`，不是参考图自身的像素数。2048 能用但慢 7 倍，8 GB 卡上不划算。

编辑质量的关键是 prompt 要具体描述「改什么、别改什么」。测试用的 prompt 是：

> Turn this black and white portrait into a color photograph. Give the person a deep olive green jacket and warm skin tones, keep the background dark concrete with the graffiti, keep the exact pose, sunglasses, hairstyle and camera angle. `<image1>`

人物姿态、发型、墨镜、镜头角度全部保留，只上了色并换了外套 —— 这是 `image_1` 作为编辑目标生效的证据。

## 依赖

**节点**：`UnetLoaderGGUF` 需要 [leejet/ComfyUI-GGUF](https://github.com/leejet/ComfyUI-GGUF)（**不要**用 city96 版，遇到 Qwen-Image 2.1 会报 `Unknown model architecture!`）。

**Python 包**：GGUF 节点自己的依赖，ComfyUI Desktop **不会**自动执行 `custom_nodes/*/requirements.txt`，装完默认是坏的（`ModuleNotFoundError: No module named 'gguf'`）：

```powershell
& "C:\path\to\ComfyUI\.venv\Scripts\python.exe" -m pip install "gguf>=0.13.0" sentencepiece protobuf
```

装完**必须重启后端**，Desktop 不会自愈。

`ModelAttentionBackend` 的 INT8 注意力走 comfy-kitchen 的 CUDA backend，**不需要额外依赖**（日志里 `backend cuda` 自带 `int8_linear`）。

`triton-windows` 只有 `TorchCompileModel`（inductor）才需要，而它在 Windows 上对本模型收益很小、稳定性也差，**建议不要启用**。

## 模型

| 文件 | 目录 | 来源 |
|---|---|---|
| `qwen-image-2.1-UC-Q4_K_M.gguf` | `diffusion_models/` | [abenzerps/Qwen-Image-2.1-Uncensored-Quantized](https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-Quantized) |
| `qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors` | `loras/` | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) |
| `qwen3vl_8b_int8_convrot.safetensors` | `text_encoders/` | 同上 |
| `qwen_image_2.1_vae_bf16.safetensors` | `vae/` | 同上 |

只换 diffusion model 是 GGUF，文本编码器和 VAE 仍走标准 safetensors 节点。

## steps 怎么调

8 步是 turbo LoRA 的设计值，**但不是上限** —— 加步数仍有画质收益，只是递减：

| steps | 耗时 | 画质 |
|---|---|---|
| 6 | 24.1s | 面部明显畸变 |
| 8 | 26.5s | 可用 |
| 12 | 29.3s | 干净 |
| 16 | 36.3s | 增益已趋平 |
| 25 | 48.6s | 几乎无额外收益 |

日常 8–12 步，要细节上 16。步数越多 `EasyCache` 省得越多。

要回退基础模型的完整调度：Bypass 掉 `Turbo (8 steps)` 节点，把 steps 提到 40–50。

## 注意事项

- `QwenImage21Cache` 的 `device` 保持 `auto`，改 `off` 会每步重算前缀，慢一个量级。
- `cfg` 固定 `1.0`，调到 1 以上明显劣化。
- 提示词增强器默认旁路（`refine_prompt=false`），不需要 `qwen3.5_9b_..._pe_t2i` / `pe_i2i` 模型；打开而模型缺失会直接报错。
- `EasyCache` 的 `reuse_threshold` / `start_percent` / `end_percent` / `verbose` 四个输入必须显式传全，省略任一项提交即被拒。
- 图生图工作流用 `TextEncodeQwenImage21`（不是 `TextEncodeQwenImageEdit`）。它同时吃参考图并输出 latent，`KSampler` 的 `latent_image` 默认取它的第三个输出（由 `custom_size` 开关在它与 `EmptyLatentImage` 之间切换）。

逐节点逐参数的取值范围、建议与踩坑见 [`参数配置说明手册.md`](参数配置说明手册.md)；更多实现细节、验收方法和踩坑记录见 [`AGENTS.md`](AGENTS.md)。

## 说明

本仓承载的是 **uncensored** 权重（无内置安全检查器）的本地工作流，仅用于在本机运行。不要接到任何对外服务或自动化链路上。