"""
The prompts other tools write into their images, for Sync images (#408).

Forge's infotext is read first (image_text.read_text); these readers run only
where it is not there. Each knows one tool's format and answers the prompt and
negative prompt it holds, with the tool's name where the file says it:
{"prompt", "negative", "tool"}, or None. A negative alone is no answer, and
neither is a blank prompt. Settings are not read: the JSON formats carry them
in shapes of their own, which #232 takes on with ComfyUI's graph.

Two kinds of reader:

- JSON that a tool writes where Forge writes its text - PNG's `parameters`,
  the EXIF UserComment, a JPEG's comment (`from_json`). The first reader whose
  mark the object has decides; JSON no reader knows gives nothing, never text.
- a tool's own text chunks in a PNG (`from_chunks`), read only when no place
  held Forge's text or JSON a reader knew. The first whose chunk is there
  decides. `workflow` is never parsed, and `prompt` holding JSON is ComfyUI's
  graph, left to #232.

The survey of the formats - 19 tools, with the commits read - is linked from
#408.
"""
import html
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

Prompts = Dict[str, Optional[str]]


_TOO_DEEP: Dict[str, Any] = {}
_WHOLE_NUMBER = object()


def _loads(text: str) -> Any:
    """json.loads, a whole number left unconverted: no reader wants one, and
    one past 4,300 digits raises in Neo's Python and not in the original
    Forge's, which would read one file two ways. JSON nested deeper than
    Python's recursion allows is JSON no reader knows."""
    try:
        return json.loads(text, parse_int=lambda digits: _WHOLE_NUMBER)
    except RecursionError:
        return _TOO_DEEP


def json_object(text: Any) -> Optional[Dict[str, Any]]:
    """`text` parsed as JSON when it is an object; None for anything else - a
    list and a quoted string included, which stay text. Forge's text fails
    within its first characters."""
    if not isinstance(text, str):
        return None
    try:
        value = _loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _value(value: Any) -> Optional[str]:
    """A prompt as a reader hands it on: stripped, and None for a blank, JSON's
    null, or the text `None` Easy Diffusion writes for a value it lacks."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and value != "None" else None


def _answer(prompt: Any, negative: Any, tool: Optional[str]) -> Optional[Prompts]:
    prompt = _value(prompt)
    if not prompt:
        return None
    return {"prompt": prompt, "negative": _value(negative), "tool": tool}


# ------------------------------------------------------------- JSON where Forge's text goes

def _swarm(data: Dict[str, Any]) -> Optional[Prompts]:
    params = data["sui_image_params"]
    return _answer(params.get("prompt"), params.get("negativeprompt"), "SwarmUI")


def _ruined_fooocus(data: Dict[str, Any]) -> Optional[Prompts]:
    # Its video pipeline's short form names the prompt in lower case.
    return _answer(data.get("Prompt", data.get("prompt")), data.get("Negative"), "RuinedFooocus")


def _fooocus(data: Dict[str, Any]) -> Optional[Prompts]:
    # The typed prompt, as the recorder keeps a prompt before styles; the one
    # its styles expanded to only when nothing was typed.
    prompt = _value(data.get("prompt"))
    if not prompt:
        full = data.get("full_prompt")
        if isinstance(full, list):
            prompt = ", ".join(p.strip() for p in full if isinstance(p, str) and p.strip())
        else:
            prompt = full
    return _answer(prompt, data.get("negative_prompt"), "Fooocus")


def _civitai(data: Dict[str, Any]) -> Optional[Prompts]:
    # Civitai's early on-site images: the prompts are in `extraMetadata`, JSON
    # in a string, at times encoded twice.
    meta = data.get("extraMetadata")
    if meta is None and isinstance(data.get("extra"), dict):
        meta = data["extra"].get("extraMetadata")
    for _ in range(2):
        if isinstance(meta, str):
            try:
                meta = _loads(meta)
            except ValueError:
                return None
    if not isinstance(meta, dict):
        return None
    return _answer(meta.get("prompt"), meta.get("negativePrompt"), "Civitai")


def _easy_diffusion(data: Dict[str, Any]) -> Optional[Prompts]:
    if "prompt" in data:
        return _answer(data.get("prompt"), data.get("negative_prompt"), "Easy Diffusion")
    return _answer(data.get("Prompt"), data.get("Negative Prompt"), "Easy Diffusion")


_JSON_READERS: List[Tuple[Callable[[Dict[str, Any]], bool], Callable[[Dict[str, Any]], Optional[Prompts]]]] = [
    (lambda d: isinstance(d.get("sui_image_params"), dict), _swarm),
    (lambda d: d.get("software") == "RuinedFooocus", _ruined_fooocus),
    (lambda d: "full_prompt" in d, _fooocus),
    (lambda d: "extra" in d, _civitai),
    (lambda d: ("prompt" in d and "negative_prompt" in d)
     or ("Prompt" in d and "Negative Prompt" in d), _easy_diffusion),
]


def from_json(data: Dict[str, Any]) -> Optional[Prompts]:
    """The prompts in a JSON object found where Forge writes its text, by the
    first reader whose mark it has; None when no reader knows it."""
    for marked, read in _JSON_READERS:
        if marked(data):
            return read(data)
    return None


# ------------------------------------------------------------- a PNG's own chunks

def _text(info: Dict[str, Any], key: str) -> Optional[str]:
    value = info.get(key)
    return value if isinstance(value, str) else None


def _invokeai(info: Dict[str, Any]) -> Optional[Prompts]:
    data = json_object(_text(info, "invokeai_metadata")) or {}
    return _answer(data.get("positive_prompt"), data.get("negative_prompt"), "InvokeAI")


_DREAM_PROMPT = re.compile(r'"([^"]*)"')


def _invokeai_2(info: Dict[str, Any]) -> Optional[Prompts]:
    # InvokeAI 2.x writes its negative inside the prompt, in brackets, and it
    # is left there: the whole text is the prompt.
    image = (json_object(_text(info, "sd-metadata")) or {}).get("image")
    prompt = image.get("prompt") if isinstance(image, dict) else None
    if isinstance(prompt, list):
        first = prompt[0] if prompt else None
        prompt = first.get("prompt") if isinstance(first, dict) else None
    if not _value(prompt):
        # `Dream` is its command line: the prompt is the first quoted text.
        match = _DREAM_PROMPT.search(_text(info, "Dream") or "")
        prompt = match.group(1) if match else None
    return _answer(prompt, None, "InvokeAI")


def _novelai(info: Dict[str, Any]) -> Optional[Prompts]:
    comment = json_object(_text(info, "Comment")) or {}
    return _answer(_text(info, "Description"), comment.get("uc"), "NovelAI")


def _plain_prompt(info: Dict[str, Any]) -> Optional[Prompts]:
    text = _text(info, "prompt")
    try:
        parsed = _loads(text) if text is not None else None
    except ValueError:
        parsed = None
    if isinstance(parsed, (dict, list)):
        return None     # ComfyUI's graph (#232)
    # A prompt such as `{red|blue} car` or `[cat:dog:0.5]` is no JSON: text.
    if "batch_index" in info or "creation_time" in info:
        tool = "Endless"
    elif "use_stable_diffusion_model" in info:
        tool = "Easy Diffusion"
    else:
        tool = None
    return _answer(text, _text(info, "negative_prompt"), tool)


def _easy_diffusion_txt(info: Dict[str, Any]) -> Optional[Prompts]:
    return _answer(_text(info, "Prompt"), _text(info, "Negative Prompt"), "Easy Diffusion")


def _xmp_comment(xmp: str) -> Optional[str]:
    """
    The text of an XMP packet's `exif:UserComment` element, where Draw Things
    puts its JSON. An image's XML is not trusted to a parser: each tag is
    found after the one before, so the packet is read once - a pattern with
    two open-ended spans read it again from every opening tag, 1.8 s for a
    made-up 10 KB packet of unclosed ones.
    """
    start = xmp.find("<exif:UserComment")
    end = xmp.find("</exif:UserComment>", start) if start >= 0 else -1
    item = xmp.find("<rdf:li", start, end) if end >= 0 else -1
    opened = xmp.find(">", item, end) if item >= 0 else -1
    closed = xmp.find("</rdf:li>", opened, end) if opened >= 0 else -1
    return xmp[opened + 1:closed] if closed >= 0 else None


def _draw_things(info: Dict[str, Any]) -> Optional[Prompts]:
    found = _xmp_comment(_text(info, "XML:com.adobe.xmp") or "")
    data = json_object(html.unescape(found)) if found is not None else None
    if not data or "c" not in data:
        return None
    return _answer(data.get("c"), data.get("uc"), "Draw Things")


_CHUNK_READERS: List[Tuple[Callable[[Dict[str, Any]], bool], Callable[[Dict[str, Any]], Optional[Prompts]]]] = [
    (lambda i: "invokeai_metadata" in i, _invokeai),
    (lambda i: "sd-metadata" in i or "Dream" in i, _invokeai_2),
    # Software is required: Crystools writes a `Description` too.
    (lambda i: (_text(i, "Software") or "").strip() == "NovelAI", _novelai),
    (lambda i: "prompt" in i, _plain_prompt),
    (lambda i: "Prompt" in i, _easy_diffusion_txt),
    (lambda i: "XML:com.adobe.xmp" in i, _draw_things),
]


def from_chunks(info: Dict[str, Any]) -> Optional[Prompts]:
    """The prompts in an image's own text chunks (PIL's `info`), by the first
    reader whose chunk is there; None when none is."""
    for there, read in _CHUNK_READERS:
        if there(info):
            return read(info)
    return None
