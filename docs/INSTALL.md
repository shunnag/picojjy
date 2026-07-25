# インストールガイド

Raspberry Pi Pico W / Pico 2 W に MicroPython と picojjy を書き込む手順です。
ハードウェア(アンテナ)の準備がまだの場合は先に [HARDWARE.md](HARDWARE.md) を参照してください。

## 1. 必要なもの

- Raspberry Pi Pico W または Raspberry Pi Pico 2 W(アンテナ接続済み)
- USB ケーブル(データ通信対応のもの。充電専用ケーブルは不可)
- PC(Windows / macOS / Linux)

## 2. MicroPython ファームウェアの書き込み

1. MicroPython 公式サイトからお使いのボード用の UF2 ファイルをダウンロードします。
   **Pico W と Pico 2 W でファイルが異なる**ので注意してください。
   - Pico W: https://micropython.org/download/RPI_PICO_W/
   - Pico 2 W: https://micropython.org/download/RPI_PICO2_W/
2. Pico の **BOOTSEL ボタンを押しながら** USB ケーブルで PC に接続します。
3. `RPI-RP2`(Pico 2 W では `RP2350`)という名前の USB ドライブとして認識されるので、
   ダウンロードした UF2 ファイルをそのドライブにコピーします。
4. コピーが終わると Pico が自動的に再起動し、MicroPython が起動します。

すでに MicroPython を書き込み済みの場合、この手順は不要です。

## 3. プログラムの転送

`main.py` と `config.py` の 2 ファイルを Pico に転送します。
方法は Thonny(GUI)か mpremote(コマンドライン)のどちらでも構いません。

### 方法 A: Thonny を使う場合

1. [Thonny](https://thonny.org/) をインストールして起動します。
2. 右下のインタープリタ表示をクリックし、
   「MicroPython (Raspberry Pi Pico)」と接続ポートを選択します。
3. 先に「4. 設定」を参考に PC 上で `config.py` を編集しておきます。
4. 「ファイル」→「開く」でこのリポジトリの `main.py` を開き、
   「ファイル」→「名前を付けて保存」→「Raspberry Pi Pico」を選んで
   `main.py` という名前で保存します。
5. 同様に `config.py` も Pico に保存します。

### 方法 B: mpremote を使う場合

```sh
# mpremote のインストール(初回のみ)
pip install mpremote

# リポジトリのディレクトリで実行(config.py は編集済みであること)
mpremote cp main.py config.py :

# 再起動して実行開始
mpremote reset
```

## 4. 設定(config.py)

転送前に `config.py` を編集します。最低限、次の 3 つを環境に合わせてください。

```python
WIFI_SSID = "your-ssid"          # 接続先 Wi-Fi の SSID
WIFI_PASSWORD = "your-password"  # Wi-Fi パスワード
JJY_FREQUENCY_KHZ = 60           # 40 または 60(時計に合わせる)
```

注意点:

- Pico W / Pico 2 W の Wi-Fi は **2.4GHz のみ**対応です。5GHz 専用 SSID には接続できません。
- NTP サーバーはデフォルトで `ntp.nict.jp` です。社内 LAN などで外部 NTP に
  アクセスできない場合は `NTP_SERVER` をローカルのサーバーに変更してください。
- その他の設定項目は [README.md](../README.md) の一覧を参照してください。

## 5. 動作確認

1. Thonny または `mpremote repl` でシリアルコンソールを開き、Pico をリセットします
   (Thonny では停止→実行、mpremote では `mpremote reset` 後に `mpremote repl`)。
2. 次のようなログが表示されれば正常です。

   ```
   Connecting to Wi-Fi SSID: your-ssid
   Wi-Fi connected, IP: 192.168.x.x
   NTP sync OK: 2026-07-09 21:30:00 (local)
   Transmitting JJY on GPIO15 at 60 kHz
   Frame 21:31 (doy 190)
   ```

3. オンボード LED が 1 秒ごとに点滅します。点灯時間はそのとき送信している
   シンボルに対応します(0.2 秒 = マーカー、0.5 秒 = 1、0.8 秒 = 0)。
4. 電波時計をアンテナの近く(数 cm 以内)に置き、**強制受信モード**にします
   (多くの時計は受信ボタン長押し。機種の説明書を参照)。
   数分以内に時刻が合えば成功です。受信しない場合は [HARDWARE.md](HARDWARE.md) の
   「うまく受信しないとき」を参照してください。

## 6. スタンドアロン運用

`main.py` という名前で保存してあれば、Pico は電源を入れるだけで自動的に
プログラムを実行します。PC から外して USB 電源アダプタに接続すれば、
そのまま常時稼働の JJY 送信機として動作します。

- 起動のたびに Wi-Fi 接続 → NTP 同期 → 送信開始、と自動で進みます。
- `RESET_ON_ERROR = True`(デフォルト)なら、ネットワーク障害などで
  復帰できない状態に陥っても 10 秒後に自動リセットして再試行します。
- さらに `WATCHDOG = True` にすると、ハードウェアウォッチドッグ(8 秒)が
  有効になり、**例外が発生しないハング**(Wi-Fi ドライバのフリーズなど)からも
  自動復帰できます。無人の常時稼働では有効化を推奨します。
  ただし一度有効にすると次のリセットまで無効化できないため、REPL で
  プログラムを停止すると約 8 秒後に再起動がかかります。開発・調査中は
  `False` のままにしてください(`NTP_TIMEOUT_S` は 7 以下である必要があります)。

## 7. 電池・バッテリーでの運用(省エネモード)

`config.py` で `POWER_SAVE = True` にすると、電池運用向けの省エネモードになります。

```python
POWER_SAVE = True
POWER_SAVE_STARTUP_MINUTES = 20                      # 起動直後の連続送信(分)
POWER_SAVE_WINDOWS = ("11:45-12:15", "23:45-00:15")  # 毎日の送信ウィンドウ
```

動作の流れ:

1. **電源投入直後** — Wi-Fi 接続・NTP 同期の後、`POWER_SAVE_STARTUP_MINUTES`
   の間(デフォルト 20 分)連続送信します。この間に時計を設置し、
   強制受信で合わせてください。
2. **送信ウィンドウ** — 以降は `POWER_SAVE_WINDOWS` の時間帯
   (デフォルトは 11:45〜12:15 と 23:45〜00:15。多くの電波時計が自動受信を
   行う正午・深夜をカバー)だけ送信します。
3. **待機中** — Wi-Fi を完全に切り、lightsleep(数 mA)で待機します。
   ウィンドウ開始の約 2 分前に起床して Wi-Fi 再接続と NTP 再同期を行うため、
   長時間スリープしても送信時刻の精度は保たれます。オフライン送信できる
   ウィンドウ(NTP_RESYNC_MINUTES 以内)の場合は、同期が済みしだい
   ウィンドウ開始を待つ残りの時間も Wi-Fi を切って待機します。
   起床後に NTP 同期できなかった場合、そのウィンドウの送信は行いません
   (不正確な時刻を送信しないための安全側の動作です)。
4. **送信中の追加省エネ** — ウィンドウ冒頭の NTP 同期が済むと Wi-Fi を
   切り、CPU クロックを `POWER_SAVE_CPU_MHZ`(デフォルト 48MHz)まで下げて
   送信します。30 分程度なら水晶のドリフトは数十 ms で、精度への影響は
   ありません。ウィンドウ終了後、次の接続前にクロックは自動的に戻ります。

消費電力の目安は、送信中 15〜25mA(Wi-Fi オフ+48MHz 時)・待機中 2mA 前後です。
デフォルト設定なら 1 日あたり約 60〜70mAh となり、単3 アルカリ×3 本
(約 2000mAh)で約 1 ヶ月の連続運用が見込めます(電池の接続方法は
[HARDWARE.md](HARDWARE.md) の「電池での駆動」参照)。

注意点:

- **`WATCHDOG` とは併用できません**(lightsleep 中は feed できないため。
  両方 `True` にすると起動時にエラーで停止します)。
- **lightsleep 中は USB シリアルが切断されます。** 開発・動作確認中は
  `POWER_SAVE = False` のままにし、設定が固まってから有効化してください。
- lightsleep の安定動作には新しめの MicroPython ファームウェア
  (v1.21 以降推奨)を使用してください。
- **モバイルバッテリーは低負荷時に自動で出力を止める**製品が多く、待機中の
  数 mA では給電が切れることがあります。乾電池や低電流対応バッテリーを
  推奨します。

## 8. トラブルシューティング

| 症状 | 確認すること |
|---|---|
| `Wi-Fi connect timeout` | SSID/パスワードの誤り、5GHz 専用 SSID でないか、電波強度 |
| `NTP attempt ... failed` | インターネット接続、ルーターの UDP 123 番ポート、`NTP_SERVER` 名 |
| LED が点滅しない | `STATUS_LED = True` か、ファームウェアが W 用(無印 Pico 用では不可)か |
| 時計が受信しない | アンテナとの距離・向き、周波数(40/60)の一致、[HARDWARE.md](HARDWARE.md) 参照 |
| 起動直後に再起動を繰り返す | シリアルログでエラー内容を確認(`RESET_ON_ERROR = False` にすると調査しやすい) |
