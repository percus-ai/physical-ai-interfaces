import { getBackendUrl } from '$lib/config';

export async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getBackendUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

export async function fetchText(path: string, options: RequestInit = {}): Promise<string> {
  const baseUrl = getBackendUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      ...options.headers
    }
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.text();
}

export async function fetchForm<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  const baseUrl = getBackendUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    method: options.method ?? 'POST',
    credentials: 'include',
    body: formData,
    headers: {
      ...options.headers
    }
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
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
    projects: () => fetchApi('/api/analytics/projects'),
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
    get: () => fetchApi('/api/config'),
    environments: () => fetchApi('/api/config/environments')
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
  projects: {
    list: () => fetchApi<{ projects: string[]; total: number }>('/api/projects'),
    get: (id: string) => fetchApi(`/api/projects/${id}`)
  },
  recording: {
    list: () => fetchApi('/api/recording/recordings')
  },
  storage: {
    environments: () => fetchApi('/api/storage/environments'),
    environment: (environmentId: string) => fetchApi(`/api/storage/environments/${environmentId}`),
    datasets: (projectId?: string) =>
      fetchApi(`/api/storage/datasets${projectId ? `?project_id=${projectId}` : ''}`),
    models: () => fetchApi('/api/storage/models'),
    dataset: (datasetId: string) => fetchApi(`/api/storage/datasets/${datasetId}`),
    model: (modelId: string) => fetchApi(`/api/storage/models/${modelId}`),
    usage: () => fetchApi('/api/storage/usage'),
    archive: () => fetchApi('/api/storage/archive'),
    mergeDatasets: (payload: {
      project_id: string;
      dataset_name: string;
      source_dataset_ids: string[];
    }) =>
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
    list: (params: { model_id?: string; environment_id?: string; limit?: number; offset?: number } = {}) => {
      const query = new URLSearchParams();
      if (params.model_id) query.set('model_id', params.model_id);
      if (params.environment_id) query.set('environment_id', params.environment_id);
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
    upload: (
      experimentId: string,
      formData: FormData,
      params: { scope: 'experiment' | 'evaluation'; trial_index?: number }
    ) => {
      const query = new URLSearchParams({ scope: params.scope });
      if (params.trial_index) query.set('trial_index', String(params.trial_index));
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
  teleop: {
    sessions: () => fetchApi('/api/teleop/local/sessions')
  },
  inference: {
    models: () => fetchApi('/api/inference/models'),
    sessions: () => fetchApi('/api/inference/sessions')
  }
};
