export const AI_CALL_STATES = {
  IDLE: "idle",
  READY: "ready",
  LISTENING: "listening",
  PROCESSING: "processing",
  SPEAKING: "speaking",
  ERROR: "error",
};

export function normalizeCallLanguage(language) {
  return String(language || "").toLowerCase().startsWith("ta") ? "ta-IN" : "en-IN";
}

export function getCallGreeting(language) {
  return normalizeCallLanguage(language) === "ta-IN"
    ? "வணக்கம். நான் உங்கள் உணவு ஆர்டர் உதவியாளர். என்ன சாப்பிட விரும்புகிறீர்கள்?"
    : "Hello. I am your AI food ordering assistant. What would you like to eat today?";
}

const VAPI_VOICES = {
  "en-IN": ["Neha", "Rohan"],
  "ta-IN": ["Kylie", "Cole"],
};

function pickRandomVoice(language) {
  const voices = VAPI_VOICES[language] || VAPI_VOICES["en-IN"];
  return voices[Math.floor(Math.random() * voices.length)];
}

export function buildRealtimeAssistantPrompt(language) {
  const preferredLanguage = normalizeCallLanguage(language);
  const languageInstruction = preferredLanguage === "ta-IN"
    ? "Respond in Tamil unless the caller clearly switches languages."
    : "Respond in English suitable for Indian restaurant ordering calls.";

  return [
    "You are RestaurantAI, a voice assistant for restaurant discovery, menu guidance, food ordering, and checkout handoff.",
    languageInstruction,
    "Stay in the food-ordering domain at all times.",
    "Use the available restaurant and menu tools to answer factual questions about restaurants, dishes, categories, prices, and cart contents.",
    "When the caller asks what restaurants are available, what options exist, or asks for a list of restaurants, call list_restaurants.",
    "Do not answer restaurant-specific or menu-specific questions from memory when a tool can verify the answer from the database.",
    "Do not present yourself as a clinic, scheduling, wellness, healthcare, banking, or generic support assistant.",
    "Keep replies short, natural, and action-oriented.",
    "IMPORTANT: Multi-restaurant ordering IS fully supported. The caller can add items from different restaurants into the same draft order. Never refuse or warn about mixing restaurants. Simply use add_draft_item with the correct item_id regardless of which restaurant it belongs to.",
    "",
    "=== STRICT TOOL CALL RULES (VIOLATIONS WILL CAUSE ERRORS) ===",
    "Rule 1: NEVER call get_restaurant_menu unless you have ALREADY received a successful response from find_restaurants or list_restaurants containing the restaurant_id you want to use.",
    "Rule 2: NEVER call add_draft_item unless you have ALREADY received a successful response from get_restaurant_menu containing the item_id you want to use.",
    "Rule 3: NEVER call get_restaurant_menu and find_restaurants at the same time. Call find_restaurants FIRST, wait for the result, THEN call get_restaurant_menu.",
    "Rule 4: NEVER call add_draft_item at the same time as get_restaurant_menu. Get the menu FIRST, wait for the result, THEN call add_draft_item.",
    "Rule 5: Only make ONE tool call at a time. Wait for each tool result before making the next call.",
    "Rule 6: ALL IDs (restaurant_id, item_id) MUST come from a previous tool result. NEVER guess, invent, or assume any ID.",
    "",
    "=== ERROR HANDLING (CRITICAL) ===",
    "If ANY tool result contains 'status: FAILED' or 'error', you MUST:",
    "- Tell the caller the action failed and explain why.",
    "- NEVER say an item was added if the tool returned an error.",
    "- NEVER pretend the action succeeded.",
    "- Follow instructions in the 'instruction' field of the error response.",
    "- If add_draft_item failed, check the 'available_items' field for valid items.",
    "",
    "Maximum quantity per add_draft_item call is 20. If the caller wants more than 20, tell them the maximum per order is 20.",
    "Help the caller choose a restaurant, clarify dishes, confirm adds or removes, summarize the draft order, and move toward checkout.",
    "When reading prices to the caller, convert cents to the currency format naturally (e.g. 16000 cents = 160 rupees). Do not read raw cent values.",
    "Do not read out item IDs or restaurant IDs to the caller. Just use names.",
    "If the caller's request is ambiguous, ask one short follow-up question instead of guessing.",
  ].join("\n");
}

export function buildRealtimeFunctionTools() {
  // async: true tells Vapi's server NOT to wait for a server webhook result.
  // The client executes the tool and sends the result via add-message with
  // role="tool" and triggerResponseEnabled=true, which injects the result
  // into the conversation and triggers the model to generate a response
  // that uses the tool data.
  return [
    {
      type: "function",
      async: true,
      function: {
        name: "list_restaurants",
        description: "List available restaurants from the live database when the caller asks what restaurants or options are available.",
        parameters: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Optional cuisine, city, or restaurant-name filter.",
            },
            limit: {
              type: "number",
              description: "Maximum number of restaurants to return.",
            },
          },
        },
      },
    },
    {
      type: "function",
      async: true,
      function: {
        name: "find_restaurants",
        description: "Find restaurant matches from the user query before answering restaurant-specific questions.",
        parameters: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Restaurant name or cuisine query from the caller.",
            },
          },
          required: ["query"],
        },
      },
    },
    {
      type: "function",
      async: true,
      function: {
        name: "get_restaurant_menu",
        description: "Get menu categories and matching menu items for a restaurant. PREREQUISITE: You must have already received a response from find_restaurants or list_restaurants. The restaurant_id parameter MUST be an exact integer 'id' from that response. Never guess this value. Never call this at the same time as find_restaurants.",
        parameters: {
          type: "object",
          properties: {
            restaurant_id: {
              type: "integer",
              description: "The exact integer restaurant ID returned by list_restaurants or find_restaurants. Never guess this value.",
            },
            restaurant_name: {
              type: "string",
              description: "The name of the restaurant you are querying the menu for (e.g. 'Aroma'). Required for verification.",
            },
            query: {
              type: "string",
              description: "Optional dish, category, or menu question such as naan, biryani, starters, desserts, or veg options.",
            },
          },
          required: ["restaurant_id", "restaurant_name"],
        },
      },
    },
    {
      type: "function",
      async: true,
      function: {
        name: "get_draft_summary",
        description: "Get the current draft cart summary from the live session state.",
        parameters: {
          type: "object",
          properties: {},
        },
      },
    },
    {
      type: "function",
      async: true,
      function: {
        name: "add_draft_item",
        description: "Add a menu item to the draft cart. PREREQUISITE: You must have already received a response from get_restaurant_menu. The item_id MUST be an exact integer 'id' from that menu response. You MUST also pass item_name (the exact name string from the menu) and restaurant_id. Never guess or invent item IDs. Never call this at the same time as get_restaurant_menu. If this tool returns an error, you MUST tell the caller it failed. Maximum quantity is 20.",
        parameters: {
          type: "object",
          properties: {
            item_id: {
              type: "integer",
              description: "The exact integer item ID from a get_restaurant_menu response.",
            },
            item_name: {
              type: "string",
              description: "The exact item name string from the menu response (e.g. 'Chicken Biryani'). Required for verification.",
            },
            restaurant_id: {
              type: "integer",
              description: "The restaurant_id this item belongs to, from the get_restaurant_menu response.",
            },
            quantity: {
              type: "integer",
              description: "Quantity to add (default 1, maximum 20). For larger quantities, call this tool multiple times.",
            },
          },
          required: ["item_id", "item_name", "restaurant_id"],
        },
      },
    },
    {
      type: "function",
      async: true,
      function: {
        name: "remove_draft_item",
        description: "Remove a menu item from the draft cart. Use the same item_id and item_name that was used in add_draft_item.",
        parameters: {
          type: "object",
          properties: {
            item_id: {
              type: "integer",
              description: "The exact integer item ID to remove.",
            },
            item_name: {
              type: "string",
              description: "The exact item name string for verification.",
            },
            restaurant_id: {
              type: "integer",
              description: "The restaurant_id this item belongs to.",
            },
            quantity: {
              type: "integer",
              description: "Quantity to remove (default 1).",
            },
          },
          required: ["item_id"],
        },
      },
    },
    {
      type: "function",
      async: true,
      function: {
        name: "finalize_draft_to_cart",
        description: "Move the confirmed draft order into the authenticated application cart.",
        parameters: {
          type: "object",
          properties: {},
        },
      },
    },
    {
      type: "function",
      async: true,
      function: {
        name: "start_checkout",
        description: "Start checkout after the user confirms they are ready to pay.",
        parameters: {
          type: "object",
          properties: {},
        },
      },
    },
  ];
}

export function buildRealtimeAssistantConfig(language, sessionId = "", serverUrl = "") {
  const normalizedLanguage = normalizeCallLanguage(language);
  const config = {
    firstMessage: getCallGreeting(normalizedLanguage),
    firstMessageMode: "assistant-speaks-first",
    transcriber: {
      provider: "deepgram",
      model: "nova-2",
      language: normalizedLanguage,
      endpointing: 300,
    },
    voice: {
      provider: "vapi",
      voiceId: pickRandomVoice(normalizedLanguage),
      speed: 1,
    },
    silenceTimeoutSeconds: 30,
    numWordsToInterruptAssistant: 3,
    backgroundDenoisingEnabled: true,
    model: {
      provider: "openai",
      model: "gpt-4o-mini",
      messages: [
        {
          role: "system",
          content: buildRealtimeAssistantPrompt(normalizedLanguage),
        },
      ],
      tools: buildRealtimeFunctionTools(),
    },
    clientMessages: [
      "conversation-update",
      "model-output",
      "speech-update",
      "status-update",
      "transcript",
      "tool-calls",
      "tool-calls-result",
      "user-interrupted",
      "voice-input",
      "assistant.started",
    ],
    serverMessages: [],
    backgroundSound: "off",
    maxDurationSeconds: 600,
    metadata: {
      source: "restaurantai-ai-call",
      language: normalizedLanguage,
      sessionId,
    },
  };

  // When a server URL is configured, Vapi will POST tool calls there and
  // receive results via the HTTP response — the reliable path.
  if (serverUrl) {
    config.server = { url: serverUrl };
    config.serverMessages = ["tool-calls"];
  }

  return config;
}

export function parseRealtimeToolArguments(argumentsText) {
  if (typeof argumentsText !== "string" || !argumentsText.trim()) {
    return {};
  }
  try {
    const parsed = JSON.parse(argumentsText);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function extractRealtimeToolCalls(message) {
  const candidates = [
    ...(Array.isArray(message?.tool_calls) ? message.tool_calls : []),
    ...(Array.isArray(message?.toolCalls) ? message.toolCalls : []),
    ...(Array.isArray(message?.message?.tool_calls) ? message.message.tool_calls : []),
    ...(Array.isArray(message?.message?.toolCalls) ? message.message.toolCalls : []),
    ...(Array.isArray(message?.artifact?.tool_calls) ? message.artifact.tool_calls : []),
    ...(Array.isArray(message?.artifact?.toolCalls) ? message.artifact.toolCalls : []),
    ...((Array.isArray(message?.messages) ? message.messages : []).flatMap((entry) => [
      ...(Array.isArray(entry?.tool_calls) ? entry.tool_calls : []),
      ...(Array.isArray(entry?.toolCalls) ? entry.toolCalls : []),
    ])),
  ];

  return candidates
    .map((toolCall) => {
      const id = String(toolCall?.id || "").trim();
      const name = String(toolCall?.function?.name || toolCall?.name || "").trim();
      if (!id || !name) return null;
      return {
        id,
        type: String(toolCall?.type || "function"),
        name,
        arguments: parseRealtimeToolArguments(toolCall?.function?.arguments || toolCall?.arguments),
      };
    })
    .filter(Boolean);
}

export function isLikelyWrongDomainAssistant(text) {
  const normalizedText = String(text || "").trim().toLowerCase();
  if (!normalizedText) return false;

  const directMismatchPhrases = [
    "wellness partners",
    "scheduling assistant",
    "medical appointments",
    "health clinic",
    "reached the wrong number",
  ];
  if (directMismatchPhrases.some((phrase) => normalizedText.includes(phrase))) {
    return true;
  }

  const healthcareSignals = ["medical", "appointment", "clinic", "wellness", "scheduler", "scheduling"];
  const matchedSignalCount = healthcareSignals.filter((signal) => normalizedText.includes(signal)).length;
  return matchedSignalCount >= 2;
}

export function getWrongDomainAssistantMessage() {
  return "Realtime AI Call stopped because the configured Vapi assistant is not a restaurant-ordering assistant. Update the Vapi assistant and try again.";
}

export function getCallCheckoutMessage(language, status) {
  const preferredLanguage = normalizeCallLanguage(language);
  if (preferredLanguage === "ta-IN") {
    if (status === "success") {
      return "உங்கள் கட்டணம் வெற்றிகரமாக முடிந்தது. ஆர்டர் உறுதியாகியுள்ளது. இன்னும் ஏதேனும் வேண்டும் என்றால் சொல்லுங்கள்.";
    }
    return "கட்டணம் ரத்து செய்யப்பட்டது. நீங்கள் உறுதிப்படுத்திய பொருட்கள் இன்னும் உங்கள் கார்டில் உள்ளன.";
  }

  if (status === "success") {
    return "Your payment is complete and the order is confirmed. If you need anything else, you can continue the call.";
  }
  return "The payment was cancelled. Your confirmed items are still waiting in the cart if you want to continue.";
}

export function getCallStateLabel(state) {
  switch (state) {
    case AI_CALL_STATES.READY:
      return "Ready to talk";
    case AI_CALL_STATES.LISTENING:
      return "Listening";
    case AI_CALL_STATES.PROCESSING:
      return "Understanding your order";
    case AI_CALL_STATES.SPEAKING:
      return "Speaking";
    case AI_CALL_STATES.ERROR:
      return "Needs attention";
    case AI_CALL_STATES.IDLE:
    default:
      return "Call not started";
  }
}

export function buildCallContext(messages, language) {
  const preferredLanguage = normalizeCallLanguage(language);
  const transcript = (Array.isArray(messages) ? messages : [])
    .slice(-6)
    .map((message) => `${message.role === "user" ? "User" : "Assistant"}: ${message.text}`)
    .join("\n");

  return [
    `Preferred language: ${preferredLanguage}.`,
    "This is a voice-first food ordering call.",
    "Reply naturally, ask one short question at a time, and avoid saying an item is unavailable when the dish name may have been misheard.",
    transcript ? `Recent conversation:\n${transcript}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

export function createTurn(role, text) {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text: String(text || "").trim(),
    createdAt: new Date().toISOString(),
  };
}
