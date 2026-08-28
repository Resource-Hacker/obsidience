/** Video-only view of the physical camera selected in Hardware. */

import { useEffect, useRef, useState } from "react";
import { Camera, LoaderCircle, TriangleAlert } from "lucide-react";
import { api, type HardwareInterfaceOption } from "@/lib/api";

function normalizeLabel(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "");
}

function selectedVideoDevice(
  devices: MediaDeviceInfo[],
  selected: HardwareInterfaceOption,
): MediaDeviceInfo | null {
  const cameras = devices.filter((device) => device.kind === "videoinput");
  const expected = normalizeLabel(selected.label);
  const aliases = selected.label.split(":")
    .map(normalizeLabel)
    .filter((alias) => alias.length >= 5);
  const matched = cameras.filter((device) => {
    const actual = normalizeLabel(device.label);
    return actual.length > 0 && expected.length > 0
      && (actual === expected || actual.includes(expected) || expected.includes(actual)
        || aliases.some((alias) => actual.includes(alias) || alias.includes(actual)));
  });
  if (matched.length === 1) return matched[0];
  return cameras.length === 1 ? cameras[0] : null;
}

function boundedCameraError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") return "Camera video permission was denied.";
    if (error.name === "NotFoundError") return "The selected physical camera is unavailable.";
    if (error.name === "NotReadableError") return "The selected camera is already busy or could not be opened.";
  }
  const detail = error instanceof Error ? error.message : String(error);
  return (detail || "The camera video could not be opened.").slice(0, 240);
}

function stopStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

export function CameraPaneBody({ active, activationError }: {
  active: boolean;
  activationError: string | null;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [phase, setPhase] = useState<"waiting" | "starting" | "live" | "error">("waiting");
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("Selected physical camera");

  useEffect(() => {
    if (!active) {
      setPhase(activationError ? "error" : "waiting");
      setError(activationError);
      return;
    }
    let closed = false;
    let stream: MediaStream | null = null;
    let bootstrap: MediaStream | null = null;

    const start = async () => {
      setPhase("starting");
      setError(null);
      try {
        if (!navigator.mediaDevices?.getUserMedia || !navigator.mediaDevices.enumerateDevices) {
          throw new Error("This renderer does not expose local camera capture.");
        }
        const hardware = await api.hardware();
        const cameraSlot = hardware.interfaces.find((item) => item.id === "camera");
        const selected = cameraSlot?.options.find((item) => item.id === cameraSlot.selected);
        if (!cameraSlot || cameraSlot.selected === "none" || !selected?.available) {
          throw new Error("Select an available physical camera in Hardware first.");
        }
        setLabel(selected.label);

        let devices = await navigator.mediaDevices.enumerateDevices();
        let device = selectedVideoDevice(devices, selected);
        if (!device && devices.some((item) => item.kind === "videoinput" && !item.label)) {
          bootstrap = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          if (bootstrap.getAudioTracks().length > 0) {
            throw new Error("The video-only camera request unexpectedly returned audio.");
          }
          stopStream(bootstrap);
          bootstrap = null;
          devices = await navigator.mediaDevices.enumerateDevices();
          device = selectedVideoDevice(devices, selected);
        }
        if (!device) {
          throw new Error("The Hardware camera could not be matched to one browser video device.");
        }
        stream = await navigator.mediaDevices.getUserMedia({
          video: { deviceId: { exact: device.deviceId } },
          audio: false,
        });
        if (stream.getAudioTracks().length > 0) {
          throw new Error("The video-only camera request unexpectedly returned audio.");
        }
        if (closed) {
          stopStream(stream);
          stream = null;
          return;
        }
        const video = videoRef.current;
        if (!video) throw new Error("The camera pane closed before video was ready.");
        video.srcObject = stream;
        await video.play();
        if (!closed) setPhase("live");
      } catch (cause) {
        stopStream(bootstrap);
        stopStream(stream);
        bootstrap = null;
        stream = null;
        if (!closed) {
          setError(boundedCameraError(cause));
          setPhase("error");
        }
      }
    };

    void start();
    return () => {
      closed = true;
      stopStream(bootstrap);
      stopStream(stream);
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [active, activationError]);

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-black font-mono text-cyan-100/80">
      <div className="relative min-h-0 flex-1 bg-black">
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          aria-label={`Live video from ${label}`}
          className={`h-full w-full object-contain transition-opacity ${phase === "live" ? "opacity-100" : "opacity-0"}`}
        />
        {phase !== "live" ? (
          <div className="absolute inset-0 grid place-items-center p-5 text-center">
            <div className="max-w-sm">
              {phase === "error"
                ? <TriangleAlert size={24} className="mx-auto text-rose-300/80" />
                : phase === "starting"
                  ? <LoaderCircle size={24} className="mx-auto animate-spin text-cyan-300/75" />
                  : <Camera size={24} className="mx-auto text-cyan-300/35" />}
              <p className={`mt-3 text-[10px] leading-5 ${phase === "error" ? "text-rose-200/80" : "text-cyan-200/50"}`}>
                {phase === "error" ? error : phase === "starting" ? "Opening video-only camera…" : "Waking physical camera…"}
              </p>
            </div>
          </div>
        ) : null}
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-cyan-300/12 bg-[#020a12] px-3 py-2 text-[8px]">
        <span className="truncate text-cyan-100/62" title={label}>{label}</span>
        <span className={phase === "live" ? "text-emerald-300/70" : "text-cyan-300/35"}>
          {phase === "live" ? "video only · live" : "video only"}
        </span>
      </div>
    </div>
  );
}
