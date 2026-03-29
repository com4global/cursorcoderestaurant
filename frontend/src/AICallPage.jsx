import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  aiCallRealtimeAddItem,
  aiCallRealtimeFindRestaurants,
  aiCallRealtimeGetDraftSummary,
  aiCallRealtimeGetMenu,
  aiCallRealtimeListRestaurants,
  aiCallRealtimeRemoveItem,
  aiCallRealtimeStartCheckout,
  callOrderTurn,
  createAICallRealtimeSession,
  createCheckoutSession,
  createRetellWebCall,
  fetchCart,
  finalizeCallOrderSession,
  getCallOrderSession,
  voiceSTT,
  voiceTTS,
} from "./api.js";
import { createRealtimeCallRuntime, parseRealtimeProviderMessage } from "./aiCall/realtimeRuntime.js";
import {
  AI_CALL_STATES,
  buildRealtimeAssistantConfig,
  buildRealtimeFunctionTools,
  buildRealtimeAssistantPrompt,
  createTurn,
  extractRealtimeToolCalls,
  getCallCheckoutMessage,
  getCallGreeting,
  getCallStateLabel,
  getWrongDomainAssistantMessage,
  isLikelyWrongDomainAssistant,
  normalizeCallLanguage,
} from "./aiCall/aiCallUtils.js";

function pickRecorderMimeType() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return "audio/webm;codecs=opus";
  if (MediaRecorder.isTypeSupported("audio/webm")) return "audio/webm";
  if (MediaRecorder.isTypeSupported("audio/mp4")) return "audio/mp4";
  return "";
}

function base64ToBlob(base64, mimeType = "audio/wav") {
  const raw = atob(base64);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) {
    bytes[index] = raw.charCodeAt(index);
  }
  return new Blob([bytes], { type: mimeType });
}

function logAICall(event, details = {}) {
  console.log("%c[AICall]", "color:#0ea5e9;font-weight:700", event, details);
}

function logAICallError(event, error, details = {}) {
  const normalizedMessage = typeof error === "string"
    ? error
    : error?.message
      || error?.errorMsg
      || error?.response?.data?.message
      || error?.response?.data?.error
      || error?.error?.message
      || (() => {
        try {
          return JSON.stringify(error);
        } catch {
          return String(error);
        }
      })();
  console.error("%c[AICall]", "color:#ef4444;font-weight:700", event, {
    ...details,
    message: normalizedMessage,
    name: error?.name,
    stack: error?.stack,
  });
}

function isMicrophoneError(error) {
  const name = String(error?.name || "");
  return (
    name === "NotAllowedError"
    || name === "NotFoundError"
    || name === "NotReadableError"
    || name === "OverconstrainedError"
    || name === "AbortError"
    || name === "SecurityError"
  );
}

function isBackendConnectionError(error) {
  const name = String(error?.name || "");
  const message = String(error?.message || "").toLowerCase();
  return (
    name === "TypeError"
    || message.includes("failed to fetch")
    || message.includes("networkerror")
    || message.includes("network request failed")
    || message.includes("cors")
  );
}

export default function AICallPage({
  token = "",
  onRequireAuth,
  onCartUpdated,
  onOrdersUpdated,
  checkoutReturnContext,
  onCheckoutReturnHandled,
  userLat = null,
  userLng = null,
  radiusMiles = null,
}) {
  const [language, setLanguage] = useState("en-IN");
  const [callState, setCallState] = useState(AI_CALL_STATES.IDLE);
  const [isConnected, setIsConnected] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Start a separate AI call to ask questions and place an order by voice.");
  const [messages, setMessages] = useState([]);
  const [latestTranscript, setLatestTranscript] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [draftCart, setDraftCart] = useState([]);
  const [draftTotalCents, setDraftTotalCents] = useState(0);
  const [pendingAction, setPendingAction] = useState(null);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [isHandsFreeEnabled, setIsHandsFreeEnabled] = useState(true);
  const [isRealtimeCall, setIsRealtimeCall] = useState(false);
  const [isRealtimeMuted, setIsRealtimeMuted] = useState(false);
  const [realtimeProviderName, setRealtimeProviderName] = useState("");

  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const chunksRef = useRef([]);
  const audioRef = useRef(null);
  const audioUrlRef = useRef("");
  const speechUtteranceRef = useRef(null);
  const lastAssistantReplyRef = useRef("");
  const messagesRef = useRef([]);
  const ignoreNextStopRef = useRef(false);
  const connectedRef = useRef(false);
  const finalizingRef = useRef(false);
  const sessionIdRef = useRef("");
  const callStateRef = useRef(AI_CALL_STATES.IDLE);
  const handsFreeEnabledRef = useRef(true);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const analyserSourceRef = useRef(null);
  const analyserDataRef = useRef(null);
  const monitorFrameRef = useRef(0);
  const turnInFlightRef = useRef(false);
  const speechDetectedRef = useRef(false);
  const lastSpeechAtRef = useRef(0);
  const recorderStartedAtRef = useRef(0);
  const realtimeCallRef = useRef(null);
  const realtimeModeRef = useRef(false);
  const realtimeDisconnectingRef = useRef(false);
  const realtimeMismatchHandledRef = useRef(false);
  const realtimeFallbackInProgressRef = useRef(false);
  const handledRealtimeToolCallsRef = useRef(new Set());
  const vapiServerUrlRef = useRef("");
  const transcriptEndRef = useRef(null);
  // Track known IDs from successful tool results to validate model calls
  const knownRestaurantIdsRef = useRef(new Set());
  const knownItemIdsRef = useRef(new Map()); // item_id -> { name, restaurant_id, price_cents }
  // Serial queue ensures tool calls execute one at a time across all messages
  const toolQueueRef = useRef(Promise.resolve());
  // Polling interval for syncing draft cart during Retell server-side tool calls
  const draftPollRef = useRef(null);

  const VAD_THRESHOLD = 0.075;
  const VAD_SILENCE_MS = 900;
  const VAD_IDLE_WAIT_MS = 4000;
  const VAD_MAX_RECORDING_MS = 12000;

  function clearMonitorLoop() {
    if (monitorFrameRef.current) {
      cancelAnimationFrame(monitorFrameRef.current);
      monitorFrameRef.current = 0;
    }
  }

  function cleanupAudioUrl() {
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = "";
    }
  }

  function mapHistory(history) {
    return Array.isArray(history)
      ? history.map((entry, index) => ({
          id: `${entry.role}-${index}-${Date.now()}`,
          role: entry.role === "assistant" ? "assistant" : "user",
          text: entry.text,
          createdAt: new Date().toISOString(),
        }))
      : [];
  }

  function applyDraftSnapshot(snapshot) {
    const draft = snapshot?.draft || snapshot;
    const cart = Array.isArray(draft?.draft_cart) ? draft.draft_cart : [];
    const total = Number(draft?.draft_total_cents || 0);
    console.log("[AICall] applyDraftSnapshot", { cartLength: cart.length, totalCents: total, cart, rawKeys: snapshot ? Object.keys(snapshot) : [] });
    setDraftCart(cart);
    setDraftTotalCents(total);
    setPendingAction(draft?.pending_action || null);
  }

  /** Extract restaurant and item IDs from successful tool results so we can
   *  validate subsequent calls and reject hallucinated IDs early. */
  function trackKnownIds(toolName, result) {
    if (!result || typeof result !== "object") return;
    const restaurants = Array.isArray(result.restaurants) ? result.restaurants : [];
    if (toolName === "list_restaurants" || toolName === "find_restaurants") {
      for (const r of restaurants) {
        if (r?.id) knownRestaurantIdsRef.current.add(Number(r.id));
      }
      logAICall("trackKnownIds:restaurants", { toolName, ids: [...knownRestaurantIdsRef.current] });
    }
    if (toolName === "get_restaurant_menu") {
      if (result.restaurant?.id) {
        knownRestaurantIdsRef.current.add(Number(result.restaurant.id));
      }
      const categories = Array.isArray(result.categories) ? result.categories : [];
      for (const cat of categories) {
        for (const item of (cat.items || [])) {
          if (item?.id) {
            knownItemIdsRef.current.set(Number(item.id), {
              name: item.name,
              restaurant_id: result.restaurant?.id,
              price_cents: item.price_cents,
            });
          }
        }
      }
      const suggested = Array.isArray(result.suggested_items) ? result.suggested_items : [];
      for (const item of suggested) {
        if (item?.id) {
          knownItemIdsRef.current.set(Number(item.id), {
            name: item.name,
            restaurant_id: item.restaurant_id || result.restaurant?.id,
            price_cents: item.price_cents,
          });
        }
      }
      logAICall("trackKnownIds:items", { toolName, count: knownItemIdsRef.current.size, ids: [...knownItemIdsRef.current.keys()].slice(0, 20) });
    }
  }

  function applyConnectedSession(session, { statusText, connectedState = AI_CALL_STATES.LISTENING } = {}) {
    const nextSessionId = String(session?.session_id || session?.id || "");
    sessionIdRef.current = nextSessionId;
    setSessionId(nextSessionId);
    connectedRef.current = true; // set immediately so error/fallback handlers see it synchronously
    setIsConnected(true);
    setCallState(connectedState);
    setStatusMessage(statusText || "Your AI call is connected. I am listening when you speak.");
    applyDraftSnapshot(session);
    setSuggestions(Array.isArray(session?.suggestions) ? session.suggestions : []);
    const history = mapHistory(session?.history);
    messagesRef.current = history;
    setMessages(history);
    const replyText = String(session?.assistant_reply || "").trim();
    if (replyText) {
      lastAssistantReplyRef.current = replyText;
    }
  }

  function isRealtimeSessionEnabled(session) {
    const provider = session?.realtime?.provider;
    const normalizedLanguage = normalizeCallLanguage(language);
    const providerName = String(provider?.name || "").toLowerCase();
    const assistantId = provider?.assistant_ids?.[normalizeCallLanguage(language)] || provider?.assistant_id;
    const agentId = provider?.agent_ids?.[normalizeCallLanguage(language)] || provider?.agent_id;

    if (providerName === "retell") {
      return Boolean(
        normalizedLanguage === "en-IN"
        && session?.realtime?.enabled
        && agentId
      );
    }

    return Boolean(
      normalizedLanguage === "en-IN" &&
      session?.realtime?.enabled
      && providerName === "vapi"
      && provider?.public_key
      && assistantId
    );
  }

  function appendMessageIfChanged(role, text) {
    const normalizedText = String(text || "").trim();
    if (!normalizedText) return;
    const lastMessage = messagesRef.current[messagesRef.current.length - 1];
    if (lastMessage?.role === role && lastMessage?.text === normalizedText) {
      return;
    }
    appendMessage(role, normalizedText);
  }

  async function cleanupRealtimeRuntime({ skipStop = false } = {}) {
    const runtime = realtimeCallRef.current;
    realtimeCallRef.current = null;
    if (!runtime) return;
    try {
      if (!skipStop) {
        await runtime.stop();
      }
    } catch (error) {
      logAICallError("realtime:stop-error", error, { sessionId: sessionIdRef.current });
    } finally {
      runtime.dispose?.();
    }
  }

  function handleRealtimeAssistantMismatch(text) {
    if (realtimeMismatchHandledRef.current || !connectedRef.current || !realtimeModeRef.current) {
      return;
    }
    realtimeMismatchHandledRef.current = true;
    logAICall("realtime:wrong-domain-assistant", {
      sessionId: sessionIdRef.current,
      textPreview: String(text || "").slice(0, 160),
    });
    void disconnectCall({
      finalStatusMessage: getWrongDomainAssistantMessage(realtimeProviderName || "vapi"),
    });
  }

  // Daily.co sendAppMessage has a ~4KB payload limit. Tool results for menus can
  // exceed this, causing messages to be silently dropped. This function produces
  // a compact, voice-friendly summary that stays well under the limit.
  function compactToolResult(toolName, payload) {
    const result = payload && typeof payload === "object" ? payload : {};

    if (toolName === "get_restaurant_menu") {
      if (result.status === "FAILED") {
        return {
          status: result.status,
          error: result.error,
          instruction: result.instruction,
          restaurant: result.restaurant || {},
        };
      }
      const restaurant = result.restaurant || {};
      const categories = Array.isArray(result.categories) ? result.categories : [];
      const suggested = Array.isArray(result.suggested_items) ? result.suggested_items : [];
      // Send suggested items (most relevant) + all category names for context.
      // Only include full item lists for the top few categories to stay under 4KB.
      const compactSuggested = suggested.slice(0, 5).map((item) => ({
        id: item.id,
        name: item.name,
        price_cents: item.price_cents,
        category: item.category_name,
        restaurant_id: item.restaurant_id,
      }));
      const topCategories = categories.slice(0, 5).map((cat) => ({
        id: cat.id,
        name: cat.name,
        items: (cat.items || []).slice(0, 6).map((item) => ({
          id: item.id,
          name: item.name,
          price_cents: item.price_cents,
        })),
      }));
      const remainingCategoryNames = categories.slice(5).map((cat) => cat.name);
      return {
        restaurant,
        suggested_items: compactSuggested,
        categories: topCategories,
        more_categories: remainingCategoryNames,
      };
    }

    if (toolName === "list_restaurants") {
      const restaurants = Array.isArray(result.restaurants) ? result.restaurants : [];
      return {
        restaurants: restaurants.slice(0, 8).map((r) => ({ id: r.id, name: r.name })),
        total: result.total_matches ?? restaurants.length,
      };
    }

    if (toolName === "find_restaurants") {
      const restaurants = Array.isArray(result.restaurants) ? result.restaurants : [];
      return {
        restaurants: restaurants.slice(0, 5).map((r) => ({ id: r.id, name: r.name, score: r.score })),
      };
    }

    if (toolName === "add_draft_item" || toolName === "remove_draft_item") {
      // Send a clear, compact result so the model knows exactly what happened
      const draft = result.draft || {};
      return {
        status: "SUCCESS",
        summary: result.summary || "",
        draft_total_items: draft.draft_total_items || 0,
        draft_total_cents: draft.draft_total_cents || 0,
      };
    }

    return result;
  }

  async function pushRealtimeToolResult(toolCall, payload) {
    if (!realtimeCallRef.current) return;
    const compacted = compactToolResult(toolCall.name, payload);
    const content = JSON.stringify(compacted);
    const providerName = String(realtimeProviderName || "vapi").toLowerCase();
    logAICall("realtime:tool-call-result", {
      sessionId: sessionIdRef.current,
      toolCallId: toolCall.id,
      name: toolCall.name,
      provider: providerName,
      resultKeys: payload && typeof payload === "object" ? Object.keys(payload) : [],
      restaurantCount: Array.isArray(payload?.restaurants) ? payload.restaurants.length : undefined,
      contentBytes: content.length,
    });

    if (providerName === "retell") {
      realtimeCallRef.current.send({
        type: "tool_result",
        toolCallId: toolCall.id,
        name: toolCall.name,
        result: content,
      });
      return;
    }

    // Vapi: tools are async, so send tool result back via add-message and trigger response.
    realtimeCallRef.current.send({
      type: "add-message",
      message: {
        role: "tool",
        toolCallId: toolCall.id,
        content,
      },
      triggerResponseEnabled: true,
    });
  }

  async function executeRealtimeToolCall(toolCall) {
    const sessionId = sessionIdRef.current;
    if (!sessionId) {
      throw new Error("Realtime AI Call session is missing.");
    }
    
    console.log("[AICall] executeRealtimeToolCall EXEC", toolCall.name, toolCall.arguments);

    switch (toolCall.name) {
      case "list_restaurants":
        return aiCallRealtimeListRestaurants(
          sessionId,
          String(toolCall.arguments?.query || ""),
          Number(toolCall.arguments?.limit || 8),
          { lat: userLat, lng: userLng, radius_miles: radiusMiles }
        );
      case "find_restaurants":
        return aiCallRealtimeFindRestaurants(sessionId, String(toolCall.arguments?.query || ""), { lat: userLat, lng: userLng, radius_miles: radiusMiles });
      case "get_restaurant_menu":
        const reqRestId = toolCall.arguments?.restaurant_id;
        return aiCallRealtimeGetMenu(
          sessionId,
          reqRestId != null ? Number(reqRestId) : undefined,
          String(toolCall.arguments?.restaurant_name || ""),
          String(toolCall.arguments?.query || ""),
          [...knownRestaurantIdsRef.current]
        );
      case "get_draft_summary":
        return aiCallRealtimeGetDraftSummary(sessionId);
      case "add_draft_item":
        return aiCallRealtimeAddItem(
          sessionId,
          Math.round(Number(toolCall.arguments?.item_id)),
          Math.min(20, Math.max(1, Math.round(Number(toolCall.arguments?.quantity || 1)))),
          String(toolCall.arguments?.item_name || ""),
          toolCall.arguments?.restaurant_id != null ? Math.round(Number(toolCall.arguments.restaurant_id)) : null
        );
      case "remove_draft_item":
        return aiCallRealtimeRemoveItem(
          sessionId,
          Math.round(Number(toolCall.arguments?.item_id)),
          Math.min(20, Math.max(1, Math.round(Number(toolCall.arguments?.quantity || 1)))),
          String(toolCall.arguments?.item_name || ""),
          toolCall.arguments?.restaurant_id != null ? Math.round(Number(toolCall.arguments.restaurant_id)) : null
        );
      case "finalize_draft_to_cart": {
        if (!token) {
          onRequireAuth?.();
          throw new Error("Sign in to move the draft into your cart.");
        }
        const result = await finalizeCallOrderSession(token, sessionId);
        syncSessionHistory(result);
        setDraftCart(Array.isArray(result?.draft_cart) ? result.draft_cart : []);
        setDraftTotalCents(Number(result?.draft_total_cents || 0));
        setPendingAction(result?.pending_action || null);
        const cart = await fetchCart(token);
        onCartUpdated?.(cart);
        return result;
      }
      case "start_checkout": {
        if (!token) {
          onRequireAuth?.();
          throw new Error("Sign in to start checkout.");
        }
        const result = await aiCallRealtimeStartCheckout(token, sessionId);
        if (result?.draft) {
          applyDraftSnapshot(result.draft);
        }
        
        const cart = await fetchCart(token);
        onCartUpdated?.(cart);
        
        // Handle Stripe redirection or dev simulation
        if (result?.checkout?.checkout_url && result.checkout.session_id !== 'sim_dev') {
          // If real Stripe, redirect the user
          window.location.href = result.checkout.checkout_url;
        } else if (result?.checkout?.session_id === 'sim_dev') {
          // If simulated, it means orders were instantly placed and cart is now empty.
          // Trigger order fetch if prop exists (though user stays on call)
          if (typeof onOrdersUpdated === 'function') {
             onOrdersUpdated();
          }
        }
        
        return result;
      }
      default:
        throw new Error(`Unsupported realtime tool call: ${toolCall.name}`);
    }
  }

  // Tools that are handled server-side by the Vapi webhook when server.url is set.
  const SERVER_HANDLED_TOOLS = new Set([
    "list_restaurants",
    "find_restaurants",
    "get_restaurant_menu",
    "get_draft_summary",
    "add_draft_item",
    "remove_draft_item",
  ]);

  /** Process a single tool call: execute, update cart state, push result to Vapi. */
  async function processOneToolCall(toolCall, hasServerUrl) {
    logAICall("realtime:tool-call", {
      sessionId: sessionIdRef.current,
      toolCallId: toolCall.id,
      name: toolCall.name,
      arguments: toolCall.arguments,
      serverHandled: hasServerUrl && SERVER_HANDLED_TOOLS.has(toolCall.name),
    });

    if (hasServerUrl && SERVER_HANDLED_TOOLS.has(toolCall.name)) {
      return;
    }

    try {
      const result = await executeRealtimeToolCall(toolCall);
      trackKnownIds(toolCall.name, result);
      if (result?.draft) {
        logAICall("applyDraft:from-tool", { toolName: toolCall.name, draftCartLength: result.draft?.draft_cart?.length, draftTotalCents: result.draft?.draft_total_cents });
        applyDraftSnapshot(result.draft);
      } else if (result?.draft_cart || result?.draft_total_cents !== undefined || result?.pending_action) {
        applyDraftSnapshot(result);
      }
      await pushRealtimeToolResult(toolCall, result);
    } catch (error) {
      logAICallError("realtime:tool-call-error", error, {
        sessionId: sessionIdRef.current,
        toolCallId: toolCall.id,
        name: toolCall.name,
      });
      if (realtimeCallRef.current) {
        realtimeCallRef.current.send({
          type: "add-message",
          message: {
            role: "tool",
            toolCallId: toolCall.id,
            content: JSON.stringify({
              status: "FAILED",
              error: error?.message || "Realtime tool call failed.",
              instruction: "This action FAILED. Tell the caller it did not work and why. Do NOT say it succeeded.",
            }),
          },
          triggerResponseEnabled: true,
        });
      }
    }
  }

  async function handleRealtimeToolCalls(message) {
    const toolCalls = extractRealtimeToolCalls(message);
    if (!toolCalls.length) return;

    const hasServerUrl = Boolean(vapiServerUrlRef.current);

    for (const toolCall of toolCalls) {
      if (handledRealtimeToolCallsRef.current.has(toolCall.id)) {
        continue;
      }
      handledRealtimeToolCallsRef.current.add(toolCall.id);

      // Queue each tool call so they execute strictly one at a time.
      // This prevents race conditions where get_restaurant_menu runs
      // before find_restaurants has returned.
      toolQueueRef.current = toolQueueRef.current.then(
        () => processOneToolCall(toolCall, hasServerUrl),
        () => processOneToolCall(toolCall, hasServerUrl)
      );
    }
  }

  function handleRealtimeMessage(message) {
    const parsed = parseRealtimeProviderMessage(realtimeProviderName || "vapi", message);
    logAICall("realtime:message", {
      type: parsed.type,
      status: parsed.status,
      role: parsed.role || null,
      textPreview: parsed.text ? parsed.text.slice(0, 120) : "",
    });

    if (parsed.role === "user" && parsed.text) {
      setLatestTranscript(parsed.text);
      appendMessageIfChanged("user", parsed.text);
    }

    if (parsed.role === "assistant" && parsed.text) {
      if (isLikelyWrongDomainAssistant(parsed.text)) {
        handleRealtimeAssistantMismatch(parsed.text);
        return;
      }
      lastAssistantReplyRef.current = parsed.text;
      appendMessageIfChanged("assistant", parsed.text);
      setStatusMessage(parsed.text);
    }

    const draftSnapshot = message?.draft || message?.artifact?.draft || message?.callOrderDraft || message?.call_order_draft;
    if (draftSnapshot) {
      applyDraftSnapshot(draftSnapshot);
      if (Array.isArray(draftSnapshot?.history)) {
        messagesRef.current = mapHistory(draftSnapshot.history);
        setMessages(messagesRef.current);
      }
    }

    // When server returns tool-calls-result, extract draft snapshot from the
    // result payload so the client-side cart UI stays in sync.
    if (parsed.type === "tool-calls-result" || message?.type === "tool-calls-result") {
      try {
        const toolResult = message?.toolCallResult || {};
        const resultStr = typeof toolResult.result === "string" ? toolResult.result : "";
        if (resultStr) {
          const resultObj = JSON.parse(resultStr);
          if (resultObj?.summary || resultObj?.draft) {
            applyDraftSnapshot(resultObj.draft || resultObj);
          }
        }
      } catch {
        // Not all tool results contain draft data - ignore parse errors
      }
    }

    void handleRealtimeToolCalls(message);

    if (parsed.type === "status-update" && parsed.status === "ended" && connectedRef.current) {
      void disconnectCall({ skipRealtimeStop: true });
    }
    if ((parsed.type === "call_ended" || parsed.type === "call-ended") && connectedRef.current) {
      void disconnectCall({ skipRealtimeStop: true });
    }
  }

  function setReadyOrListeningStatus(messageWhenListening = "Listening for you. Speak naturally when you are ready.") {
    if (realtimeModeRef.current) {
      setCallState(AI_CALL_STATES.LISTENING);
      setStatusMessage(messageWhenListening);
      return;
    }
    if (handsFreeEnabledRef.current && connectedRef.current) {
      setCallState(AI_CALL_STATES.LISTENING);
      setStatusMessage(messageWhenListening);
      if (!mediaRecorderRef.current && !turnInFlightRef.current && !finalizingRef.current) {
        void beginListening("handsfree-ready");
      }
      return;
    }
    setCallState(AI_CALL_STATES.READY);
    setStatusMessage("Assistant finished speaking. Tap Speak to resume listening.");
  }

  function stopAssistantPlayback(reason = "interrupt") {
    if (audioRef.current && !audioRef.current.paused) {
      logAICall("tts:interrupted", { sessionId: sessionIdRef.current, reason });
    }
    if (typeof window !== "undefined" && window.speechSynthesis?.speaking) {
      window.speechSynthesis.cancel();
    }
    speechUtteranceRef.current = null;
    if (!audioRef.current) return;
    audioRef.current.onended = null;
    audioRef.current.pause();
    audioRef.current.src = "";
    cleanupAudioUrl();
  }

  function isTimeoutError(error) {
    const message = String(error?.message || error || "").toLowerCase();
    return message.includes("timed out") || message.includes("timeout");
  }

  function speakWithBrowserFallback(text, langCode) {
    if (typeof window === "undefined" || typeof window.SpeechSynthesisUtterance === "undefined" || !window.speechSynthesis) {
      return false;
    }
    const utterance = new window.SpeechSynthesisUtterance(text);
    utterance.lang = normalizeCallLanguage(langCode);
    utterance.rate = 1;
    utterance.onend = () => {
      speechUtteranceRef.current = null;
      logAICall("tts:fallback-ended", { language: utterance.lang });
      setReadyOrListeningStatus();
    };
    utterance.onerror = (event) => {
      speechUtteranceRef.current = null;
      logAICall("tts:fallback-error", { language: utterance.lang, error: event?.error || "unknown" });
      setReadyOrListeningStatus("Assistant reply is available on screen. Speak when you are ready.");
    };
    speechUtteranceRef.current = utterance;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    logAICall("tts:fallback-browser", { language: utterance.lang, textPreview: text.slice(0, 120) });
    return true;
  }

  async function ensureMicrophoneMonitor(stream) {
    if (!stream) return;
    if (!audioContextRef.current) {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextCtor) return;
      audioContextRef.current = new AudioContextCtor();
    }
    if (audioContextRef.current.state === "suspended") {
      await audioContextRef.current.resume();
    }
    if (!analyserRef.current) {
      const analyser = audioContextRef.current.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.2;
      analyserRef.current = analyser;
      analyserDataRef.current = new Uint8Array(analyser.fftSize);
    }
    if (!analyserSourceRef.current) {
      analyserSourceRef.current = audioContextRef.current.createMediaStreamSource(stream);
      analyserSourceRef.current.connect(analyserRef.current);
    }
  }

  function currentInputLevel() {
    if (!analyserRef.current || !analyserDataRef.current) return 0;
    analyserRef.current.getByteTimeDomainData(analyserDataRef.current);
    let sumSquares = 0;
    for (let index = 0; index < analyserDataRef.current.length; index += 1) {
      const centered = (analyserDataRef.current[index] - 128) / 128;
      sumSquares += centered * centered;
    }
    return Math.sqrt(sumSquares / analyserDataRef.current.length);
  }

  function startVoiceMonitor() {
    if (monitorFrameRef.current || !connectedRef.current || !handsFreeEnabledRef.current) return;
    const tick = () => {
      monitorFrameRef.current = 0;
      if (!connectedRef.current || !handsFreeEnabledRef.current || !mediaStreamRef.current) return;

      const level = currentInputLevel();
      const isSpeaking = level >= VAD_THRESHOLD;
      const isProcessing = turnInFlightRef.current || callStateRef.current === AI_CALL_STATES.PROCESSING || finalizingRef.current;
      const recorder = mediaRecorderRef.current;

      if (isSpeaking) {
        lastSpeechAtRef.current = Date.now();
      }

      if (!recorder && !isProcessing && sessionIdRef.current && callStateRef.current !== AI_CALL_STATES.SPEAKING) {
        void beginListening("handsfree-ready");
      }

      if (recorder && recorder.state === "recording") {
        if (isSpeaking) {
          speechDetectedRef.current = true;
        }
        const now = Date.now();
        if (speechDetectedRef.current && lastSpeechAtRef.current && now - lastSpeechAtRef.current >= VAD_SILENCE_MS) {
          logAICall("recording:silence-stop", { sessionId: sessionIdRef.current, silenceMs: now - lastSpeechAtRef.current });
          stopListening("silence");
        } else if (!speechDetectedRef.current && recorderStartedAtRef.current && now - recorderStartedAtRef.current >= VAD_IDLE_WAIT_MS) {
          logAICall("recording:idle-stop", { sessionId: sessionIdRef.current, idleMs: now - recorderStartedAtRef.current });
          stopListening("idle");
        } else if (recorderStartedAtRef.current && now - recorderStartedAtRef.current >= VAD_MAX_RECORDING_MS) {
          logAICall("recording:max-duration-stop", { sessionId: sessionIdRef.current, durationMs: now - recorderStartedAtRef.current });
          stopListening("max-duration");
        }
      }

      if (connectedRef.current && handsFreeEnabledRef.current) {
        monitorFrameRef.current = requestAnimationFrame(tick);
      }
    };

    monitorFrameRef.current = requestAnimationFrame(tick);
  }

  function appendMessage(role, text) {
    const turn = createTurn(role, text);
    const next = [...messagesRef.current, turn];
    messagesRef.current = next;
    setMessages(next);
    return next;
  }

  async function deliverAssistantUpdate(text, langCode, { speak = false } = {}) {
    if (!text) return;
    logAICall("deliverAssistantUpdate", { speak, language: langCode, textPreview: text.slice(0, 80) });
    appendMessage("assistant", text);
    lastAssistantReplyRef.current = text;
    setStatusMessage(text);
    if (!speak) return;
    try {
      await playAssistantReply(text, langCode);
    } catch {
      setCallState(AI_CALL_STATES.READY);
    }
  }

  useEffect(() => {
    connectedRef.current = isConnected;
  }, [isConnected]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    realtimeModeRef.current = isRealtimeCall;
  }, [isRealtimeCall]);

  useEffect(() => {
    handsFreeEnabledRef.current = isHandsFreeEnabled;
    if (!connectedRef.current) return;
    if (realtimeModeRef.current) {
      clearMonitorLoop();
      return;
    }
    if (isHandsFreeEnabled) {
      setCallState((current) => (current === AI_CALL_STATES.SPEAKING || current === AI_CALL_STATES.PROCESSING ? current : AI_CALL_STATES.LISTENING));
      setStatusMessage((current) => current || "Listening for you. Speak naturally when you are ready.");
      startVoiceMonitor();
    } else {
      clearMonitorLoop();
      if (mediaRecorderRef.current?.state === "recording") {
        stopListening("mic-paused");
      } else if (callStateRef.current !== AI_CALL_STATES.SPEAKING && callStateRef.current !== AI_CALL_STATES.PROCESSING) {
        setCallState(AI_CALL_STATES.READY);
        setStatusMessage("Microphone paused. Tap Speak to resume listening.");
      }
    }
  }, [isHandsFreeEnabled]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    callStateRef.current = callState;
  }, [callState]);

  useEffect(() => {
    finalizingRef.current = isFinalizing;
  }, [isFinalizing]);

  useEffect(() => {
    return () => {
      clearMonitorLoop();
      clearInterval(draftPollRef.current);
      draftPollRef.current = null;
      stopAssistantPlayback("unmount");
      void cleanupRealtimeRuntime();
      try {
        mediaRecorderRef.current?.stop();
      } catch {
        // ignore cleanup stop errors
      }
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (audioContextRef.current && audioContextRef.current.state !== "closed") {
        audioContextRef.current.close().catch(() => {});
      }
    };
  }, []);

  useEffect(() => {
    if (!checkoutReturnContext?.sessionId) return;

    let cancelled = false;

    async function restoreCallState() {
      logAICall("restoreCheckoutReturn:start", checkoutReturnContext);
      try {
        const session = await getCallOrderSession(checkoutReturnContext.sessionId);
        if (cancelled) return;

        setIsConnected(true);
        setSessionId(session?.session_id || checkoutReturnContext.sessionId);
        setCallState(AI_CALL_STATES.READY);
        setDraftCart(Array.isArray(session?.draft_cart) ? session.draft_cart : []);
        setDraftTotalCents(Number(session?.draft_total_cents || 0));
        setPendingAction(session?.pending_action || null);
        syncSessionHistory(session);

        const checkoutMessage = getCallCheckoutMessage(language, checkoutReturnContext.status);
        if (checkoutReturnContext.status === "success") {
          await deliverAssistantUpdate(checkoutMessage, language, { speak: true });
        } else if (checkoutReturnContext.status === "cancel") {
          await deliverAssistantUpdate(checkoutMessage, language, { speak: true });
        }
        logAICall("restoreCheckoutReturn:restored", {
          sessionId: session?.session_id || checkoutReturnContext.sessionId,
          draftItems: Array.isArray(session?.draft_cart) ? session.draft_cart.length : 0,
          status: checkoutReturnContext.status,
        });
      } catch (error) {
        logAICallError("restoreCheckoutReturn:error", error, checkoutReturnContext);
        if (!cancelled) {
          setStatusMessage(
            checkoutReturnContext.status === "success"
              ? "Payment completed. Your order was confirmed, but the call session could not be restored."
              : "Payment was cancelled. The call session could not be restored."
          );
        }
      } finally {
        if (!cancelled) onCheckoutReturnHandled?.();
      }
    }

    restoreCallState();

    return () => {
      cancelled = true;
    };
  }, [checkoutReturnContext, onCheckoutReturnHandled]);

  async function playAssistantReply(text, langCode) {
    if (!text) return;

    logAICall("tts:start", { language: langCode, textPreview: text.slice(0, 120) });

    stopListening("tts-start");
    stopAssistantPlayback("replace-reply");
    setCallState(AI_CALL_STATES.SPEAKING);
    setStatusMessage("Assistant is replying");

    let ttsResult;
    try {
      ttsResult = await voiceTTS(text, normalizeCallLanguage(langCode), "kavya");
    } catch (error) {
      logAICallError("tts:error", error, { sessionId: sessionIdRef.current, language: langCode });
      const usedFallback = speakWithBrowserFallback(text, langCode);
      if (!usedFallback) {
        setReadyOrListeningStatus(
          isTimeoutError(error)
            ? "Voice playback timed out. The assistant reply is shown on screen. Speak when you are ready."
            : "Voice playback is unavailable right now. The assistant reply is shown on screen. Speak when you are ready."
        );
      }
      return;
    }
    if (!ttsResult?.audio_base64) {
      logAICall("tts:no-audio", { language: langCode });
      setReadyOrListeningStatus();
      return;
    }

    const blob = base64ToBlob(ttsResult.audio_base64, "audio/wav");
    const url = URL.createObjectURL(blob);
    audioUrlRef.current = url;

    if (!audioRef.current) audioRef.current = new Audio();
    audioRef.current.pause();
    audioRef.current.src = url;
    audioRef.current.onended = () => {
      logAICall("tts:ended", { language: langCode });
      cleanupAudioUrl();
      setReadyOrListeningStatus();
    };
    await audioRef.current.play();
    logAICall("tts:playing", { language: langCode, bytes: blob.size });
  }

  async function fallbackToLocalVoiceMode(session, realtimeError) {
    if (realtimeFallbackInProgressRef.current || realtimeDisconnectingRef.current) {
      return;
    }
    realtimeFallbackInProgressRef.current = true;
    logAICallError("realtime:fallback", realtimeError, { sessionId: session?.session_id });
    setStatusMessage("Realtime AI Call is unavailable. Switching to standard voice mode...");

    try {
      await cleanupRealtimeRuntime({ skipStop: true });
      setIsRealtimeCall(false);
      setRealtimeProviderName("");
      setIsRealtimeMuted(false);
      await connectLocalCall(session);
      setStatusMessage("Switched to standard voice mode. Speak naturally when you are ready.");
    } finally {
      realtimeFallbackInProgressRef.current = false;
    }
  }

  async function connectRealtimeCall(session) {
    const provider = session?.realtime?.provider || {};
    const providerName = String(provider?.name || "vapi").toLowerCase();
    const normalizedLanguage = normalizeCallLanguage(language);
    const assistantId = provider?.assistant_ids?.[normalizedLanguage] || provider?.assistant_id;
    const agentId = provider?.agent_ids?.[normalizedLanguage] || provider?.agent_id;
    const vapiServerUrl = provider?.server_url || "";
    const inlineAssistant = providerName === "vapi" && normalizedLanguage === "en-IN"
      ? buildRealtimeAssistantConfig(normalizedLanguage, session?.session_id, vapiServerUrl)
      : null;
    vapiServerUrlRef.current = vapiServerUrl;
    const assistantOverrides = {
      firstMessage: getCallGreeting(normalizedLanguage),
      firstMessageMode: "assistant-speaks-first",
      "tools:append": buildRealtimeFunctionTools(),
      variableValues: {
        session_id: session?.session_id,
        call_order_session_id: session?.session_id,
        language: normalizedLanguage,
      },
      metadata: {
        sessionId: session?.session_id,
        source: "restaurantai-ai-call",
        language: normalizedLanguage,
      },
    };

    if (providerName === "vapi" && !inlineAssistant && !assistantId) {
      throw new Error(`Realtime AI Call is missing a Vapi assistant for ${normalizedLanguage}.`);
    }
    if (providerName === "retell" && !agentId) {
      throw new Error(`Realtime AI Call is missing a Retell agent for ${normalizedLanguage}.`);
    }

    let retellAccessToken = null;
    if (providerName === "retell") {
      const webCall = await createRetellWebCall({
        session_id: session?.session_id,
        language: normalizedLanguage,
        metadata: {
          sessionId: session?.session_id,
          source: "restaurantai-ai-call",
          language: normalizedLanguage,
        },
      });
      retellAccessToken = webCall?.access_token;
      if (!retellAccessToken) {
        throw new Error("Failed to obtain Retell access token.");
      }
    }

    const runtime = createRealtimeCallRuntime({
      providerName,
      publicKey: provider.public_key,
      assistant: inlineAssistant,
      assistantId,
      assistantOverrides,
      agentId,
      accessToken: retellAccessToken,
      metadata: {
        sessionId: session?.session_id,
        source: "restaurantai-ai-call",
        language: normalizedLanguage,
      },
      onCallStart: () => {
        setCallState(AI_CALL_STATES.LISTENING);
        setStatusMessage("AI Call connected. Speak naturally when you are ready.");
      },
      onCallEnd: () => {
        if (realtimeDisconnectingRef.current) return;
        void disconnectCall({ skipRealtimeStop: true });
      },
      onSpeechStart: () => {
        setCallState(AI_CALL_STATES.SPEAKING);
        setStatusMessage("Assistant is replying");
      },
      onSpeechEnd: () => {
        if (!connectedRef.current) return;
        setCallState(AI_CALL_STATES.LISTENING);
        setStatusMessage("Listening for you. Speak naturally when you are ready.");
      },
      onMessage: handleRealtimeMessage,
      onError: (error) => {
        logAICallError("realtime:error", error, { sessionId: session?.session_id, provider: providerName });
        if (connectedRef.current) {
          void fallbackToLocalVoiceMode(session, error);
          return;
        }
        setCallState(AI_CALL_STATES.ERROR);
        setStatusMessage(error?.message || "Realtime AI Call hit an error.");
      },
    });

    realtimeCallRef.current = runtime;
    realtimeDisconnectingRef.current = false;
    realtimeMismatchHandledRef.current = false;
    realtimeFallbackInProgressRef.current = false;
    handledRealtimeToolCallsRef.current = new Set();
    setIsRealtimeCall(true);
    setIsRealtimeMuted(false);
    setRealtimeProviderName(providerName);
    setIsHandsFreeEnabled(true);
    applyConnectedSession(session, { statusText: "Connecting your AI call...", connectedState: AI_CALL_STATES.READY });

    // Retell tools execute server-side; poll the session to sync the draft cart UI.
    if (providerName === "retell") {
      clearInterval(draftPollRef.current);
      const pollSessionId = session?.session_id;
      draftPollRef.current = setInterval(async () => {
        if (!connectedRef.current || !pollSessionId) return;
        try {
          const snap = await aiCallRealtimeGetDraftSummary(pollSessionId);
          if (snap?.draft) applyDraftSnapshot(snap);
        } catch { /* ignore transient errors */ }
      }, 2000);
    }

    try {
      await runtime.start();
      logAICall("realtime:started", {
        sessionId: session?.session_id,
        provider: providerName,
        assistantId: providerName === "retell"
          ? agentId
          : (inlineAssistant ? "inline-restaurant-assistant" : assistantId),
        language: normalizedLanguage,
      });
      if (providerName === "vapi" && !inlineAssistant) {
        runtime.send({
          type: "add-message",
          message: {
            role: "system",
            content: buildRealtimeAssistantPrompt(normalizedLanguage),
          },
        });
      }
    } catch (error) {
      await cleanupRealtimeRuntime({ skipStop: true });
      setIsRealtimeCall(false);
      setRealtimeProviderName("");
      setIsRealtimeMuted(false);
      throw error;
    }
  }

  async function connectLocalCall(session) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    } });
    mediaStreamRef.current = stream;
    await ensureMicrophoneMonitor(stream);
    setIsRealtimeCall(false);
    setRealtimeProviderName("");
    setIsRealtimeMuted(false);
    setIsHandsFreeEnabled(true);
    applyConnectedSession(session, { statusText: "Your AI call is connected. I am listening when you speak." });
    logAICall("connect:session-ready", {
      sessionId: session?.session_id || "",
      language,
      historyCount: Array.isArray(session?.history) ? session.history.length : 0,
      mode: "local",
    });
    startVoiceMonitor();
    await playAssistantReply(String(session?.assistant_reply || getCallGreeting(language)), language);
  }

  async function connectCall() {
    try {
      logAICall("connect:start", { language });
      const session = await createAICallRealtimeSession({ language });
      const normalizedLanguage = normalizeCallLanguage(language);
      const providerName = String(session?.realtime?.provider?.name || "vapi").toLowerCase();
      if (isRealtimeSessionEnabled(session)) {
        try {
          await connectRealtimeCall(session);
          return;
        } catch (realtimeError) {
          await fallbackToLocalVoiceMode(session, realtimeError);
          return;
        }
      }
      if (normalizedLanguage === "ta-IN" && session?.realtime?.enabled) {
        setStatusMessage(`Tamil AI Call currently uses the local Sarvam voice path because ${providerName} does not support Tamil well enough yet.`);
      }
      if (session?.realtime?.enabled && Array.isArray(session?.realtime?.provider?.missing_fields) && session.realtime.provider.missing_fields.length > 0) {
        setStatusMessage(
          `Realtime AI Call is enabled but missing ${providerName} ${session.realtime.provider.missing_fields.join(", ")}. Falling back to local voice mode.`
        );
      }
      await connectLocalCall(session);
    } catch (error) {
      logAICallError("connect:error", error, { language });
      setCallState(AI_CALL_STATES.ERROR);
      if (isMicrophoneError(error)) {
        setStatusMessage(
          error?.name === "NotAllowedError"
            ? "Microphone access is blocked. Enable it to use AI Call."
            : "Microphone is not available on this device."
        );
      } else if (isBackendConnectionError(error)) {
        setStatusMessage("Unable to reach backend. Check API base URL and network connectivity.");
      } else {
        setStatusMessage(error?.message || "Unable to start AI Call.");
      }
    }
  }

  async function disconnectCall({ skipRealtimeStop = false, finalStatusMessage = "Call ended. You can start again anytime." } = {}) {
    logAICall("disconnect", {
      sessionId: sessionIdRef.current,
      messageCount: messagesRef.current.length,
      draftItems: draftCart.length,
      realtime: realtimeModeRef.current,
    });

    realtimeDisconnectingRef.current = true;
    clearInterval(draftPollRef.current);
    draftPollRef.current = null;
    clearMonitorLoop();
    try {
      ignoreNextStopRef.current = true;
      mediaRecorderRef.current?.stop();
    } catch {
      // ignore stop errors during disconnect
    }
    mediaRecorderRef.current = null;
    speechDetectedRef.current = false;
    lastSpeechAtRef.current = 0;
    recorderStartedAtRef.current = 0;
    turnInFlightRef.current = false;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    stopAssistantPlayback("disconnect");
    await cleanupRealtimeRuntime({ skipStop: skipRealtimeStop });
    setIsConnected(false);
    setIsHandsFreeEnabled(true);
    setIsRealtimeCall(false);
    setIsRealtimeMuted(false);
    setRealtimeProviderName("");
    sessionIdRef.current = "";
    setSessionId("");
    setCallState(AI_CALL_STATES.IDLE);
    setLatestTranscript("");
    setSuggestions([]);
    setDraftCart([]);
    setDraftTotalCents(0);
    setPendingAction(null);
    messagesRef.current = [];
    setMessages([]);
    setStatusMessage(finalStatusMessage);
    realtimeDisconnectingRef.current = false;
    realtimeMismatchHandledRef.current = false;
    handledRealtimeToolCallsRef.current = new Set();
    knownRestaurantIdsRef.current = new Set();
    knownItemIdsRef.current = new Map();
    toolQueueRef.current = Promise.resolve();
  }

  async function handleRecordingStop(blob, hadSpeech) {
    logAICall("recording:stopped", {
      sessionId: sessionIdRef.current,
      size: blob?.size || 0,
      type: blob?.type || "unknown",
      hadSpeech,
    });
    if (!hadSpeech) {
      logAICall("recording:no-speech", { sessionId: sessionIdRef.current });
      setReadyOrListeningStatus("Listening for you. Speak naturally when you are ready.");
      return;
    }
    if (!blob || blob.size === 0) {
      logAICall("recording:empty", { sessionId: sessionIdRef.current });
      setReadyOrListeningStatus("I could not hear anything clearly. Speak again when you are ready.");
      return;
    }

    turnInFlightRef.current = true;
    setCallState(AI_CALL_STATES.PROCESSING);
    setStatusMessage("Transcribing your voice");

    try {
      logAICall("stt:request", { sessionId: sessionIdRef.current, language: normalizeCallLanguage(language), bytes: blob.size });
      const stt = await voiceSTT(blob, normalizeCallLanguage(language));
      const transcript = String(stt?.transcript || "").trim();
      logAICall("stt:response", { sessionId: sessionIdRef.current, transcript, detectedLanguage: stt?.language || null });
      if (!transcript) {
        logAICall("stt:empty-transcript", { sessionId: sessionIdRef.current });
        setReadyOrListeningStatus("I could not catch that clearly. Speak again when you are ready.");
        return;
      }

      setLatestTranscript(transcript);
      appendMessage("user", transcript);
      setStatusMessage("Generating a natural reply");

      logAICall("turn:request", { sessionId: sessionIdRef.current, transcript });
      const replyResult = await callOrderTurn(sessionIdRef.current, transcript);
      const replyText = String(replyResult?.assistant_reply || "").trim();
      logAICall("turn:response", {
        sessionId: sessionIdRef.current,
        replyPreview: replyText.slice(0, 120),
        suggestions: Array.isArray(replyResult?.suggestions) ? replyResult.suggestions.map((item) => item.name) : [],
        draftItems: Array.isArray(replyResult?.draft_cart) ? replyResult.draft_cart.length : 0,
        pendingAction: replyResult?.pending_action?.type || null,
      });
      if (!replyText) {
        setReadyOrListeningStatus("The assistant could not respond. Please try again.");
        return;
      }

      lastAssistantReplyRef.current = replyText;
      setSuggestions(Array.isArray(replyResult?.suggestions) ? replyResult.suggestions : []);
  setDraftCart(Array.isArray(replyResult?.draft_cart) ? replyResult.draft_cart : []);
  setDraftTotalCents(Number(replyResult?.draft_total_cents || 0));
  setPendingAction(replyResult?.pending_action || null);
      if (Array.isArray(replyResult?.history)) {
        messagesRef.current = replyResult.history.map((entry, index) => ({
          id: `${entry.role}-${index}-${Date.now()}`,
          role: entry.role === "assistant" ? "assistant" : "user",
          text: entry.text,
          createdAt: new Date().toISOString(),
        }));
        setMessages(messagesRef.current);
      } else {
        appendMessage("assistant", replyText);
      }
      await playAssistantReply(replyText, language);
    } catch (error) {
      logAICallError("turn:error", error, { sessionId: sessionIdRef.current });
      if (isTimeoutError(error)) {
        setReadyOrListeningStatus("Voice processing timed out. Please try that again.");
      } else {
        setCallState(AI_CALL_STATES.ERROR);
        setStatusMessage(error?.message || "The AI call hit an error.");
      }
    } finally {
      turnInFlightRef.current = false;
    }
  }

  async function beginListening(reason = "manual") {
    if (realtimeModeRef.current) return;
    if (!connectedRef.current || !sessionIdRef.current || mediaRecorderRef.current || finalizingRef.current || turnInFlightRef.current) return;
    if (callStateRef.current === AI_CALL_STATES.PROCESSING) return;
    try {
      logAICall("recording:start", { sessionId: sessionIdRef.current, callState: callStateRef.current, language, reason });
      if (!mediaStreamRef.current) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        } });
        mediaStreamRef.current = stream;
        await ensureMicrophoneMonitor(stream);
      }
      if (audioRef.current && !audioRef.current.paused) {
        logAICall("recording:barge-in", { sessionId: sessionIdRef.current });
        stopAssistantPlayback("barge-in");
      }
      const mimeType = pickRecorderMimeType();
      const recorder = mimeType ? new MediaRecorder(mediaStreamRef.current, { mimeType }) : new MediaRecorder(mediaStreamRef.current);

      chunksRef.current = [];
      mediaRecorderRef.current = recorder;
      speechDetectedRef.current = false;
      lastSpeechAtRef.current = 0;
      recorderStartedAtRef.current = Date.now();
      setCallState(AI_CALL_STATES.LISTENING);
      setStatusMessage("Listening. Speak naturally and I will continue the conversation.");

      recorder.ondataavailable = (event) => {
        if (event.data?.size) chunksRef.current.push(event.data);
        logAICall("recording:data", { sessionId: sessionIdRef.current, chunkBytes: event.data?.size || 0 });
      };
      recorder.onstop = async () => {
        if (ignoreNextStopRef.current) {
          logAICall("recording:stop-ignored", { sessionId: sessionIdRef.current });
          ignoreNextStopRef.current = false;
          chunksRef.current = [];
          return;
        }
        const hadSpeech = speechDetectedRef.current;
        speechDetectedRef.current = false;
        lastSpeechAtRef.current = 0;
        recorderStartedAtRef.current = 0;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        mediaRecorderRef.current = null;
        await handleRecordingStop(blob, hadSpeech);
      };
      recorder.start();
    } catch (error) {
      logAICallError("recording:start-error", error, { sessionId: sessionIdRef.current, language });
      setCallState(AI_CALL_STATES.ERROR);
      setStatusMessage(error?.message || "Unable to start recording.");
    }
  }

  function stopListening(reason = "manual") {
    if (realtimeModeRef.current) return;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
      logAICall(reason === "manual" ? "recording:manual-stop" : "recording:auto-stop", { sessionId: sessionIdRef.current, reason });
      mediaRecorderRef.current.stop();
      setCallState(AI_CALL_STATES.PROCESSING);
      setStatusMessage("Finishing your voice turn");
    }
  }

  function toggleHandsFreeListening() {
    if (!isConnected) return;
    if (realtimeModeRef.current) {
      const runtime = realtimeCallRef.current;
      if (!runtime) return;
      const nextMuted = !isRealtimeMuted;
      runtime.setMuted(nextMuted);
      setIsRealtimeMuted(nextMuted);
      setCallState(nextMuted ? AI_CALL_STATES.READY : AI_CALL_STATES.LISTENING);
      setStatusMessage(
        nextMuted
          ? "Microphone muted. Unmute when you want to speak again."
          : "Listening for you. Speak naturally when you are ready."
      );
      return;
    }
    if (isHandsFreeEnabled) {
      setIsHandsFreeEnabled(false);
      return;
    }
    setIsHandsFreeEnabled(true);
    startVoiceMonitor();
  }

  async function repeatLastReply() {
    if (!lastAssistantReplyRef.current) return;
    try {
      logAICall("tts:repeat-last-reply", { sessionId: sessionIdRef.current, textPreview: lastAssistantReplyRef.current.slice(0, 80) });
      if (realtimeModeRef.current && realtimeCallRef.current) {
        realtimeCallRef.current.say(lastAssistantReplyRef.current);
        return;
      }
      await playAssistantReply(lastAssistantReplyRef.current, language);
    } catch (error) {
      logAICallError("tts:repeat-error", error, { sessionId: sessionIdRef.current });
      setCallState(AI_CALL_STATES.ERROR);
      setStatusMessage(error?.message || "Unable to replay the last reply.");
    }
  }

  function syncSessionHistory(result) {
    const history = Array.isArray(result?.history) ? result.history : [];
    messagesRef.current = mapHistory(history);
    setMessages(messagesRef.current);
    const replyText = String(result?.assistant_reply || "").trim();
    if (replyText) lastAssistantReplyRef.current = replyText;
  }

  async function finalizeDraft(startCheckout = false) {
    if (!sessionId || draftCart.length === 0 || isFinalizing) return;
    if (!token) {
      logAICall("finalize:missing-auth", { sessionId, startCheckout, draftItems: draftCart.length });
      setStatusMessage("Sign in to move this draft into your cart.");
      onRequireAuth?.();
      return;
    }

    setIsFinalizing(true);
    finalizingRef.current = true;
    setStatusMessage(startCheckout ? "Moving your draft into the cart and starting checkout" : "Moving your draft into the cart");

    try {
      logAICall("finalize:start", { sessionId, startCheckout, draftItems: draftCart.length });
      const result = await finalizeCallOrderSession(token, sessionId);
      syncSessionHistory(result);
      setDraftCart(Array.isArray(result?.draft_cart) ? result.draft_cart : []);
      setDraftTotalCents(Number(result?.draft_total_cents || 0));
      setPendingAction(result?.pending_action || null);

      const cart = await fetchCart(token);
      onCartUpdated?.(cart);
      logAICall("finalize:cart-updated", {
        sessionId,
        materializedItems: result?.materialized_item_count || 0,
        materializedRestaurants: result?.materialized_restaurant_count || 0,
        startCheckout,
      });

      if (!startCheckout) {
        setStatusMessage("Draft moved into your cart. You can keep talking or open checkout from the cart.");
        return;
      }

      const checkoutResult = await createCheckoutSession(token);
      logAICall("finalize:checkout-session", {
        sessionId,
        checkoutSessionId: checkoutResult?.session_id || null,
        redirected: Boolean(checkoutResult?.checkout_url && checkoutResult?.session_id !== "sim_dev"),
      });
      if (checkoutResult?.checkout_url && checkoutResult?.session_id !== "sim_dev") {
        localStorage.setItem("aiCallCheckoutContext", JSON.stringify({ sessionId }));
        window.location.href = checkoutResult.checkout_url;
        return;
      }

      localStorage.removeItem("aiCallCheckoutContext");

      await onOrdersUpdated?.();
      const updatedCart = await fetchCart(token);
      onCartUpdated?.(updatedCart);
      await deliverAssistantUpdate(getCallCheckoutMessage(language, "success"), language, { speak: true });
    } catch (error) {
      logAICallError("finalize:error", error, { sessionId, startCheckout, draftItems: draftCart.length });
      localStorage.removeItem("aiCallCheckoutContext");
      setStatusMessage(error?.message || "Unable to finalize your draft order.");
    } finally {
      finalizingRef.current = false;
      setIsFinalizing(false);
    }
  }

  return (
    <div className="ai-call-page">
      <motion.section
        className="ai-call-hero"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
      >
        <div className="ai-call-eyebrow">Separate voice-first ordering lane</div>
        <div className="ai-call-header-row">
          <div>
            <h1 className="ai-call-title">AI Call</h1>
            <p className="ai-call-subtitle">
              Order from any restaurant by voice. Mix items from multiple places in one call.
            </p>
          </div>
          <div className={`ai-call-status ai-call-status-${callState}`}>
            <span className="ai-call-status-dot" />
            <span>{getCallStateLabel(callState)}</span>
          </div>
        </div>

        <div className="ai-call-language-switch">
          <button
            className={`ai-call-language-btn ${language === "en-IN" ? "active" : ""}`}
            onClick={() => setLanguage("en-IN")}
          >
            English
          </button>
          <button
            className={`ai-call-language-btn ${language === "ta-IN" ? "active" : ""}`}
            onClick={() => setLanguage("ta-IN")}
          >
            Tamil
          </button>
        </div>

        <div className="ai-call-actions">
          {!isConnected ? (
            <button className="ai-call-primary" onClick={connectCall}>Start AI Call</button>
          ) : (
            <>
              <button
                className={`ai-call-primary ${callState === AI_CALL_STATES.LISTENING ? "listening" : ""}`}
                onClick={toggleHandsFreeListening}
              >
                {isRealtimeCall ? (isRealtimeMuted ? "Unmute Mic" : "Mute Mic") : (isHandsFreeEnabled ? "Pause Mic" : "Speak")}
              </button>
              <button className="ai-call-secondary" onClick={repeatLastReply}>Repeat Reply</button>
              <button className="ai-call-danger" onClick={disconnectCall}>End Call</button>
            </>
          )}
        </div>

        <div className="ai-call-status-copy">{statusMessage}</div>
      </motion.section>

      <section className="ai-call-grid">
        <motion.div
          className="ai-call-panel ai-call-cart-panel"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.25 }}
        >
          <div className="ai-call-panel-title">Your order</div>

          {draftCart.length === 0 ? (
            <div className="ai-call-cart-empty">
              <div className="ai-call-cart-empty-icon">🛒</div>
              <div className="ai-call-cart-empty-text">
                {isConnected
                  ? "Tell the assistant what you'd like to order. Items will appear here."
                  : "Start a call and order by voice. Your items will show up here."}
              </div>
            </div>
          ) : (
            <>
              <div className="ai-call-cart-items-scroll">
                {(() => {
                  const grouped = {};
                  draftCart.forEach((item) => {
                    const rName = item.restaurant_name || "Unknown";
                    if (!grouped[rName]) grouped[rName] = [];
                    grouped[rName].push(item);
                  });
                  return Object.entries(grouped).map(([restaurantName, items]) => (
                    <div key={restaurantName} className="ai-call-cart-group">
                      <div className="ai-call-cart-restaurant">{restaurantName}</div>
                      {items.map((item) => (
                        <div key={`draft-${item.id}`} className="ai-call-cart-item">
                          <div className="ai-call-cart-item-qty">{item.quantity}x</div>
                          <div className="ai-call-cart-item-info">
                            <div className="ai-call-cart-item-name">{item.name}</div>
                          </div>
                          <div className="ai-call-cart-item-price">&#8377;{((item.price_cents * item.quantity) / 100).toFixed(0)}</div>
                        </div>
                      ))}
                    </div>
                  ));
                })()}
              </div>

              <div className="ai-call-cart-total">
                <span>Total</span>
                <strong>&#8377;{(draftTotalCents / 100).toFixed(0)}</strong>
              </div>
            </>
          )}

          {pendingAction?.type === "add_item" && pendingAction?.item && (
            <div className="ai-call-pending-note">
              Confirming: {pendingAction.quantity} x {pendingAction.item.name}
            </div>
          )}

          {draftCart.length > 0 && (
            <div className="ai-call-cart-actions">
              <button className="ai-call-secondary" onClick={() => finalizeDraft(false)} disabled={isFinalizing}>
                {isFinalizing ? "Working..." : "Move to Cart"}
              </button>
              <button className="ai-call-primary" onClick={() => finalizeDraft(true)} disabled={isFinalizing}>
                {isFinalizing ? "Working..." : "Checkout"}
              </button>
            </div>
          )}

          {!token && draftCart.length > 0 && (
            <div className="ai-call-auth-note">
              Sign in to move items to your cart and checkout.
            </div>
          )}
        </motion.div>

        <motion.div
          className="ai-call-panel ai-call-transcript-panel"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.25 }}
        >
          <div className="ai-call-panel-title">Call transcript</div>
          {latestTranscript && <div className="ai-call-live-transcript">{latestTranscript}</div>}
          <div className="ai-call-transcript-list">
            {messages.length === 0 && <div className="ai-call-empty">Start the call to see the conversation appear here.</div>}
            {messages.map((message) => (
              <div key={message.id} className={`ai-call-bubble ai-call-bubble-${message.role}`}>
                <div className="ai-call-bubble-role">{message.role === "assistant" ? "AI" : "You"}</div>
                <div>{message.text}</div>
              </div>
            ))}
            <div ref={transcriptEndRef} />
          </div>
        </motion.div>
      </section>
    </div>
  );
}
