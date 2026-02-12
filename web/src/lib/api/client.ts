import { getBackendUrl } from '$lib/config';

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

let refreshPromise: Promise<boolean> | null = null;

async function baseFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const baseUrl = getBackendUrl();
  return fetch(`${baseUrl}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      ...options.headers
    }
  });
}

async function parseApiError(response: Response): Promise<string> {
  let detail = `API error: ${response.status}`;
  try {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/json')) {
      const payload = await response.json();
      if (payload?.detail) {
        detail = String(payload.detail);
      }
    } else {
      const text = await response.text();
      if (text) detail = text;
    }
  } catch {
    // ignore parsing errors
  }
  return detail;
}

async function fetchJsonNoRefresh<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await baseFetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseApiError(response));
  }

  return response.json();
}

async function fetchTextNoRefresh(path: string, options: RequestInit = {}): Promise<string> {
  const response = await baseFetch(path, options);
  if (!response.ok) {
    throw new ApiError(response.status, await parseApiError(response));
  }
  return response.text();
}

async function fetchFormNoRefresh<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  const response = await baseFetch(path, {
    ...options,
    method: options.method ?? 'POST',
    body: formData
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseApiError(response));
  }

  return response.json();
}

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        await fetchJsonNoRefresh('/api/auth/refresh', { method: 'POST' });
        return true;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

async function withAuthRetry<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refreshSession();
      if (refreshed) {
        return await fn();
      }
    }
    throw err;
  }
}

export async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  return withAuthRetry(() => fetchJsonNoRefresh<T>(path, options));
}

export async function fetchText(path: string, options: RequestInit = {}): Promise<string> {
  return withAuthRetry(() => fetchTextNoRefresh(path, options));
}

export async function fetchForm<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  return withAuthRetry(() => fetchFormNoRefresh<T>(path, formData, options));
}

export const api = {
  health: () => fetchApi<{ status: string }>('/health'),
  auth: {
    status: () =>
      fetchApi<{
        authenticated: boolean;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/status'),
    token: () =>
      fetchApi<{
        access_token: string;
        refresh_token?: string;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/token'),
    refresh: () =>
      fetchJsonNoRefresh<{
        authenticated: boolean;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/refresh', { method: 'POST' }),
    login: (email: string, password: string) =>
      fetchApi<{
        success: boolean;
        user_id: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password })
      }),
    logout: () =>
      fetchApi<{
        authenticated: boolean;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/logout', { method: 'POST' })
  },
  analytics: {
    overview: () => fetchApi('/api/analytics/overview'),
    profiles: () => fetchApi('/api/analytics/profiles'),
    training: () => fetchApi('/api/analytics/training'),
    storage: () => fetchApi('/api/analytics/storage')
  },
  system: {
    health: () => fetchApi('/api/system/health'),
    resources: () => fetchApi('/api/system/resources'),
    logs: () => fetchApi('/api/system/logs'),
    info: () => fetchApi('/api/system/info'),
    gpu: () => fetchApi('/api/system/gpu')
  },
  config: {
    get: () => fetchApi('/api/config')
  },
  user: {
    config: () => fetchApi('/api/user/config'),
    devices: () => fetchApi('/api/user/devices')
  },
  hardware: {
    status: () => fetchApi('/api/hardware'),
    cameras: () => fetchApi('/api/hardware/cameras'),
    serialPorts: () => fetchApi('/api/hardware/serial-ports')
  },
  webuiBlueprints: {
    list: () => fetchApi('/api/webui/blueprints'),
    create: (payload: { name: string; blueprint: Record<string, unknown> }) =>
      fetchApi('/api/webui/blueprints', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    get: (blueprintId: string) => fetchApi(`/api/webui/blueprints/${encodeURIComponent(blueprintId)}`),
    update: (
      blueprintId: string,
      payload: { name?: string; blueprint?: Record<string, unknown> }
    ) =>
      fetchApi(`/api/webui/blueprints/${encodeURIComponent(blueprintId)}`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    delete: (blueprintId: string) =>
      fetchApi(`/api/webui/blueprints/${encodeURIComponent(blueprintId)}`, {
        method: 'DELETE'
      }),
    resolveSession: (payload: { session_kind: 'recording' | 'teleop' | 'inference'; session_id: string }) =>
      fetchApi('/api/webui/blueprints/session/resolve', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    bindSession: (payload: {
      session_kind: 'recording' | 'teleop' | 'inference';
      session_id: string;
      blueprint_id: string;
    }) =>
      fetchApi('/api/webui/blueprints/session/binding', {
        method: 'PUT',
        body: JSON.stringify(payload)
      })
  },
  profiles: {
    classes: () => fetchApi('/api/profiles/classes'),
    class: (classId: string) => fetchApi(`/api/profiles/classes/${classId}`),
    createClass: (payload: Record<string, unknown>) =>
      fetchApi('/api/profiles/classes', { method: 'POST', body: JSON.stringify(payload) }),
    updateClass: (classId: string, payload: Record<string, unknown>) =>
      fetchApi(`/api/profiles/classes/${classId}`, { method: 'PUT', body: JSON.stringify(payload) }),
    deleteClass: (classId: string) =>
      fetchApi(`/api/profiles/classes/${classId}`, { method: 'DELETE' }),
    instances: () => fetchApi('/api/profiles/instances'),
    activeInstance: () => fetchApi('/api/profiles/instances/active'),
    activeStatus: () => fetchApi('/api/profiles/instances/active/status'),
    vlaborStatus: () => fetchApi('/api/profiles/vlabor/status'),
    vlaborStart: () => fetchApi('/api/profiles/vlabor/start', { method: 'POST' }),
    vlaborStop: () => fetchApi('/api/profiles/vlabor/stop', { method: 'POST' }),
    createInstance: (payload: Record<string, unknown>) =>
      fetchApi('/api/profiles/instances', { method: 'POST', body: JSON.stringify(payload) }),
    updateInstance: (instanceId: string, payload: Record<string, unknown>) =>
      fetchApi(`/api/profiles/instances/${instanceId}`, { method: 'PUT', body: JSON.stringify(payload) })
  },
  teleop: {
    createSession: (payload: {
      profile?: string;
      domain_id?: number;
      dev_mode?: boolean;
    } = {}) =>
      fetchApi('/api/teleop/session/create', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    startSession: (payload: { session_id: string }) =>
      fetchApi('/api/teleop/session/start', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    stopSession: (payload: { session_id?: string } = {}) =>
      fetchApi('/api/teleop/session/stop', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    sessionStatus: () => fetchApi('/api/teleop/session/status')
  },
  recording: {
    list: () => fetchApi('/api/recording/recordings'),
    createSession: (payload: {
      dataset_name: string;
      task: string;
      num_episodes: number;
      episode_time_s: number;
      reset_time_s: number;
    }) =>
      fetchApi('/api/recording/session/create', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    startSession: (payload: { dataset_id: string }) =>
      fetchApi('/api/recording/session/start', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    stopSession: (payload: {
      dataset_id?: string | null;
      save_current?: boolean;
    }) =>
      fetchApi('/api/recording/session/stop', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    pauseSession: () =>
      fetchApi('/api/recording/session/pause', {
        method: 'POST'
      }),
    resumeSession: () =>
      fetchApi('/api/recording/session/resume', {
        method: 'POST'
      }),
    redoEpisode: () =>
      fetchApi('/api/recording/episode/redo', {
        method: 'POST'
      }),
    redoPreviousEpisode: () =>
      fetchApi('/api/recording/episode/redo-previous', {
        method: 'POST'
      }),
    cancelEpisode: () =>
      fetchApi('/api/recording/episode/cancel', {
        method: 'POST'
      }),
    cancelSession: (datasetId?: string) =>
      fetchApi(`/api/recording/session/cancel${datasetId ? `?dataset_id=${datasetId}` : ''}`, {
        method: 'POST'
      }),
    sessionStatus: (sessionId: string) =>
      fetchApi(`/api/recording/sessions/${sessionId}/status`)
  },
  storage: {
    datasets: (profileInstanceId?: string) =>
      fetchApi(`/api/storage/datasets${profileInstanceId ? `?profile_instance_id=${profileInstanceId}` : ''}`),
    models: () => fetchApi('/api/storage/models'),
    dataset: (datasetId: string) => fetchApi(`/api/storage/datasets/${datasetId}`),
    model: (modelId: string) => fetchApi(`/api/storage/models/${modelId}`),
    usage: () => fetchApi('/api/storage/usage'),
    archive: () => fetchApi('/api/storage/archive'),
    mergeDatasets: (payload: { dataset_name: string; source_dataset_ids: string[] }) =>
      fetchApi('/api/storage/datasets/merge', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    archiveDataset: (datasetId: string) =>
      fetchApi(`/api/storage/datasets/${datasetId}`, { method: 'DELETE' }),
    restoreDataset: (datasetId: string) =>
      fetchApi(`/api/storage/datasets/${datasetId}/restore`, { method: 'POST' }),
    archiveModel: (modelId: string) =>
      fetchApi(`/api/storage/models/${modelId}`, { method: 'DELETE' }),
    restoreModel: (modelId: string) =>
      fetchApi(`/api/storage/models/${modelId}/restore`, { method: 'POST' }),
    restoreArchive: (payload: { dataset_ids: string[]; model_ids: string[] }) =>
      fetchApi('/api/storage/archive/restore', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    deleteArchive: (payload: { dataset_ids: string[]; model_ids: string[] }) =>
      fetchApi('/api/storage/archive/delete', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    deleteArchivedDataset: (datasetId: string) =>
      fetchApi(`/api/storage/archive/datasets/${datasetId}`, { method: 'DELETE' }),
    deleteArchivedModel: (modelId: string) =>
      fetchApi(`/api/storage/archive/models/${modelId}`, { method: 'DELETE' })
  },
  experiments: {
    list: (params: { model_id?: string; profile_instance_id?: string; limit?: number; offset?: number } = {}) => {
      const query = new URLSearchParams();
      if (params.model_id) query.set('model_id', params.model_id);
      if (params.profile_instance_id) query.set('profile_instance_id', params.profile_instance_id);
      if (typeof params.limit === 'number') query.set('limit', String(params.limit));
      if (typeof params.offset === 'number') query.set('offset', String(params.offset));
      const queryString = query.toString();
      return fetchApi(`/api/experiments${queryString ? `?${queryString}` : ''}`);
    },
    get: (experimentId: string) => fetchApi(`/api/experiments/${experimentId}`),
    create: (payload: Record<string, unknown>) =>
      fetchApi('/api/experiments', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    update: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi(`/api/experiments/${experimentId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      }),
    delete: (experimentId: string) =>
      fetchApi(`/api/experiments/${experimentId}`, { method: 'DELETE' }),
    evaluations: (experimentId: string) =>
      fetchApi(`/api/experiments/${experimentId}/evaluations`),
    replaceEvaluations: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi(`/api/experiments/${experimentId}/evaluations`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    evaluationSummary: (experimentId: string) =>
      fetchApi(`/api/experiments/${experimentId}/evaluation_summary`),
    analyses: (experimentId: string) =>
      fetchApi(`/api/experiments/${experimentId}/analyses`),
    replaceAnalyses: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi(`/api/experiments/${experimentId}/analyses`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    mediaUrls: (keys: string[]) =>
      fetchApi('/api/experiments/media-urls', {
        method: 'POST',
        body: JSON.stringify({ keys })
      }),
    upload: (
      experimentId: string,
      formData: FormData,
      params: { scope: 'experiment' | 'evaluation' | 'analysis'; trial_index?: number; block_index?: number }
    ) => {
      const query = new URLSearchParams({ scope: params.scope });
      if (params.trial_index) query.set('trial_index', String(params.trial_index));
      if (params.block_index) query.set('block_index', String(params.block_index));
      return fetchForm(`/api/experiments/${experimentId}/uploads?${query.toString()}`, formData);
    }
  },
  training: {
    jobs: () => fetchApi('/api/training/jobs'),
    job: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}`),
    createJob: (data: Record<string, unknown>) =>
      fetchApi('/api/training/jobs', {
        method: 'POST',
        body: JSON.stringify(data)
      }),
    stopJob: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}/stop`, { method: 'POST' }),
    deleteJob: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}`, { method: 'DELETE' }),
    logs: (jobId: string, logType: string, lines: number = 30) =>
      fetchApi(`/api/training/jobs/${jobId}/logs?log_type=${logType}&lines=${lines}`),
    downloadLogs: (jobId: string, logType: string) =>
      fetchText(`/api/training/jobs/${jobId}/logs/download?log_type=${logType}`),
    metrics: (jobId: string, limit: number = 2000) =>
      fetchApi(`/api/training/jobs/${jobId}/metrics?limit=${limit}`),
    progress: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}/progress`),
    gpuAvailability: () => fetchApi('/api/training/gpu-availability')
  },
  operate: {
    status: () => fetchApi('/api/operate/status')
  },
  inference: {
    models: () => fetchApi('/api/inference/models'),
    deviceCompatibility: () => fetchApi('/api/inference/device-compatibility'),
    runnerStatus: () => fetchApi('/api/inference/runner/status'),
    runnerStart: (payload: Record<string, unknown>) =>
      fetchApi('/api/inference/runner/start', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    runnerStop: (payload: Record<string, unknown>) =>
      fetchApi('/api/inference/runner/stop', {
        method: 'POST',
        body: JSON.stringify(payload)
      })
  }
};
