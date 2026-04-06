import { createVapiCallRuntime, parseVapiMessage } from "./vapiRuntime.js";
import { createRetellCallRuntime, parseRetellMessage } from "./retellRuntime.js";

export function createRealtimeCallRuntime({
  providerName,
  publicKey,
  assistant,
  assistantId,
  assistantOverrides,
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
  const provider = String(providerName || "vapi").toLowerCase();

  if (provider === "retell") {
    return createRetellCallRuntime({
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
    });
  }

  return createVapiCallRuntime({
    publicKey,
    assistant,
    assistantId,
    assistantOverrides,
    onCallStart,
    onCallEnd,
    onSpeechStart,
    onSpeechEnd,
    onMessage,
    onError,
    onVolumeLevel,
  });
}

export function parseRealtimeProviderMessage(providerName, message) {
  const provider = String(providerName || "vapi").toLowerCase();
  if (provider === "retell") {
    return parseRetellMessage(message);
  }
  return parseVapiMessage(message);
}
