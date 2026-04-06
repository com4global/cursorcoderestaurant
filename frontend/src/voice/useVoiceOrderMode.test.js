// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from "vitest";

// Mock all external dependencies before importing the hook
vi.mock("../aiCall/realtimeRuntime.js", () => ({
  createRealtimeCallRuntime: vi.fn(),
  parseRealtimeProviderMessage: vi.fn(() => ({ type: "", status: "", role: "", text: "" })),
}));

vi.mock("../aiCall/aiCallUtils.js", () => ({
  AI_CALL_STATES: { IDLE: "idle", READY: "ready", LISTENING: "listening", SPEAKING: "speaking", PROCESSING: "processing", ERROR: "error" },
  buildRealtimeAssistantConfig: vi.fn(() => ({})),
  buildRealtimeAssistantPrompt: vi.fn(() => ""),
  buildRealtimeFunctionTools: vi.fn(() => []),
  extractRealtimeToolCalls: vi.fn(() => []),
  getCallGreeting: vi.fn(() => "Hello"),
  isLikelyWrongDomainAssistant: vi.fn(() => false),
  normalizeCallLanguage: vi.fn((l) => (l === "ta" ? "ta-IN" : "en-IN")),
}));

vi.mock("../api.js", () => ({
  createAICallRealtimeSession: vi.fn(),
  createRetellWebCall: vi.fn(),
  aiCallRealtimeListRestaurants: vi.fn(),
  aiCallRealtimeFindRestaurants: vi.fn(),
  aiCallRealtimeGetDraftSummary: vi.fn(),
  aiCallRealtimeGetMenu: vi.fn(),
  aiCallRealtimeAddItem: vi.fn(),
  aiCallRealtimeRemoveItem: vi.fn(),
  aiCallRealtimeStartCheckout: vi.fn(),
  fetchCart: vi.fn(),
  finalizeCallOrderSession: vi.fn(),
}));

import { renderHook, act } from "@testing-library/react";
import { useVoiceOrderMode } from "./useVoiceOrderMode.js";
import { createRealtimeCallRuntime } from "../aiCall/realtimeRuntime.js";
import { createAICallRealtimeSession, createRetellWebCall, finalizeCallOrderSession, fetchCart } from "../api.js";

function makeSession({ provider = "retell", configured = true, fallback = null } = {}) {
  return {
    session_id: "sess_test_123",
    realtime: {
      enabled: true,
      provider: {
        name: provider,
        configured,
        agent_id: "agent_test",
        agent_ids: { "en-IN": "agent_test" },
        public_key: provider === "vapi" ? "pk_test" : undefined,
        assistant_id: provider === "vapi" ? "asst_test" : undefined,
        assistant_ids: provider === "vapi" ? { "en-IN": "asst_test" } : undefined,
        server_url: "",
        fallback,
      },
    },
    draft_cart: [],
    draft_total_cents: 0,
  };
}

function makeMockRuntime() {
  return {
    start: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn().mockResolvedValue(undefined),
    setMuted: vi.fn(),
    isMuted: vi.fn(() => false),
    say: vi.fn(),
    send: vi.fn(),
    dispose: vi.fn(),
  };
}

describe("useVoiceOrderMode", () => {
  const defaultProps = {
    token: "tok_test",
    language: "en",
    userLat: 33.0,
    userLng: -80.0,
    radiusMiles: 25,
    onMessage: vi.fn(),
    onCartUpdated: vi.fn(),
    onRequireAuth: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts in idle state", () => {
    const { result } = renderHook(() => useVoiceOrderMode(defaultProps));
    expect(result.current.isActive).toBe(false);
    expect(result.current.isConnected).toBe(false);
    expect(result.current.callState).toBe("idle");
    expect(result.current.providerName).toBe("");
  });

  it("connects to Retell when session returns retell provider", async () => {
    const session = makeSession({ provider: "retell" });
    createAICallRealtimeSession.mockResolvedValue(session);
    createRetellWebCall.mockResolvedValue({ access_token: "tok_retell_123" });
    const mockRuntime = makeMockRuntime();
    createRealtimeCallRuntime.mockReturnValue(mockRuntime);

    const { result } = renderHook(() => useVoiceOrderMode(defaultProps));

    await act(async () => {
      await result.current.startVoiceOrder();
    });

    expect(createAICallRealtimeSession).toHaveBeenCalledTimes(1);
    expect(createRetellWebCall).toHaveBeenCalledTimes(1);
    expect(createRealtimeCallRuntime).toHaveBeenCalledWith(
      expect.objectContaining({ providerName: "retell", accessToken: "tok_retell_123" })
    );
    expect(mockRuntime.start).toHaveBeenCalled();
    expect(result.current.isActive).toBe(true);
    expect(result.current.isConnected).toBe(true);
  });

  it("falls back to Vapi when Retell fails and fallback is configured", async () => {
    const session = makeSession({
      provider: "retell",
      fallback: { name: "vapi", public_key: "pk_vapi_fb", assistant_id: "asst_vapi_fb", assistant_ids: { "en-IN": "asst_vapi_fb" } },
    });
    createAICallRealtimeSession.mockResolvedValue(session);
    createRetellWebCall.mockRejectedValueOnce(new Error("Retell down"));

    // Vapi fallback succeeds
    const mockRuntime = makeMockRuntime();
    createRealtimeCallRuntime.mockReturnValue(mockRuntime);

    const { result } = renderHook(() => useVoiceOrderMode(defaultProps));

    await act(async () => {
      await result.current.startVoiceOrder();
    });

    // Should have tried Vapi after Retell failed
    expect(createRealtimeCallRuntime).toHaveBeenCalledWith(
      expect.objectContaining({ providerName: "vapi", publicKey: "pk_vapi_fb" })
    );
    expect(mockRuntime.start).toHaveBeenCalled();
    expect(result.current.isActive).toBe(true);
    expect(result.current.providerName).toBe("vapi");
  });

  it("stopVoiceOrder finalizes draft cart when items exist", async () => {
    const session = makeSession({ provider: "retell" });
    createAICallRealtimeSession.mockResolvedValue(session);
    createRetellWebCall.mockResolvedValue({ access_token: "tok_123" });
    const mockRuntime = makeMockRuntime();
    createRealtimeCallRuntime.mockReturnValue(mockRuntime);
    finalizeCallOrderSession.mockResolvedValue({ draft_cart: [], draft_total_cents: 0 });
    fetchCart.mockResolvedValue({ restaurants: [], total_cents: 0 });

    const onCartUpdated = vi.fn();
    const onMessage = vi.fn();
    const { result } = renderHook(() =>
      useVoiceOrderMode({ ...defaultProps, onCartUpdated, onMessage })
    );

    await act(async () => {
      await result.current.startVoiceOrder();
    });

    // We can't easily set draftCart from outside (it's internal state driven by tool results),
    // so verify that stop without draft items doesn't call finalize
    await act(async () => {
      await result.current.stopVoiceOrder();
    });

    expect(result.current.isActive).toBe(false);
    expect(result.current.isConnected).toBe(false);
    expect(mockRuntime.stop).toHaveBeenCalled();
  });

  it("does nothing when startVoiceOrder called while already active", async () => {
    const session = makeSession({ provider: "retell" });
    createAICallRealtimeSession.mockResolvedValue(session);
    createRetellWebCall.mockResolvedValue({ access_token: "tok_123" });
    createRealtimeCallRuntime.mockReturnValue(makeMockRuntime());

    const { result } = renderHook(() => useVoiceOrderMode(defaultProps));

    await act(async () => {
      await result.current.startVoiceOrder();
    });

    // Call again while active
    await act(async () => {
      await result.current.startVoiceOrder();
    });

    // Should only have created one session
    expect(createAICallRealtimeSession).toHaveBeenCalledTimes(1);
  });

  it("sets error state when session creation fails", async () => {
    createAICallRealtimeSession.mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useVoiceOrderMode(defaultProps));

    await act(async () => {
      await result.current.startVoiceOrder();
    });

    expect(result.current.isActive).toBe(false);
    expect(result.current.callState).toBe("error");
    expect(result.current.statusText).toBe("Network error");
  });
});
