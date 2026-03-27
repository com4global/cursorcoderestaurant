import Vapi from "@vapi-ai/web";

function pickFirstString(values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

export function parseVapiMessage(message) {
  const role = pickFirstString([
    message?.role,
    message?.speaker,
    message?.message?.role,
    message?.artifact?.role,
  ]).toLowerCase();

  const text = pickFirstString([
    message?.transcript,
    message?.text,
    message?.message,
    message?.message?.content,
    Array.isArray(message?.messages)
      ? message.messages
          .map((entry) => (typeof entry?.content === "string" ? entry.content : ""))
          .filter(Boolean)
          .join("\n")
      : "",
    typeof message?.artifact === "string" ? message.artifact : "",
    message?.artifact?.text,
    message?.artifact?.transcript,
    message?.artifact?.content,
  ]);

  let normalizedRole = "";
  if (role.includes("assistant") || role.includes("bot") || role.includes("agent")) {
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

export function createVapiCallRuntime({
  publicKey,
  assistantId,
  assistant,
  assistantOverrides,
  onCallStart,
  onCallEnd,
  onSpeechStart,
  onSpeechEnd,
  onMessage,
  onError,
  onVolumeLevel,
}) {
  if (!publicKey || (!assistantId && !assistant)) {
    throw new Error("AI Call realtime provider is not configured.");
  }

  const vapi = new Vapi(publicKey);
  const listeners = [
    ["call-start", () => onCallStart?.()],
    ["call-end", () => onCallEnd?.()],
    ["speech-start", () => onSpeechStart?.()],
    ["speech-end", () => onSpeechEnd?.()],
    ["message", (message) => onMessage?.(message)],
    ["error", (error) => onError?.(error)],
    ["volume-level", (level) => onVolumeLevel?.(level)],
  ];

  listeners.forEach(([eventName, handler]) => {
    vapi.on(eventName, handler);
  });

  return {
    async start() {
      if (assistant) {
        await vapi.start(assistant);
        return;
      }
      await vapi.start(assistantId, assistantOverrides);
    },
    async stop() {
      await vapi.stop();
    },
    setMuted(muted) {
      vapi.setMuted(muted);
    },
    isMuted() {
      return vapi.isMuted();
    },
    say(text, endCallAfterSpoken = false) {
      vapi.say(text, endCallAfterSpoken);
    },
    send(message) {
      vapi.send(message);
    },
    dispose() {
      if (typeof vapi.off !== "function") {
        return;
      }
      listeners.forEach(([eventName, handler]) => {
        vapi.off(eventName, handler);
      });
    },
  };
}