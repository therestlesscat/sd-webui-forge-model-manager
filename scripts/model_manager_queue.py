"""
The generation queue's hooks, in txt2img and img2img.

An always-on script with nothing on screen: it hands two of Forge's hooks to
model_manager.scheduler.runner, which acts on the queue's own runs alone -
their checkpoint and modules, a Stop, an Interrupt. Apart from the recording
script, so the queue works with "Your generations" off.
"""
from modules import scripts

from model_manager.scheduler import runner


class ModelManagerQueue(scripts.Script):
    def title(self):
        return "Model Manager: queue"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        return []

    def before_process(self, p, *args):
        runner.on_before_process(p)

    def postprocess(self, p, processed, *args):
        runner.on_postprocess(p, processed)
