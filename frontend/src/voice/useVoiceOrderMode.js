/**
 * useVoiceOrderMode.js — React hook for inline Voice Order in the chat window.
 *
 * Uses the same Retell → Vapi → browser fallback chain as AICallPage.
 * Pipes transcript messages into the chat via callbacks and manages the
 * realtime session + draft cart lifecycle.
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { createRealtimeCallRuntime, parseRealtimeProviderMessage } from "../aiCall/realtimeRuntime.js";
import {
  AI_CALL_STATES,
  buildRealtimeAssistantConfig,
  buildRealtimeAssistantPrompt,
  buildRealtimeFunctionTools,
  extractRealtimeToolCalls,
  getCallGreeting,
  isLikelyWrongDomainAssistant,
  normalizeCallLanguage,
} from "../aiCall/aiCallUtils.js";
import {
  aiCallRealtimeAddItem,
  aiCallRealtimeFindRestaurants,
  aiCallRealtimeGetDraftSummary,
  aiCallRealtimeGetMenu,
  aiCallRealtimeListRestaurants,
  aiCallRealtimeRemoveItem,
  aiCallRealtimeStartCheckout,
  createAICallRealtimeSession,
  createRetellWebCall,
  fetchCart,
  finalizeCallOrderSession,
} from "../api.js";

export function useVoiceOrderMode({
  token,
  language = "en",
  userLat = null,
  userLng = null,
  radiusMiles = null,
  onMessage,
  onCartUpdated,
  onRequireAuth,
}) {
  const [isActive, setIsActive] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [providerName, setProviderName] = useState("");
  const [callState, setCallState] = useState(AI_CALL_STATES.IDLE);
  const [draftCart, setDraftCart] = useState([]);
  const [draftTotalCents, setDraftTotalCents] = useState(0);
  const [statusText, setStatusText] = useState("");

  const runtimeRef = useRef(null);
  const sessionIdRef = useRef("");
  const connectedRef = useRef(false);
  const disconnectingRef = useRef(false);
  const fallbackInProgressRef = useRef(false);
  const handledToolCallsRef = useRef(new Set());
  const toolQueueRef = useRef(Promise.resolve());
  const draftPollRef = useRef(null);
  const knownRestaurantIdsRef = useRef(new Set());
  const knownItemIdsRef = useRef(new Map());

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanupRuntime({ skipStop: false });
      clearInterval(draftPollRef.current);
    };
  }, []);

  // ── Helpers ──

  function emit(role, text) {
    if (!text?.trim()) return;
    onMessage?.({ role, text: text.trim() });
  }

  function applyDraft(snapshot) {
    const draft = snapshot?.draft || snapshot;
    const cart = Array.isArray(draft?.draft_cart) ? draft.draft_cart : [];
    const total = Number(draft?.draft_total_cents || 0);
    setDraftCart(cart);
    setDraftTotalCents(total);
  }

  async function cleanupRuntime({ skipStop = false } = {}) {
    const rt = runtimeRef.current;
    runtimeRef.current = null;
    if (!rt) return;
    try {
      if (!skipStop) await rt.stop();
    } catch { /* ignore */ } finally {
      rt.dispose?.();
    }
  }

  // ── Tool execution (mirrors AICallPage) ──

  function trackKnownIds(toolName, result) {
    if (!result || typeof result !== "object") return;
    if (toolName === "list_restaurants" || toolName === "find_restaurants") {
      for (const r of (result.restaurants || [])) {
        if (r?.id) knownRestaurantIdsRef.current.add(Number(r.id));
      }
    }
    if (toolName === "get_restaurant_menu") {
      if (result.restaurant?.id) knownRestaurantIdsRef.current.add(Number(result.restaurant.id));
      for (const cat of (result.categories || [])) {
        for (const item of (cat.items || [])) {
          if (item?.id) knownItemIdsRef.current.set(Number(item.id), { name: item.name, restaurant_id: result.restaurant?.id });
        }
      }
      for (const item of (result.suggested_items || [])) {
        if (item?.id) knownItemIdsRef.current.set(Number(item.id), { name: item.name, restaurant_id: item.restaurant_id || result.restaurant?.id });
      }
    }
  }

  function compactToolResult(toolName, payload) {
    const result = payload && typeof payload === "object" ? payload : {};
    if (toolName === "get_restaurant_menu") {
      if (result.status === "FAILED") return { status: result.status, error: result.error, instruction: result.instruction, restaurant: result.restaurant || {} };
      const categories = (result.categories || []).slice(0, 5).map((c) => ({
        id: c.id, name: c.name,
        items: (c.items || []).slice(0, 6).map((i) => ({ id: i.id, name: i.name, price_cents: i.price_cents })),
      }));
      return {
        restaurant: result.restaurant || {},
        suggested_items: (result.suggested_items || []).slice(0, 5).map((i) => ({ id: i.id, name: i.name, price_cents: i.price_cents, category: i.category_name, restaurant_id: i.restaurant_id })),
        categories,
        more_categories: (result.categories || []).slice(5).map((c) => c.name),
      };
    }
    if (toolName === "list_restaurants") {
      const restaurants = result.restaurants || [];
      return { restaurants: restaurants.slice(0, 8).map((r) => ({ id: r.id, name: r.name })), total: result.total_matches ?? restaurants.length };
    }
    if (toolName === "find_restaurants") {
      return { restaurants: (result.restaurants || []).slice(0, 5).map((r) => ({ id: r.id, name: r.name, score: r.score })) };
    }
    if (toolName === "add_draft_item" || toolName === "remove_draft_item") {
      const draft = result.draft || {};
      return { status: "SUCCESS", summary: result.summary || "", draft_total_items: draft.draft_total_items || 0, draft_total_cents: draft.draft_total_cents || 0 };
    }
    return result;
  }

  async function executeToolCall(toolCall) {
    const sid = sessionIdRef.current;
    if (!sid) throw new Error("Voice order session missing.");
    const args = toolCall.arguments || {};
    switch (toolCall.name) {
      case "list_restaurants":
        return aiCallRealtimeListRestaurants(sid, String(args.query || ""), Number(args.limit || 8), { lat: userLat, lng: userLng, radius_miles: radiusMiles });
      case "find_restaurants":
        return aiCallRealtimeFindRestaurants(sid, String(args.query || ""), { lat: userLat, lng: userLng, radius_miles: radiusMiles });
      case "get_restaurant_menu":
        return aiCallRealtimeGetMenu(sid, args.restaurant_id != null ? Number(args.restaurant_id) : undefined, String(args.restaurant_name || ""), String(args.query || ""), [...knownRestaurantIdsRef.current]);
      case "get_draft_summary":
        return aiCallRealtimeGetDraftSummary(sid);
      case "add_draft_item":
        return aiCallRealtimeAddItem(sid, Math.round(Number(args.item_id)), Math.min(20, Math.max(1, Math.round(Number(args.quantity || 1)))), String(args.item_name || ""), args.restaurant_id != null ? Math.round(Number(args.restaurant_id)) : null);
      case "remove_draft_item":
        return aiCallRealtimeRemoveItem(sid, Math.round(Number(args.item_id)), Math.min(20, Math.max(1, Math.round(Number(args.quantity || 1)))), String(args.item_name || ""), args.restaurant_id != null ? Math.round(Number(args.restaurant_id)) : null);
      case "finalize_draft_to_cart": {
        if (!token) { onRequireAuth?.(); throw new Error("Sign in to move the draft into your cart."); }
        const result = await finalizeCallOrderSession(token, sid);
        applyDraft(result);
        const cart = await fetchCart(token);
        onCartUpdated?.(cart);
        return result;
      }
      case "start_checkout": {
        if (!token) { onRequireAuth?.(); throw new Error("Sign in to start checkout."); }
        const result = await aiCallRealtimeStartCheckout(token, sid);
        if (result?.draft) applyDraft(result.draft);
        const cart = await fetchCart(token);
        onCartUpdated?.(cart);
        if (result?.checkout?.checkout_url && result.checkout.session_id !== "sim_dev") {
          window.location.href = result.checkout.checkout_url;
        }
        return result;
      }
      default:
        throw new Error(`Unsupported tool: ${toolCall.name}`);
    }
  }

  async function processOneToolCall(toolCall) {
    try {
      const result = await executeToolCall(toolCall);
      trackKnownIds(toolCall.name, result);
      if (result?.draft) applyDraft(result.draft);
      else if (result?.draft_cart || result?.draft_total_cents !== undefined) applyDraft(result);
      // Push result back to provider
      const rt = runtimeRef.current;
      if (!rt) return;
      const compacted = compactToolResult(toolCall.name, result);
      const content = JSON.stringify(compacted);
      const prov = providerNameRef.current;
      if (prov === "retell") {
        rt.send({ type: "tool_result", toolCallId: toolCall.id, name: toolCall.name, result: content });
      } else {
        rt.send({ type: "add-message", message: { role: "tool", toolCallId: toolCall.id, content }, triggerResponseEnabled: true });
      }
    } catch (error) {
      const rt = runtimeRef.current;
      if (rt) {
        rt.send({
          type: "add-message",
          message: { role: "tool", toolCallId: toolCall.id, content: JSON.stringify({ status: "FAILED", error: error?.message || "Tool call failed.", instruction: "Tell the caller it failed." }) },
          triggerResponseEnabled: true,
        });
      }
    }
  }

  function handleToolCalls(message) {
    const toolCalls = extractRealtimeToolCalls(message);
    for (const tc of toolCalls) {
      if (handledToolCallsRef.current.has(tc.id)) continue;
      handledToolCallsRef.current.add(tc.id);
      toolQueueRef.current = toolQueueRef.current.then(
        () => processOneToolCall(tc),
        () => processOneToolCall(tc),
      );
    }
  }

  // ── Provider message handler ──

  const providerNameRef = useRef("");

  function handleMessage(message) {
    const parsed = parseRealtimeProviderMessage(providerNameRef.current || "vapi", message);

    if (parsed.role === "user" && parsed.text) {
      emit("user", parsed.text);
    }
    if (parsed.role === "assistant" && parsed.text) {
      if (isLikelyWrongDomainAssistant(parsed.text)) {
        stopVoiceOrder();
        return;
      }
      emit("assistant", parsed.text);
    }

    const draftSnapshot = message?.draft || message?.artifact?.draft || message?.callOrderDraft;
    if (draftSnapshot) applyDraft(draftSnapshot);

    handleToolCalls(message);

    if (parsed.status === "ended" || parsed.type === "call_ended" || parsed.type === "call-ended") {
      if (connectedRef.current && !disconnectingRef.current) {
        stopVoiceOrder();
      }
    }
  }

  // ── Connect realtime provider ──

  async function connectRetellOrVapi(session) {
    const provider = session?.realtime?.provider || {};
    const pName = String(provider?.name || "vapi").toLowerCase();
    const lang = normalizeCallLanguage(language);
    const agentId = provider?.agent_ids?.[lang] || provider?.agent_id;
    const assistantId = provider?.assistant_ids?.[lang] || provider?.assistant_id;
    const vapiServerUrl = provider?.server_url || "";
    const inlineAssistant = pName === "vapi" && lang === "en-IN"
      ? buildRealtimeAssistantConfig(lang, session?.session_id, vapiServerUrl)
      : null;

    let retellAccessToken = null;
    if (pName === "retell") {
      const webCall = await createRetellWebCall({
        session_id: session?.session_id,
        language: lang,
        metadata: { sessionId: session?.session_id, source: "restaurantai-chat-voice-order", language: lang },
      });
      retellAccessToken = webCall?.access_token;
      if (!retellAccessToken) throw new Error("Failed to get Retell access token.");
    }

    if (pName === "vapi" && !inlineAssistant && !assistantId) {
      throw new Error(`Missing Vapi assistant for ${lang}.`);
    }

    providerNameRef.current = pName;
    setProviderName(pName);

    const runtime = createRealtimeCallRuntime({
      providerName: pName,
      publicKey: provider.public_key,
      assistant: inlineAssistant,
      assistantId,
      assistantOverrides: {
        firstMessage: getCallGreeting(lang),
        firstMessageMode: "assistant-speaks-first",
        "tools:append": buildRealtimeFunctionTools(),
        variableValues: { session_id: session?.session_id, language: lang },
        metadata: { sessionId: session?.session_id, source: "restaurantai-chat-voice-order", language: lang },
      },
      agentId,
      accessToken: retellAccessToken,
      metadata: { sessionId: session?.session_id, source: "restaurantai-chat-voice-order", language: lang },
      onCallStart: () => {
        setCallState(AI_CALL_STATES.LISTENING);
        setStatusText("Voice order connected. Speak naturally.");
      },
      onCallEnd: () => {
        if (!disconnectingRef.current) stopVoiceOrder();
      },
      onSpeechStart: () => {
        setCallState(AI_CALL_STATES.SPEAKING);
        setStatusText("Assistant is replying...");
      },
      onSpeechEnd: () => {
        if (connectedRef.current) {
          setCallState(AI_CALL_STATES.LISTENING);
          setStatusText("Listening...");
        }
      },
      onMessage: handleMessage,
      onError: (error) => {
        if (connectedRef.current) {
          void fallbackFromProvider(session, error);
          return;
        }
        setCallState(AI_CALL_STATES.ERROR);
        setStatusText(error?.message || "Voice order error.");
      },
    });

    runtimeRef.current = runtime;
    disconnectingRef.current = false;
    handledToolCallsRef.current = new Set();
    knownRestaurantIdsRef.current = new Set();
    knownItemIdsRef.current = new Map();
    toolQueueRef.current = Promise.resolve();

    sessionIdRef.current = String(session?.session_id || session?.id || "");
    connectedRef.current = true;
    setIsConnected(true);
    setCallState(AI_CALL_STATES.READY);
    setStatusText("Connecting voice order...");
    applyDraft(session);

    // Start draft polling for Retell (server-side tool calls)
    if (pName === "retell") {
      clearInterval(draftPollRef.current);
      const pollSid = session?.session_id;
      draftPollRef.current = setInterval(async () => {
        if (!connectedRef.current || !pollSid || sessionIdRef.current !== pollSid) return;
        try {
          const snap = await aiCallRealtimeGetDraftSummary(pollSid);
          if (snap?.draft && sessionIdRef.current === pollSid) applyDraft(snap);
        } catch { /* ignore */ }
      }, 2000);
    }

    await runtime.start();

    if (pName === "vapi" && !inlineAssistant) {
      runtime.send({
        type: "add-message",
        message: { role: "system", content: buildRealtimeAssistantPrompt(lang) },
      });
    }
  }

  async function fallbackFromProvider(session, error) {
    if (fallbackInProgressRef.current || disconnectingRef.current) return;
    fallbackInProgressRef.current = true;
    const failedProvider = providerNameRef.current || String(session?.realtime?.provider?.name || "").toLowerCase();

    try {
      await cleanupRuntime({ skipStop: true });
      clearInterval(draftPollRef.current);
      draftPollRef.current = null;

      // If Retell failed, try Vapi fallback
      const fallbackConfig = session?.realtime?.provider?.fallback;
      if (failedProvider === "retell" && fallbackConfig?.name === "vapi" && fallbackConfig?.public_key) {
        setStatusText("Retell unavailable. Trying Vapi...");
        try {
          const vapiSession = {
            ...session,
            realtime: {
              ...session.realtime,
              enabled: true,
              provider: {
                ...session.realtime.provider,
                name: "vapi",
                public_key: fallbackConfig.public_key,
                assistant_id: fallbackConfig.assistant_id,
                assistant_ids: fallbackConfig.assistant_ids,
                server_url: fallbackConfig.server_url || "",
                fallback: null,
              },
            },
          };
          await connectRetellOrVapi(vapiSession);
          return;
        } catch {
          await cleanupRuntime({ skipStop: true });
        }
      }

      // All realtime providers failed — fall back to browser (end voice order)
      setStatusText("Voice providers unavailable. Use the mic button for browser voice.");
      disconnectInternal();
    } finally {
      fallbackInProgressRef.current = false;
    }
  }

  function disconnectInternal() {
    disconnectingRef.current = true;
    clearInterval(draftPollRef.current);
    draftPollRef.current = null;
    cleanupRuntime({ skipStop: false });
    connectedRef.current = false;
    setIsConnected(false);
    setIsActive(false);
    setCallState(AI_CALL_STATES.IDLE);
    setProviderName("");
    providerNameRef.current = "";
    sessionIdRef.current = "";
    setDraftCart([]);
    setDraftTotalCents(0);
  }

  // ── Public API ──

  const startVoiceOrder = useCallback(async () => {
    if (isActive) return;
    setIsActive(true);
    setCallState(AI_CALL_STATES.READY);
    setStatusText("Starting voice order...");
    setDraftCart([]);
    setDraftTotalCents(0);

    try {
      const session = await createAICallRealtimeSession({ language });
      const provider = session?.realtime?.provider;
      const lang = normalizeCallLanguage(language);
      const pName = String(provider?.name || "").toLowerCase();

      // Check if realtime is enabled
      const isRetellOk = pName === "retell" && (lang === "en-IN" || lang === "ta-IN") && session?.realtime?.enabled && provider?.configured !== false;
      const vapiAssistant = provider?.assistant_ids?.[lang] || provider?.assistant_id;
      const isVapiOk = pName === "vapi" && (lang === "en-IN" || lang === "ta-IN") && session?.realtime?.enabled && provider?.public_key && vapiAssistant;

      if (isRetellOk || isVapiOk) {
        try {
          await connectRetellOrVapi(session);
          return;
        } catch (realtimeError) {
          await fallbackFromProvider(session, realtimeError);
          return;
        }
      }

      // No realtime available — inform user, fall back to browser voice
      setStatusText("Realtime voice not available. Use the mic button for browser voice.");
      setIsActive(false);
      setCallState(AI_CALL_STATES.IDLE);
    } catch (error) {
      setCallState(AI_CALL_STATES.ERROR);
      setStatusText(error?.message || "Unable to start voice order.");
      setIsActive(false);
    }
  }, [isActive, language, userLat, userLng, radiusMiles, token]);

  const stopVoiceOrder = useCallback(async () => {
    if (!isActive) return;

    // If we have a draft cart and token, finalize to main cart
    if (token && sessionIdRef.current && draftCart.length > 0) {
      try {
        await finalizeCallOrderSession(token, sessionIdRef.current);
        const cart = await fetchCart(token);
        onCartUpdated?.(cart);
        emit("assistant", "Your voice order items have been added to your cart.");
      } catch {
        emit("assistant", "Could not finalize voice order to cart. You can add items manually.");
      }
    }

    disconnectInternal();
    setStatusText("");
  }, [isActive, token, draftCart.length, onCartUpdated]);

  return {
    isActive,
    isConnected,
    providerName,
    callState,
    draftCart,
    draftTotalCents,
    statusText,
    startVoiceOrder,
    stopVoiceOrder,
  };
}
