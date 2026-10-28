// Voice input: record with the browser's microphone, transcribe on the local
// server, and hand the text back. The caller puts it in the message box; it is
// never sent on its own.

import { useCallback, useRef, useState } from "react";

import { token } from "./api";

export type VoiceState = "idle" | "recording" | "transcribing";

export interface Voice {
  state: VoiceState;
  supported: boolean;
  toggle: () => void;
}

export function useVoice(onText: (text: string) => void, onError: (message: string) => void): Voice {
  const [state, setState] = useState<VoiceState>("idle");
  const recorder = useRef<MediaRecorder | null>(null);
  const supported = typeof navigator !== "undefined" && !!navigator.mediaDevices && typeof MediaRecorder !== "undefined";

  const upload = useCallback(
    async (audio: Blob) => {
      setState("transcribing");
      try {
        const response = await fetch("/api/transcribe", {
          method: "POST",
          headers: { "X-M3allema-Token": token, "Content-Type": audio.type || "audio/webm" },
          body: audio,
        });
        const body = (await response.json()) as { text?: string; detail?: string };
        if (!response.ok) throw new Error(body.detail ?? `transcription failed (${response.status})`);
        if (body.text) onText(body.text);
        else onError("I didn't catch anything. Try again a little closer to the microphone.");
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setState("idle");
      }
    },
    [onText, onError],
  );

  const start = useCallback(async () => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      onError("Microphone access was blocked. Allow it in the browser to use voice input.");
      return;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (event) => chunks.push(event.data);
    rec.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      void upload(new Blob(chunks, { type: rec.mimeType }));
    };
    recorder.current = rec;
    rec.start();
    setState("recording");
  }, [onError, upload]);

  const toggle = useCallback(() => {
    if (state === "recording") recorder.current?.stop();
    else if (state === "idle") void start();
  }, [state, start]);

  return { state, supported, toggle };
}
