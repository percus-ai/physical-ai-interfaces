<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { getBackendUrl } from '$lib/config';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';

  type VlaborProfile = {
    name: string;
    description?: string;
    updated_at?: string;
  };

  type ProfilesResponse = {
    profiles?: VlaborProfile[];
    active_profile_name?: string;
  };

  type ActiveProfileResponse = {
    profile_name?: string;
    profile_snapshot?: Record<string, unknown>;
  };

  type ProfileStatusResponse = {
    profile_name?: string;
    profile_snapshot?: Record<string, unknown>;
    cameras?: Array<{
      name: string;
      label?: string;
      enabled: boolean;
      connected: boolean;
      connected_topic?: string;
      topics?: string[];
    }>;
    arms?: Array<{
      name: string;
      label?: string;
      role?: string;
      enabled: boolean;
      connected: boolean;
      connected_topic?: string;
      topics?: string[];
    }>;
    topics?: string[];
  };

  type VlaborStatusResponse = {
    status?: string;
    service?: string;
    state?: string;
    status_detail?: string;
    running_for?: string;
    created_at?: string;
    container_id?: string;
    dashboard_url?: string;
  };

  const profilesQuery = createQuery<ProfilesResponse>({
    queryKey: ['profiles', 'list'],
    queryFn: api.profiles.list
  });

  const activeProfileQuery = createQuery<ActiveProfileResponse>({
    queryKey: ['profiles', 'active'],
    queryFn: api.profiles.active
  });

  const activeProfileName = $derived(
    $activeProfileQuery.data?.profile_name ?? $profilesQuery.data?.active_profile_name ?? ''
  );

  const activeStatusQuery = createQuery<ProfileStatusResponse>(
    toStore(() => ({
      queryKey: ['profiles', 'active', 'status'],
      queryFn: api.profiles.activeStatus,
      enabled: Boolean(activeProfileName)
    }))
  );

  const vlaborStatusQuery = createQuery<VlaborStatusResponse>({
    queryKey: ['profiles', 'vlabor', 'status'],
    queryFn: api.profiles.vlaborStatus
  });

  const vlaborState = $derived($vlaborStatusQuery.data?.status ?? 'unknown');
  const vlaborDetail = $derived(
    $vlaborStatusQuery.data?.status_detail ?? $vlaborStatusQuery.data?.running_for ?? ''
  );
  const vlaborDashboardUrl = $derived($vlaborStatusQuery.data?.dashboard_url ?? '');

  const activeProfileDescription = $derived.by(() => {
    const name = activeProfileName;
    if (!name) return 'プロファイルが選択されていません。';
    const profile = ($profilesQuery.data?.profiles ?? []).find((item) => item.name === name);
    return profile?.description ?? '説明は未設定です。';
  });

  let switchingProfile = $state(false);
  let selectionError = $state('');
  const MAX_LOG_LINES = 50;
  let restartingVlabor = $state(false);
  let restartError = $state('');
  let restartLogs = $state<string[]>([]);
  let restartWs = $state<WebSocket | null>(null);
  let logEl: HTMLPreElement | undefined = $state();

  async function refetchQuery(snapshot?: { refetch?: () => Promise<unknown> }) {
    if (snapshot && typeof snapshot.refetch === 'function') {
      await snapshot.refetch();
    }
  }

  async function handleProfileChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    const profileName = target.value;
    if (!profileName) return;
    switchingProfile = true;
    selectionError = '';
    try {
      await api.profiles.setActive({ profile_name: profileName });
      await refetchQuery($activeProfileQuery);
      await refetchQuery($profilesQuery);
      await refetchQuery($activeStatusQuery);
    } catch (error) {
      console.error(error);
      selectionError = error instanceof Error ? error.message : 'プロファイル切り替えに失敗しました。';
    } finally {
      switchingProfile = false;
    }
  }

  function handleRestartVlabor() {
    if (restartWs) return;
    restartingVlabor = true;
    restartError = '';
    restartLogs = [];

    const selectedProfile = (activeProfileName ?? '').trim();
    const restartPath = selectedProfile
      ? `/api/profiles/ws/vlabor/restart?profile=${encodeURIComponent(selectedProfile)}`
      : '/api/profiles/ws/vlabor/restart';
    const wsUrl = getBackendUrl().replace(/^http/, 'ws') + restartPath;
    const ws = new WebSocket(wsUrl);
    restartWs = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'log') {
          restartLogs = [...restartLogs, data.line].slice(-MAX_LOG_LINES);
          requestAnimationFrame(() => {
            if (logEl) logEl.scrollTop = logEl.scrollHeight;
          });
        } else if (data.type === 'complete') {
          if (data.exit_code !== '0') {
            restartError = `終了コード: ${data.exit_code}`;
          }
        } else if (data.type === 'error') {
          restartError = data.message;
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onerror = () => {
      restartError = 'WebSocket接続に失敗しました。';
      restartingVlabor = false;
      restartWs = null;
    };

    ws.onclose = () => {
      restartingVlabor = false;
      restartWs = null;
    };
  }

  let stopVlaborStream = () => {};

  onMount(() => {
    stopVlaborStream = connectStream({
      path: '/api/stream/profiles/vlabor',
      onMessage: (payload) => {
        queryClient.setQueryData(['profiles', 'vlabor', 'status'], payload);
      }
    });
  });

  onDestroy(() => {
    stopVlaborStream();
    restartWs?.close();
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Setup</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">デバイス・プロファイル設定</h1>
      <p class="mt-2 text-sm text-slate-600">VLAborプロファイルの選択と状態確認。</p>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <p class="text-xs uppercase tracking-widest text-slate-400">Active Profile</p>
      <h2 class="mt-1 text-2xl font-semibold text-slate-900">{activeProfileName || '-'}</h2>
      <p class="mt-2 text-sm text-slate-600">{activeProfileDescription}</p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <select
        class="input min-w-[260px]"
        disabled={switchingProfile || !($profilesQuery.data?.profiles ?? []).length}
        value={activeProfileName}
        onchange={handleProfileChange}
      >
        <option value="" disabled>プロファイルを選択</option>
        {#each $profilesQuery.data?.profiles ?? [] as profile}
          <option value={profile.name}>{profile.name}</option>
        {/each}
      </select>
      {#if switchingProfile}
        <span class="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-700">切り替え中…</span>
      {:else if vlaborState === 'restarting'}
        <span class="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-700">再起動中</span>
      {:else if vlaborState === 'running'}
        <span class="rounded-full bg-emerald-100 px-3 py-1 text-xs text-emerald-700">稼働中</span>
      {:else if vlaborState === 'stopped'}
        <span class="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">停止</span>
      {:else}
        <span class="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">不明</span>
      {/if}
      {#if vlaborDetail}
        <span class="text-xs text-slate-400">{vlaborDetail}</span>
      {/if}
      <button
        class="inline-flex h-9 items-center justify-center rounded-full border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        disabled={restartingVlabor}
        onclick={handleRestartVlabor}
      >
        {restartingVlabor ? '再起動中…' : 'VLAbor 再起動'}
      </button>
      {#if vlaborDashboardUrl}
        <a
          class="inline-flex h-9 items-center justify-center rounded-full border border-emerald-200 bg-emerald-50 px-4 text-xs font-semibold text-emerald-700"
          href={vlaborDashboardUrl}
          target="_blank"
          rel="noreferrer"
        >
          VLabor UI を開く
        </a>
      {/if}
    </div>
  </div>
  {#if selectionError}
    <p class="mt-3 text-xs text-rose-500">{selectionError}</p>
  {/if}
  {#if restartError}
    <p class="mt-3 text-xs text-rose-500">{restartError}</p>
  {/if}
  {#if restartLogs.length > 0}
    <pre bind:this={logEl} class="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-slate-200/60 bg-slate-900 p-3 text-xs leading-relaxed text-slate-200">{restartLogs.join('\n')}</pre>
  {/if}
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">プロファイルの生データ</h2>
    <div class="mt-4 text-sm text-slate-600">
      <pre class="max-h-[360px] overflow-auto rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-700">
{JSON.stringify($activeProfileQuery.data?.profile_snapshot ?? {}, null, 2)}
      </pre>
    </div>
  </div>
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">デバイス状態</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      {#if $activeStatusQuery.isLoading}
        <p>読み込み中...</p>
      {:else}
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <p class="label">カメラ</p>
          <div class="mt-2 space-y-2">
            {#each $activeStatusQuery.data?.cameras ?? [] as cam}
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium text-slate-700">{cam.label ?? cam.name}</p>
                  <p class="truncate text-[11px] text-slate-400">{cam.name}</p>
                  {#if cam.connected_topic}
                    <p class="truncate text-[11px] text-emerald-600">{cam.connected_topic}</p>
                  {:else if cam.topics?.length}
                    <p class="truncate text-[11px] text-slate-400">期待: {cam.topics[0]}</p>
                  {/if}
                </div>
                <span class="shrink-0 text-xs text-slate-500">
                  {cam.enabled ? (cam.connected ? '✅ 接続' : '⚠️ 未接続') : '⏸️ 無効'}
                </span>
              </div>
            {/each}
          </div>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <p class="label">ロボット/アーム</p>
          <div class="mt-2 space-y-2">
            {#each $activeStatusQuery.data?.arms ?? [] as arm}
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium text-slate-700">{arm.label ?? arm.name}</p>
                  <p class="truncate text-[11px] text-slate-400">
                    {arm.name}{arm.role ? ` (${arm.role})` : ''}
                  </p>
                  {#if arm.connected_topic}
                    <p class="truncate text-[11px] text-emerald-600">{arm.connected_topic}</p>
                  {:else if arm.topics?.length}
                    <p class="truncate text-[11px] text-slate-400">期待: {arm.topics[0]}</p>
                  {/if}
                </div>
                <span class="shrink-0 text-xs text-slate-500">
                  {arm.enabled ? (arm.connected ? '✅ 接続' : '⚠️ 未接続') : '⏸️ 無効'}
                </span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  </div>
</section>
