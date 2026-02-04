export type ScanStatus = "PENDING" | "ALPR" | "MLPR";

export type StatsResponse = {
  total_scanned: number;
  alpr_count: number;
  mlpr_count: number;
  pending_count: number;
  accuracy_percent: number;
  accuracy_verified_percent: number;
};

export type ScanLogItem = {
  id: number;
  original_image_path: string;
  cropped_plate_image_path: string;
  detected_text: string | null;
  detected_province: string | null;
  confidence_score: number;
  status: ScanStatus;
  created_at: string;
};

export type RecognizeResponse = {
  log_id: number;
  license_text: string;
  province: string;
  confidence: number;
  status: ScanStatus;
  master_id?: number | null;
  original_image_path: string;
  cropped_plate_image_path: string;
  debug?: any;
};

export type VerifyRequest = {
  corrected_license: string;
  corrected_province: string;
  is_correct: boolean;
};
