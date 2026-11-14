"""Device discovery and page operations, for the SE0420B1 four-color USB display."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import math
import time
import serial
from serial.tools.list_ports import comports
from PIL import Image
from .images import IMAGE_BYTES, decode_image, encode_image, prepare_image
from .protocol import EZSignError, ProtocolError, exchange

Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class DeviceInfo:
    port: str
    description: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    verified: bool = False


def list_candidates() -> list[DeviceInfo]:
    """List CH343/EZ Sign candidates without opening unrelated serial ports."""
    return [DeviceInfo(p.device, p.description, p.vid, p.pid, p.serial_number)
            for p in comports()
            if (p.vid, p.pid) == (0x1a86, 0x55d3)
            or any(s in (p.description or '').lower() for s in ('ch343', 'ez sign', 'ezsign'))]


def discover(*, timeout: float = 1.0) -> list[DeviceInfo]:
    """Return only candidates responding with the four-color product ID (0x42)."""
    found = []
    for info in list_candidates():
        try:
            with EZSign(info.port, timeout=timeout):
                found.append(DeviceInfo(info.port, info.description, info.vid, info.pid,
                                        info.serial_number, True))
        except (EZSignError, serial.SerialException):
            continue
    return found


def _page(page: int, *, navigation: bool = False) -> None:
    allowed = (1, 2, 3, 4, 5, 0xfe, 0xff) if navigation else (1, 2, 3, 4, 5)
    if type(page) is not int or page not in allowed:
        raise ValueError('Page must be 1..5' + (' or NEXT/PREV' if navigation else ''))


class EZSign:
    WIDTH, HEIGHT = 400, 300
    NEXT, PREV = 0xfe, 0xff
    BAUDRATE = 115200

    def __init__(self, port: str | None = None, *, timeout: float = 2.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be positive and finite')
        if port is None:
            devices = discover(timeout=timeout)
            if not devices:
                raise EZSignError('No responding four-color EZ Sign. Run ezsign list --probe; check power.')
            if len(devices) > 1:
                raise EZSignError('Multiple EZ Sign devices; specify a port explicitly: '
                                  + ', '.join(d.port for d in devices))
            port = devices[0].port
        self.port = port
        self.timeout = timeout
        self._serial = serial.Serial(port, self.BAUDRATE, timeout=min(timeout, 0.1),
                                     write_timeout=timeout)
        try:
            self._serial.reset_input_buffer()
            self.identify()
        except BaseException:
            self.close()
            raise

    @classmethod
    def auto(cls, *, timeout: float = 2.0) -> 'EZSign':
        return cls(timeout=timeout)

    def _command(self, command: int, content: bytes) -> bytes:
        return exchange(self._serial, command, content, self.timeout)

    def identify(self) -> bytes:
        # Hardware answers the 0A/07 product query with response command 01.
        identity = exchange(self._serial, 0x0a, b'\x07', self.timeout, response_command=1)
        if not identity or identity[0] != 0x42:
            raise ProtocolError(f'Expected four-color product ID 42, got {identity.hex()}')
        return identity

    def close(self) -> None:
        self._serial.close()

    def keep_awake(self, *, duration: float = 200.0, interval: float = 60.0) -> None:
        """Block while querying identity periodically; requires manual power-on first.

        Uses a 60-second interval by default. This does not
        disable the hardware timer or wake an already powered-off display.
        """
        if not math.isfinite(duration) or duration < 0:
            raise ValueError('duration must be nonnegative and finite')
        if not math.isfinite(interval) or not 0 < interval <= 60:
            raise ValueError('interval must be greater than 0 and at most 60 seconds')
        deadline = time.monotonic() + duration
        while True:
            self.identify()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(interval, remaining))

    def __enter__(self) -> 'EZSign':
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _ack(self, command: int, content: bytes) -> None:
        response = self._command(command, content)
        if response != b'\x01':
            raise ProtocolError(f'Command {command:02x} rejected: {response.hex()}')

    def show_page(self, page: int, *, wait: float = 20.0) -> None:
        _page(page, navigation=True)
        if not math.isfinite(wait) or wait < 0:
            raise ValueError('wait must be nonnegative and finite')
        response = self._command(0, bytes((page,)))
        if response != bytes((page,)):
            raise ProtocolError(f'Unexpected page response: {response.hex()}')
        time.sleep(wait)

    def read_image(self, page: int, *, progress: Progress | None = None) -> Image.Image:
        _page(page)
        data = bytearray()
        total = IMAGE_BYTES // 16
        for index in range(total):
            address = index.to_bytes(2, 'big')
            response = self._command(5, bytes((page, 0)) + address)
            if len(response) != 18 or response[:2] != address:
                raise ProtocolError(f'Invalid read block {index}: {response.hex()}')
            data.extend(response[2:])
            if progress:
                progress(index + 1, total)
        return decode_image(bytes(data))

    def write_image(self, page: int, source: Image.Image | str | Path, *,
                    dither: bool = False, refresh: bool = True, wait: float = 20.0,
                    progress: Progress | None = None) -> None:
        _page(page)
        if not math.isfinite(wait) or wait < 0:
            raise ValueError('wait must be nonnegative and finite')
        data = encode_image(prepare_image(source, dither=dither))
        self.identify()
        # Like ezsign.py: query slot, select page/plane, send indexed 16-byte blocks, show.
        status = self._command(1, bytes((page,)))
        if status not in (b'\x01', b'\xfe'):
            raise ProtocolError(f'Unexpected slot status: {status.hex()}')
        self._ack(3, bytes((page, 0)))
        total = len(data) // 16
        for index in range(total):
            self._ack(4, index.to_bytes(2, 'big') + data[index*16:(index+1)*16])
            if progress:
                progress(index + 1, total)
        if refresh:
            self.show_page(page, wait=wait)

    # Familiar spellings from the reference implementation.
    def showpage(self, page_number: int) -> None:
        self.show_page(page_number)

    def readimage(self, page_number: int, filename: str | Path | None = None) -> Image.Image:
        image = self.read_image(page_number)
        if filename is not None:
            image.save(filename)
        return image

    def writeimage(self, page_number: int, filename: str | Path) -> None:
        self.write_image(page_number, filename)
