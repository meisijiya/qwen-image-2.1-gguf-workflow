"""从官方 image_qwen_image_2_1_image_edit.json 模板派生 GGUF + 加速链的图生图工作流。

改工作流时改这个脚本再重跑，不要手改 JSON —— 手改会被下次重生成覆盖。

    & "D:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\ComfyUI\\.venv\\Scripts\\python.exe" build_i2i_workflow.py
"""
import json
import pathlib

TPL = pathlib.Path(
    r"D:/Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI/.venv/Lib/site-packages"
    r"/comfyui_workflow_templates_json/templates/image_qwen_image_2_1_image_edit.json"
)
OUT = pathlib.Path(__file__).with_name("image_qwen_image_2_1_i2i_gguf.json")

GGUF = "qwen-image-2.1-UC-Q4_K_M.gguf"
TURBO_LORA = "qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors"
PE_MODEL = "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors"
REF_A = "ref_test_a.png"
REF_B = "ref_test_b.png"

d = json.loads(TPL.read_text(encoding="utf-8"))
sg = d["definitions"]["subgraphs"][0]
nodes = {n["id"]: n for n in sg["nodes"]}

# --- 1) UNETLoader -> UnetLoaderGGUF -------------------------------------------------
unet = nodes[451]
unet["type"] = "UnetLoaderGGUF"
unet["size"] = [510, 90]
unet["inputs"] = [
    {
        "localized_name": "unet_name",
        "name": "unet_name",
        "type": "COMBO",
        "widget": {"name": "unet_name"},
        "link": 663,
    }
]
unet["properties"] = {"Node name for S&R": "UnetLoaderGGUF"}
unet["widgets_values"] = [GGUF]
unet.pop("widgets_values_named", None)

# --- 2) 插入加速链 LoRA -> INT8 attention -> EasyCache -------------------------------
accel = [
    {
        "id": 502,
        "type": "LoraLoaderModelOnly",
        "pos": [1180, 600],
        "size": [270, 90],
        "flags": {},
        "order": 15,
        "mode": 0,
        "inputs": [
            {"localized_name": "model", "name": "model", "type": "MODEL", "link": 689},
            {
                "localized_name": "lora_name",
                "name": "lora_name",
                "type": "COMBO",
                "widget": {"name": "lora_name"},
            },
            {
                "localized_name": "strength_model",
                "name": "strength_model",
                "type": "FLOAT",
                "widget": {"name": "strength_model"},
            },
        ],
        "outputs": [{"localized_name": "MODEL", "name": "MODEL", "type": "MODEL", "links": [904]}],
        "properties": {"Node name for S&R": "LoraLoaderModelOnly"},
        "widgets_values": [TURBO_LORA, 1.0],
        "widgets_values_named": {"lora_name": TURBO_LORA, "strength_model": 1.0},
    },
    {
        "id": 503,
        "type": "ModelAttentionBackend",
        "pos": [1180, 730],
        "size": [270, 90],
        "flags": {},
        "order": 16,
        "mode": 0,
        "inputs": [
            {"localized_name": "model", "name": "model", "type": "MODEL", "link": 904},
            {
                "localized_name": "attention",
                "name": "attention",
                "type": "COMBO",
                "widget": {"name": "attention"},
            },
        ],
        "outputs": [{"localized_name": "MODEL", "name": "MODEL", "type": "MODEL", "links": [905]}],
        "properties": {"Node name for S&R": "ModelAttentionBackend"},
        "widgets_values": ["comfy kitchen attention"],
        "widgets_values_named": {"attention": "comfy kitchen attention"},
    },
    {
        "id": 504,
        "type": "EasyCache",
        "pos": [1180, 860],
        "size": [270, 110],
        "flags": {},
        "order": 17,
        "mode": 0,
        "inputs": [
            {"localized_name": "model", "name": "model", "type": "MODEL", "link": 905},
            {
                "localized_name": "reuse_threshold",
                "name": "reuse_threshold",
                "type": "FLOAT",
                "widget": {"name": "reuse_threshold"},
            },
            {
                "localized_name": "start_percent",
                "name": "start_percent",
                "type": "FLOAT",
                "widget": {"name": "start_percent"},
            },
            {
                "localized_name": "end_percent",
                "name": "end_percent",
                "type": "FLOAT",
                "widget": {"name": "end_percent"},
            },
            {
                "localized_name": "verbose",
                "name": "verbose",
                "type": "BOOLEAN",
                "widget": {"name": "verbose"},
            },
        ],
        "outputs": [{"localized_name": "MODEL", "name": "MODEL", "type": "MODEL", "links": [906]}],
        "properties": {"Node name for S&R": "EasyCache"},
        "widgets_values": [0.2, 0.15, 0.95, False],
        "widgets_values_named": {
            "reuse_threshold": 0.2,
            "start_percent": 0.15,
            "end_percent": 0.95,
            "verbose": False,
        },
    },
]
sg["nodes"].extend(accel)
sg["state"]["lastNodeId"] = 504

# MODEL 链重接线: 451 -> 469(QwenImage21Cache) -> 502 -> 503 -> 504 -> 458(KSampler)
for link in sg["links"]:
    if link["id"] == 689:
        link["target_id"] = 502
sg["links"].extend(
    [
        {"id": 904, "origin_id": 502, "origin_slot": 0, "target_id": 503, "target_slot": 0, "type": "MODEL"},
        {"id": 905, "origin_id": 503, "origin_slot": 0, "target_id": 504, "target_slot": 0, "type": "MODEL"},
        {"id": 906, "origin_id": 504, "origin_slot": 0, "target_id": 458, "target_slot": 0, "type": "MODEL"},
    ]
)
sg["state"]["lastLinkId"] = 906
d["last_link_id"] = 906
d["last_node_id"] = 504

# KSampler 下移让位给加速链，并改接 504 的 MODEL
ks = nodes[458]
ks["inputs"][0]["link"] = 906
ks["pos"] = [1180, 1020]
nodes[457]["pos"] = [1620, 1040]
for g in sg["groups"]:
    if g["id"] == 37:
        g["bounding"] = [1090, 300, 470, 1010]

# --- 3) steps 25 -> 8 (turbo LoRA 的设计值) -------------------------------------------
ks["widgets_values"][2] = 8
ks["widgets_values_named"]["steps"] = 8

# --- 4) 顶层子图节点 widget 同步 --------------------------------------------------------
# 位置数组下标必须与 widgets_values_named 的顺序一致，先打印对照再改。
DEFAULT_PROMPT = (
    "Turn this black and white portrait into a color photograph. Give the person "
    "a deep olive green jacket and warm skin tones, keep the background dark "
    "concrete with the graffiti, keep the exact pose, sunglasses, hairstyle and "
    "camera angle. <image1>"
)
# resolution 是**像素预算**不是边长。官方模板默认 0（跟随 image_1 原尺寸），
# 但用户手上的图往往只有几百像素，0 会让输出缩到同样的小尺寸，画质直接崩。
# 实测：101x120 的参考图 + resolution=0 -> 96x128 糊成一团；
# 同一张图 + resolution=1024 -> 928x1120 干净完整。默认给 1024。
DEFAULT_RESOLUTION = 1024

top = next(n for n in d["nodes"] if n["id"] == 459)
WV = top["widgets_values"]
# 模板变了就靠这几条断言拦住错位，不要靠肉眼数下标
assert WV[0] == top["widgets_values_named"]["resolution"], "顶层 widget 下标已错位"
assert WV[1] == top["widgets_values_named"]["prompt"], "顶层 widget 下标已错位"
assert WV[7] == top["widgets_values_named"]["steps"], "顶层 widget 下标已错位"
assert WV[14] == top["widgets_values_named"]["unet_name"], "顶层 widget 下标已错位"
assert WV[19] == top["widgets_values_named"]["clip_name_1"], "顶层 widget 下标已错位"
WV[0] = DEFAULT_RESOLUTION  # resolution
WV[1] = DEFAULT_PROMPT  # prompt
WV[7] = 8  # steps
WV[14] = GGUF  # unet_name
WV[19] = ""  # clip_name_1，PE 模型
top["widgets_values_named"].update(
    {
        "resolution": DEFAULT_RESOLUTION,
        "prompt": DEFAULT_PROMPT,
        "steps": 8,
        "unet_name": GGUF,
        "clip_name_1": "",
    }
)

# --- 5) PE 模型置空：没下载就不能填文件名 ---------------------------------------------
# 本机没有 qwen3.5_9b_qwen_image_2.1_pe_i2i。refine_prompt 默认 false 时该分支
# 不执行，但填一个磁盘上不存在的文件名会让前端弹「missing a required model file」
# 红框。下模型后把两处都填回 PE_MODEL。
pe = nodes[477]
pe["widgets_values"][0] = ""
pe["widgets_values_named"]["clip_name"] = ""

# --- 6) LoadImage 默认参考图 -----------------------------------------------------------
for node_id, ref in ((470, REF_A), (475, REF_B)):
    node = next(n for n in d["nodes"] if n["id"] == node_id)
    node["widgets_values"] = [ref, "image"]
    node.pop("widgets_values_named", None)

# --- 7) MarkdownNote 同步当前实现 ------------------------------------------------------
note_steps = """## Size
Qwen Image 2.1 has native 2K (2048*2048) support for direct output.

- resolution is a **pixel budget, not width or height**. Aspect ratio is preserved.
- **Do not set resolution to 0 unless image_1 is already large.** 0 means "keep image_1's own size, rounded to a multiple of 32". With a small reference that produces a tiny output.
- Measured here with a 101x120 reference: resolution 0 -> 96x128 output, muddy and unrecognisable. Same reference and same prompt at resolution 1024 -> 928x1120 output, clean and complete.
- Default here is 1024. 2048 works (1888x2240 output) but costs about 350s instead of 36-53s on this 8 GB card.
- Reference image resolution is NOT the bottleneck: upscaling a 101x120 reference to 606x720 with Lanczos made no visible difference. A small reference is fine as long as resolution is set.
- custom_size off: canvas comes from the encode latent (image_1).
- custom_size on: use ResolutionSelector width/height.

## Reference images
- Up to 10 reference images (image_1 to image_10).
- Mention them in the prompt as `<image1>`, `<image2>`, ...
- image_1 is the edit target. The rest are references.
- Keep the prompt about what is actually in image_1. A mismatched instruction makes the model repaint the whole frame instead of editing.

## Custom settings
If you need custom settings, enter or unpack the subgraph to edit it. See the [Subgraph](https://docs.comfy.org/interface/features/subgraph) guide.

## Parameters
- prompt: edit instruction. Use `<image1>` ... `<image10>`.
- negative_prompt: unused while cfg is 1.
- cfg: keep 1 for the Qwen Image 2.1 official path. Raise it only if you use a negative prompt.
- steps: 8 here, because the MODEL chain loads the official turbo LoRA (distilled for 8 denoising steps at CFG 1). Measured on this machine: 4 steps 17-18s, 8 steps 25-27s, 12 steps 29s, 25 steps 96-108s. Editing is far less step-sensitive than generation - 8 and 12 look nearly identical, 4 still holds up. Bypass the LoRA node and raise steps to 40-50 to roll back to the base schedule."""

note_models = """Guide: [Subgraph](https://docs.comfy.org/interface/features/subgraph)

## Input Assets

- `ref_test_a.png` -> image_1, the edit target
- `ref_test_b.png` -> image_2, a style/subject reference

## Model Links

- [Hugging Face:Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1)
- [ModelScope:Comfy-Org/Qwen-Image-2.1](https://modelscope.cn/models/Comfy-Org/Qwen-Image-2.1)

**diffusion_models**

- `qwen-image-2.1-UC-Q4_K_M.gguf` (local GGUF, loaded by ComfyUI-GGUF). Uncensored quantized build of `qwen_image_2.1_int8_convrot.safetensors`.
- [qwen_image_2.1_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors) (6.76 GB) - the official full-precision counterpart, not needed here.

**loras**

- `qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors` (913 MB) - official 8-step turbo distillation, loaded by LoraLoaderModelOnly.

**text_encoders**

- [qwen3vl_8b_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors) (8.71 GB)
- `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` (8.82 GB) - only needed when `refine_prompt` is on; not downloaded here, keep the switch off.

**vae**

- [qwen_image_2.1_vae_bf16.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors)

## Acceleration chain

`QwenImage21Cache -> LoraLoaderModelOnly (turbo) -> ModelAttentionBackend (INT8) -> EasyCache -> KSampler`

- QwenImage21Cache keeps the 20B text-encoder prefix cache resident. Keep `device=auto`; `off` recomputes the prefix every step and costs an order of magnitude.
- turbo LoRA is the big win: 25 steps 96-108s -> 8 steps 36s before EasyCache.
- INT8 attention (comfy kitchen): 27.4s -> 25.3s, about 8%.
- EasyCache: 36.5s -> 25.3s, about 31%, the second big win. `reuse_threshold` 0.2 is the safe value, 0.35 still looks clean, higher drifts.
- End to end the chain is about 3.7x faster than the stock template with no visible quality loss.

Reference images cost real time: one reference runs 25s, two references 48.6s."""

for n in d["nodes"]:
    if n["type"] != "MarkdownNote":
        continue
    text = n["widgets_values"][0]
    if text.startswith("## Size"):
        n["widgets_values"][0] = note_steps
    elif text.startswith("Guide: [Subgraph]"):
        n["widgets_values"][0] = note_models
    named = n.get("widgets_values_named")
    if named and "text" in named:
        named["text"] = n["widgets_values"][0]

OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
print("wrote", OUT)