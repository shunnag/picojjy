# ハードウェア準備ガイド

picojjy で電波時計に信号を届けるためのハードウェア構成を説明します。
はんだ付けなしのブレッドボード構成でも十分動作します。

## 必要な部品

| 部品 | 数量 | 備考 |
|---|---|---|
| Raspberry Pi Pico W または Pico 2 W | 1 | 無印 Pico は Wi-Fi 非搭載のため不可 |
| 抵抗 330Ω〜1kΩ | 1 | GPIO の保護と放射強度の調整用 |
| 電線(ジャンパワイヤ、エナメル線など) | 適量 | アンテナとして使用 |
| ブレッドボードまたはユニバーサル基板 | 1 | 配線用 |
| USB 電源(5V) | 1 | スマホ用充電器で可 |

オプション(受信しづらい場合の改善用):

| 部品 | 備考 |
|---|---|
| エナメル線(0.2〜0.4mm、数 m) | ループアンテナ自作用 |
| バーアンテナ+同調コンデンサ | 廃品の電波時計・AM ラジオから流用可 |

## 基本回路

GPIO ピン(デフォルト GP15)から抵抗を介してアンテナ線を接続するだけです。

```
Pico W / Pico 2 W
┌──────────────┐
│         GP15 ├──[ 330Ω〜1kΩ ]──── アンテナ線(20〜50cm)
│              │
│          GND ├── (ループアンテナの場合のみ接続)
└──────────────┘
```

- `GP15` は `config.py` の `ANTENNA_PIN` で変更できます(物理ピン 20 番)。
- 抵抗は GPIO の負荷を抑えるためのものです。省略しないでください。
- 出力は 3.3V の矩形波(40kHz または 60kHz)を JJY タイムコードで ON/OFF したものです。

## 抵抗の種類と電波の強さ・消費電力

### 抵抗の種類

ごく一般的な**カーボン皮膜抵抗(1/4W、誤差 ±5%)**で十分です。この回路で抵抗が
消費する電力は数十 mW 程度なので 1/8W 品でも問題なく、精度・温度特性も要求しません。
金属皮膜抵抗や酸化金属皮膜抵抗を使っても構いません(オーバースペックなだけです)。

### 抵抗値と電波の強さの関係

ループアンテナの磁界強度は、コイルに流れる電流にほぼ比例します。
この回路の電流はおおよそ I ≈ 3.3V ÷ R で決まるため、抵抗値がそのまま
「電波の強さ」の調整つまみになります。

| 抵抗値 | ピーク電流(目安) | 用途の目安 |
|---|---|---|
| 1kΩ | 約 3mA | 最も安全。時計のすぐ横(数 cm)に置ける場合 |
| 470Ω | 約 7mA | 標準的なバランス |
| 330Ω | 約 10mA | 本構成での推奨下限 |

- **330Ω 未満にはしないでください。** RP2040/RP2350 の GPIO 駆動能力を超えるおそれがあります。
- もっと強くしたい場合は、抵抗を減らすのではなく**ループの巻数や面積を増やす**か、
  **同調させる(案 3)**方が安全で効果も大きいです。
- 逆に強すぎる場合(離れた部屋の時計まで同期してしまう等)は、抵抗値を大きくするか
  `config.py` の `CARRIER_DUTY` を 0.5 から下げてください。デューティを下げると
  基本波(40/60kHz 成分)の振幅が下がります。

### 消費電力の目安

| 項目 | 目安 |
|---|---|
| アンテナ駆動分 | 約 10mW(330Ω 時。キャリア ON 率約 6 割 × デューティ 0.5 の平均) |
| 本体(Pico W、Wi-Fi 接続状態) | 平均 60〜80mA ≒ 0.3〜0.4W |
| Wi-Fi 送受信時のピーク | 瞬間的に 200mA 程度 |

アンテナ駆動分は本体の消費に比べて誤差程度です。電源はスマホ用の
5V/500mA 以上の USB アダプタで十分で、1 ヶ月連続稼働させても電力量は
約 0.3kWh(電気代で十数円程度)です。

## アンテナの選択肢

### 案 1: 単線アンテナ(最も簡単)

20〜50cm ほどの電線を抵抗の先に接続し、先端を開放のままにします。
電線を電波時計のすぐ近く(数 cm 以内)、時計内部のバーアンテナと平行になるように
置いてください。工作は最小限ですが、到達距離は数 cm 程度です。

### 案 2: ループアンテナ(おすすめ)

直径 5〜10cm に電線を 10〜20 回巻いたコイルを作り、一端を抵抗経由で GP15 に、
もう一端を GND に接続します。

```
GP15 ──[ 330Ω〜1kΩ ]──◯◯◯◯◯(10〜20 回巻き)── GND
```

磁界成分が強くなり、10〜30cm 程度まで安定して届くようになります。
巻き枠はペットボトルや厚紙の筒で十分です。

### 案 3: 同調バーアンテナ(上級)

廃品の電波時計や AM ラジオから取り出したバーアンテナ(フェライトコア入りコイル)に
コンデンサを並列に接続し、送信周波数に共振させる方法です。
共振周波数は f = 1 / (2π√LC) で決まります。例えばインダクタンス L が既知なら、

- 60kHz: C = 1 / ((2π × 60000)² × L)
- 40kHz: C = 1 / ((2π × 40000)² × L)

共振により効率が大きく上がり、より弱いデューティ(`CARRIER_DUTY` を小さく)でも
受信できるようになります。LCR メータがあると調整が容易です。

## 電池での駆動

省エネモード(`POWER_SAVE = True`、[INSTALL.md](INSTALL.md) 参照)と組み合わせると
電池での長期運用ができます。

- **VSYS(物理ピン 39 番)に 1.8〜5.5V を給電**できます。乾電池なら
  単3×3 本(4.5V、アルカリ/ニッケル水素どちらも可)が手頃です。
  マイナス側は GND(物理ピン 38 番)へ接続します。
- USB 給電と電池を同時に接続する場合は、VSYS へショットキーダイオードを
  介して給電してください(逆流防止)。
- **モバイルバッテリーは非推奨**です。待機中の消費が数 mA まで下がるため、
  低負荷を検知して自動的に出力を停止する製品がほとんどです。
- 消費の目安: 送信中 60〜80mA、lightsleep 待機中 2mA 前後。
  デフォルトのスケジュール(1 日 2 回×30 分)では約 120mAh/日となり、
  単3 アルカリ×3 本(約 2000mAh)で 2 週間強が見込めます。

## 配置のコツ

- 電波時計の内部にはバーアンテナ(横長のコイル)が入っています。送信アンテナは
  **時計のバーアンテナと平行**に、できるだけ近づけて置きます。
- 時計を**強制受信モード**にして試します(多くの機種で受信ボタン長押し)。
- テレビ・PC・LED 電源などノイズ源からは離してください。
- 受信中は時計を動かさないでください。受信完了まで通常 2〜5 分かかります。

## うまく受信しないとき

1. **周波数の確認** — 時計が 40kHz 専用なら `JJY_FREQUENCY_KHZ = 40` に変更。
   自動選択機の場合はどちらでも可ですが、両方試してください。
2. **距離と向き** — まず数 cm まで近づけ、アンテナの向きを 90 度ずつ変えて試す。
3. **LED の確認** — オンボード LED が毎秒点滅していること(= 送信動作中)を確認。
4. **時刻のずれ方を見る** — 時計が「受信成功」と表示するのに時刻が 9 時間ずれる場合は
   `TIME_OFFSET_HOURS` の設定を確認してください(日本の時計は 9 のまま)。
5. **ループアンテナ化** — 単線で届かない場合は案 2 のループアンテナに変更。
6. **深夜に実行される自動受信** — 多くの時計は深夜に自動受信します。常時稼働させて
   おけば、手動受信に失敗しても夜間に合うことがあります。

## 注意事項(電波法・安全)

- 本構成の放射は微弱で、到達距離は数 cm〜数十 cm を想定しています。
  日本の電波法では、一定の電界強度以下の「微弱無線局」は免許不要ですが、
  **トランジスタやアンプで増幅して到達距離を伸ばすことはしないでください。**
  違法な無線局として罰則の対象になるおそれがあります。
- GPIO に直接大きなコイルや長い電線を接続すると過負荷になる場合があります。
  必ず直列抵抗を入れてください。
- 常時稼働させる場合は、発熱の少ない USB 電源を使用し、通気を確保してください。
- 日本国外で日本の電波時計を使うユーザー向けの増幅方法を、次の英語セクションに
  記載しています。**日本国内では絶対に使用しないでください。**

---

## Boosting the signal for users outside Japan (English)

> ## ⚠️ WARNING — NEVER USE THIS IN JAPAN / 日本では絶対に使用禁止
>
> The circuit below exceeds the "extremely-low-power station" (微弱無線局)
> limits of the Japanese Radio Act. Operating it **anywhere in Japan is
> illegal**, can interfere with the official JJY broadcast and with your
> neighbors' clocks, and is subject to criminal penalties.
> **日本国内でこの増幅回路を使用することは電波法違反です。絶対に使用しないでください。**
>
> Outside Japan you are still responsible for complying with **your local
> radio regulations**. 40 kHz and 60 kHz are used by licensed time services
> in many countries (WWVB 60 kHz in the US, MSF 60 kHz in the UK, etc.).
> Most jurisdictions allow unlicensed intentional radiators at these
> frequencies only below a strict field-strength limit (e.g. FCC Part 15
> in the US). Keep the power at the minimum that reaches your clock —
> a couple of meters at most — and use it indoors only.

### Why you might need this

Japanese radio-controlled clocks ("電波時計") cannot receive JJY outside
Japan, so they never synchronize. The passive antenna described above works
at a few centimeters; if you want one transmitter to cover a shelf or a
room (1–3 m), the GPIO pin alone is not strong enough, and a small
one-transistor driver becomes useful.

### One-transistor driver circuit

Instead of connecting the antenna directly to the GPIO, use the GPIO to
switch a transistor that drives the antenna from the 5 V USB rail (VBUS):

```
  VBUS 5 V (physical pin 40)
    │
   [47–330 Ω, rated 1/2 W]      ← sets the antenna current
    │
   Loop antenna (10–20 turns) or tuned ferrite-bar antenna
    │
    ├─ drain (collector)
    │
GP15 ──[1 kΩ]── gate (base)     2N7000 / IRLZ34N (MOSFET)
    │                           or 2N2222 / 2SC1815 (NPN)
    └─ source (emitter) ── GND
```

Component notes:

- **Transistor**: any logic-level N-channel MOSFET (2N7000 for up to
  ~100 mA) or a small NPN (2N2222, 2SC1815). With an NPN, the 1 kΩ base
  resistor is required; with a MOSFET it just damps ringing.
- **Series resistor**: start with 330 Ω and lower it step by step only if
  the clock does not receive. 47 Ω gives roughly 100 mA peak — dissipation
  approaches 0.2 W on average, so use a 1/2 W resistor. Never omit it.
- **Antenna**: a tuned antenna is far more effective than more current.
  Resonate the coil with a parallel capacitor at the carrier frequency
  (C = 1 / ((2πf)² L), see "案 3" above). A tuned ferrite-bar antenna at
  47–100 Ω typically reaches 1–3 m.
- Keep `CARRIER_DUTY = 0.5` and reduce it if the signal is stronger than
  you need.

### Hard limits — do not go further

- Do **not** raise the supply above the 5 V USB rail.
- Do **not** connect this to an outdoor antenna or any long-wire antenna.
- Do **not** add further amplification stages. If 1–3 m is not enough,
  move the transmitter closer to the clock instead.
- If a neighbor's clock could plausibly pick up your signal, your signal
  is too strong.
