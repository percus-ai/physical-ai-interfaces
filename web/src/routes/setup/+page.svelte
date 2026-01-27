<script lang="ts">
  import { Button } from 'bits-ui';
</script>

<section class="card-strong p-8">
  <p class="section-title">Setup</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">デバイス・プロジェクト設定</h1>
      <p class="mt-2 text-sm text-slate-600">プロジェクト管理、デバイス検出、キャリブレーションの集中管理。</p>
    </div>
    <Button.Root class="btn-ghost">セットアップウィザード</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-3">
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">プロジェクト</h2>
    <p class="mt-2 text-sm text-slate-600">YAMLインポートや既存プロジェクトの編集。</p>
    <div class="mt-6 flex flex-col gap-3">
      <Button.Root class="btn-primary">YAMLからインポート</Button.Root>
      <Button.Root class="btn-ghost">プロジェクト一覧</Button.Root>
    </div>
  </div>
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">デバイス</h2>
    <p class="mt-2 text-sm text-slate-600">カメラ・シリアルポート・ロボットを検出。</p>
    <div class="mt-6 space-y-3">
      <Button.Root class="btn-primary">デバイス検出</Button.Root>
      <Button.Root class="btn-ghost">設定を変更</Button.Root>
    </div>
  </div>
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">キャリブレーション</h2>
    <p class="mt-2 text-sm text-slate-600">ロボットアームの原点・動作範囲を調整。</p>
    <div class="mt-6 space-y-3">
      <Button.Root class="btn-primary">キャリブレーション開始</Button.Root>
      <Button.Root class="btn-ghost">手順を見る</Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">接続デバイス</h2>
    <Button.Root class="btn-ghost">更新</Button.Root>
  </div>
  <div class="mt-4 grid gap-4 sm:grid-cols-2">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
      <p class="label">カメラ</p>
      <p class="mt-2 text-sm text-slate-600">Detected: 2</p>
      <p class="text-xs text-slate-500">/dev/video0, /dev/video2</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
      <p class="label">シリアル</p>
      <p class="mt-2 text-sm text-slate-600">Detected: 3</p>
      <p class="text-xs text-slate-500">/dev/ttyUSB0, /dev/ttyUSB1</p>
    </div>
  </div>
</section>
