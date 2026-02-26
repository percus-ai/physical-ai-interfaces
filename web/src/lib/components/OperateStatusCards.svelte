<script lang="ts">
  type OperateService = {
    status?: string;
    message?: string;
    details?: Record<string, any>;
  };

  type OperateStatusResponse = {
    backend?: OperateService;
    vlabor?: OperateService;
    lerobot?: OperateService;
    network?: OperateService;
    driver?: OperateService;
  };

  let { title = 'ステータス（バックエンド / ROS2 / ネットワーク / ドライバ）', status = null, gpuLabel = '' }: {
    title?: string;
    status?: OperateStatusResponse | null;
    gpuLabel?: string;
  } = $props();

  const renderStatusLabel = (value?: string) => {
    switch (value) {
      case 'running':
      case 'healthy':
        return '正常';
      case 'degraded':
        return '注意';
      case 'stopped':
        return '停止';
      case 'error':
        return 'エラー';
      default:
        return '不明';
    }
  };

  const networkDetails = $derived(status?.network?.details ?? {});
  const driverDetails = $derived(status?.driver?.details ?? {});
</script>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">{title}</h2>
    {#if gpuLabel}
      <span class="chip">GPU: {gpuLabel}</span>
    {/if}
  </div>
  <div class="mt-4 grid gap-4 text-sm text-slate-600 sm:grid-cols-2 lg:grid-cols-5">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Backend</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(status?.backend?.status)}</p>
      <p class="text-xs text-slate-500">{status?.backend?.message ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">VLABOR (ROS2)</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(status?.vlabor?.status)}</p>
      <p class="text-xs text-slate-500">{status?.vlabor?.message ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">LeRobot (ROS2)</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(status?.lerobot?.status)}</p>
      <p class="text-xs text-slate-500">{status?.lerobot?.message ?? '-'}</p>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Network</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(status?.network?.status)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>Zenoh: {networkDetails?.zenoh?.status ?? '-'}</p>
        <p>rosbridge: {networkDetails?.rosbridge?.status ?? '-'}</p>
        <p>ZMQ: {networkDetails?.zmq?.status ?? '-'}</p>
      </div>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Driver (CUDA)</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(status?.driver?.status)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>torch: {driverDetails?.torch_version ?? '-'}</p>
        <p>cuda: {driverDetails?.cuda_available ? 'available' : 'unavailable'}</p>
        <p>gpu: {driverDetails?.gpu_name ?? '-'}</p>
      </div>
    </div>
  </div>
</section>
