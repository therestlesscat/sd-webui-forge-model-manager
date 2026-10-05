"""
A value Generate is sent, as a task keeps it, and back (#150, #165).

Most of what Gradio hands Generate is JSON already: text, numbers, flags,
lists. The rest is kept as a small dict that says what it was:

  {"__image__": path}         a PIL image, saved as PNG
  {"__array__": path}         a numpy array: PNG when it holds an image, else .npy
  {"__file__": path}          a file Gradio had uploaded, copied
  {"__dataclass__": "module:Name", "fields": {...}}
  {"__enum__": "module:Name", "value": ...}
  {"__tuple__": [...]}        JSON would read it back as a list
  {"__dict__": {...}}         a dict holding one of these keys itself
  {"__missing__": "TypeName"} could not be kept: its control's default runs

ControlNet's units are a dataclass of enums and image arrays, and are kept
by these alone, as any extension's would be. A class is looked up again only
among modules already imported - the extension that made it has loaded by
the time a task runs - and nothing is imported for a name read back.

A task's files go to a folder of its own (Keeper), deleted with the task.
"""
import dataclasses
import enum
import os
import re
import shutil
import sys
from typing import Any, Dict, List

# restore()'s answer for a value that was not kept, or cannot be rebuilt.
MISSING = object()

_MARKS = ("__image__", "__array__", "__file__", "__dataclass__", "__enum__",
          "__tuple__", "__dict__", "__missing__", "__label__")


class _Missing(Exception):
    """A part of a value cannot be rebuilt, so neither can the value."""


def _class_path(cls) -> str:
    return f"{cls.__module__}:{cls.__qualname__}"


def _lookup(path: str):
    """A dataclass or enum by its stored name, among modules already imported."""
    module_name, _, qualname = path.partition(":")
    found = sys.modules.get(module_name)
    for part in qualname.split("."):
        found = getattr(found, part, None)
    if isinstance(found, type) and (dataclasses.is_dataclass(found) or issubclass(found, enum.Enum)):
        return found
    raise _Missing(path)


def _is_image(value) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    return isinstance(value, Image.Image)


def _is_array(value) -> bool:
    return type(value).__name__ == "ndarray" and type(value).__module__ == "numpy"


def _image_shaped(array) -> bool:
    return str(array.dtype) == "uint8" and (array.ndim == 2 or (array.ndim == 3 and array.shape[2] in (3, 4)))


class Keeper:
    """
    Keeps one task's values. Files go to the task's own folder, made only
    when a first file needs it; `files` lists every one written.
    """

    def __init__(self, folder: str):
        self.folder = folder
        self.files: List[str] = []
        self._used: Dict[str, int] = {}

    def _path(self, name: str, extension: str) -> str:
        os.makedirs(self.folder, exist_ok=True)
        base = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "value"
        count = self._used.get(base, 0)
        self._used[base] = count + 1
        path = os.path.join(self.folder, f"{base}-{count}{extension}" if count else f"{base}{extension}")
        self.files.append(path)
        return path

    def keep_file(self, path: str) -> Dict[str, str]:
        """A copy of a file Gradio had uploaded, which it may not keep."""
        stem, extension = os.path.splitext(os.path.basename(path))
        copy = self._path(stem, extension)
        shutil.copy2(path, copy)
        return {"__file__": copy}

    def keep(self, value: Any, name: str = "value") -> Any:
        """The value as JSON can hold it. `name` names any file it needs."""
        # An enum first: some are ints or strings too.
        if isinstance(value, enum.Enum):
            return {"__enum__": _class_path(type(value)), "value": self.keep(value.value, name)}
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return str(value)
        if _is_image(value):
            path = self._path(name, ".png")
            try:
                value.save(path, format="PNG")
            except (OSError, ValueError):
                # A mode PNG cannot hold - floats, say.
                return {"__missing__": type(value).__name__}
            return {"__image__": path}
        if _is_array(value):
            try:
                if _image_shaped(value):
                    from PIL import Image
                    path = self._path(name, ".png")
                    Image.fromarray(value).save(path, format="PNG")
                else:
                    import numpy
                    path = self._path(name, ".npy")
                    numpy.save(path, value, allow_pickle=False)
            except (OSError, ValueError):
                # An array of objects, which .npy keeps only by pickling.
                return {"__missing__": "ndarray"}
            return {"__array__": path}
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {"__dataclass__": _class_path(type(value)),
                    "fields": {f.name: self.keep(getattr(value, f.name), f"{name}-{f.name}")
                               for f in dataclasses.fields(value)}}
        if isinstance(value, tuple):
            return {"__tuple__": [self.keep(v, f"{name}-{i}") for i, v in enumerate(value)]}
        if isinstance(value, list):
            return [self.keep(v, f"{name}-{i}") for i, v in enumerate(value)]
        if isinstance(value, dict):
            if not all(isinstance(k, str) for k in value):
                return {"__missing__": "dict"}
            kept = {k: self.keep(v, f"{name}-{k}") for k, v in value.items()}
            return {"__dict__": kept} if any(k in _MARKS for k in kept) else kept
        return {"__missing__": type(value).__name__}


def restore(stored: Any) -> Any:
    """The value a task kept, rebuilt; MISSING if any part of it cannot be."""
    try:
        return _restore(stored)
    except _Missing:
        return MISSING


def _restore(stored: Any) -> Any:
    if isinstance(stored, list):
        return [_restore(v) for v in stored]
    if not isinstance(stored, dict):
        return stored
    if "__missing__" in stored:
        raise _Missing(stored["__missing__"])
    if "__image__" in stored:
        from PIL import Image
        path = _existing(stored["__image__"])
        with Image.open(path) as image:
            image.load()
            return image.copy()
    if "__array__" in stored:
        path = _existing(stored["__array__"])
        import numpy
        if path.endswith(".npy"):
            return numpy.load(path, allow_pickle=False)
        from PIL import Image
        with Image.open(path) as image:
            return numpy.array(image)
    if "__file__" in stored:
        return _existing(stored["__file__"])
    if "__enum__" in stored:
        try:
            return _lookup(stored["__enum__"])(_restore(stored["value"]))
        except ValueError:
            raise _Missing(stored["__enum__"])
    if "__dataclass__" in stored:
        cls = _lookup(stored["__dataclass__"])
        fields = {name: _restore(value) for name, value in stored["fields"].items()}
        known = {f.name: f for f in dataclasses.fields(cls)}
        try:
            built = cls(**{n: v for n, v in fields.items() if n in known and known[n].init})
            for n, v in fields.items():
                if n in known and not known[n].init:
                    setattr(built, n, v)
        except Exception:
            raise _Missing(stored["__dataclass__"])
        return built
    if "__tuple__" in stored:
        return tuple(_restore(v) for v in stored["__tuple__"])
    if "__dict__" in stored:
        return {k: _restore(v) for k, v in stored["__dict__"].items()}
    return {k: _restore(v) for k, v in stored.items()}


def _existing(path: str) -> str:
    if not os.path.isfile(path):
        raise _Missing(path)
    return path


def files(stored: Any) -> List[str]:
    """Every file a kept value names - for deleting a task's."""
    found: List[str] = []
    if isinstance(stored, list):
        for v in stored:
            found += files(v)
    elif isinstance(stored, dict):
        for mark in ("__image__", "__array__", "__file__"):
            if isinstance(stored.get(mark), str):
                found.append(stored[mark])
        for v in stored.values():
            if isinstance(v, (list, dict)):
                found += files(v)
    return found
