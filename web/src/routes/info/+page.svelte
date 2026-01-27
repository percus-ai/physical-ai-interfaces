<script lang="ts">
  import { Button } from 'bits-ui';
</script>

<section class="card-strong p-8">
  <p class="section-title">Info</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">システム情報</h1>
      <p class="mt-2 text-sm text-slate-600">環境状態と依存関係を可視化。</p>
    </div>
    <Button.Root class="btn-ghost">再チェック</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-3">
  <div class="card p-6">
    <p class="section-title">Runtime</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">環境</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">Python</p>
        <p class="text-base font-semibold text-slate-800">3.11.x</p>
      </div>
      <div>
        <p class="label">LeRobot</p>
        <p class="text-base font-semibold text-slate-800">v0.0.x</p>
      </div>
      <div>
        <p class="label">R2 Sync</p>
        <p class="text-base font-semibold text-slate-800">enabled</p>
      </div>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Backend</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">API状態</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">Health</p>
        <p class="text-base font-semibold text-slate-800">healthy</p>
      </div>
      <div>
        <p class="label">Version</p>
        <p class="text-base font-semibold text-slate-800">2026.01</p>
      </div>
      <div>
        <p class="label">Auth</p>
        <p class="text-base font-semibold text-slate-800">ログイン済み</p>
      </div>
    </div>
  </div>
  <div class="card p-6">
    <p class="section-title">Storage</p>
    <h2 class="mt-2 text-xl font-semibold text-slate-900">R2 / S3</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">Bucket</p>
        <p class="text-base font-semibold text-slate-800">daihen</p>
      </div>
      <div>
        <p class="label">Prefix</p>
        <p class="text-base font-semibold text-slate-800">s3://daihen/v2</p>
      </div>
      <div>
        <p class="label">Region</p>
        <p class="text-base font-semibold text-slate-800">auto</p>
      </div>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">サービスログ</h2>
    <Button.Root class="btn-ghost">エクスポート</Button.Root>
  </div>
  <div class="mt-4 space-y-2 text-xs text-slate-500">
    <p>[INFO] backend: connected</p>
    <p>[INFO] r2 sync: last upload 2 minutes ago</p>
    <p>[WARN] gpu pool: H200 busy</p>
  </div>
</section>
