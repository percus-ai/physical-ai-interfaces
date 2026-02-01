<script lang="ts">
  import { Button } from 'bits-ui';
  import { get } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';

  type ProfileInstanceResponse = {
    instance?: {
      id: string;
      class_id?: string;
      class_key?: string;
      variables?: Record<string, unknown>;
      updated_at?: string;
    };
  };

  type ProfileClassDetailResponse = {
    profile_class?: {
      id?: string;
      class_key?: string;
      description?: string;
      defaults?: Record<string, unknown>;
      profile?: Record<string, unknown>;
    };
  };

  type ProfileStatusResponse = {
    profile_id?: string;
    profile_class_key?: string;
    cameras?: Array<{ name: string; enabled: boolean; connected: boolean; topics?: string[] }>;
    arms?: Array<{ name: string; enabled: boolean; connected: boolean }>;
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
  };

  const activeInstanceQuery = createQuery<ProfileInstanceResponse>({
    queryKey: ['profiles', 'instances', 'active'],
    queryFn: api.profiles.activeInstance
  });

  $: activeClassId = $activeInstanceQuery.data?.instance?.class_id ?? '';
  $: activeProfileId = $activeInstanceQuery.data?.instance?.id ?? '';
  $: vlaborState = $vlaborStatusQuery.data?.status ?? 'unknown';
  $: vlaborDetail = $vlaborStatusQuery.data?.status_detail ?? $vlaborStatusQuery.data?.running_for ?? '';

  const activeClassQuery = createQuery<ProfileClassDetailResponse>({
    queryKey: ['profiles', 'classes', activeClassId],
    queryFn: async () => {
      if (!activeClassId) return { profile_class: undefined };
      return api.profiles.class(activeClassId);
    }
  });

  const activeStatusQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'instances', 'active', 'status', activeProfileId],
    queryFn: async () => {
      if (!activeProfileId) return { cameras: [], arms: [] };
      return api.profiles.activeStatus();
    },
    refetchInterval: 5000
  });

  let restartPending = false;
  let actionPending = false;
  let actionMessage = '';
  let actionIntent: 'start' | 'stop' | '' = '';

  const vlaborStatusQuery = createQuery<VlaborStatusResponse>({
    queryKey: ['profiles', 'vlabor', 'status'],
    queryFn: api.profiles.vlaborStatus,
    refetchInterval: () => (restartPending || actionPending ? 2000 : false)
  });

  type ProfileSettingsState = {
    flags: Record<string, boolean>;
    orderedKeys: string[];
  };

  let profileSettings: ProfileSettingsState = {
    flags: {},
    orderedKeys: []
  };
  let lastInstanceId = '';
  let savingProfileSettings = false;
  let saveMessage = '';

  const labelMap: Record<string, string> = {
    overhead_camera_enabled: 'オーバーヘッドカメラ',
    d405_enabled: 'D405 サイドカメラ',
    left_arm_enabled: '左アーム',
    right_arm_enabled: '右アーム'
  };

  function labelFor(key: string) {
    if (labelMap[key]) return labelMap[key];
    return key.replace(/_/g, ' ');
  }

  function buildOrderedKeys(keys: string[]) {
    const preferred = ['overhead_camera_enabled', 'd405_enabled', 'left_arm_enabled', 'right_arm_enabled'];
    const rest = keys.filter((k) => !preferred.includes(k)).sort();
    return [...preferred.filter((k) => keys.includes(k)), ...rest];
  }

  $: {
    const instance = $activeInstanceQuery.data?.instance;
    const profileClass = $activeClassQuery.data?.profile_class;
    const defaults = (profileClass?.defaults ?? {}) as Record<string, unknown>;
    if (instance?.id && instance.id !== lastInstanceId) {
      const vars = (instance.variables ?? {}) as Record<string, unknown>;
      const keys = new Set<string>();
      Object.keys(defaults).forEach((k) => {
        if (k.endsWith('_enabled')) keys.add(k);
      });
      Object.keys(vars).forEach((k) => {
        if (k.endsWith('_enabled')) keys.add(k);
      });

      const flags: Record<string, boolean> = {};
      for (const key of keys) {
        const raw = (vars[key] ?? defaults[key]) as unknown;
        flags[key] = Boolean(raw ?? true);
      }

      profileSettings = {
        flags,
        orderedKeys: buildOrderedKeys(Array.from(keys))
      };
      lastInstanceId = instance.id;
      saveMessage = '';
    }
  }

  $: activeProfileTitle = (() => {
    const instance = $activeInstanceQuery.data?.instance;
    const classKey = instance?.class_key ?? $activeClassQuery.data?.profile_class?.class_key ?? '-';
    const instanceName = instance?.id ? instance?.id.slice(0, 6) : '-';
    return `${classKey} / ${instanceName}`;
  })();

  $: {
    const status = $vlaborStatusQuery.data?.status ?? 'unknown';
    if (restartPending && status === 'running') {
      restartPending = false;
      saveMessage = '再起動が完了しました。';
    }
    if (actionPending && (status === 'running' || status === 'stopped')) {
      actionPending = false;
      actionIntent = '';
    }
  }

  $: actionStatusLabel = (() => {
    if (restartPending) return '再起動中…';
    if (actionIntent === 'start') return '起動中…';
    if (actionIntent === 'stop') return '停止中…';
    return '';
  })();

  async function refetchQuery(queryStore: typeof activeInstanceQuery) {
    const snapshot = get(queryStore);
    if (snapshot && typeof snapshot.refetch === 'function') {
      await snapshot.refetch();
    }
  }

  async function saveProfileSettings() {
    const instance = $activeInstanceQuery.data?.instance;
    if (!instance?.id) return;
    savingProfileSettings = true;
    saveMessage = '';
    try {
      const vars = (instance.variables ?? {}) as Record<string, unknown>;
      const updated = {
        ...vars,
        ...profileSettings.flags
      };
      await api.profiles.updateInstance(instance.id, {
        variables: updated,
        activate: true
      });
      restartPending = true;
      saveMessage = '再起動中…';
      await refetchQuery(activeInstanceQuery);
      await refetchQuery(activeStatusQuery);
    } catch (error) {
      console.error(error);
      saveMessage = '更新に失敗しました。';
    } finally {
      savingProfileSettings = false;
    }
  }

  async function startVlabor() {
    actionPending = true;
    actionIntent = 'start';
    actionMessage = '';
    try {
      await api.profiles.vlaborStart();
      await refetchQuery(vlaborStatusQuery);
      await refetchQuery(activeStatusQuery);
    } catch (error) {
      console.error(error);
      const detail = error instanceof Error ? error.message : '起動に失敗しました。';
      actionMessage = `${detail} Docker権限やバックエンドログを確認してください。`;
      actionIntent = '';
    } finally {
      actionPending = false;
      if (!restartPending) {
        actionIntent = '';
      }
    }
  }

  async function stopVlabor() {
    actionPending = true;
    actionIntent = 'stop';
    actionMessage = '';
    try {
      await api.profiles.vlaborStop();
      await refetchQuery(vlaborStatusQuery);
      await refetchQuery(activeStatusQuery);
    } catch (error) {
      console.error(error);
      const detail = error instanceof Error ? error.message : '停止に失敗しました。';
      actionMessage = `${detail} Docker権限やバックエンドログを確認してください。`;
      actionIntent = '';
    } finally {
      actionPending = false;
      if (!restartPending) {
        actionIntent = '';
      }
    }
  }

</script>

<section class="card-strong p-8">
  <p class="section-title">Setup</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">デバイス・プロファイル設定</h1>
      <p class="mt-2 text-sm text-slate-600">プロファイル管理、デバイス検出、キャリブレーションの集中管理。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      {#if vlaborState === 'running'}
        <Button.Root class="btn-ghost" onclick={stopVlabor} disabled={actionPending}>
          停止
        </Button.Root>
      {:else if vlaborState === 'stopped'}
        <Button.Root class="btn-ghost" onclick={startVlabor} disabled={actionPending}>
          起動
        </Button.Root>
      {:else}
        <Button.Root class="btn-ghost" onclick={startVlabor} disabled={actionPending}>
          起動
        </Button.Root>
      {/if}
    </div>
    {#if actionMessage}
      <p class="mt-2 text-xs text-rose-500">{actionMessage}</p>
    {/if}
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <p class="text-xs uppercase tracking-widest text-slate-400">Active Profile</p>
      <h2 class="mt-1 text-2xl font-semibold text-slate-900">{activeProfileTitle}</h2>
      <p class="mt-2 text-sm text-slate-600">
        {$activeClassQuery.data?.profile_class?.description ?? 'プロファイルの説明がありません。'}
      </p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      {#if actionStatusLabel}
        <span class="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-700">{actionStatusLabel}</span>
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
      {#if vlaborState === 'running'}
        <a
          class="inline-flex h-9 items-center justify-center rounded-full border border-emerald-200 bg-emerald-50 px-4 text-xs font-semibold text-emerald-700"
          href="http://vlabor.local:8888"
          target="_blank"
          rel="noreferrer"
        >
          VLabor UI を開く
        </a>
      {/if}
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-900">プロファイル簡易設定</h2>
      <Button.Root class="btn-ghost" onclick={saveProfileSettings} disabled={savingProfileSettings}>
        {savingProfileSettings ? '保存中…' : '保存'}
      </Button.Root>
    </div>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      {#if $activeInstanceQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $activeInstanceQuery.data?.instance}
        {#if profileSettings.orderedKeys.length === 0}
          <p>編集可能なフラグがありません。</p>
        {:else}
          {#each profileSettings.orderedKeys as flagKey}
            <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2">
              <div>
                <p class="font-medium text-slate-800">{labelFor(flagKey)}</p>
                <p class="text-xs text-slate-500">{flagKey}</p>
              </div>
              <input
                type="checkbox"
                bind:checked={profileSettings.flags[flagKey]}
                class="h-5 w-5 accent-slate-900"
              />
            </div>
          {/each}
        {/if}
        {#if saveMessage}
          <p class="text-xs text-slate-500">{saveMessage}</p>
        {/if}
      {:else}
        <p>アクティブなプロファイルがありません。</p>
      {/if}
    </div>
  </div>
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">プロファイル参照の状態</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      {#if $activeStatusQuery.isLoading}
        <p>読み込み中...</p>
      {:else}
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <p class="label">カメラ</p>
          <div class="mt-2 space-y-2">
            {#each $activeStatusQuery.data?.cameras ?? [] as cam}
              <div class="flex items-center justify-between">
                <span>{cam.name}</span>
                <span class="text-xs text-slate-500">
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
              <div class="flex items-center justify-between">
                <span>{arm.name}</span>
                <span class="text-xs text-slate-500">
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
