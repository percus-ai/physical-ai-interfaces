<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';

  const projectsQuery = createQuery({
    queryKey: ['projects'],
    queryFn: api.projects.list
  });

  const hardwareStatusQuery = createQuery({
    queryKey: ['hardware', 'status'],
    queryFn: api.hardware.status
  });

  const camerasQuery = createQuery({
    queryKey: ['hardware', 'cameras'],
    queryFn: api.hardware.cameras
  });

  const portsQuery = createQuery({
    queryKey: ['hardware', 'ports'],
    queryFn: api.hardware.serialPorts
  });

  const devicesQuery = createQuery({
    queryKey: ['user', 'devices'],
    queryFn: api.user.devices
  });
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
    <div class="mt-4 space-y-2 text-sm text-slate-600">
      {#if $projectsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $projectsQuery.data?.projects?.length}
        {#each $projectsQuery.data.projects as project}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2">{project}</div>
        {/each}
      {:else}
        <p>プロジェクトがありません。</p>
      {/if}
    </div>
  </div>
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">デバイス状態</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">カメラ検出数</p>
        <p class="text-base font-semibold text-slate-800">{$hardwareStatusQuery.data?.cameras_detected ?? 0}</p>
      </div>
      <div>
        <p class="label">シリアルポート検出数</p>
        <p class="text-base font-semibold text-slate-800">{$hardwareStatusQuery.data?.ports_detected ?? 0}</p>
      </div>
      <div>
        <p class="label">OpenCV</p>
        <p class="text-base font-semibold text-slate-800">{$hardwareStatusQuery.data?.opencv_available ? 'Available' : 'Not available'}</p>
      </div>
    </div>
  </div>
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">ユーザー設定</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">リーダー右腕</p>
        <p class="text-base font-semibold text-slate-800">{$devicesQuery.data?.leader_right?.port ?? '-'}</p>
      </div>
      <div>
        <p class="label">フォロワー右腕</p>
        <p class="text-base font-semibold text-slate-800">{$devicesQuery.data?.follower_right?.port ?? '-'}</p>
      </div>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">検出カメラ</h2>
      <Button.Root class="btn-ghost">更新</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $camerasQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $camerasQuery.data?.cameras?.length}
        {#each $camerasQuery.data.cameras as camera}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2">
            Camera {camera.id} ({camera.width}x{camera.height} / {camera.fps}fps)
          </div>
        {/each}
      {:else}
        <p>カメラが見つかりません。</p>
      {/if}
    </div>
  </div>
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">シリアルポート</h2>
      <Button.Root class="btn-ghost">更新</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $portsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $portsQuery.data?.ports?.length}
        {#each $portsQuery.data.ports as port}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2">
            {port.port} {port.description ? `(${port.description})` : ''}
          </div>
        {/each}
      {:else}
        <p>ポートが見つかりません。</p>
      {/if}
    </div>
  </div>
</section>
