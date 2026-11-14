"""Read-only, logged endurance test; no image or page changes."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from ezsign_usb import EZSign


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Explicit serial port; otherwise discover automatically')
    parser.add_argument('--duration', type=float, default=200)
    parser.add_argument('--interval', type=float, default=60)
    args = parser.parse_args()
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error('duration must be positive and finite')
    if not math.isfinite(args.interval) or not 0 < args.interval <= 60:
        parser.error('interval must be greater than 0 and at most 60')
    output = Path('output')
    output.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    prefix = output / f'keepalive-{stamp}'
    summary_path = prefix.with_suffix('.json')
    samples_path = prefix.with_suffix('.jsonl')
    summary = dict(status='starting', port=args.port, duration=args.duration,
                   interval=args.interval, started_at=datetime.now(timezone.utc).isoformat(),
                   samples=0, max_gap_seconds=0.0, log=str(samples_path))
    start = time.monotonic()
    previous = None

    def save():
        summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')

    save()
    print(f'Summary: {summary_path}; samples: {samples_path}', flush=True)
    try:
        with samples_path.open('w', encoding='utf-8', buffering=1) as log:
            with EZSign(args.port) as device:
                summary['port'] = device.port
                start = time.monotonic()
                summary['status'] = 'running'
                summary['started_at'] = datetime.now(timezone.utc).isoformat()
                count = math.ceil(args.duration / args.interval)
                for index in range(count + 1):
                    identity = device.identify()
                    elapsed = time.monotonic() - start
                    if previous is not None:
                        summary['max_gap_seconds'] = max(summary['max_gap_seconds'], elapsed-previous)
                    previous = elapsed
                    sample = dict(elapsed=round(elapsed, 3), identity=identity.hex(),
                                  timestamp=datetime.now(timezone.utc).isoformat())
                    log.write(json.dumps(sample) + '\n')
                    summary.update(samples=index+1, elapsed=round(elapsed, 3), last_sample=sample)
                    save()
                    if index % max(1, round(60/args.interval)) == 0 or index == count:
                        print(json.dumps(sample), flush=True)
                    if index < count:
                        target = min((index+1)*args.interval, args.duration)
                        time.sleep(max(0, start + target - time.monotonic()))
                summary['status'] = ('passed' if summary['max_gap_seconds'] <= args.interval*2
                                     else 'completed_with_timing_gaps')
    except BaseException as exc:
        summary.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        summary['elapsed'] = round(time.monotonic()-start, 3)
        save()
        print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
