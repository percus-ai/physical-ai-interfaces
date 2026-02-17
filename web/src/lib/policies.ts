export type PolicyInfo = {
  id: string;
  displayName: string;
  skipPretrained?: boolean;
  pretrainedModels?: Array<{
    id: string;
    path: string;
    name: string;
    description?: string;
  }>;
  defaultSteps: number;
  defaultBatchSize: number;
  defaultSaveFreq: number;
  defaultLogFreq: number;
  defaultNumWorkers: number;
  recommendedStorage: number;
  recommendedGpu: string;
  compileModel?: boolean;
  gradientCheckpointing?: boolean;
  dtype?: string;
  useAmp?: boolean;
};

export const POLICY_TYPES: PolicyInfo[] = [
  {
    id: 'act',
    displayName: 'ACT (Action Chunking Transformer)',
    skipPretrained: true,
    defaultSteps: 100000,
    defaultBatchSize: 64,
    defaultSaveFreq: 20000,
    defaultLogFreq: 100,
    defaultNumWorkers: 8,
    recommendedStorage: 100,
    recommendedGpu: 'H100'
  },
  {
    id: 'smolvla',
    displayName: 'SmolVLA (Small VLA)',
    pretrainedModels: [
      {
        id: 'smolvla_base',
        path: 'lerobot/smolvla_base',
        name: 'SmolVLA Base (推奨)',
        description: '標準ベースモデル'
      }
    ],
    defaultSteps: 100000,
    defaultBatchSize: 64,
    defaultSaveFreq: 20000,
    defaultLogFreq: 100,
    defaultNumWorkers: 8,
    recommendedStorage: 100,
    recommendedGpu: 'H100'
  },
  {
    id: 'pi0',
    displayName: 'π0 (Physical Intelligence)',
    pretrainedModels: [
      {
        id: 'pi0_base',
        path: 'lerobot/pi0_base',
        name: 'π0 Base (推奨)',
        description: '標準ベースモデル'
      }
    ],
    defaultSteps: 20000,
    defaultBatchSize: 64,
    defaultSaveFreq: 3000,
    defaultLogFreq: 100,
    defaultNumWorkers: 8,
    recommendedStorage: 200,
    recommendedGpu: 'H100',
    compileModel: false,
    gradientCheckpointing: true,
    dtype: 'bfloat16',
    useAmp: false
  },
  {
    id: 'pi05',
    displayName: 'π0.5 (Open-World VLA Model)',
    pretrainedModels: [
      {
        id: 'pi05_base',
        path: 'lerobot/pi05_base',
        name: 'π0.5 Base (推奨)',
        description: '標準ベースモデル'
      },
      {
        id: 'pi05_libero',
        path: 'lerobot/pi05_libero',
        name: 'π0.5 Libero',
        description: 'Liberoベンチマーク向け'
      }
    ],
    defaultSteps: 20000,
    defaultBatchSize: 64,
    defaultSaveFreq: 3000,
    defaultLogFreq: 100,
    defaultNumWorkers: 8,
    recommendedStorage: 200,
    recommendedGpu: 'H100',
    compileModel: false,
    gradientCheckpointing: true,
    dtype: 'bfloat16',
    useAmp: false
  }
];

export const GPU_MODELS = [
  { name: 'B300', description: '262GB VRAM - Blackwell Ultra (torch nightly必須)', torchNightly: true },
  { name: 'B200', description: '180GB VRAM - Blackwell (torch nightly必須)', torchNightly: true },
  { name: 'H200', description: '141GB VRAM - Hopper 大容量', torchNightly: false },
  { name: 'H100', description: '80GB VRAM - Hopper 標準 (推奨)', torchNightly: false },
  { name: 'A100', description: '80GB VRAM - Ampere コスパ良', torchNightly: false },
  { name: 'L40S', description: '48GB VRAM - Ada Lovelace', torchNightly: false },
  { name: 'RTX6000ADA', description: '48GB VRAM - RTX 6000 Ada', torchNightly: false },
  { name: 'RTXA6000', description: '48GB VRAM - RTX A6000', torchNightly: false }
];

export const GPU_COUNTS = [1, 2, 4, 8];
