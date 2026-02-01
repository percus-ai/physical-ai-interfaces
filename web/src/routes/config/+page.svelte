<script lang="ts">
  import { onMount } from 'svelte';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { clearBackendUrl, getBackendUrl, setBackendUrl } from '$lib/config';
  import { api } from '$lib/api/client';

  let backendUrl = '';
  let saved = false;

  type AppConfigResponse = {
    config?: {
      data_dir?: string;
      robot_type?: string;
      hf_token_set?: boolean;
    };
  };

  type UserConfigResponse = {
    email?: string;
    default_fps?: number;
    auto_upload_after_recording?: boolean;
    auto_download_models?: boolean;
  };

  const configQuery = createQuery<AppConfigResponse>({
    queryKey: ['config'],
    queryFn: api.config.get
  });

  const userConfigQuery = createQuery<UserConfigResponse>({
    queryKey: ['user', 'config'],
    queryFn: api.user.config
  });

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

  const refreshUserConfig = () => {
    $userConfigQuery?.refetch?.();
  };

</script>

<section class="card-strong p-8">
  <p class="section-title">Config</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">環境設定</h1>
      <p class="mt-2 text-sm text-slate-600">接続先やアプリ設定を管理します。</p>
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
      <Button.Root class="btn-primary" type="button" onclick={save}>保存</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={reset}>デフォルトに戻す</Button.Root>
      {#if saved}
        <span class="chip">更新しました</span>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">アプリ設定</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">データディレクトリ</p>
        <p class="text-base font-semibold text-slate-800">{$configQuery.data?.config?.data_dir ?? '-'}</p>
      </div>
      <div>
        <p class="label">ロボット種別</p>
        <p class="text-base font-semibold text-slate-800">{$configQuery.data?.config?.robot_type ?? '-'}</p>
      </div>
      <div>
        <p class="label">HF Token</p>
        <p class="text-base font-semibold text-slate-800">{$configQuery.data?.config?.hf_token_set ? '設定済み' : '未設定'}</p>
      </div>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">ユーザー設定</h2>
    <Button.Root class="btn-ghost" type="button" onclick={refreshUserConfig}>更新</Button.Root>
  </div>
  <div class="mt-4 grid gap-4 sm:grid-cols-2">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
      <p class="label">メールアドレス</p>
      <p class="mt-2 font-semibold text-slate-800">{$userConfigQuery.data?.email ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
      <p class="label">デフォルトFPS</p>
      <p class="mt-2 font-semibold text-slate-800">{$userConfigQuery.data?.default_fps ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
      <p class="label">自動アップロード</p>
      <p class="mt-2 font-semibold text-slate-800">{$userConfigQuery.data?.auto_upload_after_recording ? '有効' : '無効'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
      <p class="label">自動モデルDL</p>
      <p class="mt-2 font-semibold text-slate-800">{$userConfigQuery.data?.auto_download_models ? '有効' : '無効'}</p>
    </div>
  </div>
</section>
