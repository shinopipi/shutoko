# 首都高ドライブ

ブラウザで遊べる首都高ドライブゲーム（three.js）。C1 都心環状線（内回り）と B 湾岸線（湾岸市川 ⇄ 空港中央）を走れます。

## 遊び方

- スマホ：左下 ◀ ▶ でハンドル、右下でアクセル／ブレーキ
- PC：矢印キー or WASD、N で昼夜切替、C で視点切替
- 右上：昼夜、視点、雨、画質、コース、音
- スマホのホーム画面に追加すると全画面アプリとして起動できます

## 機能

- 実在の建物・道路データ（OpenStreetMap / Overpass API）を起動時に取得
  - 沿線の建物を形・高さ（`height` / `building:levels`）付きで立体化
  - 手作りのルートを実際の首都高の線形に寄せて補正
  - 一度取得したデータはブラウザに保存され、次回から速く起動
  - 取得できないときは簡易マップで走行
- 高精細な車モデル（glTF）を読み込み。失敗時は自作モデル
- 昼・夕方・夜の切替、雨（濡れた路面の反射）
- 光のにじみ（ブルーム）、色調補正、影、空の映り込み

## GitHub Pages で公開する手順

1. このフォルダのファイル（`index.html`, `manifest.webmanifest`, `icon-192.png`, `icon-512.png`, `README.md`）をリポジトリに置く
2. リポジトリの Settings → Pages → Branch を `main` / `(root)` にして保存
3. 数分後に `https://<ユーザー名>.github.io/<リポジトリ名>/` で遊べます

## クレジット

- 地図データ © OpenStreetMap contributors（ODbL）
- 3D エンジン：three.js（MIT）
- 車モデル：Ferrari 458 Italia model by vicent091036（Sketchfab）、three.js examples 収録のものを読み込み
  - 公開範囲を広げる場合は、元モデルのライセンスを確認してください

※ 首都高速道路株式会社とは関係のない個人制作のゲームです。
