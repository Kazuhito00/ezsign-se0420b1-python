import argparse
import sys
import serial
from .device import EZSign, discover, list_candidates
from .images import prepare_image
from .protocol import EZSignError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='EZ Sign USB 4.2-inch four-color driver')
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list', help='List USB candidates; optionally verify product identity')
    listing.add_argument('--probe', action='store_true')
    preview = sub.add_parser('preview', help='Convert an image without accessing hardware')
    preview.add_argument('input')
    preview.add_argument('output')
    preview.add_argument('--dither', action='store_true')
    for name in ('read', 'write', 'show', 'identify', 'keep-awake'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--port', help='e.g. COM4; otherwise discover automatically')
        if name == 'keep-awake':
            cmd.add_argument('--duration', type=float, default=200.0, help='Seconds to keep querying identity')
            cmd.add_argument('--interval', type=float, default=60.0, help='Identity query interval in seconds (default: 60; up to 60)')
        if name in ('read', 'write', 'show'):
            cmd.add_argument('--page', type=int, choices=range(1, 6), default=1)
        if name in ('read', 'write'):
            cmd.add_argument('image')
        if name == 'write':
            cmd.add_argument('--dither', action='store_true')
            cmd.add_argument('--no-refresh', action='store_true')
        if name in ('write', 'show'):
            cmd.add_argument('--wait', type=float, default=20.0, help='Refresh wait in seconds')
    args = parser.parse_args(argv)
    try:
        if args.command == 'preview':
            prepare_image(args.input, dither=args.dither).save(args.output)
            print(args.output)
            return 0
        if args.command == 'list':
            candidates = list_candidates()
            verified = {d.port for d in discover()} if args.probe else set()
            for d in candidates:
                state = ('verified four-color EZ Sign' if d.port in verified else
                         'no valid response' if args.probe else 'unverified candidate')
                print(f'{d.port}: {d.description} [{state}] serial={d.serial_number}')
            if not candidates:
                print('No EZ Sign USB candidates found.')
            return 0 if (verified if args.probe else candidates) else 1
        with EZSign(args.port) if args.port else EZSign.auto() as device:
            if args.command == 'identify':
                print(f'{device.port}: product ID {device.identify().hex()}')
            elif args.command == 'keep-awake':
                print(f'{device.port}: querying identity every {args.interval:g} seconds for {args.duration:g} seconds', flush=True)
                device.keep_awake(duration=args.duration, interval=args.interval)
                print('Keep-awake completed.')
            elif args.command == 'read':
                device.read_image(args.page).save(args.image)
                print(f'Saved page {args.page} to {args.image}')
            elif args.command == 'write':
                device.write_image(args.page, args.image, dither=args.dither,
                                   refresh=not args.no_refresh, wait=args.wait)
                print(f'Transferred page {args.page}' + (' and requested refresh' if not args.no_refresh else ''))
            elif args.command == 'show':
                device.show_page(args.page, wait=args.wait)
        return 0
    except KeyboardInterrupt:
        print('Stopped.', file=sys.stderr)
        return 130
    except (EZSignError, serial.SerialException, OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
