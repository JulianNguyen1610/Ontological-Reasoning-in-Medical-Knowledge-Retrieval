"""Lossless raw-byte loading for MedLink-IE source documents."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from medlink_ie.domain import SourceDocument


_UTF8_BOM = b"\xef\xbb\xbf"


class BomPolicy(str, Enum):
    """The explicit handling policy for a leading UTF-8 byte-order mark."""

    PRESERVE = "preserve"
    STRIP = "strip"
    REJECT = "reject"


class RawLoaderError(Exception):
    """Base class for failures that occur while loading raw input."""


class RawLoaderConfigurationError(RawLoaderError):
    """Raised when a raw-loader configuration is unsupported."""


class BomPolicyError(RawLoaderError):
    """Raised when an input BOM violates the configured policy."""

    def __init__(self, document_id: str, byte_length: int) -> None:
        self.document_id = document_id
        self.byte_length = byte_length
        super().__init__("UTF-8 BOM rejected by raw-loader policy")


class DocumentDecodeError(RawLoaderError):
    """A decode error containing only safe positional metadata."""

    def __init__(
        self,
        document_id: str,
        encoding: str,
        byte_start: int,
        byte_end: int,
        byte_length: int,
    ) -> None:
        self.document_id = document_id
        self.encoding = encoding
        self.byte_start = byte_start
        self.byte_end = byte_end
        self.byte_length = byte_length
        super().__init__(
            "unable to decode input "
            f"(encoding={encoding}, byte_range=[{byte_start},{byte_end}), byte_length={byte_length})"
        )


@dataclass(frozen=True, slots=True)
class RawLoaderConfig:
    """Explicit, strict decoding configuration for :func:`load_path`."""

    encoding: str = "utf-8"
    bom_policy: BomPolicy = BomPolicy.STRIP

    def __post_init__(self) -> None:
        if not isinstance(self.encoding, str) or not self.encoding:
            raise RawLoaderConfigurationError("encoding must be a non-empty string")
        try:
            codec = codecs.lookup(self.encoding)
        except LookupError as error:
            raise RawLoaderConfigurationError(
                "encoding is not a registered codec"
            ) from error
        if codec.name == "utf-8-sig":
            raise RawLoaderConfigurationError(
                "utf-8-sig is not supported; configure bom_policy instead"
            )
        if not isinstance(self.bom_policy, BomPolicy):
            raise RawLoaderConfigurationError("bom_policy must be a BomPolicy")


def load_path(
    path: str | Path, config: RawLoaderConfig = RawLoaderConfig()
) -> SourceDocument:
    """Load *path* without changing its bytes, newlines, or decoded text."""

    source_path = Path(path)
    return load_bytes(source_path.read_bytes(), source_path.stem, config)


def load_bytes(
    raw_bytes: bytes,
    document_id: str,
    config: RawLoaderConfig = RawLoaderConfig(),
) -> SourceDocument:
    """Create a lossless :class:`SourceDocument` from already-read bytes."""

    if not isinstance(raw_bytes, bytes):
        raise TypeError("raw_bytes must be bytes")
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("document_id must be a non-empty string")
    if not isinstance(config, RawLoaderConfig):
        raise TypeError("config must be a RawLoaderConfig")

    had_bom = raw_bytes.startswith(_UTF8_BOM)
    bytes_to_decode = raw_bytes
    byte_offset = 0
    if had_bom:
        if config.bom_policy is BomPolicy.REJECT:
            raise BomPolicyError(document_id, len(raw_bytes))
        if config.bom_policy is BomPolicy.STRIP:
            bytes_to_decode = raw_bytes[len(_UTF8_BOM) :]
            byte_offset = len(_UTF8_BOM)

    try:
        raw_text = bytes_to_decode.decode(config.encoding, errors="strict")
    except UnicodeDecodeError as error:
        raise DocumentDecodeError(
            document_id=document_id,
            encoding=config.encoding,
            byte_start=error.start + byte_offset,
            byte_end=error.end + byte_offset,
            byte_length=len(raw_bytes),
        ) from None

    return SourceDocument(
        document_id=document_id,
        raw_bytes=raw_bytes,
        raw_text=raw_text,
        encoding=config.encoding,
        had_bom=had_bom,
        newline_style=_detect_newline_style(raw_text),
    )


def _detect_newline_style(text: str) -> str:
    """Describe newline characters without modifying the decoded source text."""

    crlf_count = text.count("\r\n")
    cr_count = text.count("\r") - crlf_count
    lf_count = text.count("\n") - crlf_count
    styles = sum(count > 0 for count in (crlf_count, cr_count, lf_count))
    if styles == 0:
        return "none"
    if styles > 1:
        return "mixed"
    if crlf_count:
        return "crlf"
    if lf_count:
        return "lf"
    return "cr"
