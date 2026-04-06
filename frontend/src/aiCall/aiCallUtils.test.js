import { describe, expect, it } from "vitest";
import {
  AI_CALL_STATES,
  buildRealtimeAssistantConfig,
  buildRealtimeFunctionTools,
  buildRealtimeAssistantPrompt,
  buildCallContext,
  createTurn,
  extractRealtimeToolCalls,
  getCallCheckoutMessage,
  getCallGreeting,
  getCallStateLabel,
  getWrongDomainAssistantMessage,
  isLikelyWrongDomainAssistant,
  normalizeCallLanguage,
  parseRealtimeToolArguments,
} from "./aiCallUtils.js";

describe("aiCallUtils", () => {
  it("normalizes Tamil and English language codes", () => {
    expect(normalizeCallLanguage("ta")).toBe("ta-IN");
    expect(normalizeCallLanguage("ta-IN")).toBe("ta-IN");
    expect(normalizeCallLanguage("english")).toBe("en-IN");
  });

  it("returns stable state labels", () => {
    expect(getCallStateLabel(AI_CALL_STATES.LISTENING)).toBe("Listening");
    expect(getCallStateLabel(AI_CALL_STATES.PROCESSING)).toBe("Understanding your order");
  });

  it("builds a constrained call context with recent messages", () => {
    const context = buildCallContext([
      { role: "user", text: "I want biryani" },
      { role: "assistant", text: "Which restaurant would you like?" },
    ], "en-IN");

    expect(context).toContain("Preferred language: en-IN.");
    expect(context).toContain("User: I want biryani");
    expect(context).toContain("Assistant: Which restaurant would you like?");
  });

  it("creates a turn payload with role and text", () => {
    const turn = createTurn("user", "Parotta");
    expect(turn.role).toBe("user");
    expect(turn.text).toBe("Parotta");
    expect(turn.id).toContain("user-");
  });

  it("returns localized greetings", () => {
    expect(getCallGreeting("en-IN")).toContain("AI food ordering assistant");
    expect(getCallGreeting("ta-IN")).toContain("உணவு ஆர்டர்");
  });

  it("builds a realtime prompt constrained to restaurant ordering", () => {
    const prompt = buildRealtimeAssistantPrompt("en-IN");
    expect(prompt).toContain("RestaurantAI");
    expect(prompt).toContain("food-ordering domain");
    expect(prompt).toContain("clinic");
    expect(prompt).toContain("restaurant and menu tools");
  });

  it("builds realtime function tools for restaurant and cart access", () => {
    const tools = buildRealtimeFunctionTools();
    expect(tools.map((tool) => tool.function?.name)).toEqual([
      "list_restaurants",
      "find_restaurants",
      "get_restaurant_menu",
      "get_draft_summary",
      "add_draft_item",
      "remove_draft_item",
      "finalize_draft_to_cart",
      "start_checkout",
    ]);
  });

  it("builds an inline realtime assistant config for restaurant ordering", () => {
    const assistant = buildRealtimeAssistantConfig("en-IN", "session-123");
    expect(assistant.firstMessage).toContain("AI food ordering assistant");
    expect(assistant.transcriber).toMatchObject({ provider: "deepgram", language: "en-IN" });
    expect(assistant.voice).toMatchObject({ provider: "vapi", voiceId: "Neha" });
    expect(assistant.model).toMatchObject({ provider: "openai", model: "gpt-4o-mini" });
    expect(assistant.model.tools.map((tool) => tool.function?.name)).toContain("list_restaurants");
    expect(assistant.metadata).toMatchObject({ sessionId: "session-123" });
  });

  it("detects clearly wrong-domain assistant replies", () => {
    expect(isLikelyWrongDomainAssistant("Thank you for calling Wellness Partners. This is Riley, your scheduling assistant.")).toBe(true);
    expect(isLikelyWrongDomainAssistant("This is a health clinic for medical appointments.")).toBe(true);
    expect(isLikelyWrongDomainAssistant("I can help you order biryani or dosa.")).toBe(false);
  });

  it("parses realtime tool arguments safely", () => {
    expect(parseRealtimeToolArguments('{"item_id": 12, "quantity": 2}')).toEqual({ item_id: 12, quantity: 2 });
    expect(parseRealtimeToolArguments("not-json")).toEqual({});
    expect(parseRealtimeToolArguments("")).toEqual({});
  });

  it("extracts realtime tool calls from Vapi-style messages", () => {
    const toolCalls = extractRealtimeToolCalls({
      message: {
        tool_calls: [
          {
            id: "call_123",
            type: "function",
            function: {
              name: "add_draft_item",
              arguments: '{"item_id": 77, "quantity": 1}',
            },
          },
        ],
      },
    });

    expect(toolCalls).toEqual([
      {
        id: "call_123",
        type: "function",
        name: "add_draft_item",
        arguments: { item_id: 77, quantity: 1 },
      },
    ]);
  });

  it("returns a clear mismatch message for Vapi misconfiguration", () => {
    expect(getWrongDomainAssistantMessage()).toContain("configured Vapi assistant");
    expect(getWrongDomainAssistantMessage()).toContain("restaurant-ordering assistant");
  });

  it("returns localized checkout completion copy", () => {
    expect(getCallCheckoutMessage("en-IN", "success")).toContain("order is confirmed");
    expect(getCallCheckoutMessage("ta-IN", "cancel")).toContain("கட்டணம் ரத்து செய்யப்பட்டது");
  });
});
