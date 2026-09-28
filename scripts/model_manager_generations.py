"""
Records the images you generate, in txt2img and img2img.

An always-on script with nothing on screen: it only hands Forge's hooks to
model_manager.generations, where what each hook can see, and why each is
used, is explained. Setting Settings -> Model Manager -> "record each image
generated" off stops it.
"""
from modules import script_callbacks, scripts

from model_manager import generations


class ModelManagerGenerations(scripts.Script):
    def title(self):
        return "Model Manager: record generations"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        return []

    def before_process(self, p, *args):
        generations.before_process(p)

    def process(self, p, *args):
        generations.process(p)

    def process_batch(self, p, *args, **kwargs):
        generations.process_batch(p)

    def postprocess_image_after_composite(self, p, pp, *args):
        generations.result_ready(p, pp)

    def postprocess(self, p, processed, *args):
        generations.postprocess(p, processed)


script_callbacks.on_image_saved(generations.image_saved)
