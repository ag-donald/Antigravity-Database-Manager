"""
Deterministic Protobuf Wire Format encoder for the Antigravity IDE's
internal ``trajectorySummaries`` schema.

Implements Wire Type 0 (Varint) and Wire Type 2 (Length-delimited) fields,
including the deeply nested Tag 3 (Field 9) and Tag 1 (Field 17) sub-messages.
"""

from __future__ import annotations

import base64


class ProtobufEncoder:
    """
    Deterministic Protobuf Wire Format encoder and non-destructive modifier.
    Supports parsing and patching existing blobs to preserve tool state.
    """

    # --- Encoding Helpers ---

    @staticmethod
    def write_varint(v: int) -> bytes:
        """Encode a non-negative integer as a Protobuf base-128 varint."""
        if v == 0:
            return b"\x00"
        result = bytearray()
        while v > 0x7F:
            result.append((v & 0x7F) | 0x80)
            v >>= 7
        result.append(v & 0x7F)
        return bytes(result)

    @classmethod
    def write_string_field(cls, field_num: int, value: str | bytes) -> bytes:
        """Encode a string or raw bytes as a length-delimited Protobuf field."""
        b = value.encode("utf-8") if isinstance(value, str) else value
        return cls.write_varint((field_num << 3) | 2) + cls.write_varint(len(b)) + b

    @classmethod
    def write_bytes_field(cls, field_num: int, value: bytes) -> bytes:
        """Encode raw bytes as a length-delimited Protobuf field."""
        return cls.write_varint((field_num << 3) | 2) + cls.write_varint(len(value)) + value

    @classmethod
    def write_varint_field(cls, field_num: int, value: int) -> bytes:
        """Encode an integer as a Protobuf varint field."""
        return cls.write_varint((field_num << 3) | 0) + cls.write_varint(value)

    @classmethod
    def write_timestamp(cls, field_num: int, epoch_seconds: int, nanos: int = 0) -> bytes:
        """Encode a Protobuf Timestamp message (seconds + nanos)."""
        inner = cls.write_varint_field(1, epoch_seconds) + cls.write_varint_field(2, nanos)
        return cls.write_bytes_field(field_num, inner)

    @classmethod
    def build_workspace_field9(cls, ws: dict[str, str]) -> bytes:
        """
        Constructs the deeply nested Field 9 workspace metadata.
        Schema: Field 9 { Field 1: uri, Field 2: uri, Field 3 { Field 1: corpus, Field 2: git_remote }, Field 4: branch }
        """
        sub3_inner = (
            cls.write_string_field(1, ws["corpus"])
            + cls.write_string_field(2, ws["git_remote"])
        )
        inner = (
            cls.write_string_field(1, ws["uri_encoded"])
            + cls.write_string_field(2, ws["uri_encoded"])
            + cls.write_bytes_field(3, sub3_inner)
            + cls.write_string_field(4, ws["branch"])
        )
        return cls.write_bytes_field(9, inner)

    @classmethod
    def build_workspace_field17(cls, ws: dict[str, str], session_uuid: str, epoch_seconds: int, nanos: int = 0) -> bytes:
        """
        Constructs the deeply nested Field 17 workspace URI parameters.
        Schema: Field 17 { Field 1 { Field 1: uri, Field 2: uri }, Field 2 { Field 1: seconds, Field 2: nanos }, Field 3: session_uuid, Field 7: uri_encoded }
        """
        sub1_inner = (
            cls.write_string_field(1, ws["uri_plain"])
            + cls.write_string_field(2, ws["uri_plain"])
        )
        sub2 = cls.write_varint_field(1, epoch_seconds) + cls.write_varint_field(2, nanos)
        inner = (
            cls.write_bytes_field(1, sub1_inner)
            + cls.write_bytes_field(2, sub2)
            + cls.write_string_field(3, session_uuid)
            + cls.write_string_field(7, ws["uri_encoded"])
        )
        return cls.write_bytes_field(17, inner)

    # --- Decoding & Patching Helpers ---

    @staticmethod
    def decode_varint(data: bytes, pos: int) -> tuple[int, int]:
        """
        Decode a Protobuf varint from raw bytes starting at the given position.

        Returns:
            tuple[int, int]: The decoded integer and the new byte position.
        """
        result, shift = 0, 0
        while pos < len(data):
            b = data[pos]
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return result, pos + 1
            shift += 7
            pos += 1
        return result, pos

    @classmethod
    def skip_protobuf_field(cls, data: bytes, pos: int, wire_type: int) -> int:
        """Skip over a Protobuf field value. Returns new_pos."""
        if wire_type == 0:    # varint
            _, pos = cls.decode_varint(data, pos)
        elif wire_type == 2:  # length-delimited
            length, pos = cls.decode_varint(data, pos)
            pos += length
        elif wire_type == 1:  # 64-bit fixed
            pos += 8
        elif wire_type == 5:  # 32-bit fixed
            pos += 4
        return pos

    @classmethod
    def strip_field_from_protobuf(cls, data: bytes, target_field_number: int) -> bytes:
        """
        Iterates over a protobuf binary blob and selectively discards all
        fields that match the target_field_number.
        """
        remaining = b""
        pos = 0
        while pos < len(data):
            start_pos = pos
            try:
                tag, pos = cls.decode_varint(data, pos)
            except Exception:
                remaining += data[start_pos:]
                break

            wire_type = tag & 7
            field_num = tag >> 3
            new_pos = cls.skip_protobuf_field(data, pos, wire_type)

            if new_pos == pos and wire_type not in (0, 1, 2, 5):
                remaining += data[start_pos:]
                break
            pos = new_pos

            if field_num != target_field_number:
                remaining += data[start_pos:pos]
        return remaining

    @classmethod
    def has_timestamp_fields(cls, inner_blob: bytes) -> bool:
        """Check if the inner blob already contains timestamp fields (3, 7, or 10)."""
        if not inner_blob:
            return False
        try:
            pos = 0
            while pos < len(inner_blob):
                tag, pos = cls.decode_varint(inner_blob, pos)
                fn = tag >> 3
                wt = tag & 7
                if fn in (3, 7, 10):
                    return True
                pos = cls.skip_protobuf_field(inner_blob, pos, wt)
        except Exception:
            pass
        return False

    @classmethod
    def extract_workspace_hint(cls, inner_blob: bytes) -> str | None:
        """
        Extract a workspace URI from the protobuf inner blob.
        Scans length-delimited fields for strings matching file:/// patterns.
        """
        if not inner_blob:
            return None
        try:
            pos = 0
            while pos < len(inner_blob):
                tag, pos = cls.decode_varint(inner_blob, pos)
                wire_type = tag & 7
                field_num = tag >> 3
                if wire_type == 2:
                    l, pos = cls.decode_varint(inner_blob, pos)
                    content = inner_blob[pos:pos + l]
                    pos += l
                    if field_num > 1:
                        try:
                            text = content.decode("utf-8", errors="strict")
                            if "file:///" in text:
                                return text
                        except Exception:
                            pass
                elif wire_type == 0:
                    _, pos = cls.decode_varint(inner_blob, pos)
                elif wire_type == 1:
                    pos += 8
                elif wire_type == 5:
                    pos += 4
                else:
                    break
        except Exception:
            pass
        return None

    @classmethod
    def build_trajectory_entry(
        cls,
        conv_uuid: str,
        title: str,
        workspace: dict[str, str] | None,
        create_epoch: int,
        modify_epoch: int,
        existing_inner_data: bytes | None = None,
        step_count: int = 1,
    ) -> bytes:
        """
        Generates a complete trajectorySummaries entry with Base64-wrapped
        inner Protobuf payload.

        If ``existing_inner_data`` is provided, fields are patched non-destructively:
        - Field 1 (Title) is overwritten.
        - Field 9 and 17 (Workspace) are injected/overwritten if ``workspace`` is active.
        - Fields 3, 7, 10 (Timestamps) are injected ONLY if entirely missing.
        """

        if existing_inner_data:
            preserved_fields = cls.strip_field_from_protobuf(existing_inner_data, 1)
            inner_pb = cls.write_string_field(1, title) + preserved_fields

            if workspace:
                inner_pb = cls.strip_field_from_protobuf(inner_pb, 9)
                inner_pb = cls.strip_field_from_protobuf(inner_pb, 17)
                inner_pb += cls.build_workspace_field9(workspace)
                inner_pb += cls.build_workspace_field17(workspace, conv_uuid, modify_epoch)

            if not cls.has_timestamp_fields(existing_inner_data):
                inner_pb += (
                    cls.write_timestamp(3, create_epoch)
                    + cls.write_timestamp(7, modify_epoch)
                    + cls.write_timestamp(10, modify_epoch)
                )

        else:
            inner_pb = (
                cls.write_string_field(1, title)
                + cls.write_varint_field(2, step_count)
                + cls.write_timestamp(3, create_epoch)
                + cls.write_string_field(4, conv_uuid)
                + cls.write_varint_field(5, 1)       # Status: ACTIVE
                + cls.write_timestamp(7, modify_epoch)
                + (cls.build_workspace_field9(workspace) if workspace else b"")
                + cls.write_timestamp(10, modify_epoch)
                + (cls.build_workspace_field17(workspace, conv_uuid, modify_epoch) if workspace else b"")
            )

        inner_b64 = base64.b64encode(inner_pb).decode("utf-8")
        wrapper = cls.write_string_field(1, inner_b64)
        entry = cls.write_string_field(1, conv_uuid) + cls.write_bytes_field(2, wrapper)
        return cls.write_bytes_field(1, entry)
