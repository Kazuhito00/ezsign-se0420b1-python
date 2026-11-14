# Public API

公開APIは `ezsign_usb` からインポートできます。時刻・待機時間の単位は秒です。

```python
from ezsign_usb import (
    EZSign, DeviceInfo, discover, list_candidates,
    prepare_image, encode_image, decode_image,
    EZSignError, ProtocolError, ResponseTimeout,
)
```

## Discovery

| API | 戻り値・動作 |
|---|---|
| `list_candidates() -> list[DeviceInfo]` | USBポートの候補を列挙。ポートを開いて通信しない |
| `discover(*, timeout=1.0) -> list[DeviceInfo]` | 候補に機種識別を送り、応答する4色機だけを返す |
| `EZSign(port=None, *, timeout=2.0)` | 接続し製品IDを検証。省略時は自動検索 |
| `EZSign.auto(*, timeout=2.0) -> EZSign` | `EZSign()` と同じ自動検索 |

候補はCH343（VID:PID=`1A86:55D3`）または名前に `CH343` / `EZ Sign` / `EZSign` を含むポートです。
`discover` は通信・識別に失敗した候補を結果に含めません。
自動接続は応答する機器が0台または複数台なら `EZSignError` を返します。
複数台の場合は `DeviceInfo.port` を選んで明示指定してください。
`timeout` は探索全体ではなく、各コマンドの応答待ち時間です。

`DeviceInfo` は変更不可のdataclassです。

| フィールド | 型 | 内容 |
|---|---|---|
| `port` | `str` | COM番号などのポート名 |
| `description` | `str` | OSから取得した説明 |
| `vid` / `pid` | `int \| None` | USB Vendor/Product ID |
| `serial_number` | `str \| None` | USBシリアル番号 |
| `verified` | `bool` | `discover` で識別できた場合は `True` |

## Device operations

```python
with EZSign() as display:
    print(display.port)
    display.read_image(1).save("backup.png")
```

`with` を抜けると接続を閉じます。明示的に `close()` を呼ぶこともできます。
`display.port` は選択したポート、`display.timeout` は応答タイムアウトです。

| メソッド | 戻り値 |
|---|---|
| `identify() -> bytes` | 識別情報。接続した実機では `b"\x42"` |
| `read_image(page, *, progress=None) -> Image.Image` | 保存済みページのPillow画像 |
| `write_image(page, source, *, dither=False, refresh=True, wait=20.0, progress=None) -> None` | 指定ページを上書きし、既定では表示も更新 |
| `show_page(page, *, wait=20.0) -> None` | 保存済みページを表示 |
| `keep_awake(*, duration=200.0, interval=60.0) -> None` | 定期識別通信を続ける |
| `close() -> None` | 接続を閉じる |

- ページは1〜5。`show_page` では `EZSign.NEXT` / `EZSign.PREV` も指定できます
- `source` はファイル名、`pathlib.Path`、Pillowの `Image` を受け付けます
- `write_image` は内部で `prepare_image` を実行します。`dither=True` で誤差拡散します
- `refresh=False` は表示更新要求を送りません。あとから `show_page` で切り替えられます
- `wait` は非負の固定待機秒数で、画面の描画完了を検出しているわけではありません
- `progress` は `callback(done, total)` で、完了ブロック数と総数1875を受け取ります
- `duration` は非負、`interval` は `0 < interval <= 60` の有限の秒数です
- `keep_awake` は呼び出し直後にも識別し、指定時間ブロックします。自動OFF解除・電源OFFからの起動・バックグラウンド動作ではありません
- 同じ接続に対する呼び出しは直列に実行してください。通信の排他制御や自動再接続は実装していません

定数は `EZSign.WIDTH=400`、`HEIGHT=300`、`BAUDRATE=115200`、`NEXT=0xFE`、`PREV=0xFF` です。

## Image processing

| 関数 | 内容 |
|---|---|
| `prepare_image(source, *, dither=False) -> Image.Image` | 縦横比を維持して白余白付き400×300・4色に変換。EXIF回転と透過部分の白合成にも対応 |
| `encode_image(image) -> bytes` | 変換済みの400×300画像を30000バイトに変換 |
| `decode_image(data) -> Image.Image` | 30000バイトを400×300の画像に復元 |

`prepare_image` の `source` はファイルパスまたはPillow画像です。
`encode_image` は黒 `(0,0,0)`、白 `(255,255,255)`、黄 `(255,192,0)`、赤 `(255,0,0)` を受け付けます。
純黄 `(255,255,0)` も黄として扱います。サイズや色が異なる場合は先に `prepare_image` を使ってください。

## Reference-compatible spellings

| メソッド | 動作 |
|---|---|
| `showpage(page_number) -> None` | `show_page` を呼び出す |
| `readimage(page_number, filename=None) -> Image.Image` | 画像を返す。ファイル名指定時は保存も行う |
| `writeimage(page_number, filename) -> None` | ファイルから書き込み・表示 |

参考実装で使われていたメソッド名を用意していますが、戻り値やエラー処理の完全互換ではありません。
コンストラクターにはpyserialのオブジェクトではなくポート名を渡します。

## Exceptions

| 型 | 内容 |
|---|---|
| `EZSignError` | ライブラリ独自例外の基底型 |
| `ProtocolError` | 不正なフレーム・応答内容・コマンド拒否 |
| `ResponseTimeout` | 完全な応答を受信できなかった |

`ProtocolError` と `ResponseTimeout` は `EZSignError` の派生型です。
引数不正は `ValueError`、ポートのオープンやI/O失敗は `serial.SerialException`、
画像ファイルの問題はPillowやファイルI/Oの例外になる場合があります。

```python
import serial
from ezsign_usb import EZSign, EZSignError

try:
    with EZSign() as display:
        display.show_page(1)
except (EZSignError, serial.SerialException) as exc:
    print(f"Device operation failed: {exc}")
```
