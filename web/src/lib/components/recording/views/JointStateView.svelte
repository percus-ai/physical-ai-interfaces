<script lang="ts">
  import { AxisX, AxisY, GridY, Line, Plot } from 'svelteplot';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  let {
    topic = '',
    title = 'Joint State',
    maxPoints = 160,
    showVelocity = false,
    renderFps = 60
  }: {
    topic?: string;
    title?: string;
    maxPoints?: number;
    showVelocity?: boolean;
    renderFps?: number;
  } = $props();

  type SeriesPoint = { i: number; value: number };
  type RingSeries = {
    name: string;
    color: string;
    buffer: SeriesPoint[];
    nextWrite: number;
    size: number;
  };
  type JointSeries = { name: string; color: string; data: SeriesPoint[] };
  type PendingSample = {
    names: string[];
    positions: number[];
    velocities: number[];
  };

  const palette = [
    '#5b7cfa',
    '#30d5c8',
    '#f48b3a',
    '#8f6fff',
    '#22c55e',
    '#ef4444',
    '#0ea5e9',
    '#f97316'
  ];

  let jointNames = $state<string[]>([]);
  let posSeries = $state<JointSeries[]>([]);
  let velSeries = $state<JointSeries[]>([]);
  let posRing = $state<RingSeries[]>([]);
  let velRing = $state<RingSeries[]>([]);
  let lastRawPositions = $state<number[]>([]);
  let index = $state(0);
  let status = $state('idle');
  let plotWidth = $state(0);
  let posHeight = $state(0);
  let velHeight = $state(0);
  let unsubscribe: (() => void) | null = null;
  let pendingSample: PendingSample | null = null;
  let animationFrameId: number | null = null;
  let lastRenderAt = 0;
  const normalizedRenderFps = $derived(
    Math.min(Math.max(Number(renderFps) || 24, 1), 60)
  );
  const renderIntervalMs = $derived(1000 / normalizedRenderFps);

  const buildRing = (names: string[]): RingSeries[] =>
    names.map((name, idx) => ({
      name,
      color: palette[idx % palette.length],
      buffer: [],
      nextWrite: 0,
      size: 0
    }));

  const appendToRing = (rings: RingSeries[], values: number[], nextIndex: number) => {
    for (let idx = 0; idx < rings.length; idx += 1) {
      const ring = rings[idx];
      const point = { i: nextIndex, value: values[idx] ?? 0 };
      if (ring.size < maxPoints) {
        ring.buffer.push(point);
        ring.size += 1;
        ring.nextWrite = ring.size % maxPoints;
        continue;
      }
      ring.buffer[ring.nextWrite] = point;
      ring.nextWrite = (ring.nextWrite + 1) % maxPoints;
    }
  };

  const materializeSeries = (rings: RingSeries[]): JointSeries[] =>
    rings.map((ring) => {
      if (ring.size < maxPoints) {
        return { name: ring.name, color: ring.color, data: ring.buffer.slice(0, ring.size) };
      }
      return {
        name: ring.name,
        color: ring.color,
        data: [...ring.buffer.slice(ring.nextWrite), ...ring.buffer.slice(0, ring.nextWrite)]
      };
    });

  const scheduleRender = () => {
    if (typeof window === 'undefined') return;
    if (animationFrameId != null) return;
    animationFrameId = window.requestAnimationFrame((timestamp) => {
      animationFrameId = null;
      if (timestamp - lastRenderAt < renderIntervalMs) {
        scheduleRender();
        return;
      }
      lastRenderAt = timestamp;

      if (!pendingSample) return;
      const sample = pendingSample;
      pendingSample = null;

      const needsReset =
        sample.names.length !== jointNames.length ||
        sample.names.some((name, idx) => jointNames[idx] !== name);

      if (needsReset) {
        jointNames = [...sample.names];
        posRing = buildRing(sample.names);
        velRing = buildRing(sample.names);
        index = 0;
      }

      index += 1;
      appendToRing(posRing, sample.positions, index);
      appendToRing(velRing, sample.velocities, index);
      posSeries = materializeSeries(posRing);
      velSeries = materializeSeries(velRing);
    });
  };

  const handleMessage = (msg: Record<string, unknown>) => {
    const positions = (msg.position as number[] | undefined) ?? [];
    const velocities = (msg.velocity as number[] | undefined) ?? [];
    if (!positions.length) return;

    const names =
      (msg.name as string[] | undefined) ??
      positions.map((_, idx) => `joint_${idx + 1}`);

    const resolvedVelocities =
      velocities.length === positions.length
        ? velocities
        : lastRawPositions.length === positions.length
          ? positions.map((value, idx) => value - (lastRawPositions[idx] ?? 0))
          : positions.map(() => 0);

    lastRawPositions = positions;
    pendingSample = {
      names: [...names],
      positions: [...positions],
      velocities: [...resolvedVelocities]
    };
    scheduleRender();
  };

  const subscribe = () => {
    if (!topic) return;
    const client = getRosbridgeClient();
    unsubscribe?.();
    unsubscribe = client.subscribe(topic, handleMessage, {
      type: 'sensor_msgs/JointState',
      throttle_rate: 60
    });
    status = client.getStatus();
  };

  $effect(() => {
    if (!topic) {
      unsubscribe?.();
      unsubscribe = null;
      posSeries = [];
      velSeries = [];
      posRing = [];
      velRing = [];
      jointNames = [];
      index = 0;
      lastRawPositions = [];
      pendingSample = null;
      if (animationFrameId != null && typeof window !== 'undefined') {
        window.cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
      }
      return;
    }
    subscribe();
    return () => {
      unsubscribe?.();
      unsubscribe = null;
      pendingSample = null;
      if (animationFrameId != null && typeof window !== 'undefined') {
        window.cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
      }
    };
  });
</script>

<div class="flex h-full min-w-0 flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{topic || 'no topic'}</span>
  </div>
  <div class="flex min-h-0 flex-1 flex-col rounded-2xl border border-slate-200/60 bg-white/70 p-3">
    {#if posSeries.length}
      <div class="flex flex-wrap gap-2 text-[10px] text-slate-500">
        {#each posSeries as series}
          <span class="flex items-center gap-1">
            <span class="h-2 w-2 rounded-full" style={`background:${series.color}`}></span>
            {series.name}
          </span>
        {/each}
      </div>
      <div class="mt-2 flex min-h-0 flex-1 flex-col gap-3" bind:clientWidth={plotWidth}>
        <div class="flex min-h-0 flex-1 flex-col">
          <div class="text-[10px] uppercase tracking-widest text-slate-400">Position</div>
          <div class="min-h-0 flex-1" bind:clientHeight={posHeight}>
            {#if plotWidth && posHeight}
              <Plot width={plotWidth} height={posHeight} grid>
                <GridY />
                <AxisX tickCount={4} />
                <AxisY tickCount={4} />
                {#each posSeries as series}
                  <Line data={series.data} x="i" y="value" stroke={series.color} strokeWidth={2} />
                {/each}
              </Plot>
            {/if}
          </div>
        </div>
        {#if showVelocity}
          <div class="flex min-h-0 flex-1 flex-col">
            <div class="text-[10px] uppercase tracking-widest text-slate-400">Velocity</div>
            <div class="min-h-0 flex-1" bind:clientHeight={velHeight}>
              {#if plotWidth && velHeight}
                <Plot width={plotWidth} height={velHeight} grid>
                  <GridY />
                  <AxisX tickCount={4} />
                  <AxisY tickCount={4} />
                  {#each velSeries as series}
                    <Line
                      data={series.data}
                      x="i"
                      y="value"
                      stroke={series.color}
                      strokeWidth={1.5}
                      strokeOpacity={0.7}
                    />
                  {/each}
                </Plot>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    {:else}
      <div class="flex h-full min-h-[160px] items-center justify-center text-xs text-slate-400">
        joint_states を待機中… ({status})
      </div>
    {/if}
  </div>
</div>
