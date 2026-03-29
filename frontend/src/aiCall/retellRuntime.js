import { RetellWebClient } from "retell-client-js-sdk";

function pickFirstString(values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

export function parseRetellMessage(message) {
  const role = pickFirstString([
    message?.role,
    message?.speaker,
    message?.message?.role,
    message?.type === "agent_response" ? "assistant" : "",
    message?.type === "user_transcript" ? "user" : "",
  ]).toLowerCase();

  const text = pickFirstString([
    message?.transcript,
    message?.text,
    message?.content,
    message?.message,
    message?.delta,
    message?.message?.content,
  ]);

  let normalizedRole = "";
  if (role.includes("assistant") || role.includes("agent") || role.includes("bot")) {
    normalizedRole = "assistant";
  } else if (role.includes("user") || role.includes("customer") || role.includes("human")) {
    normalizedRole = "user";
  }

  return {
    type: typeof message?.type === "string" ? message.type : "",
    status: typeof message?.status === "string" ? message.status : "",
    role: normalizedRole,
    text,
  };
}

export function createRetellCallRuntime({
  agentId,
  accessToken,
  metadata,
  onCallStart,
  onCallEnd,
  onSpeechStart,
  onSpeechEnd,
  onMessage,
  onError,
  onVolumeLevel,
}) {
  if (!agentId) {
    throw new Error("Retell agent is not configured.");
  }
  const retell = new RetellWebClient();

  const listeners = [
    ["call_started", () => {
      // Browser autoplay policies require startAudioPlayback after connection
      if (typeof retell.startAudioPlayback === "function") {
        retell.startAudioPlayback().catch(() => {});
      }
      onCallStart?.();
    }],
    ["call_ended", () => onCallEnd?.()],
    ["agent_start_talking", () => onSpeechStart?.()],
    ["agent_stop_talking", () => onSpeechEnd?.()],
    ["message", (message) => onMessage?.(message)],
    ["transcript", (message) => onMessage?.(message)],
    ["update", (message) => onMessage?.(message)],
    ["error", (error) => onError?.(error)],
    ["volume", (level) => onVolumeLevel?.(level)],
  ];

  listeners.forEach(([eventName, handler]) => {
    if (typeof retell.on === "function") {
      retell.on(eventName, handler);
    }
  });

  return {
    async start() {
      if (typeof retell.startCall === "function") {
        await retell.startCall({ accessToken });
        return;
      }
      if (typeof retell.start === "function") {
        await retell.start({ accessToken });
        return;
      }
      throw new Error("Retell runtime does not expose a supported start method.");
    },
    async stop() {
      if (typeof retell.stopCall === "function") {
        await retell.stopCall();
        return;
      }
      if (typeof retell.stop === "function") {
        await retell.stop();
      }
    },
    setMuted(muted) {
      if (muted && typeof retell.mute === "function") {
        retell.mute();
      } else if (!muted && typeof retell.unmute === "function") {
        retell.unmute();
      }
    },
    isMuted() {
      if (typeof retell.isMuted === "function") {
        return Boolean(retell.isMuted());
      }
      return false;
    },
    say(text) {
      if (typeof retell.say === "function") {
        retell.say(text);
      }
    },
    send(message) {
      if (typeof retell.sendMessage === "function") {
        retell.sendMessage(message);
        return;
      }
      if (typeof retell.send === "function") {
        retell.send(message);
        return;
      }
      throw new Error("Retell runtime does not support sendMessage/send.");
    },
    dispose() {
      if (typeof retell.off !== "function") {
        return;
      }
      listeners.forEach(([eventName, handler]) => {
        retell.off(eventName, handler);
      });
    },
  };
}
