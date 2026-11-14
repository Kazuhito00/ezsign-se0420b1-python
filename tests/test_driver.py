from collections import deque
from unittest.mock import patch
import pytest
from PIL import Image
from ezsign_usb import EZSign, ProtocolError, ResponseTimeout
from ezsign_usb.images import PALETTE, SIZE, prepare_image, encode_image, decode_image
from ezsign_usb.protocol import frame, exchange
from ezsign_usb.device import DeviceInfo, discover, list_candidates
from types import SimpleNamespace


class FakeSerial:
    def __init__(self, reply=None):
        self.reply = reply or self.respond
        self.incoming = deque()
        self.sent = []
        self.closed = False

    def reset_input_buffer(self):
        self.incoming.clear()

    def close(self):
        self.closed = True

    def read(self, count):
        return bytes([self.incoming.popleft()]) if self.incoming else b''

    def write(self, data):
        self.sent.append(data)
        self.incoming.extend(self.reply(data))
        return len(data)

    @staticmethod
    def respond(data):
        command, content = data[2], data[4:-2]
        if command == 0x0a:
            result = b'\x42'
            command = 1
        elif command == 0:
            result = content
        elif command == 1:
            result = b'\xfe'
        elif command == 5:
            result = content[2:] + b'\x1b' * 16
        else:
            result = b'\x01'
        return frame(command, result, 1)


def test_reference_frame_and_identity():
    # Existing ezsign.py uses identical framing/checksum for showpage.
    assert frame(0, b'\x01') == bytes.fromhex('bb00000101027e')
    assert frame(0x0a, b'\x07') == bytes.fromhex('bb000a0107127e')


def test_hardware_identity_response_uses_command_01():
    port = FakeSerial(lambda _: bytes.fromhex('bb01010142457e'))
    with patch('ezsign_usb.device.serial.Serial', return_value=port):
        with EZSign('COM_TEST') as device:
            assert device.identify() == b'\x42'
    assert port.closed


def test_four_color_bit_order_round_trip():
    image = Image.new('RGB', SIZE)
    image.putdata(list(PALETTE) * (400*300//4))
    encoded = encode_image(image)
    assert encoded == b'\x1b' * 30000
    assert decode_image(encoded).tobytes() == image.tobytes()


def test_prepare_transparency_aspect_and_colors():
    image = Image.new('RGBA', (200, 100), (255, 0, 0, 0))
    assert prepare_image(image).getpixel((200, 150)) == (255, 255, 255)
    image = prepare_image(Image.new('RGB', (200, 100), 'red'))
    assert image.size == SIZE
    assert image.getpixel((0, 0)) == PALETTE[1]
    assert image.getpixel((200, 150)) == PALETTE[3]


def test_payload_delimiters_not_treated_as_frame_boundaries():
    port = FakeSerial(lambda _: b'\x00' + frame(5, b'\xbb\x7e', 1))
    assert exchange(port, 5, b'\x01', 0.1) == b'\xbb\x7e'


@pytest.mark.parametrize('reply', [bytes.fromhex('bb01000101007e'), frame(4,b'\x01',1), frame(0,b'\x01',0)])
def test_bad_frames_rejected(reply):
    with pytest.raises(ProtocolError):
        exchange(FakeSerial(lambda _: reply), 0, b'\x01', 0.1)


def test_truncated_response_times_out():
    with pytest.raises(ResponseTimeout):
        exchange(FakeSerial(lambda _: b'\xbb\x01'), 0, b'\x01', 0.005)


def test_device_write_read_and_last_block():
    port = FakeSerial()
    with patch('ezsign_usb.device.serial.Serial', return_value=port):
        with EZSign('COM_TEST') as device:
            progress = []
            device.write_image(5, Image.new('RGB', SIZE, 'red'), wait=0,
                               progress=lambda done,total: progress.append((done,total)))
            writes = [p for p in port.sent if p[2] == 4]
            assert len(writes) == 1875
            assert writes[0][4:-2] == b'\x00\x00' + b'\xff'*16
            assert writes[-1][4:6] == (1874).to_bytes(2, 'big')
            assert progress[-1] == (1875,1875)
            assert port.sent[-1] == frame(0,b'\x05')
            image = device.read_image(1)
            assert encode_image(image) == b'\x1b' * 30000
            assert port.sent[-1] == frame(5,b'\x01\x00' + (1874).to_bytes(2,'big'))
    assert port.closed


def test_wrong_product_closes_port():
    port = FakeSerial(lambda _: frame(1,b'\x41',1))
    with patch('ezsign_usb.device.serial.Serial',return_value=port):
        with pytest.raises(ProtocolError):
            EZSign('COM_TEST')
    assert port.closed


def test_invalid_page_and_rejected_block_stop_transfer():
    port = FakeSerial()
    with patch('ezsign_usb.device.serial.Serial',return_value=port):
        with EZSign('COM_TEST') as device:
            before = len(port.sent)
            with pytest.raises(ValueError):
                device.write_image(0, Image.new('RGB',SIZE))
            assert len(port.sent) == before
            port.reply = lambda data: frame(4,b'\x00',1) if data[2] == 4 else FakeSerial.respond(data)
            with pytest.raises(ProtocolError):
                device.write_image(1, Image.new('RGB',SIZE), wait=0)
            assert len([p for p in port.sent if p[2] == 4]) == 1
            assert not any(p[2] == 0 for p in port.sent)


def test_read_wrong_block_rejected():
    port = FakeSerial()
    with patch('ezsign_usb.device.serial.Serial',return_value=port):
        with EZSign('COM_TEST') as device:
            port.reply = lambda _: frame(5,b'\xff\xff'+b'\x00'*16,1)
            with pytest.raises(ProtocolError):
                device.read_image(1)


def test_candidates_do_not_include_unrelated_ports():
    def port(name, vid, pid, description):
        return SimpleNamespace(device=name, vid=vid, pid=pid,
                               description=description, serial_number=None)
    ports = [port('COM3',None,None,'Intel AMT SOL'),
             port('COM4',0x1a86,0x55d3,'USB Serial'),
             port('COM5',0x1234,0x5678,'Other Serial')]
    with patch('ezsign_usb.device.comports',return_value=ports):
        assert [d.port for d in list_candidates()] == ['COM4']


def test_discover_requires_identity_and_auto_rejects_ambiguity():
    candidate = DeviceInfo('COM4','CH343',0x1a86,0x55d3,'test')
    port = FakeSerial()
    with patch('ezsign_usb.device.list_candidates', return_value=[candidate]), \
         patch('ezsign_usb.device.serial.Serial',return_value=port):
        assert discover()[0].verified
        assert port.closed
    from ezsign_usb import EZSignError
    with patch('ezsign_usb.device.discover',return_value=[candidate,candidate]):
        with pytest.raises(EZSignError,match='Multiple'):
            EZSign.auto()


def test_keep_awake_queries_without_changing_images():
    device = EZSign.__new__(EZSign)
    with patch.object(device, 'identify', return_value=b'\x42') as identify, \
         patch('ezsign_usb.device.time.monotonic', side_effect=[0,0,5,10]), \
         patch('ezsign_usb.device.time.sleep') as sleep:
        device.keep_awake(duration=10, interval=5)
    assert identify.call_count == 3
    assert sleep.call_count == 2
    with pytest.raises(ValueError):
        device.keep_awake(interval=0)
    with pytest.raises(ValueError):
        device.keep_awake(interval=61)


def test_keep_awake_default_interval_is_60_seconds():
    device = EZSign.__new__(EZSign)
    with patch.object(device, 'identify', return_value=b'\x42') as identify, \
         patch('ezsign_usb.device.time.monotonic', side_effect=[0,0,60,120]), \
         patch('ezsign_usb.device.time.sleep') as sleep:
        device.keep_awake(duration=120)
    assert identify.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [60,60]


def test_constructor_auto_selects_verified_device():
    candidate = DeviceInfo('COM9', 'CH343', 0x1a86, 0x55d3, 'test', True)
    port = FakeSerial()
    with patch('ezsign_usb.device.discover', return_value=[candidate]) as search, \
         patch('ezsign_usb.device.serial.Serial', return_value=port) as serial:
        with EZSign(timeout=0.5) as device:
            assert device.port == 'COM9'
        search.assert_called_once_with(timeout=0.5)
        assert serial.call_args.args[0] == 'COM9'
    assert port.closed


def test_constructor_no_device_does_not_open_port():
    from ezsign_usb import EZSignError
    with patch('ezsign_usb.device.discover', return_value=[]), \
         patch('ezsign_usb.device.serial.Serial') as serial:
        with pytest.raises(EZSignError, match='No responding'):
            EZSign()
        serial.assert_not_called()
