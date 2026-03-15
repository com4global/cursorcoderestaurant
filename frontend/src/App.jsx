import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { listRestaurants, fetchNearby, login, register, sendMessage, fetchCart, addComboToCart, removeCartItem, clearCart, checkout, fetchMyOrders, submitFeedback, voiceSTT, voiceTTS, voiceChat, createCheckoutSession, verifyPayment, trackOrder, getRestaurantQueue, mealOptimizer, searchMenuItems, fetchPopularItems, searchByIntent, generateMealPlan, swapMeal, fetchCategoryItems, createGroupSession, getGroupSession, joinGroupSession, getGroupRecommendation, getGroupSplitEqual } from "./api.js";
import OwnerPortal from "./OwnerPortal.jsx";
import TasteProfile from "./TasteProfile.jsx";
import { useVoiceController } from "./voice/useVoiceController.js";
import { trace, traceError } from "./voice/trace.js";

const RADIUS_OPTIONS = [5, 10, 15, 25, 50];

/** Normalize name so OSM "Anjappar" matches partnered "Anjappar" / "Anjappar — …" */
function normRestName(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Nearby (OpenStreetMap) rows have no DB id. Map them to the partnered restaurant
 * so /restaurants/:id/categories works. Prefer exact name, then substring match.
 */
function resolvePartneredRestaurant(r, partneredList) {
  if (!r || !partneredList?.length) return r;
  const hasNumericId = r.id != null && r.id !== "" && Number.isFinite(Number(r.id));
  if (hasNumericId && r.partnered !== false) return r;
  if (hasNumericId) {
    const byId = partneredList.find((p) => p.id === Number(r.id));
    if (byId) return { ...byId, partnered: true };
  }
  const n = normRestName(r.name);
  if (n.length < 2) return r;
  let hit = partneredList.find((p) => normRestName(p.name) === n);
  if (hit) return { ...hit, partnered: true };
  hit = partneredList.find(
    (p) => {
      const pn = normRestName(p.name);
      return pn.includes(n) || n.includes(pn);
    }
  );
  if (hit && n.length >= 3) return { ...hit, partnered: true };
  return r;
}

// Smart food emoji mapper
const FOOD_EMOJI_MAP = [
  [/pizza|pie|margherita|pepperoni|calzone|supreme/i, "🍕"],
  [/burger|hamburger|cheeseburger/i, "🍔"],
  [/fries|french fries|potato/i, "🍟"],
  [/hot ?dog/i, "🌭"],
  [/taco/i, "🌮"],
  [/burrito|wrap|quesadilla/i, "🌯"],
  [/salad|caesar|garden|coleslaw/i, "🥗"],
  [/soup|chowder|bisque|stew/i, "🍲"],
  [/steak|ribeye|filet|sirloin|beef/i, "🥩"],
  [/chicken|wing|tender|nugget|poultry/i, "🍗"],
  [/fish|salmon|tuna|cod|shrimp|seafood|lobster|crab/i, "🐟"],
  [/sushi|sashimi|maki|roll/i, "🍣"],
  [/ramen|noodle|pho|udon|lo mein|pad thai/i, "🍜"],
  [/rice|fried rice|biryani|risotto/i, "🍚"],
  [/pasta|spaghetti|penne|linguine|fettuccine|mac/i, "🍝"],
  [/sandwich|sub|panini|club|blt|hoagie/i, "🥪"],
  [/bread|toast|baguette|roll|biscuit|garlic bread|naan/i, "🍞"],
  [/cake|cheesecake|brownie|tiramisu/i, "🍰"],
  [/ice cream|gelato|sundae|frozen/i, "🍨"],
  [/cookie|biscuit/i, "🍪"],
  [/donut|doughnut/i, "🍩"],
  [/pie|cobbler|tart/i, "🥧"],
  [/coffee|espresso|latte|cappuccino|mocha/i, "☕"],
  [/tea|chai|matcha/i, "🍵"],
  [/beer|ale|lager|ipa|stout/i, "🍺"],
  [/wine|merlot|cabernet|chardonnay/i, "🍷"],
  [/cocktail|martini|margarita|mojito/i, "🍸"],
  [/juice|smoothie|lemonade/i, "🧃"],
  [/soda|cola|sprite|pepsi|coke|drink|beverage/i, "🥤"],
  [/water|sparkling/i, "💧"],
  [/egg|omelet|omelette|benedict|scramble/i, "🍳"],
  [/pancake|waffle|french toast|crepe/i, "🥞"],
  [/cheese|mozzarella|cheddar|gouda/i, "🧀"],
  [/nachos|chip|guac|salsa/i, "🫔"],
  [/curry|tikka|masala|vindaloo/i, "🍛"],
  [/bbq|barbecue|ribs|brisket|pulled pork|smoked/i, "🔥"],
  [/corn|cob/i, "🌽"],
  [/mushroom/i, "🍄"],
  [/pepper|jalapeño|chili/i, "🌶️"],
  [/tomato|marinara/i, "🍅"],
  [/apple|fruit/i, "🍎"],
  [/chocolate|cocoa/i, "🍫"],
  [/catering/i, "📦"],
];

function getFoodEmoji(name = "", category = "") {
  const text = `${name} ${category}`.toLowerCase();
  for (const [regex, emoji] of FOOD_EMOJI_MAP) {
    if (regex.test(text)) return emoji;
  }
  return "🍽️";
}

// Distinct gradient colors for restaurant cards
const CARD_GRADIENTS = [
  ['#1a1a2e', '#e94560'],
  ['#0f3460', '#16213e'],
  ['#2d132c', '#ee4c7c'],
  ['#1b262c', '#0f4c75'],
  ['#1a1a40', '#7952b3'],
  ['#0d1117', '#238636'],
  ['#1e1e3f', '#e07c24'],
  ['#162447', '#1f4068'],
  ['#2c003e', '#d4418e'],
  ['#0a192f', '#64ffda'],
];

// Smart restaurant → image mapping
const RESTAURANT_IMAGE_MAP = [
  [/desi|district|indian/i, '/food-images/food_indian_thali.png'],
  [/triveni|supermarket|grocery/i, '/food-images/food_indian_grocery.png'],
  [/bbq|barbecue|southern|grill|smoke/i, '/food-images/food_bbq_platter.png'],
  [/thai|orchid|pad|pho/i, '/food-images/food_thai_spread.png'],
  [/domino|pizza|hut|papa/i, '/food-images/food_pizza_fresh.png'],
  [/aroma|italian|pasta|olive/i, '/food-images/food_italian_aroma.png'],
];

function getRestaurantImage(name = '') {
  const text = name.toLowerCase();
  for (const [regex, img] of RESTAURANT_IMAGE_MAP) {
    if (regex.test(text)) return img;
  }
  return null; // falls back to gradient
}

// Smart food item/category → image mapping
const FOOD_IMAGE_MAP = [
  [/biryani|biriyani|pulao|pulav|rice|fried rice/i, '/food-images/food_biryani.png'],
  [/snack|samosa|pakora|chaat|appetizer|starter|bhaji|pani puri|bhel/i, '/food-images/food_snacks_plate.png'],
  [/curry|masala|tikka|butter chicken|paneer|dal|gravy|korma|vindaloo/i, '/food-images/food_curry_bowl.png'],
  [/naan|bread|roti|paratha|kulcha|garlic|chapati|puri/i, '/food-images/food_naan_bread.png'],
  [/dessert|sweet|gulab|jalebi|kheer|halwa|rasgulla|cake|mithai/i, '/food-images/food_desserts_indian.png'],
  [/drink|lassi|chai|tea|coffee|juice|beverage|smoothie|milkshake/i, '/food-images/food_drinks_lassi.png'],
  [/falooda|faluda/i, '/food-images/food_falooda.png'],
  [/frankie|kathi|roll|wrap/i, '/food-images/food_frankie_wrap.png'],
  [/tiffin|breakfast|dosa|idli|vada|upma|uttapam|poha/i, '/food-images/food_tiffin_breakfast.png'],
  [/indo.?chinese|chinese|manchurian|hakka|noodle|chilli|gobi|schezwan/i, '/food-images/food_indo_chinese.png'],
  [/chat(?!.*bot)|chaat|puri|sev|papdi|bhel/i, '/food-images/food_chaat_street.png'],
  [/burger|hamburger|cheeseburger/i, '/food-images/food_burger_desi.png'],
  [/combo|meal|deal|buy 1|bogo|value|offer/i, '/food-images/food_combo_meal.png'],
  [/pizza|pie|margherita|pepperoni/i, '/food-images/food_pizza_fresh.png'],
  [/bbq|ribs|brisket|pulled|smoked|barbecue/i, '/food-images/food_bbq_platter.png'],
  [/thai|pad|spring roll|tom yum/i, '/food-images/food_thai_spread.png'],
  [/pasta|spaghetti|fettuccine|penne|italian/i, '/food-images/food_italian_aroma.png'],
  [/platter|special|friday|ramadan|festiv|feast/i, '/food-images/food_indian_thali.png'],
  [/new|categor|misc|other/i, '/food-images/food_indian_thali.png'],
];

function getFoodItemImage(name = '', category = '') {
  const text = `${name} ${category}`.toLowerCase();
  for (const [regex, img] of FOOD_IMAGE_MAP) {
    if (regex.test(text)) return img;
  }
  return null; // falls back to emoji
}

const welcomeMsg = {
  role: "bot",
  content: "Hello! Pick a restaurant from the Home tab, then browse menus and add items here.",
};

const API = import.meta.env.DEV ? "" : (import.meta.env.VITE_API_BASE || "http://localhost:8000");

export default function App() {
  // Active tab
  const [tab, setTab] = useState("home");

  // Auth
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [status, setStatus] = useState("Ready.");

  // Chat
  const [messageText, setMessageText] = useState("");
  const [messages, setMessages] = useState([welcomeMsg]);
  // Session persisted in localStorage to survive hot reload / refresh
  const [sessionId, _setSessionId] = useState(() => {
    const saved = localStorage.getItem("chat_sessionId");
    return saved ? parseInt(saved, 10) : null;
  });
  const setSessionId = (id) => {
    _setSessionId(id);
    if (id != null) localStorage.setItem("chat_sessionId", String(id));
    else localStorage.removeItem("chat_sessionId");
  };

  // Restaurants
  const [restaurants, setRestaurants] = useState([]);
  const [nearbyPlaces, setNearbyPlaces] = useState([]);
  // Selected restaurant persisted in localStorage
  const [selectedRestaurant, _setSelectedRestaurant] = useState(() => {
    try {
      const saved = localStorage.getItem("chat_selectedRestaurant");
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });
  const setSelectedRestaurant = (r) => {
    _setSelectedRestaurant(r);
    if (r) localStorage.setItem("chat_selectedRestaurant", JSON.stringify({ id: r.id, name: r.name, slug: r.slug }));
    else localStorage.removeItem("chat_selectedRestaurant");
  };

  // Location state
  const [zipcode, setZipcode] = useState(localStorage.getItem("zipcode") || "");
  const [radius, setRadius] = useState(Number(localStorage.getItem("radius")) || 25);
  const [userLat, setUserLat] = useState(null);
  const [userLng, setUserLng] = useState(null);
  const [locationLabel, setLocationLabel] = useState("");
  const [locating, setLocating] = useState(false);
  const [citySearch, setCitySearch] = useState("");
  const [citySuggestions, setCitySuggestions] = useState([]);
  const [showCitySuggestions, setShowCitySuggestions] = useState(false);
  const citySearchTimeout = useRef(null);

  // Categories & Menu items
  const [activeCategories, setActiveCategories] = useState([]);
  const [activeCategoryName, setActiveCategoryName] = useState(null);
  const [currentItems, setCurrentItems] = useState([]);

  // Autocomplete
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [filteredRestaurants, setFilteredRestaurants] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Cart
  const [cartData, setCartData] = useState(null);
  const [showCartPanel, setShowCartPanel] = useState(false);
  const [checkingOut, setCheckingOut] = useState(false);
  const [checkoutDone, setCheckoutDone] = useState(null);
  const [paymentToast, setPaymentToast] = useState(null); // { type: 'success'|'cancel', message: string }

  // Orders
  const [myOrders, setMyOrders] = useState([]);
  const [ordersTab, setOrdersTab] = useState("current");
  // Post-order feedback (per order)
  const [feedbackRating, setFeedbackRating] = useState({});
  const [feedbackIssues, setFeedbackIssues] = useState({});
  const [feedbackComment, setFeedbackComment] = useState({});
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(null);

  // Voice Conversation Mode — powered by useVoiceController hook (English / Tamil)
  const doSendRef = useRef(null);
  const voiceSpeakRef = useRef(null);
  const [voiceLanguage, setVoiceLanguage] = useState("en");
  const voice = useVoiceController({ apiBase: API, doSendRef, language: voiceLanguage });
  const { voiceMode, voiceState, setVoiceState, liveTranscript, voiceTranscript, isListening, voiceModeRef, voiceStateRef } = voice;
  const voiceStartListeningRef = useRef(null);
  const lastVoicePromptRef = useRef(null);
  // Bridge voiceSpeakRef for doSend's fromVoice paths
  useEffect(() => {
    voiceSpeakRef.current = (text) => voice.speak(text);
    voiceStartListeningRef.current = () => voice.startListening();
  }, [voice.speak, voice.startListening]);

  // Owner
  const [showOwnerPortal, setShowOwnerPortal] = useState(() => localStorage.getItem("userRole") === "owner");
  const [userRole, setUserRole] = useState(() => localStorage.getItem("userRole") || "customer");

  // Refs
  const inputRef = useRef(null);
  const chatEndRef = useRef(null);
  const [addedItemId, setAddedItemId] = useState(null);
  // Conversation state (persists filters across turns: dish, price, restaurant, diet)
  const convStateRef = useRef({ dish: null, protein: null, cuisine: null, spice: null, diet: null, priceMax: null, priceMin: null, priceRange: null, restaurant: null, restaurantId: null, quantity: 1, rating: null, sortBy: null, lastQuery: null, lastResults: null, turnCount: 0 });

  // Helper: build sendMessage payload with restaurant_id for session recovery
  const buildChatPayload = (text, overrideSessionId) => {
    const payload = { session_id: overrideSessionId !== undefined ? overrideSessionId : sessionId, text };
    if (selectedRestaurant?.id) payload.restaurant_id = selectedRestaurant.id;
    return payload;
  };

  // Budget Optimizer
  const [showOptimizer, setShowOptimizer] = useState(false);
  const [optPeople, setOptPeople] = useState(5);
  const [optBudget, setOptBudget] = useState(50);
  const [optCuisine, setOptCuisine] = useState("");
  const [optResults, setOptResults] = useState(null);
  const [optLoading, setOptLoading] = useState(false);
  const [optError, setOptError] = useState("");

  // Group Order
  const [groupSession, setGroupSession] = useState(null);
  const [groupJoinCodeInput, setGroupJoinCodeInput] = useState("");
  const [groupViewSession, setGroupViewSession] = useState(null);
  const [groupRecommendation, setGroupRecommendation] = useState(null);
  const [groupSplit, setGroupSplit] = useState(null);
  const [groupJoinName, setGroupJoinName] = useState("");
  const [groupJoinPref, setGroupJoinPref] = useState("");
  const [groupJoinBudget, setGroupJoinBudget] = useState("");
  const [groupJoinDiet, setGroupJoinDiet] = useState("");
  const [groupJoinLoading, setGroupJoinLoading] = useState(false);
  const [groupRecLoading, setGroupRecLoading] = useState(false);
  const [groupAddToCartLoading, setGroupAddToCartLoading] = useState(false);
  const [groupStatus, setGroupStatus] = useState("");
  const [groupPreferRestaurantIds, setGroupPreferRestaurantIds] = useState([]);
  const [groupPreferCuisine, setGroupPreferCuisine] = useState("");
  const [groupRestaurantOptions, setGroupRestaurantOptions] = useState([]);

  // ===================== EFFECTS =====================

  useEffect(() => {
    if (token) {
      localStorage.setItem("token", token);
      fetchCart(token).then(setCartData).catch(() => { });
      fetchMyOrders(token).then(setMyOrders).catch(() => { });
    }
  }, [token]);

  useEffect(() => {
    if (!token || showOwnerPortal) return;
    const interval = setInterval(() => {
      fetchMyOrders(token).then(setMyOrders).catch(() => { });
    }, 15000);
    return () => clearInterval(interval);
  }, [token, showOwnerPortal]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Group order: open tab and load session from hash (#group/8734)
  useEffect(() => {
    const hash = window.location.hash || "";
    const m = hash.match(/^#?group\/([^/]+)/);
    if (m) {
      setTab("group");
      getGroupSession(m[1]).then(setGroupViewSession).catch(() => {});
    }
  }, []);

  // Load restaurant list for group recommendation preference (when group session exists)
  useEffect(() => {
    if (tab !== "group" || (!groupSession && !groupViewSession)) return;
    listRestaurants().then(setGroupRestaurantOptions).catch(() => setGroupRestaurantOptions([]));
  }, [tab, groupSession, groupViewSession]);

  // Handle Stripe payment redirect URL params
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const payment = params.get('payment');
    const sessionId = params.get('session_id');
    if (!payment) return;

    // Clean URL immediately so refresh doesn't re-trigger
    window.history.replaceState({}, '', window.location.pathname);

    if (payment === 'order_success') {
      setTab('orders');
      setOrdersTab('current');
      setCartData(null);
      setShowCartPanel(false);
      setPaymentToast({ type: 'success', message: '✅ Payment successful! Your order has been confirmed.' });
      setTimeout(() => setPaymentToast(null), 8000);

      // Verify payment and confirm orders on the backend
      const storedToken = token || localStorage.getItem('token');
      if (storedToken && sessionId) {
        verifyPayment(storedToken, sessionId)
          .then(() => fetchMyOrders(storedToken))
          .then(setMyOrders)
          .catch(() => { });
      } else if (storedToken) {
        fetchMyOrders(storedToken).then(setMyOrders).catch(() => { });
      }
    } else if (payment === 'order_cancel') {
      setPaymentToast({ type: 'cancel', message: '❌ Payment was cancelled. Your items are still in the cart.' });
      setTimeout(() => setPaymentToast(null), 6000);
    }
  }, []); // Run once on mount

  // Fetch restaurants
  const fetchRestaurantsData = useCallback(async (lat, lng, r) => {
    try {
      const params = {};
      if (lat != null && lng != null) { params.lat = lat; params.lng = lng; params.radius_miles = r; }
      const data = await listRestaurants(params);
      setRestaurants(data);
      if (lat != null && lng != null) {
        try {
          const nearby = await fetchNearby({ lat, lng, radius_miles: r });
          setNearbyPlaces(nearby);
        } catch { setNearbyPlaces([]); }
      }
    } catch { setRestaurants([]); }
  }, []);

  // Auto-detect location on mount
  useEffect(() => {
    const savedZip = localStorage.getItem("zipcode");
    if (savedZip) { setZipcode(savedZip); lookupZipcodeAuto(savedZip); return; }
    if (navigator.geolocation) {
      setLocating(true); setLocationLabel("Detecting...");
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const lat = pos.coords.latitude, lng = pos.coords.longitude;
          setUserLat(lat); setUserLng(lng);
          try {
            const res = await fetch(`https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lng}&localityLanguage=en`);
            const geo = await res.json();
            setLocationLabel(`${geo.city || geo.locality || ""}, ${geo.principalSubdivisionCode || geo.countryCode || ""}`);
          } catch { setLocationLabel(`${lat.toFixed(2)}, ${lng.toFixed(2)}`); }
          await fetchRestaurantsData(lat, lng, radius);
          setLocating(false);
        },
        () => { setLocationLabel(""); fetchRestaurantsData(null, null, radius); setLocating(false); },
        { timeout: 5000 }
      );
    } else { fetchRestaurantsData(null, null, radius); }
  }, []);

  const lookupZipcodeAuto = async (zip) => {
    setLocating(true);
    try {
      const res = await fetch(`https://api.zippopotam.us/us/${zip}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const place = data.places[0];
      const lat = parseFloat(place.latitude), lng = parseFloat(place.longitude);
      setUserLat(lat); setUserLng(lng);
      const cityLabel = `${place["place name"]}, ${place["state abbreviation"]}`;
      setLocationLabel(cityLabel); setCitySearch(cityLabel);
      await fetchRestaurantsData(lat, lng, radius);
    } catch { fetchRestaurantsData(null, null, radius); }
    setLocating(false);
  };

  // ===================== LOCATION =====================

  const lookupZipcode = async (zip) => {
    if (!zip || zip.length < 5) return;
    setLocating(true);
    try {
      const res = await fetch(`https://api.zippopotam.us/us/${zip}`);
      if (!res.ok) throw new Error("Invalid zipcode");
      const data = await res.json();
      const place = data.places[0];
      const lat = parseFloat(place.latitude), lng = parseFloat(place.longitude);
      setUserLat(lat); setUserLng(lng);
      const cityLabel = `${place["place name"]}, ${place["state abbreviation"]}`;
      setLocationLabel(cityLabel); setCitySearch(cityLabel);
      localStorage.setItem("zipcode", zip); localStorage.setItem("radius", radius);
      await fetchRestaurantsData(lat, lng, radius);
    } catch { setLocationLabel("Invalid zipcode"); }
    setLocating(false);
  };

  const handleZipcodeChange = (val) => {
    const cleaned = val.replace(/\D/g, "").slice(0, 5);
    setZipcode(cleaned);
    if (cleaned.length === 5) lookupZipcode(cleaned);
  };

  const searchCity = async (query) => {
    if (!query || query.length < 2) { setCitySuggestions([]); return; }
    try {
      const results = [];
      const seenKeys = new Set();
      const res = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)},US&format=json&addressdetails=1&limit=6&countrycodes=us`);
      if (res.ok) {
        const data = await res.json();
        for (const item of data) {
          const addr = item.address || {};
          const city = addr.city || addr.town || addr.village || addr.county || "";
          const state = addr.state || "";
          const postcode = addr.postcode || "";
          const zip5 = postcode.split("-")[0].split(" ")[0];
          const key = `${city}-${state}-${zip5}`;
          if (city && !seenKeys.has(key)) {
            seenKeys.add(key);
            results.push({ city, state, zipcode: zip5, lat: parseFloat(item.lat), lng: parseFloat(item.lon), display: `${city}, ${state}${zip5 ? " · " + zip5 : ""}` });
          }
        }
      }
      setCitySuggestions(results.slice(0, 5));
      setShowCitySuggestions(results.length > 0);
    } catch { setCitySuggestions([]); }
  };

  const handleCitySearchChange = (val) => {
    setCitySearch(val);
    if (citySearchTimeout.current) clearTimeout(citySearchTimeout.current);
    citySearchTimeout.current = setTimeout(() => searchCity(val), 400);
  };

  const selectCity = async (suggestion) => {
    setZipcode(suggestion.zipcode || "");
    setCitySearch(`${suggestion.city}, ${suggestion.state}`);
    setLocationLabel(`${suggestion.city}, ${suggestion.state}`);
    setUserLat(suggestion.lat); setUserLng(suggestion.lng);
    setShowCitySuggestions(false);
    if (suggestion.zipcode) localStorage.setItem("zipcode", suggestion.zipcode);
    localStorage.setItem("radius", radius);
    await fetchRestaurantsData(suggestion.lat, suggestion.lng, radius);
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) { setLocationLabel("Not supported"); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude, lng = pos.coords.longitude;
        setUserLat(lat); setUserLng(lng);
        setLocationLabel(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
        await fetchRestaurantsData(lat, lng, radius);
        setLocating(false);
      },
      () => { setLocationLabel("Location denied"); setLocating(false); }
    );
  };

  const handleRadiusChange = async (newRadius) => {
    setRadius(newRadius);
    localStorage.setItem("radius", newRadius);
    if (userLat != null && userLng != null) await fetchRestaurantsData(userLat, userLng, newRadius);
  };

  // ===================== VOICE (ULTRA-LOW LATENCY via useVoiceController) =====================
  // All voice logic (STT, TTS, intent parsing, state machine, barge-in) is in the hook.
  // toggleVoiceMode and startListening are thin wrappers.
  const toggleVoiceMode = () => voice.toggleVoiceMode();
  const startListening = () => voice.toggleVoiceMode();


  // ===================== CHAT / SEND =====================

  const doSend = async (text, fromVoice = false, voiceConfidence = 0) => {
    if (!text.trim()) return;
    const trimmed = text.trim();
    trace('doSend.entry', { fromVoice, text: trimmed, voiceConfidence, selectedRestaurant: selectedRestaurant?.name ?? null, sessionId });
    setMessages((p) => [...p, { role: "user", content: trimmed }]);
    setMessageText(""); setShowSuggestions(false); setStatus("Thinking...");

    // ── Intent Router ────────────────────────────────────────────────
    // Classify the message into an intent, then route accordingly.

    // Voice input: run through 5-layer production validation pipeline
    let cleanedText = trimmed;
    if (fromVoice) {
      const { validateVoiceInput, getRejectionMessage } = await import("./voice/VoiceValidator.js");
      const allRestsForValidation = [
        ...restaurants,
        ...nearbyPlaces.map(r => ({ ...r, slug: r.slug || r.name.toLowerCase().replace(/[^a-z0-9]+/g, '-') })),
      ];
      const validation = validateVoiceInput(trimmed, voiceConfidence, allRestsForValidation, { language: voiceLanguage });
      trace('voice.validation', { valid: validation.valid, reason: validation.reason, cleaned: validation.text, layers: validation.layers });

      // Log all layer decisions
      validation.layers.forEach(l => {
        const color = l.startsWith('✅') ? '#00ff88' : l.startsWith('❌') ? '#ff4444' : '#ffaa00';
        console.log(`%c[Validator] ${l}`, `color: ${color}`);
      });

      if (!validation.valid) {
        const msg = getRejectionMessage(validation.reason);
        trace('voice.rejected', { reason: validation.reason, message: msg });
        console.log(`%c[Validator] ❌ REJECTED: ${validation.reason} — "${msg}"`, 'color: #ff4444; font-weight: bold');
        setMessages((p) => [...p, { role: "bot", content: msg }]);
        setStatus("Ready.");
        if (voiceModeRef.current) voiceSpeakRef.current(msg, true);
        return;
      }

      cleanedText = validation.text;
      if (cleanedText !== trimmed.toLowerCase()) {
        console.log(`%c[Validator] ✅ PASSED — cleaned: "${cleanedText}"`, 'color: #00ff88; font-weight: bold');
      }
    }

    const skipIntentSearch = cleanedText.startsWith("#") || cleanedText.startsWith("add:") || cleanedText.length <= 2;

    if (!skipIntentSearch) {
      const { parseIntent, INTENTS, buildSearchQuery } = await import("./voice/IntentParser.js");
      const { applyUpdate, buildQuery, describeFilters, resetForNewSearch } = await import("./voice/ConversationState.js");

      // Combine partnered restaurants + nearby places (from Google) for matching
      const allRestaurants = [
        ...restaurants.map(r => ({ ...r, partnered: true })),
        ...nearbyPlaces.map(r => ({ ...r, slug: r.slug || r.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''), partnered: false })),
      ];
      console.log(`%c[IntentRouter] 📊 Available: ${restaurants.length} partnered + ${nearbyPlaces.length} nearby = ${allRestaurants.length} restaurants`, 'color: #888');
      if (allRestaurants.length > 0) console.log(`%c[IntentRouter] 🏪 Names: ${allRestaurants.map(r => r.name).join(', ')}`, 'color: #888; font-size: 10px');

      const intentResult = parseIntent(cleanedText, convStateRef.current, allRestaurants);
      trace('intent.parsed', {
        intent: intentResult.intent,
        parseTimeMs: intentResult.parseTimeMs,
        input: cleanedText,
        restaurantMatch: intentResult.restaurantMatch?.name ?? null,
        entities: intentResult.entities,
      });
      console.log(`%c[IntentRouter] 🎯 Intent: ${intentResult.intent} (${intentResult.parseTimeMs.toFixed(1)}ms)`, 'color: #ff6600; font-weight: bold; font-size: 13px');
      console.log(`%c[IntentRouter] 📝 Input: "${cleanedText}" | Entities:`, 'color: #aaa', intentResult.entities, '| StateUpdate:', intentResult.stateUpdate);
      if (intentResult.restaurantMatch) console.log(`%c[IntentRouter] 🏪 Restaurant match: "${intentResult.restaurantMatch.name}"`, 'color: #00ff88; font-weight: bold');
      console.log(`%c[IntentRouter] 💾 Conv state:`, 'color: #aaa', { ...convStateRef.current });

      // ── GREETING / HELP / THANKS / GOODBYE ──────────────────────
      if (intentResult.intent === INTENTS.GREETING) {
        const reply = "Yes, I can hear you! 🎤 Try asking for food like \"pizza\" or \"biryani\", or say a restaurant name to get started.";
        setMessages((p) => [...p, { role: "bot", content: reply }]);
        setStatus("Ready.");
        if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("I can hear you! Ask for any food like pizza or biryani.", true);
        return;
      }
      if (intentResult.intent === INTENTS.HELP) {
        const reply = "I'm your AI food assistant! 🍽️ You can:\n• Search for food: \"pizza\", \"biryani\"\n• Find deals: \"cheap Indian food under $15\"\n• Modify results: \"make it veg\", \"show cheaper\"\n• Switch restaurants: \"change to Desi District\"\n• Plan meals: \"plan meals for the week\"\nJust speak or type what you're craving!";
        setMessages((p) => [...p, { role: "bot", content: reply }]);
        setStatus("Ready.");
        if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("I'm your food assistant. What are you looking for?", true);
        return;
      }
      if (intentResult.intent === INTENTS.THANKS) {
        const reply = "You're welcome! 😊 Let me know if you need anything else — just ask for any food!";
        setMessages((p) => [...p, { role: "bot", content: reply }]);
        setStatus("Ready.");
        if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("You're welcome! Ask for anything else.", true);
        return;
      }
      if (intentResult.intent === INTENTS.GOODBYE) {
        const reply = "Goodbye! 👋 Come back anytime you're hungry!";
        setMessages((p) => [...p, { role: "bot", content: reply }]);
        setStatus("Ready.");
        if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("Goodbye! Come back anytime.", true);
        return;
      }

      // ── CHANGE RESTAURANT (with specific restaurant name) ───────
      // When no restaurantMatch ("change restaurant", "different restaurant"), fall through to send to backend
      if (intentResult.intent === INTENTS.CHANGE_RESTAURANT && intentResult.restaurantMatch) {
        const matchedRest = resolvePartneredRestaurant(intentResult.restaurantMatch, restaurants);
        if (matchedRest.id == null || matchedRest.id === "" || Number.isNaN(Number(matchedRest.id))) {
          setMessages((p) => [
            ...p,
            {
              role: "bot",
              content: `Couldn't open **${intentResult.restaurantMatch?.name || "that"}** on the menu. Pick a restaurant from **Order Now** or type **#** and choose one with the ✓ badge.`,
            },
          ]);
          setStatus("Ready.");
          if (fromVoice && voiceModeRef.current) {
            voiceSpeakRef.current("Pick a restaurant from Order Now, or type hash and choose one with the checkmark.");
          }
          return;
        }
        // Update conversation state: keep dish/diet/price, change restaurant
        convStateRef.current = applyUpdate(convStateRef.current, intentResult.stateUpdate);

        setSelectedRestaurant(matchedRest);
        setTab("chat");

        // IMPORTANT: await the restaurant selection so sessionId is updated
        // This was previously fire-and-forget, causing the next call to use a stale session
        try {
          console.log(`%c[IntentRouter] 🏪 Selecting restaurant: #${matchedRest.slug}`, 'color: #00bbff; font-weight: bold');
          // Pre-fetch TTS in parallel with backend call (we know the text ahead of time)
          if (fromVoice && voiceModeRef.current) {
            voiceSpeakRef.current(`Welcome to ${matchedRest.name}. Pick a category.`);
          }
          const selectRes = await sendMessage(token, buildChatPayload(`#${matchedRest.slug}`, null));
          // Sync selectedRestaurant with backend (avoids ID mismatch: voice match can be from nearby list)
          if (selectRes.restaurant_id != null) {
            const fromList = restaurants.find((r) => r.id === selectRes.restaurant_id)
              ?? nearbyPlaces.find((r) => r.id === selectRes.restaurant_id);
            if (fromList) setSelectedRestaurant(fromList);
          }
          // Update session with the new restaurant's session
          if (selectRes.session_id) {
            setSessionId(selectRes.session_id);
            console.log(`%c[IntentRouter] ✅ Session updated: ${selectRes.session_id}`, 'color: #00ff88');
          }
          // Show categories if returned
          if (selectRes.categories && selectRes.categories.length > 0) {
            setActiveCategories(selectRes.categories);
            setActiveCategoryName(null);
            setCurrentItems([]);
            const catNames = selectRes.categories.map(c => typeof c === 'string' ? c : c.name).join(', ');
            setMessages((p) => [...p, {
              role: "bot",
              content: selectRes.reply || `Welcome to **${matchedRest.name}**! Categories: ${catNames}`,
              categories: selectRes.categories,
            }]);
            setStatus("Ready.");
            return;
          }

          // Categories empty — fetch via REST then fallback to 'show menu'
          if (selectRes.restaurant_id != null) {
            try {
              const apiBase = import.meta.env.DEV ? "" : (import.meta.env.VITE_API_BASE || "http://localhost:8000");
              const catRes = await fetch(`${apiBase}/restaurants/${selectRes.restaurant_id}/categories`);
              if (catRes.ok) {
                const cats = await catRes.json();
                if (cats && cats.length > 0) {
                  setActiveCategories(cats);
                  setActiveCategoryName(null);
                  setCurrentItems([]);
                  const catNames = cats.map((c) => (typeof c === "string" ? c : c.name)).join(", ");
                  setMessages((p) => [...p, {
                    role: "bot",
                    content: selectRes.reply || `Welcome to **${matchedRest.name}**! Categories: ${catNames}`,
                    categories: cats,
                  }]);
                  setStatus("Ready.");
                  if (fromVoice && voiceModeRef.current) {
                    voiceSpeakRef.current(`${matchedRest.name}. We have: ${catNames}. Which one would you like?`);
                  }
                  return;
                }
              }
            } catch (_) { /* ignore */ }
          }
          console.log(`%c[IntentRouter] ⚠️ No categories from #slug — trying process_message('show menu')`, 'color: #ffaa00');
          const menuRes = await sendMessage(token, buildChatPayload('show menu'));
          if (menuRes.session_id) setSessionId(menuRes.session_id);
          if (menuRes.categories && menuRes.categories.length > 0) {
            if (fromVoice && voiceModeRef.current) {
              voiceSpeakRef.current(`Welcome to ${matchedRest.name}. Pick a category.`);
            }
            setActiveCategories(menuRes.categories);
            setActiveCategoryName(null);
            setCurrentItems([]);
            const catNames = menuRes.categories.map(c => typeof c === 'string' ? c : c.name).join(', ');
            setMessages((p) => [...p, {
              role: "bot",
              content: menuRes.reply || `Welcome to **${matchedRest.name}**! Categories: ${catNames}`,
              categories: menuRes.categories,
            }]);
            setStatus("Ready.");
            return;
          }
          // Still nothing — show reply from backend or generic message
          setMessages((p) => [...p, {
            role: "bot",
            content: menuRes.reply || selectRes.reply || `Switched to **${matchedRest.name}**! Ask me what you'd like to order.`,
          }]);
          setStatus("Ready.");
          if (fromVoice && voiceModeRef.current) {
            voiceSpeakRef.current(`Switched to ${matchedRest.name}. What would you like?`);
          }
          return;
        } catch (err) {
          console.error(`%c[IntentRouter] ❌ Restaurant select failed:`, 'color: #ff4444', err);
          setMessages((p) => [...p, {
            role: "bot",
            content: `Couldn't load **${matchedRest.name}**. You can try again or pick another restaurant.`,
          }]);
          setStatus("Ready.");
          if (fromVoice && voiceModeRef.current) {
            voiceSpeakRef.current("Couldn't load that restaurant. Try again or pick another.");
          }
          return;
        }

        // Fallback: if we have existing food filters, re-search with the new restaurant context
        const cs = convStateRef.current;
        if (cs.dish || cs.protein || cs.cuisine) {
          const filterDesc = describeFilters(cs);
          setMessages((p) => [...p, { role: "bot", content: `Switched to **${matchedRest.name}**! Searching for ${filterDesc}...` }]);
          setStatus("Searching...");
          try {
            const query = buildQuery(cs);
            const data = await searchByIntent(query);
            if (data.results && data.results.length > 0) {
              cs.lastResults = data.results;
              setMessages((p) => [...p, { role: "bot", content: `__PRICE_COMPARE__`, priceCompare: data }]);
              setStatus("Ready.");
              if (fromVoice && voiceModeRef.current) voiceSpeakRef.current(`Found ${data.results.length} options at ${matchedRest.name}.`);
            } else {
              setMessages((p) => [...p, { role: "bot", content: `No ${filterDesc} found at **${matchedRest.name}**. Try a different dish!` }]);
              setStatus("Ready.");
              if (fromVoice && voiceModeRef.current) voiceSpeakRef.current(`No matching items. Try a different dish.`);
            }
          } catch {
            setMessages((p) => [...p, { role: "bot", content: `Switched to **${matchedRest.name}**! What would you like to order?` }]);
            setStatus("Ready.");
          }
        } else {
          setMessages((p) => [...p, { role: "bot", content: `Switched to **${matchedRest.name}**! What would you like to order?` }]);
          setStatus("Ready.");
          if (fromVoice && voiceModeRef.current) voiceSpeakRef.current(`Switched to ${matchedRest.name}. What would you like?`);
        }
        return;
      }

      // ── FILTER UPDATE (modify existing search) ─────────────────
      if (intentResult.intent === INTENTS.FILTER_UPDATE) {
        convStateRef.current = applyUpdate(convStateRef.current, intentResult.stateUpdate);
        const cs = convStateRef.current;
        const filterDesc = describeFilters(cs);
        const query = buildQuery(cs);

        setMessages((p) => [...p, { role: "bot", content: `Updating filters: ${filterDesc}...` }]);
        setStatus("Searching...");

        try {
          const data = await searchByIntent(query);
          if (data.results && data.results.length > 0) {
            cs.lastResults = data.results;
            setMessages((p) => [...p, { role: "bot", content: `__PRICE_COMPARE__`, priceCompare: data }]);
            setStatus("Ready.");
            if (fromVoice && voiceModeRef.current) voiceSpeakRef.current(`Found ${data.results.length} options for ${filterDesc}.`, true);
          } else {
            setMessages((p) => [...p, { role: "bot", content: `No results for ${filterDesc}. Try relaxing your filters!` }]);
            setStatus("Ready.");
            if (fromVoice && voiceModeRef.current) voiceSpeakRef.current(`No results for ${filterDesc}. Try different filters.`, true);
          }
        } catch {
          setMessages((p) => [...p, { role: "bot", content: "Sorry, I had trouble updating the search. Try again!" }]);
          setStatus("Ready.");
        }
        return;
      }

      // ── MEAL PLAN ──────────────────────────────────────────────
      if (intentResult.intent === INTENTS.MEAL_PLAN) {
        try {
          const data = await generateMealPlan(trimmed);
          if (data.days && data.days.length > 0) {
            setMessages((p) => [...p, { role: "bot", content: `__MEAL_PLAN__`, mealPlan: data }]);
            setStatus("Ready.");
            if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("Here's your meal plan! Say another request or say 'done'.", true);
            return;
          }
        } catch { }
        setMessages((p) => [...p, { role: "bot", content: "Sorry, I had trouble generating a meal plan. Try: \"plan meals for the week under $100\"" }]);
        setStatus("Ready.");
        if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("Sorry, I couldn't generate a meal plan.", true);
        return;
      }

      // ── CHECKOUT ───────────────────────────────────────────────
      if (intentResult.intent === INTENTS.CHECKOUT) {
        // Fall through to the existing checkout logic in process_message
      }

      // ── SHOW CART ──────────────────────────────────────────────
      if (intentResult.intent === INTENTS.SHOW_CART) {
        setShowCartPanel(true);
        setMessages((p) => [...p, { role: "bot", content: "Here's your cart! 🛒" }]);
        setStatus("Ready.");
        if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("Here's your cart.", true);
        return;
      }

      // ── NEW SEARCH ─────────────────────────────────────────────
      // Only do global search when no restaurant is selected AND no active categories
      // If restaurant IS selected or categories are active, fall through to process_message
      if (intentResult.intent === INTENTS.NEW_SEARCH && !selectedRestaurant && activeCategories.length === 0) {
        // Reset state with new search filters
        const { createState } = await import("./voice/ConversationState.js");
        convStateRef.current = applyUpdate(createState(), intentResult.stateUpdate);
        convStateRef.current.lastQuery = trimmed;

        try {
          const data = await searchByIntent(trimmed);
          if (data.results && data.results.length > 0) {
            convStateRef.current.lastResults = data.results;
            const topItem = data.results[0]?.name || 'food';
            const count = data.results.length;
            setMessages((p) => [...p, { role: "bot", content: `__PRICE_COMPARE__`, priceCompare: data }]);
            setStatus("Ready.");
            if (fromVoice && voiceModeRef.current) {
              voiceSpeakRef.current(`Found ${count} options. Which one?`, true);
            }
            return;
          }
          setMessages((p) => [...p, { role: "bot", content: "I couldn't find anything matching that. Try a dish name, cuisine, or say \"suggest something\"!" }]);
          setStatus("Ready.");
          if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("I couldn't find anything. Try a different dish name.", true);
          return;
        } catch {
          setMessages((p) => [...p, { role: "bot", content: "Sorry, I had trouble processing that. Try again or ask for a specific dish!" }]);
          setStatus("Ready.");
          if (fromVoice && voiceModeRef.current) voiceSpeakRef.current("Network issue, try again.", true);
          return;
        }
      }

      // If restaurant is selected or categories are active, check for category match FIRST
      if (selectedRestaurant || activeCategories.length > 0) {
        // ── Client-side category matching (instant, no backend) ──────
        // Skip when input is more specific than a category name (e.g. "iced coffee" → item, not category "Coffee")
        if (activeCategories.length > 0) {
          const rawInput = (fromVoice ? cleanedText : trimmed).trim();
          const inputLower = rawInput.toLowerCase().replace(/\s+/g, '');
          const inputWords = rawInput.split(/\s+/).length;
          // Extract possible category phrase: "go to the appetizers" → "appetizers", "show me coffee" → "coffee"
          const goToPrefixes = /^(?:go\s+to\s+(?:the\s+)?|show\s+me\s+(?:the\s+)?|take\s+me\s+to\s+(?:the\s+)?|switch\s+to\s+(?:the\s+)?|i\s+want\s+(?:the\s+)?|open\s+(?:the\s+)?)\s*/i;
          const categoryPhrase = rawInput.replace(goToPrefixes, '').trim();
          const phraseLower = categoryPhrase.toLowerCase().replace(/\s+/g, '');
          const phraseWords = categoryPhrase.split(/\s+/).length;
          const candidates = [
            { lower: inputLower, words: inputWords },
            ...(phraseLower && phraseLower !== inputLower ? [{ lower: phraseLower, words: phraseWords }] : []),
          ];
          let matchedCat = null;
          for (const { lower: tryLower, words: tryWords } of candidates) {
            matchedCat = activeCategories.find(cat => {
              const catLower = (typeof cat.name === 'string' ? cat.name : cat).toLowerCase().replace(/\s+/g, '');
              const catWords = (typeof cat.name === 'string' ? cat.name : cat).trim().split(/\s+/).length;
              if (tryWords > catWords || tryLower.length > catLower.length + 3) return false;
              return catLower === tryLower
                || catLower.startsWith(tryLower)
                || tryLower.startsWith(catLower)
                || (catLower.includes(tryLower) && tryLower.length >= catLower.length - 2);
            });
            if (matchedCat) break;
          }
          if (matchedCat) {
            console.log(`%c[CategoryMatch] ✅ "${fromVoice ? cleanedText : trimmed}" → category "${matchedCat.name}" (id: ${matchedCat.id})`, 'color: #00ff88; font-weight: bold');
            setActiveCategoryName(matchedCat.name);
            // Pre-fetch TTS in parallel with backend call (we know the text ahead of time)
            if (fromVoice && voiceModeRef.current) {
              voiceSpeakRef.current(`${matchedCat.name}. Which one would you like?`, true);
            }
            try {
              const res = await sendMessage(token, buildChatPayload(`category:${matchedCat.id}`));
              setSessionId(res.session_id);
              if (res.items && res.items.length > 0) setCurrentItems(res.items);
              if (res.categories && res.categories.length > 0) setActiveCategories(res.categories);
              setMessages((p) => [...p, {
                role: "bot",
                content: res.reply || `${matchedCat.name} — ${res.items?.length || 0} items`,
                items: res.items,
              }]);
              setStatus("Ready.");
              return;
            } catch (err) {
              console.error('[CategoryMatch] ❌ Failed:', err);
            }
          }
        }
        console.log(`%c[IntentRouter] ➡️ Restaurant selected — sending to process_message`, 'color: #00bbff; font-weight: bold');
        // Don't return — fall through to process_message below
      }

      // ── UNCLEAR but no restaurant selected ──────────────────────
      if (!selectedRestaurant && intentResult.intent === INTENTS.UNCLEAR) {
        // For voice: don't do global search on unclear/garbled input — it returns random results
        if (fromVoice) {
          console.log('%c[IntentRouter] ⚠️ UNCLEAR voice input — asking to retry (no global search)', 'color: #ffaa00; font-weight: bold');
          setMessages((p) => [...p, { role: "bot", content: "I didn't quite get that. Try saying a dish name like \"biryani\" or a restaurant name." }]);
          setStatus("Ready.");
          if (voiceModeRef.current) voiceSpeakRef.current("I didn't quite get that. Try saying a dish name or restaurant name.", true);
          return;
        }
        // For text: try searchByIntent as fallback
        try {
          const data = await searchByIntent(cleanedText);
          if (data.results && data.results.length > 0) {
            convStateRef.current.lastQuery = cleanedText;
            convStateRef.current.lastResults = data.results;
            setMessages((p) => [...p, { role: "bot", content: `__PRICE_COMPARE__`, priceCompare: data }]);
            setStatus("Ready.");
            return;
          }
        } catch { }
        // Fall through to process_message
      }
    }



    if (selectedRestaurant && /cheapest|cheap|compare|price|best\s+value|lowest/i.test(trimmed)) {
      try {
        const data = await searchByIntent(trimmed);
        if (data.results && data.results.length > 0) {
          const topItem = data.results[0]?.name || 'food';
          const count = data.results.length;
          setMessages((p) => [...p, {
            role: "bot",
            content: `__PRICE_COMPARE__`,
            priceCompare: data,
          }]);
          setStatus("Ready.");
          if (fromVoice && voiceModeRef.current) {
            voiceSpeakRef.current(`Found ${count} options. Which one?`, true);
          }
          return;
        }
      } catch (err) { /* fall through to normal chat */ }
    }

    // Guard: if no restaurant is selected, don't send freeform text to process_message
    // (backend session may retain a stale restaurant_id from a previous interaction)
    // BUT: allow #slug (restaurant selection), category:, add: commands through
    //      because setSelectedRestaurant is async and hasn't updated yet when doSend runs
    const trimmedForGuard = (fromVoice ? cleanedText : text.trim());
    if (!selectedRestaurant && !trimmedForGuard.startsWith('#') && !trimmedForGuard.startsWith('category:') && !trimmedForGuard.startsWith('add:') && trimmedForGuard !== 'show menu') {
      trace('guard.noRestaurant', { trimmedForGuard });
      const msg = "Please pick a restaurant first! Go to the Home tab or type # to search.";
      setMessages((p) => [...p, { role: "bot", content: msg }]);
      setStatus("Ready.");
      if (fromVoice && voiceModeRef.current) {
        voiceSpeakRef.current("Please pick a restaurant first.", true);
      }
      return;
    }

    try {
      const textToSend = fromVoice ? cleanedText : text.trim();
      const payload = buildChatPayload(textToSend);
      trace('backend.send', { textToSend, session_id: payload.session_id });
      console.log(`%c[Backend] 📤 process_message("${textToSend}")`, 'color: #bb88ff; font-weight: bold');
      const res = await sendMessage(token, payload);
      trace('backend.response', {
        session_id: res.session_id,
        restaurant_id: res.restaurant_id,
        category_id: res.category_id,
        order_id: res.order_id,
        replyLength: res.reply?.length ?? 0,
        replySnippet: res.reply?.substring(0, 120) ?? '',
        voice_promptSnippet: res.voice_prompt?.substring(0, 80) ?? '',
        categoriesCount: res.categories?.length ?? 0,
        itemsCount: res.items?.length ?? 0,
        itemNames: res.items?.map(i => i.name) ?? [],
      });
      console.log(`%c[Backend] 📥 Reply: "${res.reply?.substring(0, 80)}..." | Categories: ${res.categories?.length || 0} | Items: ${res.items?.length || 0}`, 'color: #bb88ff', { categories: res.categories, items: res.items?.map(i => i.name) });
      setSessionId(res.session_id);
      setMessages((p) => [...p, {
        role: "bot", content: res.reply,
        categories: res.categories || null,
        items: res.items || null,
      }]);
      if (res.categories && res.categories.length > 0) {
        setActiveCategories(res.categories);
        if (!res.items || res.items.length === 0) {
          setActiveCategoryName(null);
          setCurrentItems([]);
        }
      }
      if (res.items && res.items.length > 0) {
        setCurrentItems(res.items);
        if (textToSend.startsWith('category:')) {
          // handleCategoryClick already set activeCategoryName
        } else if (res.category_id != null && res.categories?.length > 0) {
          const selectedCat = res.categories.find(c => c.id === res.category_id);
          setActiveCategoryName(selectedCat ? selectedCat.name : text.trim());
        } else {
          setActiveCategoryName(text.trim());
        }
      } else if (textToSend.startsWith('category:') && res.category_id) {
        // Chat returned category but no items (e.g. session/restaurant mismatch) — load items via REST
        fetchCategoryItems(res.category_id).then((items) => setCurrentItems(Array.isArray(items) ? items : [])).catch(() => {});
      }
      if (res.cart_summary) setCartData(res.cart_summary);
      if (text.trim().startsWith("add:")) {
        setTimeout(() => { fetchCart(token).then(setCartData).catch(() => { }); }, 300);
      }

      // Group order intent: open Group tab (voice or text)
      if (res.open_group_tab) {
        setTab("group");
      }

      // Update selectedRestaurant from backend response (for voice-driven restaurant switching)
      if ("restaurant_id" in res && res.restaurant_id == null) {
        setSelectedRestaurant(null);
        setActiveCategories([]);
        setCurrentItems([]);
        setActiveCategoryName(null);
      } else if (res.restaurant_id && (!selectedRestaurant || selectedRestaurant.id !== res.restaurant_id)) {
        const matchedRest = restaurants.find(r => r.id === res.restaurant_id);
        if (matchedRest) setSelectedRestaurant(matchedRest);
      }

      // Voice mode: use voice_prompt from backend (fast, no extra API call)
      if (fromVoice && voiceModeRef.current) {
        const voiceReply = res.voice_prompt || res.reply;
        if (res.reply.toLowerCase().includes("submitted") || res.reply.toLowerCase().includes("placed")) {
          console.log('%c[TTS] 🔊 Speaking: "Order placed! Thank you!"', 'color: #ff88ff; font-weight: bold');
          voiceSpeakRef.current("Order placed! Thank you!", false);
          setTimeout(() => {
            voiceModeRef.current = false;
            setVoiceMode(false); setVoiceState("idle");
          }, 2000);
        } else {
          console.log(`%c[TTS] 🔊 Speaking: "${voiceReply?.substring(0, 80)}..."`, 'color: #ff88ff; font-weight: bold');
          // Speak the voice_prompt and auto-listen after
          voiceSpeakRef.current(voiceReply, true);
        }
      }

      setStatus("Ready.");
    } catch (err) {
      traceError('backend.error', err, { fromVoice, text: trimmed });
      setVoiceState("idle");
      if (err.status === 401) {
        localStorage.removeItem("token"); setToken(null);
        setStatus("Session expired. Please log in again.");
      } else { setStatus(err.message || "Failed"); }
      if (fromVoice && voiceModeRef.current) {
        voiceSpeakRef.current("Error. Try again.", true);
      }
    }
  };
  // Keep ref in sync so voice callbacks (stale closures) always call the latest doSend
  doSendRef.current = doSend;

  const handleSend = (e) => { e.preventDefault(); doSend(messageText); };
  const handleCategoryClick = async (cat) => {
    setActiveCategoryName(cat.name);
    setStatus("Loading...");
    // Always load menu items via REST so the list shows regardless of chat session state
    try {
      const items = await fetchCategoryItems(cat.id);
      const list = Array.isArray(items) ? items : [];
      setCurrentItems(list);
      if (token) {
        // Logged in: also notify chat for cart/session; reply will append in doSend
        doSend(`category:${cat.id}`);
      } else {
        setMessages((p) => [...p, {
          role: "bot",
          content: `${cat.name} — ${list.length} items. Sign in to add to cart, or browse below.`,
          items: list.length ? list : null,
        }]);
      }
    } catch (err) {
      setCurrentItems([]);
      setMessages((p) => [...p, { role: "bot", content: "Couldn't load this category. Try again or sign in." }]);
      if (token) doSend(`category:${cat.id}`);
    }
    setStatus("Ready.");
  };
  const handleAddItem = (item) => {
    setAddedItemId(item.id);
    setTimeout(() => setAddedItemId(null), 500);
    doSend(`add:${item.id}:1`);
  };

  // ===================== RESTAURANT SELECTION =====================

  const selectRestaurant = async (r) => {
    const resolved = resolvePartneredRestaurant(r, restaurants);
    if (resolved.id == null || resolved.id === "" || Number.isNaN(Number(resolved.id))) {
      setShowSuggestions(false);
      setStatus("Ready.");
      setMessages((p) => [
        ...p,
        {
          role: "bot",
          content:
            `**${r.name}** isn’t on our order menu yet (map-only listing). Pick a restaurant under **Order Now** or type **#** and choose one with the ✓ badge.`,
        },
      ]);
      return;
    }
    setSelectedRestaurant(resolved);
    setShowSuggestions(false);
    setTab("chat");
    setActiveCategories([]);
    setActiveCategoryName(null);
    setCurrentItems([]);
    setStatus("Loading menu...");

    const apiBase = import.meta.env.DEV ? "" : (import.meta.env.VITE_API_BASE || "http://localhost:8000");

    // Fire both in parallel: fast categories REST + session setup via process_message
    const catPromise = fetch(`${apiBase}/restaurants/${resolved.id}/categories`)
      .then(res => res.ok ? res.json() : [])
      .catch(() => []);

    const sessionPromise = token
      ? sendMessage(token, buildChatPayload(`#${resolved.slug}`)).catch(() => null)
      : Promise.resolve(null);

    // Categories come back first (simple DB query)
    const cats = await catPromise;
    if (cats && cats.length > 0) {
      setActiveCategories(cats);
    }

    // Session setup finishes second — use it for session ID and welcome message only
    const sessionRes = await sessionPromise;
    if (sessionRes) {
      if (sessionRes.session_id) setSessionId(sessionRes.session_id);
      // Show welcome message but DON'T override categories (pre-fetch is authoritative)
      const welcomeText = sessionRes.reply || `Welcome to **${resolved.name}**! Pick a category or just tell me what you want.`;
      setMessages((p) => [...p, { role: "bot", content: welcomeText }]);
      // If pre-fetch returned nothing, fall back to backend categories
      if ((!cats || cats.length === 0) && sessionRes.categories && sessionRes.categories.length > 0) {
        setActiveCategories(sessionRes.categories);
      }
    } else {
      // No token or backend error — still show categories from pre-fetch
      setMessages((p) => [...p, { role: "bot", content: `Welcome to **${resolved.name}**! Pick a category or just tell me what you want.` }]);
    }
    setStatus("Ready.");
  };

  const handleInputChange = (e) => {
    const val = e.target.value;
    setMessageText(val);
    if (val.startsWith("#")) {
      const q = val.slice(1).toLowerCase();
      const partnered = restaurants.filter(
        (r) => r.name.toLowerCase().includes(q) || r.slug.toLowerCase().includes(q)
      ).map((r) => ({ ...r, partnered: true }));
      const partneredNorms = new Set(partnered.map((p) => normRestName(p.name)));
      const nearby = nearbyPlaces
        .filter((r) => r.name.toLowerCase().includes(q))
        .filter((r) => {
          const nn = normRestName(r.name);
          for (const pn of partneredNorms) {
            if (pn === nn || pn.includes(nn) || nn.includes(pn)) return false;
          }
          return true;
        })
        .map((r) => ({
          ...r,
          slug: r.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
          partnered: false,
        }));
      const combined = [...partnered, ...nearby];
      setFilteredRestaurants(combined);
      setShowSuggestions(combined.length > 0);
      setSelectedIndex(0);
    } else { setShowSuggestions(false); }
  };

  const handleKeyDown = (e) => {
    if (!showSuggestions) { if (e.key === "Enter") { e.preventDefault(); handleSend(e); } return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIndex((i) => (i + 1) % filteredRestaurants.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIndex((i) => (i - 1 + filteredRestaurants.length) % filteredRestaurants.length); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); if (filteredRestaurants[selectedIndex]) selectRestaurant(filteredRestaurants[selectedIndex]); }
    else if (e.key === "Escape") setShowSuggestions(false);
  };

  // ===================== AUTH =====================

  const handleAuth = async (e) => {
    e.preventDefault(); setStatus("Signing in...");
    try {
      const res = mode === "login" ? await login({ email, password }) : await register({ email, password });
      setToken(res.access_token);
      const role = res.role || "customer";
      setUserRole(role); localStorage.setItem("userRole", role);
      if (role === "owner" || role === "admin") {
        setShowOwnerPortal(true);
      } else {
        // Redirect customers to home and sync location
        setTab("home");
        // Use saved zipcode or detect GPS location
        const savedZip = localStorage.getItem("zipcode");
        if (savedZip) {
          lookupZipcodeAuto(savedZip);
        } else if (userLat != null && userLng != null) {
          fetchRestaurantsData(userLat, userLng, radius);
        } else if (navigator.geolocation) {
          setLocating(true); setLocationLabel("Detecting...");
          navigator.geolocation.getCurrentPosition(
            async (pos) => {
              const lat = pos.coords.latitude, lng = pos.coords.longitude;
              setUserLat(lat); setUserLng(lng);
              try {
                const geoRes = await fetch(`https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lng}&localityLanguage=en`);
                const geo = await geoRes.json();
                setLocationLabel(`${geo.city || geo.locality || ""}, ${geo.principalSubdivisionCode || geo.countryCode || ""}`);
              } catch { setLocationLabel(`${lat.toFixed(2)}, ${lng.toFixed(2)}`); }
              await fetchRestaurantsData(lat, lng, radius);
              setLocating(false);
            },
            () => { setLocationLabel(""); fetchRestaurantsData(null, null, radius); setLocating(false); },
            { timeout: 5000 }
          );
        } else {
          fetchRestaurantsData(null, null, radius);
        }
      }
      setStatus("Ready.");
    } catch (err) { setStatus(err.message || "Auth failed."); }
  };

  const handleLogout = () => {
    setToken(""); setSessionId(null); setMessages([welcomeMsg]);
    setCartData(null); setShowCartPanel(false); localStorage.removeItem("token");
    setActiveCategories([]); setActiveCategoryName(null); setCurrentItems([]);
    setUserRole("customer"); localStorage.removeItem("userRole"); setShowOwnerPortal(false);
    setSelectedRestaurant(null); setTab("home");
  };

  // ===================== HELPERS =====================

  const renderContent = (text) => {
    return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
      p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p
    );
  };

  const cartItemCount = cartData?.restaurants?.reduce((t, g) => t + g.items.reduce((s, i) => s + i.quantity, 0), 0) || 0;
  const cartTotal = cartData?.grand_total_cents ? (cartData.grand_total_cents / 100).toFixed(2) : "0.00";

  const activeOrders = myOrders.filter(o => !['completed', 'rejected'].includes(o.status) || (Date.now() - new Date(o.created_at).getTime() < 3600000));
  const completedOrders = myOrders.filter(o => ['completed'].includes(o.status) && (Date.now() - new Date(o.created_at).getTime() >= 3600000));

  // ===================== OWNER PORTAL =====================

  if (showOwnerPortal) {
    return (
      <OwnerPortal
        token={token}
        onBack={() => { if (userRole === "owner") handleLogout(); else setShowOwnerPortal(false); }}
        onTokenUpdate={(t) => { setToken(t); setUserRole("owner"); localStorage.setItem("userRole", "owner"); setShowOwnerPortal(true); }}
      />
    );
  }

  // ===================== RENDER =====================

  return (
    <div className="app-shell">
      <div className="app-content">
        {/* Payment Toast */}
        <AnimatePresence>
          {paymentToast && (
            <motion.div
              className={`payment-toast ${paymentToast.type}`}
              initial={{ y: -60, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -60, opacity: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
              onClick={() => setPaymentToast(null)}
              style={{
                position: "fixed", top: 0, left: 0, right: 0, zIndex: 9999,
                padding: "14px 20px", textAlign: "center", fontWeight: 600, fontSize: "15px",
                cursor: "pointer",
                background: paymentToast.type === "success"
                  ? "linear-gradient(135deg, #00c853, #00e676)"
                  : "linear-gradient(135deg, #ff9800, #ffc107)",
                color: "#fff",
                boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
              }}
            >
              {paymentToast.message}
            </motion.div>
          )}
        </AnimatePresence>
        {/* ====== HOME TAB ====== */}
        {tab === "home" && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
            {/* Location Bar */}
            <div className="location-bar">
              <span className="loc-icon">📍</span>
              <div className="loc-info">
                <span className="loc-label">{locating ? "Detecting..." : locationLabel || "Set location"}</span>
                {zipcode && <span className="loc-sub">ZIP: {zipcode}</span>}
              </div>
              <div className="loc-actions">
                <input className="loc-zip-input" type="text" placeholder="Zip" value={zipcode}
                  onChange={(e) => handleZipcodeChange(e.target.value)} maxLength={5} />
                <button className="loc-gps-btn" onClick={useMyLocation} disabled={locating} title="Use GPS">🎯</button>
                <select className="loc-radius-select" value={radius} onChange={(e) => handleRadiusChange(Number(e.target.value))}>
                  {RADIUS_OPTIONS.map((r) => <option key={r} value={r}>{r} mi</option>)}
                </select>
              </div>
            </div>

            {/* Search */}
            <div className="search-bar">
              <span className="search-icon">🔍</span>
              <input placeholder="Search restaurants or cuisines..."
                value={citySearch} onChange={(e) => handleCitySearchChange(e.target.value)}
                onFocus={() => { if (citySuggestions.length > 0) setShowCitySuggestions(true); }}
                onBlur={() => setTimeout(() => setShowCitySuggestions(false), 200)}
              />
              {showCitySuggestions && citySuggestions.length > 0 && (
                <div className="city-suggestions">
                  {citySuggestions.map((s, i) => (
                    <div key={i} className="city-suggestion-item" onMouseDown={() => selectCity(s)}>
                      <span>{s.city}, {s.state}</span>
                      {s.zipcode && <span className="city-suggestion-zip">{s.zipcode}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Featured Restaurant */}
            {restaurants.length > 0 && (
              <motion.div className="featured-card" onClick={() => {
                if (!token) { setTab("profile"); return; }
                selectRestaurant(restaurants[0]);
              }}
                whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.99 }} style={{ cursor: 'pointer' }}>
                {(() => {
                  const heroImg = getRestaurantImage(restaurants[0].name);
                  return heroImg ? (
                    <img src={heroImg} alt={restaurants[0].name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div style={{ width: '100%', height: '100%', background: `linear-gradient(135deg, ${CARD_GRADIENTS[0][0]}, ${CARD_GRADIENTS[0][1]})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '4rem' }}>
                      {getFoodEmoji(restaurants[0].name)}
                    </div>
                  );
                })()}
                <div className="featured-overlay">
                  <span className="featured-badge">PARTNERED</span>
                  <div className="featured-name">{restaurants[0].name}</div>
                  <div className="featured-sub">
                    {restaurants[0].city && `${restaurants[0].city} · `}
                    {restaurants[0].distance_miles != null && `${restaurants[0].distance_miles} mi away`}
                  </div>
                </div>
              </motion.div>
            )}

            {/* Budget Optimizer Floating Button */}
            <motion.button
              className="optimizer-fab"
              onClick={() => { if (!token) { setTab("profile"); return; } setShowOptimizer(true); }}
              whileHover={{ scale: 1.08 }}
              whileTap={{ scale: 0.95 }}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
            >
              💰 Budget Optimizer
            </motion.button>

            {/* Hero Video - See AI in Action */}
            <motion.div className="hero-video-section"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <div className="hero-video-header">
                <span className="hero-video-badge">🎬 NEW</span>
                <span className="hero-video-title">See AI in Action</span>
                <span className="hero-video-sub">Watch how RestaurantAI finds your perfect meal</span>
              </div>
              <div className="hero-video-wrapper">
                <video
                  className="hero-video"
                  src="/hero-video.mp4"
                  autoPlay
                  muted
                  loop
                  playsInline
                  onClick={(e) => {
                    const v = e.currentTarget;
                    if (v.paused) { v.play(); } else { v.pause(); }
                  }}
                />
                <div className="hero-video-play-hint">Tap to play/pause</div>
              </div>
            </motion.div>

            {/* All Restaurants Grid */}
            {restaurants.length > 0 && (
              <>
                <div className="section-header">
                  <span className="section-title">🟢 Order Now ({restaurants.length})</span>
                </div>
                <div className="restaurant-grid">
                  {restaurants.map((r, idx) => {
                    const grad = CARD_GRADIENTS[idx % CARD_GRADIENTS.length];
                    const rImg = getRestaurantImage(r.name);
                    return (
                      <motion.div key={r.id} className="restaurant-card-v"
                        onClick={() => {
                          if (!token) { setTab("profile"); return; }
                          selectRestaurant(r);
                        }}
                        initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.04 }}>
                        <div className="restaurant-card-v-img" style={rImg ? {} : { background: `linear-gradient(135deg, ${grad[0]}, ${grad[1]})` }}>
                          {rImg ? (
                            <img src={rImg} alt={r.name} style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'inherit' }} />
                          ) : (
                            <span className="restaurant-card-v-emoji">{getFoodEmoji(r.name)}</span>
                          )}
                        </div>
                        <div className="restaurant-card-v-body">
                          <div className="restaurant-card-v-name">{r.name}</div>
                          <div className="restaurant-card-v-meta">
                            {r.distance_miles != null && <span>{r.distance_miles} mi</span>}
                            {r.city && <span>· {r.city}</span>}
                          </div>
                          <span className="order-chip">{token ? 'Order' : 'Sign in'}</span>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              </>
            )}

            {/* Nearby */}
            {(nearbyPlaces.length > 0 || (!locating && userLat)) && (
              <>
                <div className="section-header" style={{ marginTop: 16 }}>
                  <span className="section-title">📍 Nearby Restaurants</span>
                </div>
                <div className="nearby-list">
                  {nearbyPlaces.length > 0 ? (
                    nearbyPlaces.slice(0, 8).map((p, i) => (
                      <motion.div key={`nearby-${i}`} className="nearby-item"
                        initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.05 }}>
                        <div className="nearby-item-img" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.5rem' }}>
                          {getFoodEmoji(p.name, p.cuisine || "")}
                        </div>
                        <div className="nearby-item-info">
                          <div className="nearby-item-name">{p.name}</div>
                          <div className="nearby-item-meta">
                            {p.cuisine && <span className="cuisine-tag">{p.cuisine}</span>}
                            {p.address && ` · ${p.address}`}
                          </div>
                        </div>
                        <span className="nearby-item-distance">{p.distance_miles} mi</span>
                      </motion.div>
                    ))
                  ) : (
                    <div className="menu-empty">
                      <div className="menu-empty-emoji">⏳</div>
                      <div className="menu-empty-text">Searching nearby restaurants...</div>
                    </div>
                  )}
                </div>
              </>
            )}
          </motion.div>
        )}

        {/* ====== CHAT + MENU TAB ====== */}
        {tab === "chat" && (
          <div className="chat-page">
            {!token ? (
              <div className="menu-empty" style={{ paddingTop: 60 }}>
                <div className="menu-empty-emoji">🔐</div>
                <div className="menu-empty-text">Sign in to start ordering</div>
                <div className="menu-empty-hint">Go to the Profile tab to log in</div>
              </div>
            ) : (
              <>
                {/* Chat Header */}
                <div className="chat-header">
                  <div className="chat-header-left">
                    {selectedRestaurant && (
                      <button className="chat-header-back" onClick={() => { setSelectedRestaurant(null); setActiveCategories([]); setCurrentItems([]); setTab("home"); }}>←</button>
                    )}
                    <div>
                      <div className="chat-header-title">{selectedRestaurant?.name || "RestaurantAI"}</div>
                      <div className="chat-header-status">{selectedRestaurant ? "● Online" : status}</div>
                    </div>
                  </div>
                  {cartData && cartData.restaurants && cartData.restaurants.length > 0 && (
                    <button className="chat-cart-btn" onClick={() => setShowCartPanel((v) => !v)}>
                      🛒 ${cartTotal}
                      {cartItemCount > 1 && <span className="cart-count">{cartItemCount}</span>}
                    </button>
                  )}
                </div>

                {/* Category Pills */}
                {activeCategories.length > 0 && (
                  <div className="category-pills">
                    {activeCategories.map((cat) => {
                      const catImg = getFoodItemImage(cat.name);
                      return (
                        <button key={cat.id}
                          className={`cat-pill ${activeCategoryName === cat.name ? "active" : ""}`}
                          onClick={() => handleCategoryClick(cat)}>
                          {catImg ? (
                            <img src={catImg} alt="" className="cat-thumb" />
                          ) : (
                            <span className="cat-emoji">{getFoodEmoji(cat.name)}</span>
                          )}
                          {cat.name}
                          <span className="cat-count">{cat.item_count}</span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Menu Items */}
                <div className="menu-area">
                  {currentItems.length > 0 ? (
                    currentItems.map((item, ii) => (
                      <motion.div key={item.id} className="menu-item"
                        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: ii * 0.04 }}>
                        <div className="menu-item-img">
                          {(() => {
                            const itemImg = getFoodItemImage(item.name, activeCategoryName || '');
                            return itemImg ? (
                              <img src={itemImg} alt={item.name} style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 'inherit' }} />
                            ) : getFoodEmoji(item.name);
                          })()}
                        </div>
                        <div className="menu-item-info">
                          <div className="menu-item-name">{item.name}</div>
                          {item.description && <div className="menu-item-desc">{item.description}</div>}
                          <div className="menu-item-price">${(item.price_cents / 100).toFixed(2)}</div>
                        </div>
                        <motion.button
                          className={`menu-add-btn ${addedItemId === item.id ? 'added' : ''}`}
                          onClick={() => handleAddItem(item)}
                          whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.85 }}>
                          +
                        </motion.button>
                      </motion.div>
                    ))
                  ) : activeCategories.length > 0 ? (
                    <div className="menu-empty">
                      <div className="menu-empty-emoji">👆</div>
                      <div className="menu-empty-text">Tap a category above to see items</div>
                    </div>
                  ) : selectedRestaurant ? (
                    <div className="menu-empty">
                      <div className="menu-empty-emoji">⏳</div>
                      <div className="menu-empty-text">Loading menu...</div>
                    </div>
                  ) : (
                    <div className="menu-empty">
                      <div className="menu-empty-emoji">🍽️</div>
                      <div className="menu-empty-text">Pick a restaurant from the Home tab</div>
                      <div className="menu-empty-hint">Or type # to search restaurants below</div>
                    </div>
                  )}
                </div>

                {/* AI Chat Strip */}
                <div className="ai-strip">
                  {/* Show latest bot message */}
                  {messages.length > 0 && (() => {
                    const lastBot = [...messages].reverse().find(m => m.role === "bot");
                    if (!lastBot) return null;
                    // Price Comparison Card
                    if (lastBot.priceCompare) {
                      const { query, results, best_value } = lastBot.priceCompare;
                      return (
                        <div className="price-compare-card">
                          <div className="compare-header">
                            <span className="compare-icon">🔍</span>
                            <span className="compare-title">Price Comparison: <b>{query}</b></span>
                          </div>
                          <div className="compare-results">
                            {results.slice(0, 8).map((r, i) => (
                              <div key={i} className={`compare-row ${best_value && r.price_cents === best_value.price_cents && r.restaurant_name === best_value.restaurant_name ? 'best-value' : ''}`}>
                                <div className="compare-rank">{i === 0 ? '🏆' : `#${i + 1}`}</div>
                                <div className="compare-info">
                                  <div className="compare-item-name">{r.item_name}</div>
                                  <div className="compare-restaurant">{r.restaurant_name}{r.city ? ` · ${r.city}` : ''}{r.rating ? ` ⭐${r.rating}` : ''}</div>
                                </div>
                                <div className="compare-price">${(r.price_cents / 100).toFixed(2)}</div>
                                <button className="compare-order-btn" onClick={async (e) => {
                                  const btn = e.currentTarget;
                                  if (!token) { setStatus("Please log in to order"); return; }
                                  try {
                                    btn.textContent = "…";
                                    await addComboToCart(token, r.restaurant_id, [{ item_id: r.item_id, quantity: 1 }]);
                                    const cartRes = await fetchCart(token);
                                    setCartData(cartRes);
                                    btn.textContent = "✓ Added";
                                    btn.style.background = "var(--success)";
                                    setTimeout(() => { btn.textContent = "Order"; btn.style.background = ""; }, 1500);
                                  } catch (err) {
                                    btn.textContent = "Order";
                                    setStatus(err.message || "Failed to add");
                                  }
                                }}>Order</button>
                              </div>
                            ))}
                          </div>
                          {best_value && <div className="compare-footer">🏆 Best Value: <b>{best_value.restaurant_name}</b> — ${(best_value.price_cents / 100).toFixed(2)}</div>}
                        </div>
                      );
                    }
                    // Meal Plan Card
                    if (lastBot.mealPlan) {
                      const plan = lastBot.mealPlan;
                      const DAY_SHORT = { Monday: "MON", Tuesday: "TUE", Wednesday: "WED", Thursday: "THU", Friday: "FRI", Saturday: "SAT", Sunday: "SUN" };
                      const DAY_COLORS = ["#f59e0b", "#8b5cf6", "#3b82f6", "#ec4899", "#22c55e", "#06b6d4", "#ef4444"];
                      return (
                        <div className="mp-card">
                          {/* Header */}
                          <div className="mp-header">
                            <div className="mp-title-row">
                              <span className="mp-icon">🍽️</span>
                              <span className="mp-title">Your {plan.days.length}-Day Meal Plan</span>
                            </div>
                            <div className="mp-stats">
                              <span className="mp-stat">💰 ${(plan.total_cents / 100).toFixed(2)}</span>
                              <span className="mp-stat mp-saved">✅ ${(plan.savings_cents / 100).toFixed(2)} saved</span>
                              <span className="mp-stat">{new Set(plan.days.map(d => d.restaurant_name)).size} restaurants</span>
                            </div>
                          </div>

                          {/* Days */}
                          <div className="mp-days">
                            {plan.days.map((d, i) => (
                              <div key={i} className="mp-row">
                                <div className="mp-day-pill" style={{ background: DAY_COLORS[i % 7] }}>
                                  {DAY_SHORT[d.day] || d.day.slice(0, 3).toUpperCase()}
                                </div>
                                <div className="mp-meal-info">
                                  <div className="mp-meal-name">{d.item_name}</div>
                                  <div className="mp-meal-rest">{d.restaurant_name}</div>
                                </div>
                                <div className="mp-meal-right">
                                  <div className="mp-meal-price">${(d.price_cents / 100).toFixed(2)}</div>
                                  <div className="mp-meal-btns">
                                    <button className="mp-btn-order" onClick={async (e) => {
                                      const btn = e.currentTarget;
                                      if (!token) { setStatus("Please log in to order"); return; }
                                      try {
                                        btn.textContent = "…";
                                        await addComboToCart(token, d.restaurant_id, [{ item_id: d.item_id, quantity: 1 }]);
                                        const cartRes = await fetchCart(token);
                                        setCartData(cartRes);
                                        btn.textContent = "✓";
                                        btn.style.background = "var(--success)";
                                        setTimeout(() => { btn.textContent = "Order"; btn.style.background = ""; }, 1500);
                                      } catch (err) {
                                        btn.textContent = "Order";
                                        setStatus(err.message || "Failed");
                                      }
                                    }}>Order</button>
                                    <button className="mp-btn-swap" onClick={async (e) => {
                                      const btn = e.currentTarget;
                                      try {
                                        btn.textContent = "…";
                                        const newMeal = await swapMeal({
                                          text: "",
                                          day_index: i,
                                          current_item_id: d.item_id,
                                          budget_remaining_cents: plan.savings_cents + d.price_cents,
                                        });
                                        setMessages((prev) => prev.map((msg) => {
                                          if (msg.mealPlan) {
                                            const newDays = [...msg.mealPlan.days];
                                            const oldPrice = newDays[i].price_cents;
                                            newDays[i] = newMeal;
                                            const newTotal = msg.mealPlan.total_cents - oldPrice + newMeal.price_cents;
                                            return {
                                              ...msg,
                                              mealPlan: { ...msg.mealPlan, days: newDays, total_cents: newTotal, savings_cents: msg.mealPlan.budget_cents - newTotal },
                                            };
                                          }
                                          return msg;
                                        }));
                                        btn.textContent = "🔄";
                                        setTimeout(() => { btn.textContent = "↻"; }, 1000);
                                      } catch (err) {
                                        btn.textContent = "↻";
                                        setStatus(err.message || "No alternatives");
                                      }
                                    }}>↻</button>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>

                          {/* Footer */}
                          <div className="mp-footer">
                            <div className="mp-footer-left">
                              <div className="mp-footer-total">${(plan.total_cents / 100).toFixed(2)}</div>
                              <div className="mp-footer-savings">You saved ${(plan.savings_cents / 100).toFixed(2)} ✨</div>
                            </div>
                            <button className="mp-order-all" onClick={async (e) => {
                              const btn = e.currentTarget;
                              if (!token) { setStatus("Please log in to order"); return; }
                              try {
                                btn.textContent = "Ordering…";
                                for (const d of plan.days) {
                                  await addComboToCart(token, d.restaurant_id, [{ item_id: d.item_id, quantity: 1 }]);
                                }
                                const cartRes = await fetchCart(token);
                                setCartData(cartRes);
                                btn.textContent = "✓ All Added";
                                btn.style.background = "var(--success)";
                                setTimeout(() => { btn.textContent = "Order Full Plan"; btn.style.background = ""; }, 2000);
                              } catch (err) {
                                btn.textContent = "Order Full Plan";
                                setStatus(err.message || "Failed");
                              }
                            }}>Order Full Plan</button>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div className="ai-message">
                        <div className="ai-avatar">✨</div>
                        <div className="ai-bubble">{renderContent(lastBot.content)}</div>
                      </div>
                    );
                  })()}

                  {/* Voice language: English / Tamil (conversation mode) */}
                  <div className="voice-lang-row" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, color: "#64748b" }}>Voice language / மொழி</span>
                    <button type="button" className={`voice-lang-btn ${voiceLanguage === "en" ? "active" : ""}`}
                      onClick={() => setVoiceLanguage("en")}
                      style={{
                        padding: "6px 12px", borderRadius: 8, border: `2px solid ${voiceLanguage === "en" ? "#2563eb" : "#e2e8f0"}`,
                        background: voiceLanguage === "en" ? "#2563eb" : "#fff", color: voiceLanguage === "en" ? "#fff" : "#334155",
                        cursor: "pointer", fontWeight: 600, fontSize: 13,
                      }}>
                      English
                    </button>
                    <button type="button" className={`voice-lang-btn ${voiceLanguage === "ta" ? "active" : ""}`}
                      onClick={() => setVoiceLanguage("ta")}
                      style={{
                        padding: "6px 12px", borderRadius: 8, border: `2px solid ${voiceLanguage === "ta" ? "#2563eb" : "#e2e8f0"}`,
                        background: voiceLanguage === "ta" ? "#2563eb" : "#fff", color: voiceLanguage === "ta" ? "#fff" : "#334155",
                        cursor: "pointer", fontWeight: 600, fontSize: 13,
                      }}>
                      தமிழ் (Tamil)
                    </button>
                  </div>

                  {/* Compact voice status bar (non-blocking) */}
                  {voiceMode && (
                    <div className="voice-status-bar">
                      <div className={`voice-dot ${voiceState}`} />
                      <span className="voice-status-text">
                        {voiceState === "speaking" ? "🔊 Speaking..." : voiceState === "listening" ? "🎙️ Listening..." : voiceState === "processing" ? "⏳ Processing..." : "🎤 Voice On"}
                      </span>
                      {liveTranscript && <span className="voice-live" style={{ color: "#aef", fontStyle: "italic", marginLeft: 6, fontSize: "0.85em" }}>{liveTranscript}</span>}
                      <button className="voice-end-btn" onClick={toggleVoiceMode}>✕</button>
                    </div>
                  )}

                  {/* Input */}
                  <form onSubmit={handleSend} className="ai-chat-input-row" style={{ position: 'relative' }}>
                    <input ref={inputRef} className="ai-chat-input" value={messageText}
                      onChange={handleInputChange} onKeyDown={handleKeyDown}
                      placeholder={voiceMode ? (voiceLanguage === "ta" ? "பேசுங்கள் அல்லது தட்டச்சு செய்யுங்கள்..." : "Voice active — speak or type...") : "Type # for restaurants, or ask anything..."} />
                    <button type="button" className={`mic-btn ${voiceMode ? "voice-active" : ""}`} onClick={toggleVoiceMode}
                      title={voiceMode ? "End voice mode" : "Start conversation (voice)"}>
                      {voiceMode ? "🔴" : "🎤"}
                    </button>
                    <button type="submit" className="send-btn">➤</button>
                    {/* Restaurant suggestions */}
                    {showSuggestions && (
                      <div className="suggestions">
                        {filteredRestaurants.map((r, i) => (
                          <div key={r.slug + "-" + i}
                            className={`suggestion-item ${i === selectedIndex ? "selected" : ""}`}
                            onMouseDown={(e) => { e.preventDefault(); selectRestaurant(r); }}
                            onMouseEnter={() => setSelectedIndex(i)}>
                            <div>
                              <div className="suggestion-name">
                                {r.partnered && <span className="suggestion-badge">✓</span>}
                                {r.name}
                              </div>
                              {r.city && <div className="suggestion-meta">{r.city}{r.distance_miles != null ? ` · ${r.distance_miles} mi` : ''}</div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </form>
                </div>
              </>
            )}
          </div>
        )}

        {/* ====== ORDERS TAB ====== */}
        {/* ====== TASTE PROFILE TAB (AI Flavor / Recommendations) ====== */}
        {tab === "taste" && (
          <motion.div className="taste-tab-wrap" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <TasteProfile token={token} />
          </motion.div>
        )}

        {tab === "orders" && (
          <motion.div className="orders-page" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className="orders-title">Your Orders</div>

            {!token ? (
              <div className="orders-empty">
                <div className="orders-empty-emoji">🔐</div>
                <div className="menu-empty-text">Sign in to see your orders</div>
              </div>
            ) : (
              <>
                <div className="orders-tabs">
                  <button className={`orders-tab ${ordersTab === "current" ? "active" : ""}`} onClick={() => setOrdersTab("current")}>Current</button>
                  <button className={`orders-tab ${ordersTab === "history" ? "active" : ""}`} onClick={() => setOrdersTab("history")}>History</button>
                </div>

                {ordersTab === "current" && (
                  <>
                    {activeOrders.length === 0 ? (
                      <div className="orders-empty">
                        <div className="orders-empty-emoji">📦</div>
                        <div className="menu-empty-text">No active orders</div>
                        <div className="menu-empty-hint">Go to Home tab and pick a restaurant to start ordering!</div>
                      </div>
                    ) : (
                      <>
                        <div className="orders-section-title">In Progress</div>
                        {activeOrders.map((order) => {
                          const steps = ['confirmed', 'accepted', 'preparing', 'ready', 'completed'];
                          const stepLabels = { confirmed: '📋 Ordered', accepted: '✅ Accepted', preparing: '🍳 Preparing', ready: '📦 Ready', completed: '🎉 Picked Up' };
                          const isRejected = order.status === 'rejected';
                          const currentStep = isRejected ? -1 : steps.indexOf(order.status);
                          const etaMins = order.estimated_ready_at ? Math.max(0, Math.round((new Date(order.estimated_ready_at) - Date.now()) / 60000)) : null;
                          const queuePos = order.queue_position || 0;
                          return (
                            <motion.div key={order.id} className={`order-card ${isRejected ? 'rejected' : ''}`}
                              initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                              <div className="order-card-header">
                                <div>
                                  <div className="order-restaurant-name">🍽️ {order.restaurant_name}</div>
                                  <div className="order-time">{new Date(order.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
                                </div>
                                <div className="order-price">${(order.total_cents / 100).toFixed(2)}</div>
                              </div>

                              {/* ETA & Queue Badge */}
                              {!isRejected && (etaMins !== null || queuePos > 0) && (
                                <div className="order-eta-bar">
                                  {etaMins !== null && <div className="eta-countdown">⏱️ Ready in ~{etaMins} min</div>}
                                  {queuePos > 0 && <div className="queue-badge">{queuePos === 1 ? '🔥 You\'re next!' : `📊 ${queuePos - 1} order${queuePos - 1 > 1 ? 's' : ''} ahead`}</div>}
                                </div>
                              )}

                              <div className="order-items-summary">
                                {order.items.map((it) => `${it.quantity}x ${it.name}`).join(', ')}
                              </div>
                              {isRejected ? (
                                <div className="order-rejected-badge">❌ Order Rejected</div>
                              ) : (
                                <div className="progress-tracker">
                                  {steps.map((s, i) => (
                                    <div key={s} className={`progress-step ${i <= currentStep ? 'active' : ''} ${i === currentStep ? 'current' : ''}`}>
                                      <div className="progress-dot" />
                                      <span className="progress-label">{stepLabels[s] || s}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </motion.div>
                          );
                        })}
                      </>
                    )}
                  </>
                )}

                {ordersTab === "history" && (
                  <>
                    {completedOrders.length === 0 ? (
                      <div className="orders-empty">
                        <div className="orders-empty-emoji">📋</div>
                        <div className="menu-empty-text">No past orders yet</div>
                      </div>
                    ) : (
                      completedOrders.map((order) => (
                        <div key={order.id} className="recent-order-wrap">
                          <div className="recent-order">
                            <div className="recent-order-info">
                              <div className="recent-order-name">🍽️ {order.restaurant_name}</div>
                              <div className="recent-order-detail">
                                {order.items.map((it) => `${it.quantity}x ${it.name}`).join(', ')} · ${(order.total_cents / 100).toFixed(2)}
                              </div>
                            </div>
                            {order.feedback ? (
                              <span className="feedback-done-badge">✓ Rated {order.feedback.rating}★</span>
                            ) : (
                              <span className="delivered-badge">Delivered</span>
                            )}
                          </div>
                          {order.feedback_eligible && !order.feedback && (
                            <div className="feedback-card">
                              <div className="feedback-card-title">How was your order from {order.restaurant_name}?</div>
                              <div className="feedback-stars">
                                {[1, 2, 3, 4, 5].map((star) => (
                                  <button
                                    key={star}
                                    type="button"
                                    className={`feedback-star ${(feedbackRating[order.id] || 0) >= star ? 'on' : ''}`}
                                    onClick={() => setFeedbackRating((p) => ({ ...p, [order.id]: star }))}
                                    aria-label={`${star} star`}
                                  >
                                    ★
                                  </button>
                                ))}
                              </div>
                              <div className="feedback-star-labels">
                                {(feedbackRating[order.id] || 0) <= 3 && feedbackRating[order.id] != null && (
                                  <div className="feedback-issues-section">
                                    <div className="feedback-issues-title">What went wrong?</div>
                                    {[
                                      { id: 'cold_food', label: 'Food was cold' },
                                      { id: 'taste_bad', label: 'Taste was bad' },
                                      { id: 'missing_items', label: 'Missing items' },
                                      { id: 'late_delivery', label: 'Late delivery' },
                                      { id: 'wrong_order', label: 'Wrong order' },
                                      { id: 'packaging_issue', label: 'Packaging issue' },
                                      { id: 'other', label: 'Other' },
                                    ].map(({ id, label }) => (
                                      <label key={id} className="feedback-issue-chip">
                                        <input
                                          type="checkbox"
                                          checked={((feedbackIssues[order.id] || [])).includes(id)}
                                          onChange={(e) => {
                                            const next = (feedbackIssues[order.id] || []).filter((x) => x !== id);
                                            if (e.target.checked) next.push(id);
                                            setFeedbackIssues((p) => ({ ...p, [order.id]: next }));
                                          }}
                                        />
                                        <span>{label}</span>
                                      </label>
                                    ))}
                                  </div>
                                )}
                              </div>
                              <textarea
                                className="feedback-comment"
                                placeholder="Tell us more (optional)"
                                value={feedbackComment[order.id] || ''}
                                onChange={(e) => setFeedbackComment((p) => ({ ...p, [order.id]: e.target.value }))}
                                rows={2}
                              />
                              <button
                                type="button"
                                className="feedback-submit-btn"
                                disabled={!feedbackRating[order.id] || feedbackSubmitting === order.id}
                                onClick={async () => {
                                  if (!token || !feedbackRating[order.id]) return;
                                  setFeedbackSubmitting(order.id);
                                  try {
                                    await submitFeedback(token, {
                                      order_id: order.id,
                                      rating: feedbackRating[order.id],
                                      issues: (feedbackRating[order.id] || 0) <= 3 ? (feedbackIssues[order.id] || []) : undefined,
                                      comment: (feedbackComment[order.id] || '').trim() || undefined,
                                    });
                                    setFeedbackRating((p) => { const n = { ...p }; delete n[order.id]; return n; });
                                    setFeedbackIssues((p) => { const n = { ...p }; delete n[order.id]; return n; });
                                    setFeedbackComment((p) => { const n = { ...p }; delete n[order.id]; return n; });
                                    fetchMyOrders(token).then(setMyOrders).catch(() => {});
                                  } catch (err) {
                                    console.error(err);
                                  } finally {
                                    setFeedbackSubmitting(null);
                                  }
                                }}
                              >
                                {feedbackSubmitting === order.id ? 'Submitting…' : 'Submit Feedback'}
                              </button>
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </>
                )}
              </>
            )}
          </motion.div>
        )}

        {/* ====== GROUP ORDER TAB ====== */}
        {tab === "group" && (
          <motion.div className="group-order-page" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className="group-order-title">👥 Group Order</div>

            {!groupSession && !groupViewSession && (
              <>
                <div className="group-order-section">
                  <div className="group-order-section-title">Start a group order</div>
                  <button
                    type="button"
                    className="group-order-btn primary"
                    onClick={async () => {
                      setGroupStatus("Creating…");
                      try {
                        const session = await createGroupSession(token || null, {});
                        setGroupSession(session);
                        setGroupStatus("");
                      } catch (e) {
                        setGroupStatus(e?.message || "Failed to create session");
                      }
                    }}
                  >
                    Start Group Order
                  </button>
                </div>
                <div className="group-order-section">
                  <div className="group-order-section-title">Join with code</div>
                  <input
                    type="text"
                    className="group-order-input"
                    placeholder="Enter group code (e.g. 8734)"
                    value={groupJoinCodeInput}
                    onChange={(e) => setGroupJoinCodeInput(e.target.value)}
                  />
                  <button
                    type="button"
                    className="group-order-btn"
                    onClick={async () => {
                      const code = groupJoinCodeInput.trim();
                      if (!code) return;
                      setGroupStatus("Loading…");
                      try {
                        const session = await getGroupSession(code);
                        setGroupViewSession(session);
                        setGroupStatus("");
                      } catch (e) {
                        setGroupStatus(e?.message || "Group not found");
                      }
                    }}
                  >
                    Join Group
                  </button>
                </div>
              </>
            )}

            {groupSession && (
              <div className="group-order-section">
                <div className="group-order-section-title">Share with friends</div>
                <div className="group-order-share-box">
                  <span className="group-order-share-label">Link:</span>
                  <span className="group-order-share-link">{window.location.origin}/#group/{groupSession.share_code}</span>
                  <button
                    type="button"
                    className="group-order-copy-btn"
                    onClick={() => {
                      navigator.clipboard.writeText(`${window.location.origin}/#group/${groupSession.share_code}`);
                      setGroupStatus("Link copied!");
                      setTimeout(() => setGroupStatus(""), 2000);
                    }}
                  >
                    Copy
                  </button>
                </div>
                <div className="group-order-members-title">Members ({groupSession.members?.length || 0})</div>
                {groupSession.members?.length ? (
                  <ul className="group-order-members-list">
                    {groupSession.members.map((m) => (
                      <li key={m.id}>{m.name} – {m.preference || "—"} {m.budget_cents != null ? `$${(m.budget_cents / 100).toFixed(0)}` : ""} {m.dietary_restrictions || ""}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="group-order-hint">Share the link; friends will add their preferences here.</div>
                )}
                <div className="group-order-section-title" style={{ marginTop: 16 }}>Restaurant preference (optional)</div>
                <div className="group-order-hint">By default we search all restaurants. Select one or more to limit the AI to those only:</div>
                <div className="group-order-restaurant-checkboxes">
                  {groupRestaurantOptions.map((r) => (
                    <label key={r.id} className="group-order-checkbox-label">
                      <input
                        type="checkbox"
                        checked={groupPreferRestaurantIds.includes(r.id)}
                        onChange={() => setGroupPreferRestaurantIds((prev) => prev.includes(r.id) ? prev.filter((x) => x !== r.id) : [...prev, r.id])}
                      />
                      <span>{r.name}</span>
                    </label>
                  ))}
                </div>
                <input
                  type="text"
                  className="group-order-input"
                  placeholder="Prefer cuisine (e.g. Indian, Italian)"
                  value={groupPreferCuisine}
                  onChange={(e) => setGroupPreferCuisine(e.target.value)}
                />
                <button
                  type="button"
                  className="group-order-btn"
                  onClick={async () => {
                    setGroupRecLoading(true);
                    try {
                      const rec = await getGroupRecommendation(groupSession.share_code, {
                        restaurantIds: groupPreferRestaurantIds.length > 0 ? groupPreferRestaurantIds : undefined,
                        cuisine: groupPreferCuisine.trim() || undefined,
                      });
                      setGroupRecommendation(rec);
                      if (rec?.total_cents != null && groupSession.members?.length) {
                        const split = await getGroupSplitEqual(groupSession.share_code, rec.total_cents, 600, 400);
                        setGroupSplit(split);
                      }
                    } catch (e) {
                      setGroupStatus(e?.message || "No recommendation found");
                    } finally {
                      setGroupRecLoading(false);
                    }
                  }}
                  disabled={!groupSession.members?.length || groupRecLoading}
                >
                  {groupRecLoading ? "Finding…" : "Get AI Recommendation"}
                </button>
                {groupRecommendation && (
                  <div className="group-order-recommendation">
                    <div className="group-order-rec-title">Best: {groupRecommendation.restaurant_name}</div>
                    <ul className="group-order-rec-items">
                      {groupRecommendation.suggested_items?.map((it, i) => (
                        <li key={i}>{it.quantity}x {it.name} – ${(it.price_cents * it.quantity / 100).toFixed(2)}</li>
                      ))}
                    </ul>
                    <div className="group-order-rec-total">Total: ${(groupRecommendation.total_cents / 100).toFixed(2)} · ~${(groupRecommendation.estimated_per_person_cents / 100).toFixed(2)}/person</div>
                    {groupRecommendation.reasons?.length > 0 && (
                      <div className="group-order-rec-reasons">{groupRecommendation.reasons.join(" · ")}</div>
                    )}
                    {groupRecommendation.group_discount_message && (
                      <div className="group-order-rec-discount">{groupRecommendation.group_discount_message}</div>
                    )}
                  </div>
                )}
                {groupSplit && (
                  <div className="group-order-split">
                    <div className="group-order-split-title">Bill split (equal)</div>
                    {groupSplit.members?.map((m, i) => (
                      <div key={i} className="group-order-split-row">{m.member_name}: ${(m.amount_cents / 100).toFixed(2)}</div>
                    ))}
                  </div>
                )}
                {groupRecommendation && (
                  <button
                    type="button"
                    className="group-order-btn primary"
                    style={{ marginTop: 12 }}
                    disabled={groupAddToCartLoading || !token}
                    onClick={async () => {
                      if (!token) { setTab("profile"); setGroupStatus("Sign in to add to cart"); return; }
                      setGroupAddToCartLoading(true);
                      setGroupStatus("");
                      try {
                        const items = groupRecommendation.suggested_items.map((it) => ({ item_id: it.item_id, quantity: it.quantity }));
                        await addComboToCart(token, groupRecommendation.restaurant_id, items);
                        const cart = await fetchCart(token);
                        setCartData(cart);
                        setSelectedRestaurant({ id: groupRecommendation.restaurant_id, name: groupRecommendation.restaurant_name, slug: groupRecommendation.restaurant_name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "") });
                        setShowCartPanel(true);
                        setTab("chat");
                        setGroupStatus("");
                      } catch (e) {
                        setGroupStatus(e?.message || "Failed to add to cart");
                      } finally {
                        setGroupAddToCartLoading(false);
                      }
                    }}
                  >
                    {groupAddToCartLoading ? "Adding…" : "🛒 Add to cart & order"}
                  </button>
                )}
                {groupRecommendation && !token && (
                  <div className="group-order-hint" style={{ marginTop: 6 }}>Sign in from the Profile tab to add this order to your cart.</div>
                )}
                <button type="button" className="group-order-btn secondary" onClick={() => { setGroupSession(null); setGroupRecommendation(null); setGroupSplit(null); }}>Start over</button>
              </div>
            )}

            {groupViewSession && !groupSession && (
              <div className="group-order-section">
                <div className="group-order-section-title">Group: {groupViewSession.share_code}</div>
                <div className="group-order-members-title">Members</div>
                {groupViewSession.members?.length ? (
                  <ul className="group-order-members-list">
                    {groupViewSession.members.map((m) => (
                      <li key={m.id}>{m.name} – {m.preference || "—"} {m.budget_cents != null ? `$${(m.budget_cents / 100).toFixed(0)}` : ""}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="group-order-hint">No members yet.</div>
                )}
                <div className="group-order-join-form">
                  <input type="text" className="group-order-input" placeholder="Your name" value={groupJoinName} onChange={(e) => setGroupJoinName(e.target.value)} />
                  <input type="text" className="group-order-input" placeholder="Preference (e.g. biryani, veg)" value={groupJoinPref} onChange={(e) => setGroupJoinPref(e.target.value)} />
                  <input type="text" className="group-order-input" placeholder="Budget $ (e.g. 15)" value={groupJoinBudget} onChange={(e) => setGroupJoinBudget(e.target.value)} />
                  <input type="text" className="group-order-input" placeholder="Dietary (e.g. vegetarian)" value={groupJoinDiet} onChange={(e) => setGroupJoinDiet(e.target.value)} />
                  <button
                    type="button"
                    className="group-order-btn primary"
                    disabled={!groupJoinName.trim() || groupJoinLoading}
                    onClick={async () => {
                      setGroupJoinLoading(true);
                      try {
                        const budget = groupJoinBudget.trim() ? Math.round(parseFloat(groupJoinBudget) * 100) : null;
                        await joinGroupSession(groupViewSession.share_code, {
                          name: groupJoinName.trim(),
                          preference: groupJoinPref.trim() || null,
                          budget_cents: budget,
                          dietary_restrictions: groupJoinDiet.trim() || null,
                        }, token || null);
                        const updated = await getGroupSession(groupViewSession.share_code);
                        setGroupViewSession(updated);
                        setGroupJoinName(""); setGroupJoinPref(""); setGroupJoinBudget(""); setGroupJoinDiet("");
                      } catch (e) {
                        setGroupStatus(e?.message || "Join failed");
                      } finally {
                        setGroupJoinLoading(false);
                      }
                    }}
                  >
                    {groupJoinLoading ? "Adding…" : "Join"}
                  </button>
                </div>
                <div className="group-order-hint" style={{ marginTop: 12 }}>
                  Once everyone has joined, anyone can get the AI recommendation below.
                </div>
                <div className="group-order-section-title" style={{ marginTop: 12 }}>Restaurant preference (optional)</div>
                <div className="group-order-hint">Select one or more restaurants to limit the AI to those only:</div>
                <div className="group-order-restaurant-checkboxes">
                  {groupRestaurantOptions.map((r) => (
                    <label key={r.id} className="group-order-checkbox-label">
                      <input
                        type="checkbox"
                        checked={groupPreferRestaurantIds.includes(r.id)}
                        onChange={() => setGroupPreferRestaurantIds((prev) => prev.includes(r.id) ? prev.filter((x) => x !== r.id) : [...prev, r.id])}
                      />
                      <span>{r.name}</span>
                    </label>
                  ))}
                </div>
                <input
                  type="text"
                  className="group-order-input"
                  placeholder="Prefer cuisine (e.g. Indian, Italian)"
                  value={groupPreferCuisine}
                  onChange={(e) => setGroupPreferCuisine(e.target.value)}
                />
                <button
                  type="button"
                  className="group-order-btn"
                  onClick={async () => {
                    setGroupRecLoading(true);
                    try {
                      const rec = await getGroupRecommendation(groupViewSession.share_code, {
                        restaurantIds: groupPreferRestaurantIds.length > 0 ? groupPreferRestaurantIds : undefined,
                        cuisine: groupPreferCuisine.trim() || undefined,
                      });
                      setGroupRecommendation(rec);
                      if (rec?.total_cents != null && groupViewSession.members?.length) {
                        const split = await getGroupSplitEqual(groupViewSession.share_code, rec.total_cents, 600, 400);
                        setGroupSplit(split);
                      }
                    } catch (e) {
                      setGroupStatus(e?.message || "No recommendation found");
                    } finally {
                      setGroupRecLoading(false);
                    }
                  }}
                  disabled={!groupViewSession.members?.length || groupRecLoading}
                >
                  {groupRecLoading ? "Finding…" : "Get AI Recommendation"}
                </button>
                {groupRecommendation && (
                  <>
                    <div className="group-order-recommendation">
                      <div className="group-order-rec-title">Best: {groupRecommendation.restaurant_name}</div>
                      <ul className="group-order-rec-items">
                        {groupRecommendation.suggested_items?.map((it, i) => (
                          <li key={i}>{it.quantity}x {it.name} – ${(it.price_cents * it.quantity / 100).toFixed(2)}</li>
                        ))}
                      </ul>
                      <div className="group-order-rec-total">Total: ${(groupRecommendation.total_cents / 100).toFixed(2)} · ~${(groupRecommendation.estimated_per_person_cents / 100).toFixed(2)}/person</div>
                      {groupRecommendation.reasons?.length > 0 && (
                        <div className="group-order-rec-reasons">{groupRecommendation.reasons.join(" · ")}</div>
                      )}
                      {groupRecommendation.group_discount_message && (
                        <div className="group-order-rec-discount">{groupRecommendation.group_discount_message}</div>
                      )}
                    </div>
                    {groupSplit && (
                      <div className="group-order-split">
                        <div className="group-order-split-title">Bill split (equal)</div>
                        {groupSplit.members?.map((m, i) => (
                          <div key={i} className="group-order-split-row">{m.member_name}: ${(m.amount_cents / 100).toFixed(2)}</div>
                        ))}
                      </div>
                    )}
                    {groupRecommendation && (
                      <button
                        type="button"
                        className="group-order-btn primary"
                        style={{ marginTop: 12 }}
                        disabled={groupAddToCartLoading || !token}
                        onClick={async () => {
                          if (!token) { setTab("profile"); setGroupStatus("Sign in to add to cart"); return; }
                          setGroupAddToCartLoading(true);
                          setGroupStatus("");
                          try {
                            const items = groupRecommendation.suggested_items.map((it) => ({ item_id: it.item_id, quantity: it.quantity }));
                            await addComboToCart(token, groupRecommendation.restaurant_id, items);
                            const cart = await fetchCart(token);
                            setCartData(cart);
                            setSelectedRestaurant({ id: groupRecommendation.restaurant_id, name: groupRecommendation.restaurant_name, slug: groupRecommendation.restaurant_name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "") });
                            setShowCartPanel(true);
                            setTab("chat");
                            setGroupStatus("");
                          } catch (e) {
                            setGroupStatus(e?.message || "Failed to add to cart");
                          } finally {
                            setGroupAddToCartLoading(false);
                          }
                        }}
                      >
                        {groupAddToCartLoading ? "Adding…" : "🛒 Add to cart & order"}
                      </button>
                    )}
                    {groupRecommendation && !token && (
                      <div className="group-order-hint" style={{ marginTop: 6 }}>Sign in from the Profile tab to add this order to your cart.</div>
                    )}
                  </>
                )}
                <button type="button" className="group-order-btn secondary" onClick={() => { setGroupViewSession(null); setGroupJoinCodeInput(""); setGroupRecommendation(null); setGroupSplit(null); setGroupStatus(""); }}>Back</button>
              </div>
            )}

            {groupStatus && <div className="group-order-status">{groupStatus}</div>}
          </motion.div>
        )}

        {/* ====== PROFILE TAB ====== */}
        {tab === "profile" && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            {!token ? (
              <div className="auth-page">
                <div className="auth-logo">RestaurantAI</div>
                <div className="auth-subtitle">{mode === "login" ? "Welcome back" : "Create your account"}</div>
                <form className="auth-form" onSubmit={handleAuth}>
                  <label>Email
                    <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required placeholder="you@example.com" />
                  </label>
                  <label>Password
                    <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required minLength={6} placeholder="••••••••" />
                  </label>
                  <motion.button className="auth-submit" type="submit" whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
                    {mode === "login" ? "Sign in" : "Create account"}
                  </motion.button>
                </form>
                <button className="auth-switch" onClick={() => setMode(mode === "login" ? "register" : "login")}>
                  {mode === "login" ? "Need an account? Sign up" : "Already have an account? Sign in"}
                </button>
                <button className="auth-switch" onClick={() => setShowOwnerPortal(true)} style={{ marginTop: 4, color: '#f59e0b' }}>
                  🏪 Are you a restaurant owner?
                </button>
                {status !== "Ready." && <p className="auth-status">{status}</p>}
              </div>
            ) : (
              <div className="profile-page">
                <div className="profile-header">
                  <div className="profile-avatar">👤</div>
                  <div>
                    <div className="profile-name">{email.split("@")[0]}</div>
                    <div className="profile-email">{email}</div>
                  </div>
                </div>
                <div className="profile-actions">
                  <button className="profile-action-btn" onClick={() => setShowOwnerPortal(true)}>
                    <span className="action-icon">🏪</span> Restaurant Owner Portal
                  </button>
                  <button className="profile-action-btn danger" onClick={handleLogout}>
                    <span className="action-icon">🚪</span> Log out
                  </button>
                </div>
              </div>
            )}
          </motion.div>
        )}
      </div>

      {/* Cart Panel */}
      <AnimatePresence>
        {showCartPanel && cartData && cartData.restaurants && cartData.restaurants.length > 0 && (
          <motion.div className="cart-panel" initial={{ y: 300 }} animate={{ y: 0 }} exit={{ y: 300 }} transition={{ type: "spring", damping: 25 }}>
            <div className="cart-panel-header">
              <span>🛒 Your Cart</span>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <button className="cart-clear-btn" onClick={async () => {
                  try {
                    const c = await clearCart(token);
                    setCartData(c);
                    if (!c.restaurants || c.restaurants.length === 0) setShowCartPanel(false);
                  } catch { }
                }}>🗑 Clear All</button>
                <button className="cart-panel-close" onClick={() => setShowCartPanel(false)}>✕</button>
              </div>
            </div>
            <div className="cart-panel-body">
              {cartData.restaurants.map((group) => (
                <div key={group.restaurant_id} className="cart-restaurant-group">
                  <div className="cart-restaurant-name">🍽️ {group.restaurant_name}</div>
                  {group.items.map((item, i) => (
                    <div key={item.order_item_id || i} className="cart-item-row">
                      <span>{item.quantity}x {item.name}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span>${(item.line_total_cents / 100).toFixed(2)}</span>
                        <button className="cart-item-delete" onClick={async () => {
                          try {
                            const c = await removeCartItem(token, item.order_item_id);
                            setCartData(c);
                            if (!c.restaurants || c.restaurants.length === 0) setShowCartPanel(false);
                          } catch { }
                        }}>✕</button>
                      </div>
                    </div>
                  ))}
                  <div className="cart-subtotal">Subtotal: ${(group.subtotal_cents / 100).toFixed(2)}</div>
                </div>
              ))}
            </div>
            <div className="cart-panel-footer">
              <div className="cart-grand-total">Grand Total: ${cartTotal}</div>
              <button className="cart-checkout-btn" disabled={checkingOut}
                onClick={async () => {
                  setCheckingOut(true);
                  try {
                    const res = await createCheckoutSession(token);
                    if (res.checkout_url && res.session_id !== 'sim_dev') {
                      // Redirect to Stripe Checkout
                      window.location.href = res.checkout_url;
                    } else {
                      // Dev mode: orders confirmed directly
                      setCartData(null); setShowCartPanel(false);
                      setTab("orders"); setOrdersTab("current");
                      setTimeout(() => { fetchMyOrders(token).then(setMyOrders).catch(() => { }); }, 500);
                      setTimeout(() => { fetchMyOrders(token).then(setMyOrders).catch(() => { }); }, 2000);
                      setTimeout(async () => {
                        try { const c = await fetchCart(token); setCartData(c); } catch { }
                        fetchMyOrders(token).then(setMyOrders).catch(() => { });
                      }, 5000);
                    }
                  } catch (err) { alert(err.message || "Checkout failed"); }
                  setCheckingOut(false);
                }}>
                {checkingOut ? "⏳ Processing Payment..." : "💳 Pay & Place Order"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Budget Optimizer Modal */}
      <AnimatePresence>
        {showOptimizer && (
          <motion.div className="optimizer-overlay"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setShowOptimizer(false)}
          >
            <motion.div className="optimizer-modal"
              initial={{ opacity: 0, y: 60, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 40, scale: 0.95 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="optimizer-header">
                <span className="optimizer-title">💰 AI Budget Optimizer</span>
                <button className="optimizer-close" onClick={() => setShowOptimizer(false)}>✕</button>
              </div>

              <div className="optimizer-body">
                <p className="optimizer-desc">Find the best meal combo for your group — powered by AI.</p>

                <div className="optimizer-field">
                  <label>👥 People to feed</label>
                  <div className="optimizer-stepper">
                    <button onClick={() => setOptPeople(Math.max(1, optPeople - 1))}>−</button>
                    <span className="optimizer-stepper-value">{optPeople}</span>
                    <button onClick={() => setOptPeople(Math.min(50, optPeople + 1))}>+</button>
                  </div>
                </div>

                <div className="optimizer-field">
                  <label>💵 Budget ($)</label>
                  <input type="number" className="optimizer-input" min="1" max="1000"
                    value={optBudget} onChange={(e) => setOptBudget(Number(e.target.value) || 0)} />
                </div>

                <div className="optimizer-field">
                  <label>🍽️ Cuisine (optional)</label>
                  <select className="optimizer-input" value={optCuisine} onChange={(e) => setOptCuisine(e.target.value)}>
                    <option value="">Any cuisine</option>
                    <option value="Indian">Indian</option>
                    <option value="Italian">Italian</option>
                    <option value="Chinese">Chinese</option>
                    <option value="Mexican">Mexican</option>
                    <option value="Thai">Thai</option>
                    <option value="Japanese">Japanese</option>
                    <option value="American">American</option>
                  </select>
                </div>

                <motion.button className="optimizer-find-btn"
                  disabled={optLoading || optBudget < 1 || optPeople < 1}
                  whileTap={{ scale: 0.97 }}
                  onClick={async () => {
                    setOptLoading(true); setOptError(""); setOptResults(null);
                    try {
                      const res = await mealOptimizer({
                        people: optPeople,
                        budgetCents: optBudget * 100,
                        cuisine: optCuisine || undefined,
                      });
                      setOptResults(res);
                      if (!res.combos || res.combos.length === 0) {
                        setOptError("No combos found. Try a higher budget or fewer people.");
                      }
                    } catch (err) {
                      setOptError(err.message || "Optimizer failed");
                    }
                    setOptLoading(false);
                  }}
                >
                  {optLoading ? "⏳ Finding best combos..." : "🔍 Find Best Combo"}
                </motion.button>

                {optError && <div className="optimizer-error">{optError}</div>}

                {/* Results */}
                {optResults && optResults.combos && optResults.combos.length > 0 && (
                  <div className="optimizer-results">
                    {optResults.combos.map((combo, ci) => (
                      <motion.div key={ci} className="optimizer-combo-card"
                        initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: ci * 0.1 }}
                      >
                        <div className="combo-header">
                          <span className="combo-rank">{ci === 0 ? '🏆' : ci === 1 ? '🥈' : '🥉'}</span>
                          <span className="combo-restaurant">{combo.restaurant_name}</span>
                          <span className="combo-score">Score: {combo.score.toFixed(1)}</span>
                        </div>
                        <div className="combo-items">
                          {combo.items.map((item, ii) => (
                            <div key={ii} className="combo-item-row">
                              <span>{getFoodEmoji(item.name)} {item.quantity}x {item.name}</span>
                              <span className="combo-item-price">${(item.price_cents * item.quantity / 100).toFixed(2)}</span>
                            </div>
                          ))}
                        </div>
                        <div className="combo-footer">
                          <div className="combo-stats">
                            <span className="combo-total">Total: ${(combo.total_cents / 100).toFixed(2)}</span>
                            <span className="combo-feeds">Feeds {combo.feeds_people} people</span>
                          </div>
                          <button className="combo-order-btn" onClick={async () => {
                            setShowOptimizer(false);
                            // Add all items to cart in one shot via direct API
                            try {
                              const cartItems = combo.items.map(i => ({ item_id: i.item_id, quantity: i.quantity }));
                              const cart = await addComboToCart(token, combo.restaurant_id, cartItems);
                              setCartData(cart);
                              setShowCartPanel(true);
                            } catch (e) {
                              console.error('Failed to add items to cart:', e);
                            }
                          }}>
                            🛒 Order This
                          </button>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom Nav */}
      <nav className="bottom-nav">
        <button className={`nav-item ${tab === "home" ? "active" : ""}`} onClick={() => setTab("home")}>
          <span className="nav-icon">🏠</span>
          <span>Home</span>
        </button>
        <button className={`nav-item ${tab === "chat" ? "active" : ""}`} onClick={() => setTab("chat")}>
          <span className="nav-icon">💬</span>
          <span>Chat</span>
          {selectedRestaurant && <span className="nav-badge">●</span>}
        </button>
        <button className={`nav-item ${tab === "orders" ? "active" : ""}`} onClick={() => setTab("orders")}>
          <span className="nav-icon">📦</span>
          <span>Orders</span>
          {activeOrders.length > 0 && <span className="nav-badge">{activeOrders.length}</span>}
        </button>
        <button className={`nav-item ${tab === "taste" ? "active" : ""}`} onClick={() => setTab("taste")}>
          <span className="nav-icon">🧠</span>
          <span>Taste</span>
        </button>
        <button className={`nav-item ${tab === "group" ? "active" : ""}`} onClick={() => setTab("group")}>
          <span className="nav-icon">👥</span>
          <span>Group</span>
        </button>
        <button className={`nav-item ${tab === "profile" ? "active" : ""}`} onClick={() => setTab("profile")}>
          <span className="nav-icon">👤</span>
          <span>Profile</span>
        </button>
      </nav>
    </div>
  );
}
