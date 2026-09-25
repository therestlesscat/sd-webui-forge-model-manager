"""
What a model file is, and which model it is for, from the file alone.

Civitai's type is what an uploader filed a file under: VAEs arrive as
"Checkpoint", text encoders as "LORA", and a file Civitai does not know has
no type at all. The file's tensor names and shapes say what it is, and for
most files which model it serves. Each family is built here from the names
and widths its real files have - the ones checked by hand against a library
of 1,262 files, and the ones that library had none of (Anima, Lumina,
Flux.2 Klein, ERNIE), from Forge's own model code.

A .ckpt or .pt is a pickle, which an ordinary unpickler runs as it loads.
Its shapes are read here without running anything in it; a pickle that
would create a file, and does under pickle.load, is checked not to.
"""
import io
import json
import os
import pickle
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import model_manager.architecture as arch                # noqa: E402
import model_manager.file_identity as fi                 # noqa: E402

WORK = os.path.join(TESTS, 'work', 'file_identity')
os.makedirs(WORK, exist_ok=True)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def not_forge(shapes):
    raise ValueError('Forge does not recognise this')


def what(tensors, guess=not_forge):
    """(type, preset) for tensors given as name -> shape."""
    found = fi.identify_shapes({n: (tuple(s), 'F16') for n, s in tensors.items()}, guess)
    return found.file_type, found.preset


def lora(names, down_in, up_out, rank=16, style='kohya'):
    """A LoRA's tensors for each layer name: down (rank, in), up (out, rank)."""
    out = {}
    for name in names:
        if style == 'kohya':
            out[f'{name}.alpha'] = ()
            out[f'{name}.lora_down.weight'] = (rank, down_in)
            out[f'{name}.lora_up.weight'] = (up_out, rank)
        else:
            out[f'{name}.lora_A.weight'] = (rank, down_in)
            out[f'{name}.lora_B.weight'] = (up_out, rank)
    return out


# ------------------------------------------------------- the SD family
SDXL_K = 'lora_unet_input_blocks_4_1_transformer_blocks_0_attn2_to_k'
SD1_K = 'lora_unet_down_blocks_0_attentions_0_transformer_blocks_0_attn2_to_k'
check('SD 1.x and SDXL LoRAs share names; the cross-attention context is 768 or 2048 wide',
      (what(lora([SD1_K], 768, 320)), what(lora([SDXL_K], 2048, 640))),
      (('LORA', 'sd'), ('LORA', 'xl')))
check('an SD 2.x LoRA is SD 2.x, which Forge Neo has no preset for',
      what(lora([SD1_K], 1024, 320)), ('LORA', None))
check('with no cross-attention, layers only SDXL has still say SDXL',
      what(lora(['lora_te2_text_model_encoder_layers_0_mlp_fc1'], 1280, 5120)), ('LORA', 'xl'))
check('and a block SD and SDXL share says nothing',
      what(lora(['lora_unet_output_blocks_8_0_in_layers_2'], 640, 320)), ('LORA', None))

# ------------------------------------------------- the LoRA family's formats
conv = lora(['lora_unet_down_blocks_0_resnets_0_conv1'], 320, 320)
conv['lora_unet_down_blocks_0_resnets_0_conv1.lora_down.weight'] = (16, 320, 3, 3)
check('LoRA on the 3x3 convolutions too is LoCon', what({**lora([SD1_K], 768, 320), **conv}),
      ('LoCon', 'sd'))
check('a 1x1 convolution does not make it one',
      what({**lora([SD1_K], 768, 320),
            'lora_unet_down_blocks_0_attentions_0_proj_in.lora_down.weight': (16, 320, 1, 1)}),
      ('LORA', 'sd'))
check('Hadamard weights are LoHa, and still carry the context width',
      what({f'{SD1_K}.hada_w1_a': (320, 32), f'{SD1_K}.hada_w1_b': (32, 768),
            f'{SD1_K}.hada_w2_a': (320, 32), f'{SD1_K}.hada_w2_b': (32, 768)}), ('LoHa', 'sd'))
check('Kronecker weights are LoKr',
      what({f'{SDXL_K}.lokr_w1': (8, 8), f'{SDXL_K}.lokr_w2': (80, 256)})[0], 'LoKr')
check('a magnitude term is DoRA', what({**lora([SDXL_K], 2048, 640), f'{SDXL_K}.dora_scale': (1, 2048)}),
      ('DoRA', 'xl'))
check('whole weight differences are LyCORIS Full', what({f'{SD1_K}.diff': (320, 768)}),
      ('LyCORIS Full', 'sd'))

# --------------------------------------------------------- the DiT families
check('Flux.1: single_blocks.linear2 takes attention plus a 4x MLP - 5x the width',
      what(lora(['lora_unet_single_blocks_0_linear2'], 15360, 3072)), ('LORA', 'flux'))
check('Flux.2 Klein: a gated 3x MLP makes it 4x',
      what(lora(['lora_unet_single_blocks_0_linear2'], 12288, 3072)), ('LORA', 'klein'))
check('and linear1\'s output, 7x against 9x',
      (what(lora(['single_blocks.0.linear1'], 3072, 21504, style='peft'))[1],
       what(lora(['single_blocks.0.linear1'], 3072, 27648, style='peft'))[1]), ('flux', 'klein'))
check('attention alone at 3072 cannot tell Flux.1 from Klein 4B',
      what(lora(['lora_unet_double_blocks_0_img_attn_proj'], 3072, 3072)), ('LORA', None))
check('at 4096 it is Klein 9B',
      what(lora(['lora_unet_double_blocks_0_img_attn_proj'], 4096, 4096)), ('LORA', 'klein'))
check('Qwen-Image by its image and text streams',
      what(lora(['diffusion_model.transformer_blocks.0.img_mlp.net.0.proj'], 3072, 12288, style='peft')),
      ('LORA', 'qwen'))
check('Wan by its self- and cross-attention',
      what(lora(['diffusion_model.blocks.0.cross_attn.k'], 5120, 5120, style='peft')), ('LORA', 'wan'))
check('as kohya names them too',
      what(lora(['lora_unet_blocks_0_cross_attn_k'], 5120, 5120)), ('LORA', 'wan'))
check('Anima\'s q_proj is not Wan\'s q',
      what(lora(['diffusion_model.blocks.0.self_attn.q_proj'], 2048, 2048, style='peft')),
      ('LORA', 'anima'))
check('Z-Image and Lumina 2 share a layout: 3840 wide against 2304',
      (what(lora(['diffusion_model.layers.0.attention.to_k'], 3840, 3840, style='peft')),
       what(lora(['diffusion_model.layers.0.attention.qkv'], 2304, 6912, style='peft'))),
      (('LORA', 'zit'), ('LORA', 'lumina')))
check('ERNIE-Image by its MLP names',
      what(lora(['layers.0.mlp.linear_fc1'], 4096, 12288, style='peft')), ('LORA', 'ernie'))
check('Krea 2 by its text fusion',
      what(lora(['transformer.text_fusion.layerwise_blocks.0.attn.to_gate'], 2560, 2560, style='peft')),
      ('LORA', 'krea'))

# ---------------------------------------------------------------- modules
check('a VAE is a VAE; an SD one fits SD and SDXL alike, so no one preset',
      what({'decoder.conv_in.weight': (512, 4, 3, 3)}), ('VAE', None))
check('as the Wan-style one fits four',
      what({'decoder.middle.0.residual.0.gamma': (384, 1, 1, 1)}), ('VAE', None))
check('a text encoder only one model uses gives that model',
      what({'model.embed_tokens.weight': (152064, 3584), 'visual.blocks.0.attn.qkv.weight': (3, 3)}),
      ('Text Encoder', 'qwen'))
check('one several use gives none',
      what({'model.embed_tokens.weight': (151936, 2560)}), ('Text Encoder', None))
check('a UMT5 in a layout Forge cannot load is still a text encoder - just not one to pick',
      what({'token_embedding.weight': (256384, 4096), 'blocks.0.attn.k.weight': (4096, 4096)}),
      ('Text Encoder', 'wan'))

# ---------------------------------------------------- the older file kinds
check('an embedding by its vector width', what({'emb_params': (8, 768)}), ('TextualInversion', 'sd'))
check('as a .pt names it', what({'string_to_param.*': (4, 768)}), ('TextualInversion', 'sd'))
check('an SDXL one carries a vector for each encoder',
      what({'clip_l': (8, 768), 'clip_g': (8, 1280)}), ('TextualInversion', 'xl'))
check('a hypernetwork by the attention widths it keys its layers by',
      what({'768.0.linear.0.weight': (1536, 768), '320.0.linear.0.weight': (640, 320)}),
      ('Hypernetwork', 'sd'))
check('an upscaler fits any model',
      what({'model.0.weight': (64, 3, 3, 3), 'model.1.sub.0.RDB1.conv1.0.weight': (32, 64, 3, 3)}),
      ('Upscaler', None))
check('and a layout nothing knows is Unknown', what({'something.weight': (3, 3)}), ('Unknown', None))

# ------------------------------------------------------------- checkpoints
class SDXL:
    text_encoder_key_prefix = ['conditioner.embedders.']
    vae_key_prefix = ['first_stage_model.']


def forge_says(config):
    return lambda shapes: (config, {n: None for n in shapes})


check('a checkpoint Forge recognises is its answer',
      what({'model.diffusion_model.x': (1,)}, guess=forge_says(SDXL())), ('Checkpoint', 'xl'))
check('one it does not is still a checkpoint, and its layers can say which',
      what({'model.diffusion_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight': (320, 768)}),
      ('Checkpoint', 'sd'))
check('SD3 is a checkpoint Forge Neo has no preset for',
      what({'model.diffusion_model.joint_blocks.0.x_block.attn.qkv.weight': (4608, 1536)}),
      ('Checkpoint', None))
check('a file whose header cannot be read is Unknown',
      (fi.identify(os.path.join(WORK, 'missing.safetensors')).file_type), 'Unknown')

# ------------------------------------------------------------ pickle files
marker = os.path.join(WORK, 'ran.txt')
proof = os.path.join(WORK, 'pickle_runs_it.txt')
for p in (marker, proof):
    if os.path.exists(p):
        os.remove(p)


class Payload:
    """Unpickles as a call to open(path, 'w') - a file appears if it runs."""
    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (open, (self.path, 'w'))


pickle.loads(pickle.dumps(Payload(proof)))
check('the payload does run under pickle.load - so it can show a reader does not',
      os.path.exists(proof))

bad = os.path.join(WORK, 'bad.ckpt')
with zipfile.ZipFile(bad, 'w') as z:
    z.writestr('archive/data.pkl', pickle.dumps({'state_dict': {'x': Payload(marker)}}))
arch.read_pickle_shapes(bad)
legacy_bad = os.path.join(WORK, 'bad_legacy.pt')
with open(legacy_bad, 'wb') as f:
    f.write(pickle.dumps(Payload(marker)))
arch.read_pickle_shapes(legacy_bad)
check('reading a pickle runs nothing in it, zipped or not', os.path.exists(marker), False)

try:
    import torch
except ImportError:
    torch = None
if torch is not None:
    ckpt = os.path.join(WORK, 'real.ckpt')
    torch.save({'state_dict': {'model.diffusion_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight':
                               torch.zeros(320, 768)}, 'global_step': 1}, ckpt)
    check('a real torch checkpoint gives its tensors, state_dict unwrapped',
          arch.read_pickle_shapes(ckpt),
          {'model.diffusion_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight': ((320, 768), 'F16')})
    old = os.path.join(WORK, 'old.pt')
    torch.save({'string_to_param': {'*': torch.zeros(4, 768)}}, old, _use_new_zipfile_serialization=False)
    check('as does the format before zip', arch.read_pickle_shapes(old),
          {'string_to_param.*': ((4, 768), 'F16')})
    check('and identify() reads .ckpt and .pt files', (fi.identify(old).file_type, fi.identify(old).preset),
          ('TextualInversion', 'sd'))
    hyper = os.path.join(WORK, 'hyper.pt')
    torch.save({768: [{'linear.0.weight': torch.zeros(2, 768)}], 'layer_structure': [1, 2, 1]}, hyper)
    check('a hypernetwork\'s layers sit in lists, and are read too',
          (fi.identify(hyper).file_type, fi.identify(hyper).preset), ('Hypernetwork', 'sd'))
else:
    print('torch is not installed; the real pickle checks were skipped')

# ------------------------------------------------------------- migration v23
# Before v23 only checkpoints were read, and never a .ckpt or .pt: every file
# read then has to be read again, once, for its type. One already read for
# its type is not.
import sqlite3                                            # noqa: E402
import model_manager.db.database as dbmod                 # noqa: E402
from model_manager.db.migrations import run_migrations    # noqa: E402
path22 = os.path.join(WORK, 'v22.db')
if os.path.exists(path22):
    os.remove(path22)
conn = sqlite3.connect(path22)
cur = conn.cursor()
cur.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
cur.execute("CREATE TABLE model_versions (id INTEGER, file_path TEXT PRIMARY KEY, "
            "architecture TEXT, architecture_checked TEXT)")
cur.executemany("INSERT INTO model_versions VALUES (?, ?, ?, ?)",
                [(1, 'sdxl.safetensors', 'xl', '2026-01-01'), (2, 'a_lora.safetensors', None, '2026-01-01')])
run_migrations(cur, 22, dbmod.SCHEMA_VERSION, path22, WORK)
columns = [row[1] for row in cur.execute("PRAGMA table_info(model_versions)")]
check('v23 adds the file\'s type and what decided it',
      ('file_type' in columns, 'identified_by' in columns), (True, True))
check('and marks every file read before as unread, so the next scan reads it for its type',
      cur.execute("SELECT architecture_checked FROM model_versions").fetchall(), [(None,), (None,)])
cur.execute("UPDATE model_versions SET file_type = 'LORA', architecture_checked = 'x' WHERE id = 2")
run_migrations(cur, 22, dbmod.SCHEMA_VERSION, path22, WORK)
check('run again, it leaves a file already read for its type alone',
      cur.execute("SELECT architecture_checked FROM model_versions WHERE id = 2").fetchone(), ('x',))
conn.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
