<script lang="ts">
  import { Button } from 'bits-ui';
</script>

<section class="card-strong p-8">
  <div class="flex flex-wrap items-start justify-between gap-6">
    <div class="space-y-3">
      <p class="section-title">Overview</p>
      <h1 class="text-3xl font-semibold text-slate-900">PerCUs Web Console</h1>
      <p class="max-w-xl text-sm text-slate-600">
        CLIと同等の運用フローをブラウザで再現するための統合コンソールです。各メニューの状態確認と、
        よく使う操作へのショートカットを用意しています。
      </p>
      <div class="flex flex-wrap gap-3">
        <span class="chip">CLI互換フロー</span>
        <span class="chip">SvelteKit + Svelte 5</span>
        <span class="chip">TanStack Query</span>
      </div>
    </div>
    <div class="flex flex-col gap-3">
      <Button.Root class="btn-primary" href="/train">学習ジョブを作成</Button.Root>
      <Button.Root class="btn-ghost" href="/record">録画を開始</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-3">
  <div class="card p-6">
    <p class="section-title">Operate</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">テレオペ / 推論</h2>
    <p class="mt-3 text-sm text-slate-600">テレオペ・推論実行・セッション監視を統合表示。</p>
    <div class="mt-6 flex gap-3">
      <Button.Root class="btn-ghost" href="/operate">開く</Button.Root>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Record</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">録画セッション</h2>
    <p class="mt-3 text-sm text-slate-600">プロジェクト選択、エピソード指定、進行状況を可視化。</p>
    <div class="mt-6 flex gap-3">
      <Button.Root class="btn-ghost" href="/record">開く</Button.Root>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Train</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">学習ジョブ</h2>
    <p class="mt-3 text-sm text-slate-600">新規学習/継続学習、GPU・ストレージ指定を整理。</p>
    <div class="mt-6 flex gap-3">
      <Button.Root class="btn-ghost" href="/train">開く</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <p class="section-title">Recent Activity</p>
    <h3 class="mt-2 text-lg font-semibold text-slate-900">最新の操作ログ</h3>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>録画: 0001_black_cube_to_tray</span>
        <span class="chip">進行中</span>
      </div>
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>学習: pi05_a1b2c3_260109_143052</span>
        <span class="chip">待機</span>
      </div>
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>データセット: project/session_20260107</span>
        <span class="chip">完了</span>
      </div>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">System</p>
    <h3 class="mt-2 text-lg font-semibold text-slate-900">システム状態</h3>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">Backend</p>
        <p class="text-base font-semibold text-slate-800">http://localhost:8000</p>
      </div>
      <div>
        <p class="label">GPU Pool</p>
        <p class="text-base font-semibold text-slate-800">H100 / A100 / B200</p>
      </div>
      <div>
        <p class="label">Storage</p>
        <p class="text-base font-semibold text-slate-800">R2 (s3://daihen/v2)</p>
      </div>
    </div>
    <div class="mt-6">
      <Button.Root class="btn-ghost" href="/info">詳細</Button.Root>
    </div>
  </div>
</section>
