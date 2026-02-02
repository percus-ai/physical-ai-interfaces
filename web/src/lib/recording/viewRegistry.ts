import type { SvelteComponent } from 'svelte';
import CameraView from '$lib/components/recording/views/CameraView.svelte';
import JointStateView from '$lib/components/recording/views/JointStateView.svelte';
import StatusView from '$lib/components/recording/views/StatusView.svelte';
import TopicsView from '$lib/components/recording/views/TopicsView.svelte';
import ControlsView from '$lib/components/recording/views/ControlsView.svelte';
import ProgressView from '$lib/components/recording/views/ProgressView.svelte';
import DevicesView from '$lib/components/recording/views/DevicesView.svelte';
import PlaceholderView from '$lib/components/recording/views/PlaceholderView.svelte';

export type ConfigField = {
  key: string;
  label: string;
  type: 'topic' | 'boolean' | 'number';
  filter?: (topic: string) => boolean;
};

export type ViewTypeDefinition = {
  type: string;
  label: string;
  description?: string;
  component: typeof SvelteComponent;
  fields?: ConfigField[];
  defaultConfig?: (topics: string[]) => Record<string, unknown>;
};

const firstMatch = (topics: string[], filter: (topic: string) => boolean) =>
  topics.find(filter) ?? '';

const cameraFilter = (topic: string) => topic.endsWith('/compressed');
const jointFilter = (topic: string) => topic.includes('joint_states');
const statusFilter = (topic: string) => topic.includes('status') || topic.includes('client');

export const viewRegistry: ViewTypeDefinition[] = [
  {
    type: 'placeholder',
    label: 'Empty',
    component: PlaceholderView
  },
  {
    type: 'camera',
    label: 'Camera',
    description: 'Compressed image preview',
    component: CameraView,
    fields: [
      {
        key: 'topic',
        label: 'Topic',
        type: 'topic',
        filter: cameraFilter
      }
    ],
    defaultConfig: (topics) => ({
      topic: firstMatch(topics, cameraFilter)
    })
  },
  {
    type: 'joint_state',
    label: 'Joint State',
    description: 'Joint state timeseries',
    component: JointStateView,
    fields: [
      {
        key: 'topic',
        label: 'Topic',
        type: 'topic',
        filter: jointFilter
      },
      {
        key: 'showVelocity',
        label: 'Show velocity',
        type: 'boolean'
      },
      {
        key: 'maxPoints',
        label: 'Max points',
        type: 'number'
      }
    ],
    defaultConfig: (topics) => ({
      topic: firstMatch(topics, jointFilter),
      showVelocity: true,
      maxPoints: 160
    })
  },
  {
    type: 'status',
    label: 'Status',
    description: 'Key-value status',
    component: StatusView,
    fields: [
      {
        key: 'topic',
        label: 'Topic',
        type: 'topic',
        filter: statusFilter
      }
    ],
    defaultConfig: (topics) => ({
      topic: firstMatch(topics, (t) => t.includes('lerobot_recorder/status')) || firstMatch(topics, statusFilter)
    })
  },
  {
    type: 'topics',
    label: 'Topics',
    description: 'Topic list',
    component: TopicsView
  },
  {
    type: 'controls',
    label: 'Controls',
    description: 'Recording actions',
    component: ControlsView
  },
  {
    type: 'progress',
    label: 'Progress',
    description: 'Episode progress',
    component: ProgressView
  },
  {
    type: 'devices',
    label: 'Devices',
    description: 'Camera/arm status',
    component: DevicesView
  }
];

export const getViewDefinition = (type: string) => viewRegistry.find((view) => view.type === type);

export const getViewOptions = () => viewRegistry.filter((view) => view.type !== 'placeholder');
