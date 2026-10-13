# Qwen-Image-2.1 GGUF 工作流

在 8 GB 显存笔记本上跑 [Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) 的 ComfyUI 工作流。

产物只有一个文件：[`image_qwen_image_2_1_t2i_gguf.json`](image_qwen_image_2_1_t2i_gguf.json) —— 拖进 ComfyUI 画布即可用。

## 实测效果

RTX 4060 Laptop 8 GB / 1024×1024，接默认 `euler` + `simple`：

| 配置 | 耗时 |
|---|---|
| 官方模板原样（25 步） | 105.7s |
| 本工作流默认（8 步 + 三级加速） | **约 27s** |

连续 20 轮实测 24.3–30.3s，显存稳定 5.1 GB，无泄漏。

## 三级加速

官方模板的采样链路是裸的 `KSampler`，这里在 `QwenImage21Cache` 之后串了三层：

| 节点 | 作用 | 单独收益 |
|---|---|---|
| `LoraLoaderModelOnly` | 官方 turbo LoRA，蒸馏到 8 步 | 25→8 步：105.7s → 44.7s |
| `ModelAttentionBackend` | comfy-kitchen INT8 注意力 | ~10% |
| `EasyCache` | latent 变化小时复用前一步 | ~50% |

叠加后约 3.8×，出图对比无可见劣化。

## 依赖

**节点**：`UnetLoaderGGUF` 需要 [leejet/ComfyUI-GGUF](https://github.com/leejet/ComfyUI-GGUF)（**不要**用 city96 版，遇到 Qwen-Image 2.1 会报 `Unknown model architecture!`）。

**Python 包**：INT8 注意力依赖 triton，Windows 上装社区版：

```powershell
& "C:\path\to\ComfyUI\.venv\Scripts\python.exe" -m pip install "triton-windows==3.8.0.post29"
```

⚠️ ComfyUI Desktop **不会**自动执行 `custom_nodes/*/requirements.txt`，GGUF 节点装完默认是坏的（`ModuleNotFoundError: No module named 'gguf'`），必须手动 pip。装完**必须重启后端**。

`TorchCompileModel`（inductor）在本机仍不可用，不建议折腾。

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
- 提示词增强器默认旁路（`refine_prompt=false`），不需要 `qwen3.5_9b_..._pe_t2i` 模型；打开而模型缺失会直接报错。
- `EasyCache` 的三个参数必须显式传全，省略任一项提交即被拒。

更多实现细节、验收方法和踩坑记录见 [`AGENTS.md`](AGENTS.md)。

## 说明

本仓承载的是 **uncensored** 权重（无内置安全检查器）的本地工作流，仅用于在本机运行。不要接到任何对外服务或自动化链路上。