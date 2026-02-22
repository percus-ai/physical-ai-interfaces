import { getBackendUrl } from '$lib/config';

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

export type ExperimentDetail = {
  id: string;
  model_id: string;
  profile_instance_id?: string | null;
  name?: string | null;
  purpose?: string | null;
  evaluation_count?: number;
  metric?: string;
  metric_options?: string[] | null;
  result_image_files?: string[] | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type ExperimentListResponse = {
  experiments?: ExperimentDetail[];
  total?: number;
};

export type ExperimentEvaluation = {
  id?: string;
  experiment_id?: string;
  trial_index: number;
  value?: string;
  image_files?: string[] | null;
  notes?: string | null;
  created_at?: string;
};

export type ExperimentEvaluationListResponse = {
  evaluations?: ExperimentEvaluation[];
  total?: number;
};

export type ExperimentAnalysis = {
  id?: string;
  experiment_id?: string;
  block_index?: number;
  name?: string | null;
  purpose?: string | null;
  notes?: string | null;
  image_files?: string[] | null;
  created_at?: string;
  updated_at?: string;
};

export type ExperimentAnalysisListResponse = {
  analyses?: ExperimentAnalysis[];
  total?: number;
};

export type ExperimentEvaluationSummary = {
  total?: number;
  counts?: Record<string, number>;
  rates?: Record<string, number>;
};

export type ExperimentMediaUrlResponse = {
  urls?: Record<string, string>;
};

export type ExperimentUploadResponse = {
  keys?: string[];
};

export type StartupOperationAcceptedResponse = {
  operation_id: string;
  message?: string;
};

export type StartupOperationStatusResponse = {
  operation_id: string;
  kind: 'inference_start' | 'recording_create';
  state: 'queued' | 'running' | 'completed' | 'failed';
  phase?: string;
  progress_percent?: number;
  message?: string | null;
  target_session_id?: string | null;
  error?: string | null;
  detail?: {
    files_done?: number;
    total_files?: number;
    transferred_bytes?: number;
    total_bytes?: number;
    current_file?: string | null;
  };
  updated_at?: string | null;
};

export type InferenceRunnerStartPayload = {
  model_id: string;
  device?: string;
  task?: string;
  policy_options?: {
    pi0?: {
      denoising_steps?: number;
    };
    pi05?: {
      denoising_steps?: number;
    };
  };
};

export type DatasetPlaybackCameraInfo = {
  key: string;
  label: string;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  codec?: string | null;
  pix_fmt?: string | null;
};

export type DatasetPlaybackResponse = {
  dataset_id: string;
  is_local: boolean;
  total_episodes: number;
  fps: number;
  use_videos: boolean;
  cameras: DatasetPlaybackCameraInfo[];
};

export type TrainingReviveResult = {
  job_id: string;
  old_instance_id: string;
  volume_id: string;
  instance_id: string;
  instance_type: string;
  ip: string;
  ssh_user: string;
  ssh_private_key: string;
  location: string;
  message: string;
};

export type TrainingReviveProgressMessage = {
  type?: string;
  message?: string;
  error?: string;
  elapsed?: number;
  timeout?: number;
  result?: TrainingReviveResult;
};

export type RemoteCheckpointListResponse = {
  job_id: string;
  checkpoint_names: string[];
  checkpoint_root: string;
};

export type RemoteCheckpointUploadResult = {
  job_id: string;
  checkpoint_name: string;
  step: number;
  r2_step_path: string;
  model_id: string;
  db_registered: boolean;
  message: string;
};

export type RemoteCheckpointUploadProgressMessage = {
  type?: string;
  message?: string;
  error?: string;
  checkpoint_name?: string;
  step?: number;
  model_id?: string;
  result?: RemoteCheckpointUploadResult;
};

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
    list: () => fetchApi('/api/profiles'),
    active: () => fetchApi('/api/profiles/active'),
    setActive: (payload: { profile_name: string }) =>
      fetchApi('/api/profiles/active', { method: 'PUT', body: JSON.stringify(payload) }),
    activeStatus: () => fetchApi('/api/profiles/active/status'),
    vlaborStatus: () => fetchApi('/api/profiles/vlabor/status'),
    restartVlabor: () => fetchApi('/api/profiles/vlabor/restart', { method: 'POST' })
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
      profile?: string;
      num_episodes: number;
      episode_time_s: number;
      reset_time_s: number;
    }) =>
      fetchApi<StartupOperationAcceptedResponse>('/api/recording/session/create', {
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
    nextEpisode: () =>
      fetchApi('/api/recording/episode/next', {
        method: 'POST'
      }),
    cancelSession: (datasetId?: string) =>
      fetchApi(`/api/recording/session/cancel${datasetId ? `?dataset_id=${datasetId}` : ''}`, {
        method: 'POST'
      }),
    sessionStatus: (sessionId: string) =>
      fetchApi(`/api/recording/sessions/${sessionId}/status`),
    sessionUploadStatus: (sessionId: string) =>
      fetchApi(`/api/recording/sessions/${sessionId}/upload-status`)
  },
  storage: {
    datasets: (profileName?: string) =>
      fetchApi(`/api/storage/datasets${profileName ? `?profile_name=${profileName}` : ''}`),
    models: (profileName?: string) =>
      fetchApi(`/api/storage/models${profileName ? `?profile_name=${profileName}` : ''}`),
    dataset: (datasetId: string) => fetchApi(`/api/storage/datasets/${datasetId}`),
    datasetPlayback: (datasetId: string) =>
      fetchApi<DatasetPlaybackResponse>(`/api/storage/datasets/${datasetId}/playback`),
    datasetPlaybackVideoUrl: (datasetId: string, videoKey: string, episodeIndex: number) =>
      `${getBackendUrl()}/api/storage/datasets/${encodeURIComponent(datasetId)}/playback/${encodeURIComponent(videoKey)}/${episodeIndex}`,
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
    reuploadDataset: (datasetId: string) =>
      fetchApi(`/api/storage/datasets/${datasetId}/reupload`, { method: 'POST' }),
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
      return fetchApi<ExperimentListResponse>(`/api/experiments${queryString ? `?${queryString}` : ''}`);
    },
    get: (experimentId: string) => fetchApi<ExperimentDetail>(`/api/experiments/${experimentId}`),
    create: (payload: Record<string, unknown>) =>
      fetchApi<ExperimentDetail>('/api/experiments', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    update: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi<ExperimentDetail>(`/api/experiments/${experimentId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      }),
    delete: (experimentId: string) =>
      fetchApi<{ deleted: boolean }>(`/api/experiments/${experimentId}`, { method: 'DELETE' }),
    evaluations: (experimentId: string) =>
      fetchApi<ExperimentEvaluationListResponse>(`/api/experiments/${experimentId}/evaluations`),
    replaceEvaluations: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi<{ updated: boolean; count: number }>(`/api/experiments/${experimentId}/evaluations`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    evaluationSummary: (experimentId: string) =>
      fetchApi<ExperimentEvaluationSummary>(`/api/experiments/${experimentId}/evaluation_summary`),
    analyses: (experimentId: string) =>
      fetchApi<ExperimentAnalysisListResponse>(`/api/experiments/${experimentId}/analyses`),
    replaceAnalyses: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi<{ updated: boolean; count: number }>(`/api/experiments/${experimentId}/analyses`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    mediaUrls: (keys: string[]) =>
      fetchApi<ExperimentMediaUrlResponse>('/api/experiments/media-urls', {
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
      return fetchForm<ExperimentUploadResponse>(
        `/api/experiments/${experimentId}/uploads?${query.toString()}`,
        formData
      );
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
    remoteCheckpoints: (jobId: string) =>
      fetchApi<RemoteCheckpointListResponse>(`/api/training/jobs/${jobId}/checkpoints/remote`),
    uploadCheckpointWs: (
      jobId: string,
      checkpointName: string,
      progressCallback?: (message: RemoteCheckpointUploadProgressMessage) => void
    ): Promise<RemoteCheckpointUploadResult> =>
      new Promise((resolve, reject) => {
        const ws = new WebSocket(
          `${getBackendUrl().replace(/^http/, 'ws')}/api/training/ws/jobs/${encodeURIComponent(jobId)}/checkpoints/upload`
        );
        let settled = false;
        let requestSent = false;

        const fail = (message: string) => {
          if (settled) return;
          settled = true;
          reject(new Error(message));
        };

        ws.onopen = () => {
          try {
            ws.send(JSON.stringify({ checkpoint_name: checkpointName }));
            requestSent = true;
          } catch {
            ws.close();
            fail('チェックポイントアップロード要求の送信に失敗しました。');
          }
        };

        ws.onmessage = (event) => {
          let payload: RemoteCheckpointUploadProgressMessage;
          try {
            payload = JSON.parse(event.data as string) as RemoteCheckpointUploadProgressMessage;
          } catch {
            ws.close();
            fail('チェックポイントアップロード応答の解析に失敗しました。');
            return;
          }

          if (progressCallback) {
            progressCallback(payload);
          }

          if (payload.type === 'complete') {
            const result = payload.result;
            ws.close();
            if (!result) {
              fail('チェックポイントアップロード結果が取得できませんでした。');
              return;
            }
            settled = true;
            resolve(result);
            return;
          }

          if (payload.type === 'error') {
            ws.close();
            fail(payload.error || payload.message || 'チェックポイントアップロードに失敗しました。');
          }
        };

        ws.onerror = () => {
          ws.close();
          fail('チェックポイントアップロードWebSocket接続に失敗しました。');
        };

        ws.onclose = () => {
          if (!settled && requestSent) {
            fail('チェックポイントアップロードストリームが切断されました。');
          }
        };
      }),
    reviveJobWs: (
      jobId: string,
      progressCallback?: (message: TrainingReviveProgressMessage) => void
    ): Promise<TrainingReviveResult> =>
      new Promise((resolve, reject) => {
        const ws = new WebSocket(
          `${getBackendUrl().replace(/^http/, 'ws')}/api/training/ws/jobs/${encodeURIComponent(jobId)}/revive`
        );
        let settled = false;

        const fail = (message: string) => {
          if (settled) return;
          settled = true;
          reject(new Error(message));
        };

        ws.onmessage = (event) => {
          let payload: TrainingReviveProgressMessage;
          try {
            payload = JSON.parse(event.data as string) as TrainingReviveProgressMessage;
          } catch {
            ws.close();
            fail('インスタンス蘇生レスポンスの解析に失敗しました。');
            return;
          }

          if (progressCallback) {
            progressCallback(payload);
          }

          if (payload.type === 'complete') {
            const result = payload.result;
            ws.close();
            if (!result) {
              fail('インスタンス蘇生結果が取得できませんでした。');
              return;
            }
            settled = true;
            resolve(result);
            return;
          }

          if (payload.type === 'error') {
            ws.close();
            fail(payload.error || payload.message || 'インスタンス蘇生に失敗しました。');
          }
        };

        ws.onerror = () => {
          ws.close();
          fail('インスタンス蘇生WebSocket接続に失敗しました。');
        };

        ws.onclose = () => {
          if (!settled) {
            fail('インスタンス蘇生ストリームが切断されました。');
          }
        };
      }),
    gpuAvailability: () => fetchApi('/api/training/gpu-availability')
  },
  operate: {
    status: () => fetchApi('/api/operate/status')
  },
  startup: {
    operation: (operationId: string) =>
      fetchApi<StartupOperationStatusResponse>(`/api/startup/operations/${encodeURIComponent(operationId)}`)
  },
  inference: {
    models: () => fetchApi('/api/inference/models'),
    deviceCompatibility: () => fetchApi('/api/inference/device-compatibility'),
    runnerStatus: () => fetchApi('/api/inference/runner/status'),
    runnerStart: (payload: InferenceRunnerStartPayload) =>
      fetchApi<StartupOperationAcceptedResponse>('/api/inference/runner/start', {
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
