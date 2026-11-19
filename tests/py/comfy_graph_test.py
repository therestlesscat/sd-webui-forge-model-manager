"""
ComfyUI's run graph read into plain fields (#232): model_manager.comfy_graph's
`read`, over made-up graphs of each shape the reader follows - one per row of
the plan's reader table, posted on #232. No real graph is used.

The module imports only `json`, so this suite runs under the original Forge's
Python 3.10 as it is, with no stub: the same graphs must read the same there.
"""
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from model_manager import comfy_graph            # noqa: E402
from model_manager.comfy_graph import read      # noqa: E402

sys.stdout.reconfigure(errors='backslashreplace')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def watched(graph, seconds=5):
    """read(graph) in a thread of its own: "hangs" where it does not end, so a
    loop the reader fails to stop fails a check rather than the whole suite."""
    answer = []
    thread = threading.Thread(target=lambda: answer.append(read(graph)), daemon=True)
    thread.start()
    thread.join(seconds)
    return answer[0] if answer else "hangs"


def without(answer, *keys):
    return {k: v for k, v in answer.items() if k not in keys}


def node(kind, **inputs):
    return {"class_type": kind, "inputs": inputs}


def sd15(**overrides):
    """SD 1.5's default graph, as ComfyUI's own: a checkpoint, two prompts,
    an empty latent, one KSampler, the decoder and SaveImage."""
    graph = {
        "4": node("CheckpointLoaderSimple", ckpt_name="SD15\\dreamy_v2.safetensors"),
        "5": node("EmptyLatentImage", width=512, height=768, batch_size=1),
        "6": node("CLIPTextEncode", text="a red fox in snow", clip=["4", 1]),
        "7": node("CLIPTextEncode", text="blurry", clip=["4", 1]),
        "3": node("KSampler", seed=123456789, steps=25, cfg=7.5, sampler_name="dpmpp_2m",
                  scheduler="karras", denoise=1.0, model=["4", 0], positive=["6", 0],
                  negative=["7", 0], latent_image=["5", 0]),
        "8": node("VAEDecode", samples=["3", 0], vae=["4", 2]),
        "9": node("SaveImage", filename_prefix="ComfyUI", images=["8", 0]),
    }
    graph.update(overrides)
    return graph


SD15_FIELDS = {"source": "run", "seed": 123456789, "steps": 25, "cfg": 7.5, "sampler": "dpmpp_2m",
               "scheduler": "karras", "prompt": "a red fox in snow", "negative": "blurry",
               "checkpoint": "dreamy_v2", "width": 512, "height": 768}


# ------------------------------------------------------------------ the shapes

check('SD 1.5: every field, under the reader\'s own names', read(sd15()), SD15_FIELDS)

sdxl = sd15(**{"6": node("CLIPTextEncodeSDXL", text_g="a lighthouse at dusk", text_l="lighthouse",
                         width=1024, height=1024, crop_w=0, crop_h=0, target_width=1024,
                         target_height=1024, clip=["4", 1])})
check('SDXL\'s CLIPTextEncodeSDXL: its text_g as the prompt', read(sdxl).get("prompt"), "a lighthouse at dusk")


def flux(guider="CFGGuider"):
    graph = {
        "10": node("UNETLoader", unet_name="flux\\flux1-dev.safetensors", weight_dtype="default"),
        "11": node("DualCLIPLoader", clip_name1="t5xxl_fp16.safetensors", clip_name2="clip_l.safetensors", type="flux"),
        "12": node("VAELoader", vae_name="ae.safetensors"),
        "13": node("ModelSamplingFlux", model=["10", 0], max_shift=1.15, base_shift=0.5, width=1024, height=1024),
        "14": node("CLIPTextEncodeFlux", clip_l="a cat", t5xxl="a cat on a windowsill", guidance=3.5, clip=["11", 0]),
        "15": node("FluxGuidance", guidance=3.5, conditioning=["14", 0]),
        "16": node("ConditioningZeroOut", conditioning=["14", 0]),
        "17": node("RandomNoise", noise_seed=42),
        "18": node("KSamplerSelect", sampler_name="euler"),
        "19": node("BasicScheduler", scheduler="simple", steps=20, denoise=1.0, model=["13", 0]),
        "20": node("EmptySD3LatentImage", width=896, height=1152, batch_size=1),
        "22": node("SamplerCustomAdvanced", noise=["17", 0], guider=["21", 0], sampler=["18", 0],
                   sigmas=["19", 0], latent_image=["20", 0]),
        "23": node("VAEDecode", samples=["22", 0], vae=["12", 0]),
        "24": node("SaveImage", filename_prefix="flux", images=["23", 0]),
    }
    if guider == "CFGGuider":
        graph["21"] = node("CFGGuider", cfg=1.0, model=["13", 0], positive=["15", 0], negative=["16", 0])
    else:
        graph["21"] = node("BasicGuider", model=["13", 0], conditioning=["15", 0])
    return graph


for guider in ("CFGGuider", "BasicGuider"):
    got = read(flux(guider))
    want = {"source": "run", "seed": 42, "sampler": "euler", "scheduler": "simple", "steps": 20,
            "distilled_cfg": 3.5, "width": 896, "height": 1152, "checkpoint": "flux1-dev",
            "text_encoders": ["t5xxl_fp16.safetensors", "clip_l.safetensors"], "vae": "ae.safetensors",
            "prompt": "a cat on a windowsill"}
    if guider == "CFGGuider":
        want["cfg"] = 1.0
    check('Flux with %s: its fields; no negative, no shift' % guider, got, want)

aura = sd15(**{"30": node("ModelSamplingAuraFlow", model=["4", 0], shift=3.0)})
aura["3"]["inputs"]["model"] = ["30", 0]
check('ModelSamplingAuraFlow on the model\'s way: its shift', read(aura).get("shift"), 3.0)

strings = sd15(**{
    "40": node("PrimitiveStringMultiline", value="an old mill"),
    "41": node("PrimitiveStringMultiline", value="by a river"),
    "42": node("StringConcatenate", string_a=["40", 0], string_b=["41", 0], delimiter=", "),
    "6": node("CLIPTextEncode", text=["42", 0], clip=["4", 1]),
    "7": node("CLIPTextEncode", text=["40", 0], clip=["4", 1]),
})
got = read(strings)
check('Prompt text in a string node, and in a concatenation of two',
      (got.get("negative"), got.get("prompt")), ("an old mill", "an old mill, by a river"))

wired = sd15(**{"50": node("PrimitiveInt", value=777), "51": node("ImpactInt", value=30)})
wired["3"]["inputs"]["seed"] = ["50", 0]
wired["3"]["inputs"]["steps"] = ["51", 0]
got = read(wired)
check('A seed and steps wired from primitives: their values', (got.get("seed"), got.get("steps")), (777, 30))
wired["53"] = node("SeedPlus", seed=888, increment=1)
wired["3"]["inputs"]["seed"] = ["53", 0]
check('A seed from a node holding two values: no seed', "seed" in read(wired), False)

loras = sd15(**{
    "60": node("LoraLoader", lora_name="styles\\ink_wash.safetensors", strength_model=0.8, strength_clip=0.6,
               model=["4", 0], clip=["4", 1]),
    "61": node("LoraLoader", lora_name="detail_tweaker.safetensors", strength_model=0.5, strength_clip=0.5,
               model=["60", 0], clip=["60", 1]),
    "62": node("Power Lora Loader (rgthree)", model=["61", 0], clip=["61", 1],
               lora_1={"on": True, "lora": "chars/heroine.safetensors", "strength": 1.0},
               lora_2={"on": False, "lora": "off_one.safetensors", "strength": 1.0}),
})
loras["3"]["inputs"]["model"] = ["62", 0]
check('Two LoraLoaders and a Power Lora Loader with one switched off: three LoRAs with their strengths',
      read(loras).get("loras"),
      [{"name": "heroine", "strength_model": 1.0, "strength_clip": 1.0},
       {"name": "detail_tweaker", "strength_model": 0.5, "strength_clip": 0.5},
       {"name": "ink_wash", "strength_model": 0.8, "strength_clip": 0.6}])

hires = sd15(**{
    "70": node("LatentUpscaleBy", samples=["3", 0], upscale_method="nearest-exact", scale_by=1.5),
    "71": node("KSampler", seed=5, steps=12, cfg=5.0, sampler_name="euler", scheduler="normal", denoise=0.5,
               model=["4", 0], positive=["6", 0], negative=["7", 0], latent_image=["70", 0]),
    "8": node("VAEDecode", samples=["71", 0], vae=["4", 2]),
})
check('A hires chain: the first pass\'s settings and size', read(hires), SD15_FIELDS)

post = sd15(**{
    "80": node("UpscaleModelLoader", model_name="4x_ultra.pth"),
    "81": node("ImageUpscaleWithModel", upscale_model=["80", 0], image=["8", 0]),
    "82": node("FaceDetailer", image=["81", 0], model=["4", 0], clip=["4", 1], vae=["4", 2],
               positive=["6", 0], negative=["7", 0], seed=1, steps=10, cfg=4.0, sampler_name="euler",
               scheduler="normal", denoise=0.4, bbox_detector=["83", 0]),
    "83": node("UltralyticsDetectorProvider", model_name="face_yolov8m.pt"),
    "84": node("ImageSharpen", image=["82", 0], sharpen_radius=1, sigma=1.0, alpha=0.5),
    "9": node("SaveImage", filename_prefix="ComfyUI", images=["84", 0]),
})
check('An upscale, a FaceDetailer and an ImageSharpen after the decoder: the first pass\'s fields',
      read(post), SD15_FIELDS)

two_inputs = sd15(**{
    "85": node("SomeMerge", image=["8", 0], images=["8", 0]),
    "9": node("SaveImage", filename_prefix="ComfyUI", images=["85", 0]),
})
check('A node with two listed picture inputs wired before the save: nothing', read(two_inputs), {})

preprocessor = sd15(**{
    "86": node("LoadImage", image="pose.png", upload="image"),
    "87": node("CannyEdgePreprocessor", image=["86", 0], low_threshold=100, high_threshold=200),
    "88": node("SaveImage", filename_prefix="canny", images=["87", 0]),
})
check('A ControlNet preprocessor\'s map saved beside the picture: the picture\'s fields',
      read(preprocessor), SD15_FIELDS)

repeat = sd15(**{"89": node("RepeatLatentBatch", samples=["5", 0], amount=4)})
repeat["3"]["inputs"]["latent_image"] = ["89", 0]
got = read(repeat)
check('A RepeatLatentBatch between the empty latent and the sampler: its size',
      (got.get("width"), got.get("height")), (512, 768))

two_firsts = sd15(**{
    "90": node("EmptyLatentImage", width=640, height=640, batch_size=1),
    "91": node("KSampler", seed=9, steps=9, cfg=3.0, sampler_name="euler", scheduler="normal", denoise=1.0,
               model=["4", 0], positive=["6", 0], negative=["7", 0], latent_image=["90", 0]),
    "92": node("VAEDecode", samples=["91", 0], vae=["4", 2]),
    "93": node("SaveImage", filename_prefix="second", images=["92", 0]),
})
check('Two save nodes leading to two first-pass samplers: no sampler field', read(two_firsts), {})
one_first = sd15(**{"93": node("SaveImage", filename_prefix="again", images=["8", 0])})
check('Two save nodes leading to one first-pass sampler: every field', read(one_first), SD15_FIELDS)

img2img = sd15(**{
    "100": node("LoadImage", image="photo.png", upload="image"),
    "101": node("VAEEncode", pixels=["100", 0], vae=["4", 2]),
})
img2img["3"]["inputs"]["latent_image"] = ["101", 0]
img2img["3"]["inputs"]["denoise"] = 0.6
del img2img["5"]
want = {k: v for k, v in SD15_FIELDS.items() if k not in ("width", "height")}
check('An img2img graph: the sampler\'s settings, no size, no denoise', read(img2img), want)
img2img2 = dict(img2img)
img2img2["102"] = node("KSampler", seed=1, steps=8, cfg=2.0, sampler_name="euler", scheduler="normal", denoise=0.3,
                       model=["4", 0], positive=["6", 0], negative=["7", 0], latent_image=["3", 0])
img2img2["8"] = node("VAEDecode", samples=["102", 0], vae=["4", 2])
check('An img2img graph with a second pass: the pass farthest back', read(img2img2), want)

combine = sd15(**{"110": node("ConditioningCombine", conditioning_1=["6", 0], conditioning_2=["7", 0])})
combine["3"]["inputs"]["positive"] = ["110", 0]
check('A ConditioningCombine on the prompt\'s way: no prompt, every other field read',
      read(combine), without(SD15_FIELDS, "prompt"))
unknown = sd15(**{
    "111": node("MysteryModelPatch", model=["4", 0], amount=2),
    "112": node("LoraLoader", lora_name="after.safetensors", strength_model=1.0, strength_clip=1.0,
                model=["111", 0], clip=["4", 1]),
})
unknown["3"]["inputs"]["model"] = ["112", 0]
got = read(unknown)
check('An unknown node on the model\'s way: no checkpoint, the LoRAs before it read',
      ("checkpoint" in got, [x["name"] for x in got.get("loras", [])]), (False, ["after"]))

loop = sd15()
loop["8"] = node("VAEDecode", samples=["120", 0], vae=["4", 2])
loop["120"] = node("SomeFilter", samples=["121", 0])
loop["121"] = node("SomeFilter", samples=["120", 0])
check('Wires that loop on the picture\'s way: answers and stops', watched(loop), {})
model_loop = sd15(**{"130": node("LoraLoader", lora_name="x.safetensors", strength_model=1.0, strength_clip=1.0,
                                 model=["131", 0], clip=["4", 1]),
                     "131": node("RescaleCFG", model=["130", 0], multiplier=0.7)})
model_loop["3"]["inputs"]["model"] = ["130", 0]
check('Wires that loop on the model\'s way: answers and stops, no checkpoint',
      watched(model_loop), dict(without(SD15_FIELDS, "checkpoint"),
                                loras=[{"name": "x", "strength_model": 1.0, "strength_clip": 1.0}]))
prompt_loop = sd15(**{"132": node("ControlNetApplyAdvanced", positive=["133", 0], negative=["7", 0], strength=1.0),
                      "133": node("ConditioningSetTimestepRange", conditioning=["132", 0], start=0.0, end=1.0)})
prompt_loop["3"]["inputs"]["positive"] = ["132", 0]
check('Wires that loop on the prompt\'s way: answers and stops, no prompt',
      watched(prompt_loop), without(SD15_FIELDS, "prompt"))
latent_loop = sd15(**{"134": node("SomeLatentFilter", samples=["135", 0]),
                      "135": node("SomeLatentFilter", samples=["134", 0])})
latent_loop["3"]["inputs"]["latent_image"] = ["134", 0]
check('Wires that loop on the latent\'s way: answers and stops, no size',
      watched(latent_loop), without(SD15_FIELDS, "width", "height"))
text_loop = sd15(**{"136": node("StringConcatenate", string_a="a fox", string_b=["136", 0], delimiter=" ")})
text_loop["6"]["inputs"]["text"] = ["136", 0]
check('A concatenation that leads back into itself: answers and stops, no prompt',
      watched(text_loop), without(SD15_FIELDS, "prompt"))
big = sd15(**{str(1000 + i): node("Note", text="x") for i in range(comfy_graph.NODE_LIMIT)})
check('A graph over the node limit: nothing', read(big), {})
chain = sd15()
last = ["8", 0]
for i in range(comfy_graph.NODE_LIMIT - len(chain)):
    chain[str(5000 + i)] = node("SomeFilter", image=last)
    last = [str(5000 + i), 0]
chain["9"] = node("SaveImage", filename_prefix="long", images=last)
try:
    got = read(chain)
except RecursionError:
    got = "RecursionError"
check('A chain of nodes at the limit: read, no RecursionError', got, SD15_FIELDS)

huge_seed = json.dumps(sd15()).replace("123456789", "9" * 5001)
check('A seed of 5,001 digits: no seed, every other field read', read(huge_seed), without(SD15_FIELDS, "seed"))
deep = '{"1": ' * 100000 + '1' + '}' * 100000
check('Nesting deeper than Python\'s limit: no graph, no error', read(deep), {})

check('A checkpoint named with a Windows subfolder, read under Linux\'s path rules: its stem',
      (comfy_graph.stem("SDXL\\model.safetensors"), comfy_graph.stem("a/b\\c.ckpt")), ("model", "c"))
check('The same for a LoRA', read(loras)["loras"][-1]["name"], "ink_wash")

preview = sd15()
preview["9"] = node("PreviewImage", images=["8", 0])
check('PreviewImage only: read from the preview', read(preview), SD15_FIELDS)
nothing = sd15()
del nothing["9"]
check('No output node: nothing', read(nothing), {})

check('The graph as text holding JSON, and as an object: the same answer', read(json.dumps(sd15())), read(sd15()))
check('Not a graph: nothing', (read("not json"), read([1, 2]), read(None), read({"a": 1})), ({}, {}, {}, {}))


# ------------------------------------------------- the rest of part 1's rules

for odd in (["CLIPTextEncode"], {"a": 1}, 5, None):
    bad = sd15()
    bad["8"]["class_type"] = odd
    bad["6"]["class_type"] = odd
    bad["4"]["class_type"] = odd
    try:
        got = read(bad)
    except Exception as e:                     # noqa: BLE001 - any error is the fault
        got = type(e).__name__
    # The decoder, of no class, is passed by its one picture input (decision 12);
    # the prompt's encoder and the checkpoint loader, of none, give nothing.
    check('A class_type of %r: no error; no prompt or checkpoint from those nodes' % (odd,), got,
          without(SD15_FIELDS, "prompt", "checkpoint"))

nan_cfg = json.dumps(sd15()).replace('"cfg": 7.5', '"cfg": NaN')
check('A CFG of NaN: no CFG, every other field read', read(nan_cfg), without(SD15_FIELDS, "cfg"))
inf_lora = json.dumps(loras).replace('"strength_model": 0.8', '"strength_model": Infinity')
check('A LoRA strength of Infinity: no strength', read(inf_lora)["loras"][-1]["strength_model"], None)

advanced = sd15()
advanced["3"] = node("KSamplerAdvanced", add_noise="enable", noise_seed=4242, steps=30, cfg=6.0,
                     sampler_name="euler_ancestral", scheduler="normal", start_at_step=0, end_at_step=10000,
                     return_with_leftover_noise="disable", model=["4", 0], positive=["6", 0], negative=["7", 0],
                     latent_image=["5", 0])
check('KSamplerAdvanced: its noise_seed as the seed', read(advanced),
      dict(SD15_FIELDS, seed=4242, steps=30, cfg=6.0, sampler="euler_ancestral", scheduler="normal"))

custom = sd15(**{"140": node("KSamplerSelect", sampler_name="lms"),
                 "141": node("BasicScheduler", scheduler="exponential", steps=18, denoise=1.0, model=["4", 0])})
custom["3"] = node("SamplerCustom", add_noise=True, noise_seed=31337, cfg=4.5, model=["4", 0], positive=["6", 0],
                   negative=["7", 0], sampler=["140", 0], sigmas=["141", 0], latent_image=["5", 0])
check('SamplerCustom: its seed, CFG, sampler, schedule type and steps', read(custom),
      dict(SD15_FIELDS, seed=31337, cfg=4.5, sampler="lms", scheduler="exponential", steps=18))

shifts = sd15(**{"142": node("ModelSamplingSD3", model=["143", 0], shift=6.0),
                 "143": node("ModelSamplingAuraFlow", model=["4", 0], shift=2.0)})
shifts["3"]["inputs"]["model"] = ["142", 0]
check('ModelSamplingSD3 nearest the sampler, an AuraFlow one behind it: the nearest shift',
      read(shifts).get("shift"), 6.0)

guidance = flux("BasicGuider")
guidance["150"] = node("FluxGuidance", guidance=2.0, conditioning=["14", 0])
guidance["15"] = node("FluxGuidance", guidance=4.0, conditioning=["150", 0])
check('Two FluxGuidance on the prompt\'s way: the one nearest the sampler', read(guidance).get("distilled_cfg"), 4.0)

clip_way = sd15(**{"151": node("CLIPLoader", clip_name="clip_g.safetensors", type="stable_diffusion"),
                   "152": node("CLIPSetLastLayer", clip=["151", 0], stop_at_clip_layer=-2),
                   "153": node("LoraLoader", lora_name="ink.safetensors", strength_model=1.0, strength_clip=1.0,
                               model=["4", 0], clip=["152", 0])})
clip_way["6"]["inputs"]["clip"] = ["153", 1]
check('The prompt encoder\'s clip through CLIP Set Last Layer and a LoRA loader: its text encoder',
      read(clip_way).get("text_encoders"), ["clip_g.safetensors"])

controlnet = sd15(**{"154": node("CLIPTextEncode", text="other text", clip=["4", 1]),
                     "155": node("ControlNetApplyAdvanced", positive=["6", 0], negative=["7", 0],
                                 conditioning=["154", 0], strength=1.0, start_percent=0.0, end_percent=1.0)})
controlnet["3"]["inputs"]["positive"] = ["155", 0]
controlnet["3"]["inputs"]["negative"] = ["155", 1]
got = read(controlnet)
check('A ControlNet apply: each side followed by its own input',
      (got.get("prompt"), got.get("negative")), ("a red fox in snow", "blurry"))

kinds = flux()
kinds["23"] = node("VAEDecodeTiled", samples=["22", 0], vae=["12", 0], tile_size=512)
kinds["11"] = node("TripleCLIPLoader", clip_name1="a.safetensors", clip_name2="b.safetensors",
                   clip_name3="c.safetensors")
kinds["10"] = node("UnetLoaderGGUF", unet_name="gguf/flux1-dev-Q8_0.gguf")
got = read(kinds)
check('VAEDecodeTiled, TripleCLIPLoader and the GGUF loader',
      (got.get("vae"), got.get("text_encoders"), got.get("checkpoint")),
      ("ae.safetensors", ["a.safetensors", "b.safetensors", "c.safetensors"], "flux1-dev-Q8_0"))

two = sd15(**{"156": node("Power Lora Loader (rgthree)", model=["4", 0], clip=["4", 1],
                          lora_1={"on": True, "lora": "split.safetensors", "strength": 0.7, "strengthTwo": 0.3})})
two["3"]["inputs"]["model"] = ["156", 0]
check('A Power Lora Loader\'s strengthTwo as the CLIP strength', read(two).get("loras"),
      [{"name": "split", "strength_model": 0.7, "strength_clip": 0.3}])

zero_size = sd15()
zero_size["5"]["inputs"]["width"] = 0
check('An empty latent of width 0: no width', "width" in read(zero_size), False)

for seed in (18446744073709551615, 0):
    seeded = sd15()
    seeded["3"]["inputs"]["seed"] = seed
    check('A seed of %d, as text and as an object: kept' % seed,
          (read(json.dumps(seeded)).get("seed"), read(seeded).get("seed")), (seed, seed))

twice = sd15(**{"157": node("PrimitiveStringMultiline", value="snow"),
                "158": node("StringConcatenate", string_a=["157", 0], string_b=["157", 0], delimiter=" and ")})
twice["6"]["inputs"]["text"] = ["158", 0]
check('A concatenation of one text twice: both joined', read(twice).get("prompt"), "snow and snow")

vaes = sd15(**{"160": node("VAELoader", vae_name="a.safetensors"), "161": node("VAELoader", vae_name="b.safetensors"),
               "162": node("VAEDecode", samples=["3", 0], vae=["161", 0]),
               "163": node("SaveImage", filename_prefix="second", images=["162", 0])})
vaes["8"]["inputs"]["vae"] = ["160", 0]
check('Two decoders naming two VAEs: no VAE', "vae" in read(vaes), False)
vaes["162"]["inputs"]["vae"] = ["160", 0]
check('Two decoders naming one VAE: that VAE', read(vaes).get("vae"), "a.safetensors")


for line in fails:
    print('FAIL', line)
print('%d failed' % len(fails) if fails else 'comfy_graph_test: all passed')
sys.exit(1 if fails else 0)
