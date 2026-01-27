# WebUI 共通化メモ

CLIとWebUIで共通化すべきが後回しの項目をここに記録。

## バックエンドへ寄せる候補
- ポリシー種別・推奨パラメータ一覧（train: POLICY_TYPES）
- GPUモデル / GPU数 / torch nightly要否（train: GPU_MODELS, GPU_COUNTS）
- データセット一覧、プロジェクト一覧（record/storage/setup）
- 学習ジョブ一覧とステータス（train）
- デバイス検出 / シリアルポート一覧 / カメラ一覧（setup）
- ストレージ使用量 / アーカイブ一覧（storage）
- テレオペ・推論のセッション状態（operate）

## UIでの仮置き
- 画面内の一覧・数値はダミー表示
- API連携は `src/lib/api/client.ts` を入口に統一
