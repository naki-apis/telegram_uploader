import os
import re
import shutil
import subprocess


SIZE_UNITS = {
    "k": 1024,
    "kb": 1024,
    "m": 1024 ** 2,
    "mb": 1024 ** 2,
    "g": 1024 ** 3,
    "gb": 1024 ** 3,
}


def parse_size(text):
    text = text.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(k|kb|m|mb|g|gb)", text)
    if not m:
        raise ValueError(f"Tamaño inválido: {text}")
    value = float(m.group(1))
    unit = m.group(2)
    return int(value * SIZE_UNITS[unit])


def parse_zip_option(text, premium=False):
    if "/" in text:
        size_part, level_part = text.split("/", 1)
        try:
            level = int(level_part)
        except ValueError:
            raise ValueError(f"Nivel de compresión inválido: {level_part}")
        if level < 0 or level > 9:
            raise ValueError(f"Nivel de compresión fuera de rango (0-9): {level}")
    else:
        size_part = text
        level = 0

    size = parse_size(size_part)

    limit = 3995 * 1024 * 1024 if premium else 1995 * 1024 * 1024

    if size > limit:
        limit_label = "3.995G" if premium else "1.995G"
        raise ValueError(f"El tamaño {text} supera el límite permitido ({limit_label})")

    return size, level


def seven_zip_binary():
    for candidate in ("7zz", "7z", "7za"):
        path = shutil.which(candidate)
        if path:
            return path
    raise FileNotFoundError("No se encontró 7zz/7z/7za en el PATH")


def compress_to_volumes(path, volume_size, level=0):
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    seven = seven_zip_binary()

    path = os.path.abspath(path)

    if os.path.isdir(path):
        base_name = os.path.basename(os.path.normpath(path))
        parent = os.path.dirname(path)
        output_base = os.path.join(parent, base_name + ".7z")
    else:
        base_name = os.path.splitext(os.path.basename(path))[0]
        parent = os.path.dirname(path)
        output_base = os.path.join(parent, base_name + ".7z")

    volume_option = f"-v{volume_size}b"
    level_option = f"-mx{level}"

    cmd = [seven, "a", output_base, path, level_option, volume_option, "-y"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"7z falló: {result.stderr.strip() or result.stdout.strip()}")

    parts = _find_volumes(output_base)
    if not parts:
        if os.path.exists(output_base):
            parts = [output_base]
        else:
            raise RuntimeError("7z no generó volúmenes")

    return parts


def _find_volumes(output_base):
    parent = os.path.dirname(output_base)
    base = os.path.basename(output_base)
    parts = []
    if not os.path.isdir(parent):
        return parts
    for name in sorted(os.listdir(parent)):
        if name == base or name.startswith(base + "."):
            full = os.path.join(parent, name)
            if os.path.isfile(full):
                parts.append(full)
    return parts


def cleanup_volumes(parts):
    for p in parts:
        try:
            os.remove(p)
        except OSError:
            pass
