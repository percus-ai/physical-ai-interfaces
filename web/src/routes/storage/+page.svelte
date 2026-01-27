<script lang="ts">
  import { Button } from 'bits-ui';
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ管理</h1>
      <p class="mt-2 text-sm text-slate-600">データセット/モデル/アーカイブを統合管理。</p>
    </div>
    <Button.Root class="btn-ghost">ストレージ使用量</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
      <div class="flex gap-2">
        <Button.Root class="btn-ghost">一括操作</Button.Root>
        <Button.Root class="btn-primary">新規追加</Button.Root>
      </div>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>project/session_20260107 (12.4GB)</span>
        <span class="chip">active</span>
      </div>
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>project/session_20260105 (8.1GB)</span>
        <span class="chip">active</span>
      </div>
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">ストレージ使用量</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">データセット</p>
        <p class="text-base font-semibold text-slate-800">2.1 TB / 6.0 TB</p>
      </div>
      <div>
        <p class="label">モデル</p>
        <p class="text-base font-semibold text-slate-800">820 GB / 2.0 TB</p>
      </div>
      <div>
        <p class="label">アーカイブ</p>
        <p class="text-base font-semibold text-slate-800">410 GB</p>
      </div>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">モデル管理</h2>
      <Button.Root class="btn-ghost">同期</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>pi05_base_finetuned_v2</span>
        <span class="chip">R2</span>
      </div>
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>act_policy_20260120</span>
        <span class="chip">local</span>
      </div>
    </div>
  </div>

  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">アーカイブ</h2>
      <Button.Root class="btn-ghost">一覧</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>archive/datasets/20251230</span>
        <span class="chip">32 items</span>
      </div>
      <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
        <span>archive/models/20251201</span>
        <span class="chip">9 items</span>
      </div>
    </div>
  </div>
</section>
