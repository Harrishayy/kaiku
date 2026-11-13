'use client';

import { EXPRESSION_BLENDSHAPES, expressivityIndex } from './metrics.ts';

/**
 * Webcam facial expressivity, fully in the browser (D11).
 * MediaPipe FaceLandmarker is loaded lazily from a pinned CDN URL only when the person opts in, so it
 * adds nothing to other routes. Frames are read from the <video> element in memory, turned into
 * blendshape scores, and discarded; no image is ever stored, drawn to a canvas we keep, or sent.
 * If anything fails (no camera, permission denied, CDN unreachable) the session continues without it.
 */

const MP_VERSION = '0.10.35';
const MP_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`;
const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
const SAMPLE_MS = 150;

interface Category {
  categoryName: string;
  score: number;
}
interface FaceLandmarkerLike {
  detectForVideo(video: HTMLVideoElement, ts: number): { faceBlendshapes?: { categories: Category[] }[] };
  close(): void;
}
interface VisionModule {
  FilesetResolver: { forVisionTasks(base: string): Promise<unknown> };
  FaceLandmarker: {
    createFromOptions(fileset: unknown, opts: Record<string, unknown>): Promise<FaceLandmarkerLike>;
  };
}

export interface ExpressivitySession {
  stream: MediaStream;
  /** stop sampling, release the camera; resolves to the index (0..1) or null if not enough frames */
  stop: () => Promise<number | null>;
}

async function loadLandmarker(timeoutMs = 20_000): Promise<FaceLandmarkerLike> {
  const timeout = new Promise<never>((_, rej) => setTimeout(() => rej(new Error('model load timed out')), timeoutMs));
  const work = (async () => {
    const mod = (await import(/* webpackIgnore: true */ `${MP_BASE}/vision_bundle.mjs`)) as VisionModule;
    const fileset = await mod.FilesetResolver.forVisionTasks(`${MP_BASE}/wasm`);
    return mod.FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate: 'GPU' },
      runningMode: 'VIDEO',
      numFaces: 1,
      outputFaceBlendshapes: true,
    });
  })();
  return Promise.race([work, timeout]);
}

/** Ask for the camera, attach it to `video`, sample blendshapes until stop(). Throws if the camera is unavailable. */
export async function startExpressivity(video: HTMLVideoElement): Promise<ExpressivitySession> {
  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240, facingMode: 'user' }, audio: false });
  video.srcObject = stream;
  video.muted = true;
  await video.play().catch(() => undefined);

  const frames: number[][] = [];
  let landmarker: FaceLandmarkerLike | null = null;
  let stopped = false;
  let timer: ReturnType<typeof setInterval> | undefined;

  const ready = loadLandmarker()
    .then((lm) => {
      if (stopped) {
        lm.close();
        return;
      }
      landmarker = lm;
      timer = setInterval(() => {
        if (!landmarker || video.readyState < 2) return;
        try {
          const res = landmarker.detectForVideo(video, performance.now());
          const cats = res.faceBlendshapes?.[0]?.categories;
          if (!cats) return;
          const byName = new Map(cats.map((c) => [c.categoryName, c.score]));
          frames.push(EXPRESSION_BLENDSHAPES.map((n) => byName.get(n) ?? 0));
        } catch {
          /* skip a bad frame */
        }
      }, SAMPLE_MS);
    })
    .catch(() => {
      /* model unavailable: we'll report null */
    });

  return {
    stream,
    stop: async () => {
      stopped = true;
      if (timer) clearInterval(timer);
      stream.getTracks().forEach((t) => t.stop());
      video.srcObject = null;
      await Promise.race([ready, new Promise((r) => setTimeout(r, 50))]);
      const lm = landmarker as FaceLandmarkerLike | null;
      lm?.close();
      landmarker = null;
      return expressivityIndex(frames);
    },
  };
}
