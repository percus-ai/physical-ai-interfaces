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

## Svelte 5 実装ルール（runes 前提）
Svelte 5 への全面移行を行ったため、以後の実装は以下を基本ルールとする。

### 1) 状態管理は runes を中心に置く
- **状態**は `$state`、**派生**は `$derived`、**副作用**は `$effect` を使う。
- `$derived` の中に副作用（fetch / setTimeout / subscribe 等）を入れない。副作用は必ず `$effect` に分離する。
- 旧来の `svelte/store` の `writable/derived/get` を常用しない（例外: `toStore` のみ許可）。

**理由**: runes は依存関係の解決が明示的で、更新伝播が読みやすい。副作用の混入がバグ源になるため、役割を分離する。

### 2) ルーティング依存は `$app/state` の `page` を直接参照
- `page` は store ではないので、**`$page` ではなく** `page.url` / `page.params` を直接読む。
- 旧来の `derived(page, ...)` は使わない。

**理由**: `$app/state` の `page` は runes と相性が良く、store 形態に戻すと `store_invalid_shape` などの事故が起きやすい。

### 3) TanStack Query は `toStore` 経由で動的オプションを渡す
- `createQuery` の `queryKey` / `enabled` / `queryFn` などが state に依存する場合は  
  **`toStore(() => ({ ... }))`** で渡す。
- `enabled` は認証・パラメータ・画面状態と連動させ、未準備状態でのリクエストを防ぐ。

**理由**: Svelte 5 では store の `derived` を多用しない方針。`toStore` を入口に統一すると依存関係の管理が明確になる。

### 4) データの持ち主を 1 箇所にする
- **単一ソースオブトゥルース**を徹底し、同じ値を複数 state で持たない。
- 「表示用の値」は `$derived` で計算し、**元データは query または API の結果に集約**する。

**理由**: 二重管理は更新漏れ・表示ズレの原因になる。SSE/WS で更新される値は特に注意。

### 5) 長寿命の副作用は必ず解放する
- SSE/WS/Timer/Observer などは `$effect` で開始し、返り値の cleanup で解放する。
- `onDestroy` での cleanup も併用し、画面遷移時のリークを防ぐ。

**理由**: 画面遷移が多い UI でリークが起きると再接続が増え、バックエンド負荷や UI 挙動が悪化する。

### 6) props は `$props()` で明示する
- `export let` は原則使わない。  
  `let { foo = 'default', bar }: { foo?: string; bar: number } = $props();` の形で宣言する。

**理由**: runes モードでは props の意図と型を明示した方が読みやすく、デフォルト値も一箇所に集約できる。

### 7) UI イベントと状態更新の関係を直線化する
- `onclick` などのハンドラは **副作用→状態更新→表示** の順に整理する。
- 複数の非同期呼び出しがある場合は、**状態の競合**が起きないように `pending` を明示する。

**理由**: Svelte 5 はリアクティブが強いため、更新順序が曖昧だとちらつきや状態破綻が起きやすい。
