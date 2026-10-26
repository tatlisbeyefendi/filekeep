"""Map file extensions to coarse kinds used for filtering and organising."""

from __future__ import annotations

KIND_FOLDERS: dict[str, str] = {
    "image": "Photos",
    "video": "Videos",
    "audio": "Music",
    "document": "Documents",
    "sheet": "Spreadsheets",
    "slides": "Presentations",
    "archive": "Archives",
    "code": "Code",
    "data": "Data",
    "font": "Fonts",
    "app": "Apps",
    "other": "Other",
}

EXT_KINDS: dict[str, str] = {}


def _register(kind: str, extensions: str) -> None:
    for extension in extensions.split():
        EXT_KINDS[extension] = kind


_register(
    "image",
    "jpg jpeg png gif bmp webp tif tiff heic heif avif svg ico raw cr2 nef arw dng psd xcf",
)
_register("video", "mp4 mkv avi mov wmv flv webm m4v mpg mpeg 3gp ts vob")
_register("audio", "mp3 wav flac aac ogg oga opus m4a wma aiff alac mid midi")
_register(
    "document",
    "pdf doc docx odt rtf txt md rst tex epub mobi azw3 djvu pages log nfo",
)
_register("sheet", "xls xlsx xlsm ods csv tsv numbers")
_register("slides", "ppt pptx odp key")
_register(
    "archive",
    "zip tar gz tgz bz2 tbz2 xz txz zst zstd 7z rar iso dmg pkg deb rpm apk jar war",
)
_register(
    "code",
    "py pyi pyx js mjs cjs ts tsx jsx go rs rb java kt kts c h cpp cc cxx hpp hh cs swift "
    "php pl lua r jl scala clj ex exs erl hs ml fs sh bash zsh fish ps1 bat cmd sql html htm "
    "css scss sass less vue svelte astro toml yaml yml json jsonc ini cfg conf env proto graphql",
)
_register("data", "db sqlite sqlite3 parquet avro orc pkl pickle npy npz h5 hdf5 feather arrow")
_register("font", "ttf otf woff woff2 eot")
_register("app", "exe msi app appimage snap flatpak bin run out o dll so dylib")
_register("archive", "gitignore")

TEXT_EXTENSIONS = frozenset(
    {"txt", "md", "rst", "log", "csv", "tsv", "json", "yaml", "yml", "toml"}
)


def kind_for(ext: str) -> str:
    """Return the kind for a lower-case extension (without the dot)."""
    if not ext:
        return "other"
    return EXT_KINDS.get(ext.lower(), "other")


def ext_of(name: str) -> str:
    """Return the lower-case extension of a file name, or ``""`` when there is none."""
    dot = name.rfind(".")
    # ".bashrc" has no extension but "archive.tar.gz" has "gz".
    if dot <= 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1 :].lower()


def folder_for_kind(kind: str) -> str:
    """Return the destination folder name used by ``filekeep organize --by kind``."""
    return KIND_FOLDERS.get(kind, KIND_FOLDERS["other"])


def known_kinds() -> list[str]:
    """Return all kind names, in a stable display order."""
    return list(KIND_FOLDERS)
