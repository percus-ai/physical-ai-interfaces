<script lang="ts">
  import { onDestroy } from 'svelte';
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { AxisX, AxisY, GridY, Line, Plot } from 'svelteplot';
  import { api } from '$lib/api/client';
  import { getBackendUrl } from '$lib/config';

  type RecordingSessionStatusResponse = {
    dataset_id?: string;
    status?: Record<string, unknown>;
  };

  type ProfileStatusResponse = {
    profile_id?: string;
    profile_class_key?: string;
    topics?: string[];
    cameras?: Array<{
      name?: string;
      enabled?: boolean;
      connected?: boolean;
      topics?: string[];
    }>;
    arms?: Array<{
      name?: string;
      enabled?: boolean;
      connected?: boolean;
    }>;
  };

  type JointSnapshot = {
    names: string[];
    position: number[];
    velocity?: number[];
  };

  type SeriesPoint = { i: number; value: number };
  type TopicSeries = {
    index: number;
    pos: SeriesPoint[];
    vel: SeriesPoint[];
    lastPositions?: number[];
  };

  const STATUS_LABELS: Record<string, string> = {
    idle: '待機',
    warming: '準備中',
    recording: '録画中',
    paused: '一時停止',
    resetting: 'リセット中',
    completed: '完了'
  };

  const DATASET_NAME_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

  const pad = (value: number) => String(value).padStart(2, '0');
  const buildDefaultName = () => {
    const now = new Date();
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(
      now.getMinutes()
    )}${pad(now.getSeconds())}`;
  };

  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  let sessionId = '';
  $: sessionId = $page.params.session_id;

  const statusQuery = createQuery<RecordingSessionStatusResponse>(
    derived(page, ($page) => {
      const currentId = $page.params.session_id;
      return {
        queryKey: ['recording', 'session', currentId],
        queryFn: api.recording.sessionStatus,
        enabled: Boolean(currentId),
        refetchInterval: 1500
      };
    })
  );

  const topicsQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'instances', 'active', 'status', 'topics'],
    queryFn: api.profiles.activeStatus,
    refetchInterval: 5000
  });

  let datasetName = buildDefaultName();
  let task = '';
  let episodeCount: number | string = 1;
  let episodeTimeSec: number | string = 60;
  let resetWaitSec: number | string = 10;
  let startBusy = false;
  let startError = '';

  let actionBusy = '';
  let actionError = '';
  let actionMessage = '';

  let previewTopic = '';
  let previewImgSrc = '';
  let previewStatus = 'disconnected';
  let previewError = '';
  let previewSocket: WebSocket | null = null;
  let previewSubscribedTopic = '';
  let lastFrameAt = 0;
  let previewTopics: string[] = [];

  let stateFocusTopic = '';
  let stateTopics: string[] = [];
  let stateChartTopics: string[] = [];
  let stateSubscribedTopics: string[] = [];
  let chartSeries: Array<{ topic: string; pos: SeriesPoint[]; vel: SeriesPoint[] }> = [];
  let stateStatus = 'disconnected';
  let stateError = '';
  let stateSocket: WebSocket | null = null;
  let currentStateTopics: string[] = [];
  let jointSnapshots: Record<string, JointSnapshot> = {};
  let stateSeries: Record<string, TopicSeries> = {};
  let stateLastUpdate = 0;

  let status: Record<string, unknown> = {};
  let datasetId = '';
  let statusState = '';
  let statusLabel = '';
  let statusDetail = '';
  let taskLabel = '';
  let episodeIndex = 0;
  let episodeCountValue = 0;
  let numEpisodes = 0;
  let frameCount = 0;
  let episodeTime = 0;
  let resetTime = 0;
  let progress = 0;
  let canPause = false;
  let canResume = false;
  let canStop = false;
  let canStart = false;
  let canRedo = false;
  let canCancelEpisode = false;
  let focusSnapshot: JointSnapshot | null = null;
  let focusNames: string[] = [];
  let focusPositions: number[] = [];
  let focusVelocities: number[] = [];

  const validateDatasetName = (value: string) => {
    const trimmed = value.trim();
    const errors: string[] = [];
    if (!trimmed) {
      errors.push('データセット名を入力してください。');
      return errors;
    }
    if (trimmed.length > 64) {
      errors.push('データセット名は64文字以内にしてください。');
    }
    if (!DATASET_NAME_PATTERN.test(trimmed)) {
      errors.push('英数字で開始し、英数字・_・- のみ使用できます。');
    }
    const lower = trimmed.toLowerCase();
    if (lower.startsWith('archive') || lower.startsWith('temp') || trimmed.startsWith('_')) {
      errors.push('archive / temp / _ で始まる名前は使えません。');
    }
    if (trimmed.includes('..') || trimmed.includes('/') || trimmed.includes('\\')) {
      errors.push('パス区切りは使えません。');
    }
    return errors;
  };

  const parseNumber = (value: number | string) => {
    if (typeof value === 'number') return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : NaN;
  };

  const refreshStatus = async () => {
    await $statusQuery?.refetch?.();
  };

  const runAction = async (label: string, action: () => Promise<unknown>) => {
    actionError = '';
    actionMessage = '';
    actionBusy = label;
    try {
      const result = (await action()) as { message?: string };
      actionMessage = result?.message ?? `${label} を実行しました。`;
    } catch (err) {
      actionError = err instanceof Error ? err.message : `${label} に失敗しました。`;
    } finally {
      actionBusy = '';
      await refreshStatus();
    }
  };

  const handleStart = async () => {
    startError = '';
    const nameErrors = validateDatasetName(datasetName);
    if (nameErrors.length) {
      startError = nameErrors[0];
      return;
    }
    if (!task.trim()) {
      startError = 'タスク説明を入力してください。';
      return;
    }

    const episodes = Math.floor(parseNumber(episodeCount));
    const episodeTime = parseNumber(episodeTimeSec);
    const resetWait = parseNumber(resetWaitSec);
    if (!Number.isFinite(episodes) || episodes < 1) {
      startError = 'エピソード総数は1以上の数値にしてください。';
      return;
    }
    if (!Number.isFinite(episodeTime) || episodeTime <= 0) {
      startError = 'エピソード秒数は0より大きい数値にしてください。';
      return;
    }
    if (!Number.isFinite(resetWait) || resetWait < 0) {
      startError = 'リセット待機秒数は0以上の数値にしてください。';
      return;
    }

    startBusy = true;
    try {
      const payload = {
        dataset_name: datasetName.trim(),
        task: task.trim(),
        num_episodes: episodes,
        episode_time_s: episodeTime,
        reset_time_s: resetWait
      };
      const result = (await api.recording.startSession(payload)) as {
        dataset_id?: string;
      };
      if (!result?.dataset_id) {
        throw new Error('録画セッションの開始に失敗しました。');
      }
      await goto(`/record/sessions/${result.dataset_id}`);
    } catch (err) {
      startError = err instanceof Error ? err.message : '録画セッションの開始に失敗しました。';
    } finally {
      startBusy = false;
    }
  };

  const handlePause = async () => runAction('中断', () => api.recording.pauseSession());
  const handleResume = async () => runAction('再開', () => api.recording.resumeSession());
  const handleStop = async () => {
    if (!confirm('録画セッションを終了しますか？（現在のエピソードは保存されます）')) return;
    await runAction('終了', () =>
      api.recording.stopSession({
        dataset_id: datasetId,
        save_current: true
      })
    );
  };
  const handleCancelSession = async () => {
    if (!confirm('録画セッションを破棄しますか？（現在のエピソードは保存されません）')) return;
    await runAction('破棄', () => api.recording.cancelSession(datasetId));
  };
  const handleRedoEpisode = async () => {
    if (!confirm('1つ前のエピソードに戻しますか？')) return;
    await runAction('前エピソードへ戻る', () => api.recording.redoEpisode());
  };
  const handleCancelEpisode = async () => {
    if (!confirm('現在のエピソードを破棄しますか？')) return;
    await runAction('エピソード破棄', () => api.recording.cancelEpisode());
  };

  function buildRosbridgeUrl() {
    if (typeof window === 'undefined') return '';
    const backendUrl = getBackendUrl();
    try {
      const parsed = new URL(backendUrl);
      const protocol = parsed.protocol === 'https:' ? 'wss' : 'ws';
      const host = parsed.hostname || window.location.hostname || 'localhost';
      return `${protocol}://${host}:9090`;
    } catch {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const host = window.location.hostname || 'localhost';
      return `${protocol}://${host}:9090`;
    }
  }

  function closePreviewSocket() {
    if (!previewSocket) return;
    try {
      if (previewSubscribedTopic) {
        previewSocket.send(JSON.stringify({ op: 'unsubscribe', topic: previewSubscribedTopic }));
      }
    } catch {
      // ignore
    }
    previewSocket.close();
    previewSocket = null;
    previewSubscribedTopic = '';
    previewStatus = 'disconnected';
  }

  function subscribePreviewTopic(topic: string) {
    if (!previewSocket || previewSocket.readyState !== WebSocket.OPEN) return;
    if (previewSubscribedTopic && previewSubscribedTopic !== topic) {
      previewSocket.send(JSON.stringify({ op: 'unsubscribe', topic: previewSubscribedTopic }));
    }
    previewSocket.send(
      JSON.stringify({
        op: 'subscribe',
        topic,
        type: 'sensor_msgs/CompressedImage',
        queue_length: 1,
        throttle_rate: 100
      })
    );
    previewSubscribedTopic = topic;
  }

  function connectPreviewSocket() {
    const url = buildRosbridgeUrl();
    if (!url) return;
    if (previewSocket && previewSocket.readyState !== WebSocket.CLOSED) return;
    previewStatus = 'connecting';
    previewError = '';

    const ws = new WebSocket(url);
    previewSocket = ws;

    ws.onopen = () => {
      previewStatus = 'connected';
      if (previewTopic) {
        subscribePreviewTopic(previewTopic);
      }
    };

    ws.onerror = () => {
      previewStatus = 'error';
      previewError = 'rosbridge に接続できません。';
    };

    ws.onclose = () => {
      previewStatus = 'disconnected';
    };

    ws.onmessage = (event) => {
      if (!event?.data) return;
      let payload: Record<string, unknown> | null = null;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!payload || payload.op !== 'publish') return;
      if (payload.topic !== previewSubscribedTopic) return;
      const msg = payload.msg as { data?: string; format?: string } | undefined;
      if (!msg?.data) return;
      const now = Date.now();
      if (now - lastFrameAt < 100) return;
      lastFrameAt = now;
      const format = (msg.format ?? 'jpeg').toLowerCase();
      const mime = format.includes('png') ? 'image/png' : 'image/jpeg';
      previewImgSrc = `data:${mime};base64,${msg.data}`;
    };
  }

  function closeStateSocket() {
    if (!stateSocket) return;
    try {
      for (const topic of currentStateTopics) {
        stateSocket.send(JSON.stringify({ op: 'unsubscribe', topic }));
      }
    } catch {
      // ignore
    }
    stateSocket.close();
    stateSocket = null;
    currentStateTopics = [];
    stateStatus = 'disconnected';
  }

  function updateStateSubscriptions(topics: string[]) {
    if (!stateSocket || stateSocket.readyState !== WebSocket.OPEN) return;
    const next = topics.filter(Boolean);
    const nextSet = new Set(next);
    for (const topic of currentStateTopics) {
      if (!nextSet.has(topic)) {
        stateSocket.send(JSON.stringify({ op: 'unsubscribe', topic }));
      }
    }
    for (const topic of next) {
      if (!currentStateTopics.includes(topic)) {
        stateSocket.send(JSON.stringify({ op: 'subscribe', topic, type: 'sensor_msgs/JointState', throttle_rate: 50 }));
      }
    }
    currentStateTopics = next;
  }

  function connectStateSocket() {
    const url = buildRosbridgeUrl();
    if (!url) return;
    if (stateSocket && stateSocket.readyState !== WebSocket.CLOSED) return;
    stateStatus = 'connecting';
    stateError = '';

    const ws = new WebSocket(url);
    stateSocket = ws;

    ws.onopen = () => {
      stateStatus = 'connected';
      updateStateSubscriptions(stateSubscribedTopics);
    };

    ws.onerror = () => {
      stateStatus = 'error';
      stateError = 'joint_states の取得に失敗しました。';
    };

    ws.onclose = () => {
      stateStatus = 'disconnected';
    };

    ws.onmessage = (event) => {
      if (!event?.data) return;
      let payload: Record<string, unknown> | null = null;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!payload || payload.op !== 'publish') return;
      const topic = payload.topic as string | undefined;
      if (!topic) return;
      const msg = payload.msg as { name?: string[]; position?: number[]; velocity?: number[] } | undefined;
      if (!msg?.position) return;

      const positions = msg.position ?? [];
      const velocities = msg.velocity ?? [];
      const posMean = positions.length
        ? positions.reduce((sum, v) => sum + Math.abs(v), 0) / positions.length
        : 0;
      let velMean = 0;
      if (velocities.length) {
        velMean = velocities.reduce((sum, v) => sum + Math.abs(v), 0) / velocities.length;
      }

      const prevSeries = stateSeries[topic] ?? { index: 0, pos: [], vel: [] };
      let inferredVel = velMean;
      if (!velocities.length && prevSeries.lastPositions && prevSeries.lastPositions.length === positions.length) {
        inferredVel =
          positions.reduce((sum, v, idx) => sum + Math.abs(v - (prevSeries.lastPositions?.[idx] ?? 0)), 0) /
          positions.length;
      }

      const nextIndex = (prevSeries.index ?? 0) + 1;
      const nextPos = [...prevSeries.pos, { i: nextIndex, value: posMean }].slice(-120);
      const nextVel = [...prevSeries.vel, { i: nextIndex, value: inferredVel }].slice(-120);

      stateSeries = {
        ...stateSeries,
        [topic]: {
          index: nextIndex,
          pos: nextPos,
          vel: nextVel,
          lastPositions: positions
        }
      };
      jointSnapshots = {
        ...jointSnapshots,
        [topic]: {
          names: msg.name ?? positions.map((_, idx) => `joint_${idx + 1}`),
          position: positions,
          velocity: velocities
        }
      };
      stateLastUpdate = Date.now();
    };
  }

  $: previewTopics = ($topicsQuery.data?.topics ?? []).filter((t) => t.endsWith('/compressed'));
  $: if (previewTopics.length > 0 && (!previewTopic || !previewTopics.includes(previewTopic))) {
    previewTopic = previewTopics[0];
  }

  $: stateTopics = ($topicsQuery.data?.topics ?? []).filter((t) => t.endsWith('/joint_states'));
  $: if (stateTopics.length > 0 && (!stateFocusTopic || !stateTopics.includes(stateFocusTopic))) {
    stateFocusTopic = stateTopics[0];
  }
  $: stateChartTopics = stateTopics.slice(0, 2);
  $: stateSubscribedTopics = Array.from(new Set([...stateChartTopics, stateFocusTopic].filter(Boolean)));
  $: chartSeries = stateChartTopics.map((topic) => ({
    topic,
    pos: stateSeries[topic]?.pos ?? [],
    vel: stateSeries[topic]?.vel ?? []
  }));

  $: if (previewTopic && typeof window !== 'undefined') {
    if (!previewSocket || previewSocket.readyState === WebSocket.CLOSED) {
      connectPreviewSocket();
    } else if (previewSocket.readyState === WebSocket.OPEN) {
      subscribePreviewTopic(previewTopic);
    }
  }

  $: if (!previewTopic && previewSocket) {
    closePreviewSocket();
  }

  $: if (stateSubscribedTopics.length > 0 && typeof window !== 'undefined') {
    if (!stateSocket || stateSocket.readyState === WebSocket.CLOSED) {
      connectStateSocket();
    } else if (stateSocket.readyState === WebSocket.OPEN) {
      updateStateSubscriptions(stateSubscribedTopics);
    }
  }

  $: if (!stateSubscribedTopics.length && stateSocket) {
    closeStateSocket();
  }

  onDestroy(() => {
    closePreviewSocket();
    closeStateSocket();
  });

  $: status = $statusQuery.data?.status ?? {};
  $: datasetId = $statusQuery.data?.dataset_id ?? sessionId;
  $: statusState =
    (status as Record<string, unknown>)?.state ?? (status as Record<string, unknown>)?.status ?? '';
  $: statusLabel = STATUS_LABELS[String(statusState)] ?? String(statusState || 'unknown');
  $: statusDetail =
    (status as Record<string, unknown>)?.message ??
    (status as Record<string, unknown>)?.detail ??
    (status as Record<string, unknown>)?.error ??
    (status as Record<string, unknown>)?.last_error ??
    '';
  $: taskLabel = (status as Record<string, unknown>)?.task ?? '';

  $: episodeIndex = asNumber((status as Record<string, unknown>)?.episode_index ?? 0, 0);
  $: episodeCountValue = asNumber((status as Record<string, unknown>)?.episode_count ?? 0, 0);
  $: numEpisodes = asNumber((status as Record<string, unknown>)?.num_episodes ?? 0, 0);
  $: frameCount = asNumber((status as Record<string, unknown>)?.frame_count ?? 0, 0);
  $: episodeTime = asNumber((status as Record<string, unknown>)?.episode_time_s ?? 0, 0);
  $: resetTime = asNumber((status as Record<string, unknown>)?.reset_time_s ?? 0, 0);
  $: progress = numEpisodes > 0 ? Math.min(episodeCountValue / numEpisodes, 1) : 0;

  $: canPause = statusState === 'recording';
  $: canResume = statusState === 'paused';
  $: canStop = ['recording', 'paused', 'resetting', 'warming'].includes(String(statusState));
  $: canStart = ['idle', 'completed'].includes(String(statusState));
  $: canRedo = Boolean(statusState) && !['recording', 'paused'].includes(String(statusState));
  $: canCancelEpisode = statusState === 'recording';

  $: focusSnapshot = stateFocusTopic ? jointSnapshots[stateFocusTopic] : null;
  $: focusNames = focusSnapshot?.names ?? [];
  $: focusPositions = focusSnapshot?.position ?? [];
  $: focusVelocities = focusSnapshot?.velocity ?? [];
</script>

<section class="card-strong p-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="section-title">Record Session</p>
      <h1 class="text-3xl font-semibold text-slate-900">録画セッション</h1>
      <p class="mt-2 text-sm text-slate-600">
        {taskLabel || 'タスク未設定 / 状態を同期中...'}
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span class="chip">状態: {statusLabel}</span>
        {#if datasetId}
          <span class="chip">Dataset: {datasetId}</span>
        {/if}
        {#if numEpisodes}
          <span class="chip">エピソード {episodeCountValue}/{numEpisodes}</span>
        {/if}
      </div>
      {#if $statusQuery.isLoading}
        <p class="mt-2 text-xs text-slate-500">ステータス取得中...</p>
      {:else if $statusQuery.error}
        <p class="mt-2 text-xs text-rose-600">ステータス取得に失敗しました。</p>
      {/if}
    </div>
    <div class="flex flex-wrap gap-3">
      <Button.Root class="btn-ghost" href="/record">録画一覧</Button.Root>
      <Button.Root class="btn-ghost" href="/record/new">新規セッション</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={refreshStatus}>更新</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
  <div class="space-y-6 min-w-0">
    <section class="card p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="label">Preview</p>
          <h2 class="text-lg font-semibold text-slate-900">カメラ映像プレビュー</h2>
        </div>
        <span class="chip">{previewStatus}</span>
      </div>
      {#if previewError}
        <p class="mt-2 text-xs text-rose-500">{previewError}</p>
      {/if}
      <div class="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <label class="text-xs text-slate-500">トピック</label>
        <select
          class="h-9 min-w-[260px] rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-700"
          bind:value={previewTopic}
        >
          {#if previewTopics.length === 0}
            <option value="">/compressed トピックなし</option>
          {:else}
            {#each previewTopics as topic}
              <option value={topic}>{topic}</option>
            {/each}
          {/if}
        </select>
      </div>
      <div class="mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-slate-950/5">
        {#if previewImgSrc}
          <img src={previewImgSrc} alt="camera preview" class="block w-full object-contain" />
        {:else}
          <div class="flex h-64 items-center justify-center text-xs text-slate-400">
            映像を待機中…
          </div>
        {/if}
      </div>
      <div class="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
        {#each $topicsQuery.data?.cameras ?? [] as cam}
          <span class={`chip ${cam.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
            {cam.name ?? 'camera'}: {cam.connected ? '接続' : '未接続'}
          </span>
        {/each}
      </div>
    </section>

    <section class="card p-5">
      <div class="flex items-center justify-between">
        <div>
          <p class="label">ROS2</p>
          <h2 class="text-lg font-semibold text-slate-900">Topics モニター</h2>
        </div>
        <span class="text-xs text-slate-400">{($topicsQuery.data?.topics ?? []).length} 件</span>
      </div>
      <div class="mt-4 max-h-64 space-y-1 overflow-auto text-xs text-slate-500">
        {#if $topicsQuery.isLoading}
          <p>読み込み中...</p>
        {:else if $topicsQuery.error}
          <p>取得に失敗しました。</p>
        {:else if ($topicsQuery.data?.topics ?? []).length === 0}
          <p>トピックがありません。</p>
        {:else}
          {#each $topicsQuery.data?.topics ?? [] as topic}
            <div class="flex items-center gap-2">
              <span class="h-1.5 w-1.5 rounded-full bg-slate-300"></span>
              <span class="truncate">{topic}</span>
            </div>
          {/each}
        {/if}
      </div>
    </section>
  </div>

  <div class="space-y-6 min-w-0">
    <section class="card p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="label">Control</p>
          <h2 class="text-lg font-semibold text-slate-900">録画操作</h2>
        </div>
        <span class="chip">{statusLabel}</span>
      </div>

      {#if actionError}
        <p class="mt-3 text-sm text-rose-600">{actionError}</p>
      {/if}
      {#if actionMessage}
        <p class="mt-3 text-sm text-emerald-600">{actionMessage}</p>
      {/if}

      <div class="mt-4 grid gap-3 text-sm">
        <div class="grid gap-3 sm:grid-cols-2">
          <Button.Root
            class="btn-primary"
            type="button"
            onclick={handleResume}
            disabled={!canResume || Boolean(actionBusy)}
          >
            {actionBusy === '再開' ? '再開中...' : '再開'}
          </Button.Root>
          <Button.Root
            class="btn-ghost"
            type="button"
            onclick={handlePause}
            disabled={!canPause || Boolean(actionBusy)}
          >
            {actionBusy === '中断' ? '中断中...' : '中断'}
          </Button.Root>
          <Button.Root
            class="btn-primary"
            type="button"
            onclick={handleStop}
            disabled={!canStop || Boolean(actionBusy)}
          >
            {actionBusy === '終了' ? '終了中...' : '終了'}
          </Button.Root>
          <Button.Root
            class="btn-ghost"
            type="button"
            onclick={handleCancelSession}
            disabled={!canStop || Boolean(actionBusy)}
          >
            保存せず終了
          </Button.Root>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <Button.Root
            class="btn-ghost"
            type="button"
            onclick={handleRedoEpisode}
            disabled={!canRedo || Boolean(actionBusy)}
          >
            1個前に戻る
          </Button.Root>
          <Button.Root
            class="btn-ghost"
            type="button"
            onclick={handleCancelEpisode}
            disabled={!canCancelEpisode || Boolean(actionBusy)}
          >
            エピソード破棄
          </Button.Root>
        </div>
      </div>

      {#if canStart}
        <div class="mt-5 rounded-2xl border border-slate-200/70 bg-white/70 p-4">
          <p class="label">新規開始</p>
          <form class="mt-3 grid gap-3" on:submit|preventDefault={handleStart}>
            <label class="text-sm font-semibold text-slate-700">
              <span class="text-xs text-slate-500">データセット名</span>
              <input class="input mt-2" type="text" bind:value={datasetName} required />
            </label>
            <label class="text-sm font-semibold text-slate-700">
              <span class="text-xs text-slate-500">タスク説明</span>
              <textarea class="input mt-2 min-h-[80px]" bind:value={task} required></textarea>
            </label>
            <div class="grid gap-3 sm:grid-cols-3">
              <label class="text-sm font-semibold text-slate-700">
                <span class="text-xs text-slate-500">エピソード数</span>
                <input class="input mt-2" type="number" min="1" step="1" bind:value={episodeCount} required />
              </label>
              <label class="text-sm font-semibold text-slate-700">
                <span class="text-xs text-slate-500">秒数</span>
                <input class="input mt-2" type="number" min="1" step="1" bind:value={episodeTimeSec} required />
              </label>
              <label class="text-sm font-semibold text-slate-700">
                <span class="text-xs text-slate-500">リセット</span>
                <input class="input mt-2" type="number" min="0" step="0.5" bind:value={resetWaitSec} required />
              </label>
            </div>
            {#if startError}
              <p class="text-sm text-rose-600">{startError}</p>
            {/if}
            <Button.Root class="btn-primary" type="submit" disabled={startBusy} aria-busy={startBusy}>
              {startBusy ? '開始中...' : '録画を開始'}
            </Button.Root>
          </form>
        </div>
      {/if}
    </section>

    <section class="card p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="label">Robot</p>
          <h2 class="text-lg font-semibold text-slate-900">ロボット状態</h2>
        </div>
        <span class="chip">{stateStatus}</span>
      </div>
      {#if stateError}
        <p class="mt-2 text-xs text-rose-500">{stateError}</p>
      {/if}

      {#if chartSeries.length}
        <div class="mt-4 space-y-4 text-sm text-slate-600">
          {#each chartSeries as series}
            <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
              <div class="flex items-center justify-between text-xs text-slate-500">
                <span class="font-semibold text-slate-700">{series.topic}</span>
                <span>pos / vel</span>
              </div>
              <div class="mt-2">
                <Plot height={160} grid>
                  <GridY />
                  <AxisX tickCount={4} />
                  <AxisY tickCount={4} />
                  {#if series.pos.length}
                    <Line data={series.pos} x="i" y="value" stroke="#5b7cfa" strokeWidth={2} />
                  {/if}
                  {#if series.vel.length}
                    <Line data={series.vel} x="i" y="value" stroke="#30d5c8" strokeWidth={2} />
                  {/if}
                </Plot>
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <p class="mt-3 text-sm text-slate-500">joint_states トピックがありません。</p>
      {/if}

      {#if stateTopics.length}
        <div class="mt-4 text-xs text-slate-500">
          <label class="text-xs">詳細トピック</label>
          <select
            class="mt-2 h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-700"
            bind:value={stateFocusTopic}
          >
            {#each stateTopics as topic}
              <option value={topic}>{topic}</option>
            {/each}
          </select>
        </div>
      {/if}

      {#if focusNames.length}
        <div class="mt-4 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
          {#each focusNames.slice(0, 8) as name, idx}
            <div class="flex items-center justify-between rounded-lg border border-slate-200/60 bg-white/70 px-3 py-2">
              <span class="truncate">{name}</span>
              <span class="text-slate-800">
                {focusPositions[idx] !== undefined ? focusPositions[idx].toFixed(2) : '-'}
                {focusVelocities[idx] !== undefined ? ` / ${focusVelocities[idx].toFixed(2)}` : ''}
              </span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="mt-3 text-xs text-slate-500">関節データを待機中...</p>
      {/if}

      <p class="mt-3 text-xs text-slate-400">最終更新: {stateLastUpdate ? new Date(stateLastUpdate).toLocaleTimeString() : '-'}</p>
    </section>

    <section class="card p-5">
      <div class="flex items-center justify-between">
        <div>
          <p class="label">Progress</p>
          <h2 class="text-lg font-semibold text-slate-900">エピソード進行</h2>
        </div>
        <span class="text-xs text-slate-400">{Math.round(progress * 100)}%</span>
      </div>
      <div class="mt-4">
        <div class="flex items-center justify-between text-xs text-slate-500">
          <span>Episode {numEpisodes ? Math.max(episodeIndex, 0) + 1 : '-'}</span>
          <span>{numEpisodes ? `${episodeCountValue}/${numEpisodes}` : '-'}</span>
        </div>
        <div class="mt-2 h-2 w-full rounded-full bg-slate-100">
          <div
            class="h-2 rounded-full bg-brand transition"
            style={`width: ${Math.min(progress * 100, 100)}%`}
          ></div>
        </div>
      </div>
      <div class="mt-4 grid gap-3 text-sm text-slate-600 sm:grid-cols-2">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
          <p class="label">frame</p>
          <p class="mt-2 text-base font-semibold text-slate-800">{frameCount}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
          <p class="label">episode time</p>
          <p class="mt-2 text-base font-semibold text-slate-800">{episodeTime || '-'}s</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
          <p class="label">reset</p>
          <p class="mt-2 text-base font-semibold text-slate-800">{resetTime || '-'}s</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
          <p class="label">state</p>
          <p class="mt-2 text-base font-semibold text-slate-800">{statusLabel}</p>
        </div>
      </div>
      {#if statusDetail}
        <p class="mt-3 text-xs text-slate-500">{statusDetail}</p>
      {/if}
    </section>

    <section class="card p-5">
      <div class="flex items-center justify-between">
        <div>
          <p class="label">Devices</p>
          <h2 class="text-lg font-semibold text-slate-900">デバイス状態</h2>
        </div>
        <span class="text-xs text-slate-400">{($topicsQuery.data?.arms ?? []).length} arms</span>
      </div>
      <div class="mt-4 space-y-3 text-sm text-slate-600">
        {#if ($topicsQuery.data?.arms ?? []).length === 0 && ($topicsQuery.data?.cameras ?? []).length === 0}
          <p class="text-sm text-slate-500">デバイス情報を取得中です。</p>
        {:else}
          <div class="grid gap-2">
            {#each $topicsQuery.data?.arms ?? [] as arm}
              <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-3 py-2">
                <span class="font-semibold text-slate-700">{arm.name ?? 'arm'}</span>
                <span class={`chip ${arm.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                  {arm.connected ? '接続' : '未接続'}
                </span>
              </div>
            {/each}
          </div>
          <div class="grid gap-2">
            {#each $topicsQuery.data?.cameras ?? [] as cam}
              <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-3 py-2">
                <span class="font-semibold text-slate-700">{cam.name ?? 'camera'}</span>
                <span class={`chip ${cam.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                  {cam.connected ? '接続' : '未接続'}
                </span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </section>
  </div>
</section>
