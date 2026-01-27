<script lang="ts">
  import { onMount } from 'svelte';
  import { Button } from 'bits-ui';
  import { clearBackendUrl, getBackendUrl, setBackendUrl } from '$lib/config';

  let backendUrl = '';
  let saved = false;

  onMount(() => {
    backendUrl = getBackendUrl();
  });

  const save = () => {
    setBackendUrl(backendUrl);
    saved = true;
    setTimeout(() => (saved = false), 1500);
  };

  const reset = () => {
    clearBackendUrl();
    backendUrl = getBackendUrl();
    saved = true;
    setTimeout(() => (saved = false), 1500);
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Config</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">環境設定</h1>
      <p class="mt-2 text-sm text-slate-600">CLIの設定画面に合わせたWebUI版設定。</p>
    </div>
    <Button.Root class="btn-ghost" href="/auth">ログアウト</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">Backend URL</h2>
    <p class="mt-2 text-sm text-slate-600">API接続先を変更できます。</p>
    <div class="mt-4">
      <p class="label">URL</p>
      <input class="input mt-2" bind:value={backendUrl} />
    </div>
    <div class="mt-6 flex flex-wrap gap-3">
      <Button.Root class="btn-primary" on:click={save}>保存</Button.Root>
      <Button.Root class="btn-ghost" on:click={reset}>デフォルトに戻す</Button.Root>
      {#if saved}
        <span class="chip">更新しました</span>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">ユーザー設定</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">ユーザー</p>
        <p class="text-base font-semibold text-slate-800">watanabe</p>
      </div>
      <div>
        <p class="label">プロジェクト</p>
        <p class="text-base font-semibold text-slate-800">default</p>
      </div>
      <div>
        <p class="label">権限</p>
        <p class="text-base font-semibold text-slate-800">admin</p>
      </div>
    </div>
    <div class="mt-6">
      <Button.Root class="btn-ghost">ユーザー設定を編集</Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">環境変数チェック</h2>
    <Button.Root class="btn-ghost">検証</Button.Root>
  </div>
  <div class="mt-4 grid gap-4 sm:grid-cols-2">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
      <p class="label">PERCUS_BACKEND_URL</p>
      <p class="mt-2 font-semibold text-slate-800">{backendUrl}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
      <p class="label">R2 Endpoint</p>
      <p class="mt-2 font-semibold text-slate-800">configured</p>
    </div>
  </div>
</section>
