# WebUI 開発メモ

WebUIの設計・実装で後回しの項目をここに記録。

## 既にAPI連携済み
- /api/analytics/overview
- /api/system/health, /api/system/resources, /api/system/info, /api/system/gpu, /api/system/logs
- /api/projects (一覧)
- /api/recording/recordings
- /api/storage/datasets, /api/storage/models, /api/storage/usage, /api/storage/archive
- /api/training/jobs, /api/training/gpu-availability
- /api/config, /api/config/environments
- /api/user/config, /api/user/devices
- /api/hardware, /api/hardware/cameras, /api/hardware/serial-ports
- /api/teleop/local/sessions
- /api/inference/models, /api/inference/sessions

## フロント定義を参照している箇所
- POLICY_TYPES / GPU_MODELS / GPU_COUNTS: `interfaces/web/src/lib/policies.ts`

## バックエンドへ寄せる候補（未整備/不足）
- ポリシー種別・推奨パラメータ一覧（POLICY_TYPES をAPIで返す）
- 学習ジョブ作成ウィザードのデフォルト値（steps/batch/save_freq）
- テレオペ/推論の詳細セッション状態（WebSocket進行状況）
- 録画進行中のステータス/アップロード進捗

## UIでの残タスク
- ボタン操作（開始/停止/作成/削除/編集）
- リアルタイム更新（WebSocket購読）
- エラーハンドリングとトースト

## 実装メモ
- bits-ui の `Button.Root` は Svelte5 では `on:click` が効かない場合があるため、`onclick` を使う（DOM 属性に直接渡す）
