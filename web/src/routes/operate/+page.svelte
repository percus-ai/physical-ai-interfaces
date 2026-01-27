<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatDate } from '$lib/format';

  const teleopSessionsQuery = createQuery({
    queryKey: ['teleop', 'sessions'],
    queryFn: api.teleop.sessions
  });

  const inferenceModelsQuery = createQuery({
    queryKey: ['inference', 'models'],
    queryFn: api.inference.models
  });

  const inferenceSessionsQuery = createQuery({
    queryKey: ['inference', 'sessions'],
    queryFn: api.inference.sessions
  });

  const devicesQuery = createQuery({
    queryKey: ['user', 'devices'],
    queryFn: api.user.devices
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Operate</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">テレオペ / 推論</h1>
      <p class="mt-2 text-sm text-slate-600">テレオペレーションと推論セッションの状態を確認します。</p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-primary">セッションを開始</Button.Root>
      <Button.Root class="btn-ghost">推論を実行</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">テレオペレーション状態</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $teleopSessionsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $teleopSessionsQuery.data?.sessions?.length}
        {#each $teleopSessionsQuery.data.sessions as session}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div>
              <p class="font-semibold text-slate-800">{session.session_id}</p>
              <p class="text-xs text-slate-500">{session.mode} / {session.leader_port} → {session.follower_port}</p>
            </div>
            <span class="chip">{session.is_running ? '実行中' : '待機'}</span>
          </div>
        {/each}
      {:else}
        <p>稼働中のセッションはありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">デバイス設定</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">リーダー右腕</p>
        <p class="text-base font-semibold text-slate-800">
          {$devicesQuery.data?.leader_right?.port ?? '-'}
        </p>
      </div>
      <div>
        <p class="label">フォロワー右腕</p>
        <p class="text-base font-semibold text-slate-800">
          {$devicesQuery.data?.follower_right?.port ?? '-'}
        </p>
      </div>
      <div>
        <p class="label">カメラ</p>
        <p class="text-sm text-slate-600">
          {Object.keys($devicesQuery.data?.cameras ?? {}).length} 台登録
        </p>
      </div>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">推論モデル</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $inferenceModelsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $inferenceModelsQuery.data?.models?.length}
        {#each $inferenceModelsQuery.data.models as model}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div>
              <p class="font-semibold text-slate-800">{model.name}</p>
              <p class="text-xs text-slate-500">{model.policy_type} / {model.source}</p>
            </div>
            <span class="chip">{model.is_loaded ? 'ロード済み' : '未ロード'}</span>
          </div>
        {/each}
      {:else}
        <p>利用可能なモデルがありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">推論セッション</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $inferenceSessionsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $inferenceSessionsQuery.data?.sessions?.length}
        {#each $inferenceSessionsQuery.data.sessions as session}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <div>
              <p class="font-semibold text-slate-800">{session.session_id}</p>
              <p class="text-xs text-slate-500">{session.model_id} / {session.device}</p>
            </div>
            <span class="chip">{formatDate(session.created_at)}</span>
          </div>
        {/each}
      {:else}
        <p>稼働中のセッションはありません。</p>
      {/if}
    </div>
  </div>
</section>
