export type GpuAvailabilityItem = {
  gpu_model: string;
  gpu_count: number;
  instance_type: string;
  spot_available?: boolean;
  ondemand_available?: boolean;
  spot_locations?: string[];
  ondemand_locations?: string[];
  spot_price_per_hour?: number | null;
};

export type GpuAvailabilityResponse = {
  available?: GpuAvailabilityItem[];
};
