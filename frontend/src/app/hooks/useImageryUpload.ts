import { useCallback, useState } from "react";
import { getApiBaseEndpoint } from "../config";

export type ImageryMeta = {
  imagery_id: string;
  filename: string;
  crs: string | null;
  bounds: number[] | null;
  width: number;
  height: number;
  band_count: number;
  preview_url?: string | null;
  working_width?: number;
  working_height?: number;
  compressed?: boolean;
  compression_ratio?: number | null;
};

export function useImageryUpload(endpoint: string) {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<ImageryMeta | null>(null);

  const upload = useCallback(
    async (file: File): Promise<ImageryMeta | null> => {
      setUploading(true);
      setProgress(0);
      setError(null);

      const formData = new FormData();
      formData.append("file", file);

      const base = getApiBaseEndpoint(endpoint);
      try {
        const res = await fetch(`${base}/imagery/upload`, {
          method: "POST",
          body: formData,
          credentials: "include",
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `Upload failed: ${res.status}`);
        }

        const meta: ImageryMeta = await res.json();
        setLastUpload(meta);
        setProgress(100);
        return meta;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        return null;
      } finally {
        setUploading(false);
      }
    },
    [endpoint],
  );

  return { upload, uploading, progress, error, lastUpload };
}
