"""BB/type/command/length/content/checksum/7E framing shared with ezsign.py."""
import time


class EZSignError(Exception):
    """Base driver error."""


class ProtocolError(EZSignError):
    """Invalid frame, unexpected command, or device rejection."""


class ResponseTimeout(EZSignError):
    """Device did not return a complete response within the deadline."""


def frame(command: int, content: bytes, direction: int = 0) -> bytes:
    if len(content) > 255:
        raise ValueError("Content is limited to 255 bytes")
    body = bytes((direction, command, len(content))) + content
    return b'\xbb' + body + bytes((sum(body) & 255, 0x7e))


def exchange(port, command: int, content: bytes, timeout: float, *,
             response_command: int | None = None) -> bytes:
    """Send once; parse by length so BB/7E bytes in image data are preserved."""
    packet = frame(command, content)
    if port.write(packet) != len(packet):
        raise ProtocolError("Incomplete serial write")
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = port.read(1)
        if not chunk:
            continue
        buf.extend(chunk)
        if buf[0] != 0xbb:
            buf.clear()
            continue
        if len(buf) < 4:
            continue
        total = buf[3] + 6
        if len(buf) < total:
            continue
        if buf[-1] != 0x7e or buf[-2] != sum(buf[1:-2]) & 255:
            raise ProtocolError(f"Bad response checksum or terminator: {buf.hex()}")
        expected = command if response_command is None else response_command
        if buf[1] != 1 or buf[2] != expected:
            raise ProtocolError(f"Unexpected response: {buf.hex()}")
        return bytes(buf[4:-2])
    raise ResponseTimeout(
        f"No complete response for command 0x{command:02x}; received {buf.hex() or '(none)'}. "
        "Check power (blue LED), USB data cable, and close the official application."
    )
