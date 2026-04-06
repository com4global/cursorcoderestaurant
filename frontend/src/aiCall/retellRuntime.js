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
  // Retell SDK emits "update" events with transcript as an array of
  // { role: "agent"|"user", content: "..." } objects.  Extract the last
  // entry so the UI always shows the most recent utterance.
  if (Array.isArray(message?.transcript)) {
    const last = message.transcript[message.transcript.length - 1];
    if (last) {
      const rawRole = String(last.role || "").toLowerCase();
      let normalizedRole = "";
      if (rawRole.includes("agent") || rawRole.includes("assistant") || rawRole.includes("bot")) {
        normalizedRole = "assistant";
      } else if (rawRole.includes("user") || rawRole.includes("customer") || rawRole.includes("human")) {
        normalizedRole = "user";
      }
      return {
        type: "transcript",
        status: "",
        role: normalizedRole,
        text: String(last.content || ""),
      };
    }
  }

  const role = pickFirstString([
    message?.role,
    message?.speaker,
    message?.message?.role,
    message?.type === "agent_response" ? "assistant" : "",
    message?.type === "user_transcript" ? "user" : "",
  ]).toLowerCase();

  const text = pickFirstString([
    typeof message?.transcript === "string" ? message.transcript : "",
    message?.text,
    message?.content,
    typeof message?.message === "string" ? message.message : "",
    message?.delta,
    message?.message?.content,
  ]);

  let normalizedRole = "";
  if (role.includes("assistant") || role.includes("agent") || role.includes("bot")) {
    normalizedRole = "assistant";
  } else if (role.includes("user") || role.includes("customer") || role.includes("human")) {
    normalizedRole = "user";
  }

  // Skip events with no useful data (heartbeats, metadata updates)
  if (!normalizedRole && !text) {
    return { type: "", status: "", role: "", text: "" };
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
  if (!accessToken) {
    throw new Error("Retell access token is missing.");
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
    ["message", (message) => { console.log("[RetellRAW] message", JSON.stringify(message).slice(0, 500)); onMessage?.(message); }],
    ["transcript", (message) => { console.log("[RetellRAW] transcript", JSON.stringify(message).slice(0, 500)); onMessage?.(message); }],
    ["update", (message) => { console.log("[RetellRAW] update", JSON.stringify(message).slice(0, 500)); onMessage?.(message); }],
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
        await retell.startCall({ accessToken, ...(agentId ? { agentId } : {}) });
        return;
      }
      if (typeof retell.start === "function") {
        await retell.start({ accessToken, ...(agentId ? { agentId } : {}) });
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
