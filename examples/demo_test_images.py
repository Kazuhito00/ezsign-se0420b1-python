"""Generate diagnostic images and optionally back up/write/read back pages 1..3."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ezsign_usb import EZSign, prepare_image, encode_image
from ezsign_usb.images import PALETTE, SIZE


def generate(folder):
    font_paths = ('C:/Windows/Fonts/BIZ-UDGothicR.ttc', 'DejaVuSans.ttf')
    def font(size):
        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)
    images = []
    im = Image.new('RGB', SIZE, 'white')
    draw = ImageDraw.Draw(im)
    draw.text((16, 12), '01  FOUR COLOR TEST', fill='black', font=font(23))
    for i, (color, label) in enumerate(zip(PALETTE, ['BLACK', 'WHITE', 'YELLOW', 'RED'])):
        x = 12 + i*96
        draw.rectangle((x, 58, x+87, 213), fill=color, outline='black', width=1)
        draw.text((x+4, 224), label, fill='black', font=font(15))
    draw.text((16, 264), '400 x 300 / K W Y R / PAGE 1', fill='black', font=font(16))
    images.append(('01-colors.png', im))

    im = Image.new('RGB', SIZE, 'white')
    draw = ImageDraw.Draw(im)
    draw.rectangle((0, 0, 399, 48), fill='black')
    draw.text((14, 9), '02  TEXT / LINE TEST', fill='white', font=font(24))
    draw.text((16, 61), 'Hello, EZ Sign!', fill='black', font=font(28))
    draw.text((16, 106), 'Red text / ABC 12345', fill=PALETTE[3], font=font(21))
    draw.rectangle((12, 145, 387, 185), fill=PALETTE[2])
    draw.text((20, 151), 'Yellow background / TEST', fill='black', font=font(22))
    for i, width in enumerate((1, 2, 3, 4)):
        y = 210 + i*16
        draw.line((16, y, 230, y), fill='black', width=width)
        draw.text((250, y-7), f'{width} px', fill='black', font=font(13))
    draw.rectangle((0, 0, 399, 299), outline='black', width=1)
    images.append(('02-text-lines.png', prepare_image(im)))

    im = Image.new('RGB', SIZE, 'white')
    draw = ImageDraw.Draw(im)
    draw.text((14, 10), '03  DITHER / GEOMETRY', fill='black', font=font(22))
    for x in range(368):
        g = round(x*255/367)
        draw.line((16+x, 52, 16+x, 111), fill=(g,g,g))
        draw.line((16+x, 122, 16+x, 181), fill=(255,g,0))
    draw.ellipse((20, 201, 96, 277), fill='red', outline='black', width=2)
    draw.rectangle((120, 205, 197, 276), fill=PALETTE[2], outline='black', width=2)
    draw.polygon([(260,201),(218,277),(302,277)], fill='black')
    for y in range(210, 275, 6):
        for x in range(320, 386, 6):
            if ((x-320)//6 + (y-210)//6) % 2 == 0:
                draw.rectangle((x,y,x+5,y+5),fill='black')
    images.append(('03-dither-pattern.png', prepare_image(im,dither=True)))
    for name, image in images:
        image.save(folder/name)
    gallery = Image.new('RGB', (400, 900), 'white')
    for i, (_, im) in enumerate(images):
        gallery.paste(im, (0,i*300))
    gallery.save(folder/'contact-sheet.png')
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Back up and overwrite pages 1..3')
    args = parser.parse_args()
    folder = Path('output') / ('image-test-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    images = generate(folder)
    print(f'Images: {folder.resolve()}', flush=True)
    if not args.write:
        return
    report = dict(folder=str(folder), pages=[], status='starting')
    def save():
        (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    def progress(done,total):
        if done % 375 == 0 or done == total:
            print(f'  {done}/{total}', flush=True)
    save()
    try:
        with EZSign() as display:
            report['port'] = display.port
            for page in range(1,4):
                print(f'Backup page {page}', flush=True)
                display.read_image(page,progress=progress).save(folder/f'backup-page{page}.png')
            report['status'] = 'backed_up'
            save()
            for page, (name, image) in enumerate(images,1):
                record = dict(page=page, image=name, status='writing')
                report['pages'].append(record)
                save()
                print(f'Write page {page}: {name}', flush=True)
                display.write_image(page,image,wait=30,progress=progress)
                record['status'] = 'written'
                save()
                print(f'Read back page {page}', flush=True)
                result = display.read_image(page,progress=progress)
                result.save(folder/f'readback-page{page}.png')
                record['matches'] = encode_image(result) == encode_image(prepare_image(image))
                record['status'] = 'verified' if record['matches'] else 'mismatch'
                save()
                if not record['matches']:
                    raise RuntimeError(f'Page {page} readback differs from the transmitted image')
            display.show_page(1,wait=30)
            report['status'] = 'passed'
            report['displayed_page'] = 1
    except BaseException as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save()
        print(json.dumps(report),flush=True)


if __name__ == '__main__':
    main()
