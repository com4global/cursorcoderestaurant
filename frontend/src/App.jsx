import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { listRestaurants, fetchNearby, login, register, sendMessage, fetchCart, checkout, fetchMyOrders, voiceSTT, voiceTTS, voiceChat, createCheckoutSession } from "./api.js";
import OwnerPortal from "./OwnerPortal.jsx";

const RADIUS_OPTIONS = [5, 10, 15, 25, 50];

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
  const [sessionId, setSessionId] = useState(null);

  // Restaurants
  const [restaurants, setRestaurants] = useState([]);
  const [nearbyPlaces, setNearbyPlaces] = useState([]);
  const [selectedRestaurant, setSelectedRestaurant] = useState(null);

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

  // Orders
  const [myOrders, setMyOrders] = useState([]);
  const [ordersTab, setOrdersTab] = useState("current");

  // Voice Conversation Mode
  const [voiceMode, setVoiceMode] = useState(false);
  const [voiceState, setVoiceState] = useState("idle"); // idle | speaking | listening | processing
  const [voiceTranscript, setVoiceTranscript] = useState("");
  const [isListening, setIsListening] = useState(false);
  const voiceRecRef = useRef(null);
  const voiceModeRef = useRef(false);
  const voiceStateRef = useRef("idle");
  const lastVoicePromptRef = useRef(null);
  // Keep voiceStateRef synced
  useEffect(() => { voiceStateRef.current = voiceState; }, [voiceState]);

  // Owner
  const [showOwnerPortal, setShowOwnerPortal] = useState(() => localStorage.getItem("userRole") === "owner");
  const [userRole, setUserRole] = useState(() => localStorage.getItem("userRole") || "customer");

  // Refs
  const inputRef = useRef(null);
  const chatEndRef = useRef(null);
  const [addedItemId, setAddedItemId] = useState(null);
  const doSendRef = useRef(null);
  const voiceSpeakRef = useRef(null);
  const voiceStartListeningRef = useRef(null);

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

  // ===================== VOICE CONVERSATION MODE (SARVAM AI) =====================

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioContextRef = useRef(null);
  const voiceAudioRef = useRef(null); // for playing TTS audio
  const ttsAudioElRef = useRef(null); // persistent <audio> element for iOS
  // Tiny silent WAV to 'warm up' audio element on user gesture (iOS requirement)
  const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";

  // Speak text — Browser SpeechSynthesis (synchronous, works on all mobile devices)
  // NOTE: Sarvam AI TTS code removed from voiceSpeak — it caused async context issues
  // that broke audio playback on mobile. Sarvam AI is still used for STT + LLM matching.
  const voiceSpeak = (text, autoListenAfter = true) => {
    if (!text) return;
    window.speechSynthesis?.cancel();
    setVoiceState("speaking");

    const afterSpeak = () => {
      if (autoListenAfter && voiceModeRef.current) {
        voiceStartListeningRef.current();
      } else {
        setVoiceState("idle");
      }
    };

    if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05;
      u.pitch = 1.0;
      u.lang = "en-US";
      u.onend = afterSpeak;
      u.onerror = afterSpeak;
      window.speechSynthesis.speak(u);
    } else {
      afterSpeak();
    }
  };
  voiceSpeakRef.current = voiceSpeak;  // Keep ref in sync

  // Start listening via browser SpeechRecognition (fast, works on mobile)
  const voiceStartListening = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      console.error("SpeechRecognition not supported");
      setVoiceState("idle");
      return;
    }
    if (voiceRecRef.current) { try { voiceRecRef.current.abort(); } catch (e) { } }

    const rec = new SR();
    rec.lang = "en-US";
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    voiceRecRef.current = rec;

    rec.onstart = () => {
      setIsListening(true);
      setVoiceState("listening");
      setVoiceTranscript("");
    };

    rec.onresult = (e) => {
      let finalText = "", interimText = "";
      for (let i = 0; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else interimText += e.results[i][0].transcript;
      }
      setVoiceTranscript(finalText || interimText);
      if (finalText) {
        setIsListening(false);
        setVoiceState("processing");
        doSendRef.current(finalText.trim(), true);  // Use ref to avoid stale closure
      }
    };

    rec.onerror = (e) => {
      console.error("SpeechRecognition error:", e.error);
      setIsListening(false);
      if (e.error === 'no-speech' && voiceModeRef.current) {
        setTimeout(() => { if (voiceModeRef.current) voiceStartListeningRef.current(); }, 500);
      } else if (e.error === 'aborted') {
        // Intentionally aborted, do nothing
      } else {
        setVoiceTranscript("Mic error: " + e.error);
        setVoiceState("idle");
      }
    };

    rec.onend = () => {
      setIsListening(false);
      if (voiceModeRef.current && voiceStateRef.current === "listening") {
        setTimeout(() => { if (voiceModeRef.current) voiceStartListeningRef.current(); }, 300);
      }
    };

    try {
      rec.start();
    } catch (err) {
      console.error("Failed to start recognition:", err);
      setVoiceState("idle");
    }
  };
  voiceStartListeningRef.current = voiceStartListening;  // Keep ref in sync

  // Toggle voice mode
  const toggleVoiceMode = () => {
    if (voiceMode) {
      voiceModeRef.current = false;
      setVoiceMode(false); setVoiceState("idle"); setVoiceTranscript(""); setIsListening(false);
      if (voiceAudioRef.current) { voiceAudioRef.current.pause(); voiceAudioRef.current = null; }
      if (voiceRecRef.current) { try { voiceRecRef.current.abort(); } catch (e) { } }
    } else {
      voiceModeRef.current = true;
      setVoiceMode(true);
      // Short initial prompt based on current state
      let prompt;
      if (!selectedRestaurant) prompt = "Which restaurant would you like?";
      else if (currentItems.length > 0) prompt = "Which item would you like to add?";
      else prompt = "Say a category name.";
      voiceSpeakRef.current(prompt, true);
    }
  };

  const startListening = () => { toggleVoiceMode(); };

  // ===================== CHAT / SEND =====================

  const doSend = async (text, fromVoice = false) => {
    if (!text.trim()) return;
    setMessages((p) => [...p, { role: "user", content: text.trim() }]);
    setMessageText(""); setShowSuggestions(false); setStatus("Thinking...");
    try {
      const res = await sendMessage(token, { session_id: sessionId, text: text.trim() });
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
        setActiveCategoryName(text.trim());
      }
      if (res.cart_summary) setCartData(res.cart_summary);
      if (text.trim().startsWith("add:")) {
        setTimeout(() => { fetchCart(token).then(setCartData).catch(() => { }); }, 300);
      }

      // Update selectedRestaurant from backend response (for voice-driven restaurant switching)
      if (res.restaurant_id && (!selectedRestaurant || selectedRestaurant.id !== res.restaurant_id)) {
        const matchedRest = restaurants.find(r => r.id === res.restaurant_id);
        if (matchedRest) setSelectedRestaurant(matchedRest);
      }

      // Voice mode: use voice_prompt from backend (fast, no extra API call)
      if (fromVoice && voiceModeRef.current) {
        const voiceReply = res.voice_prompt || res.reply;
        if (res.reply.toLowerCase().includes("submitted") || res.reply.toLowerCase().includes("placed")) {
          voiceSpeakRef.current("Order placed! Thank you!", false);
          setTimeout(() => {
            voiceModeRef.current = false;
            setVoiceMode(false); setVoiceState("idle");
          }, 2000);
        } else {
          // Speak the voice_prompt and auto-listen after
          voiceSpeakRef.current(voiceReply, true);
        }
      }

      setStatus("Ready.");
    } catch (err) {
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
  const handleCategoryClick = (cat) => { setActiveCategoryName(cat.name); doSend(`category:${cat.id}`); };
  const handleAddItem = (item) => {
    setAddedItemId(item.id);
    setTimeout(() => setAddedItemId(null), 500);
    doSend(`add:${item.id}:1`);
  };

  // ===================== RESTAURANT SELECTION =====================

  const selectRestaurant = (r) => {
    setSelectedRestaurant(r);
    setShowSuggestions(false);
    setTab("chat");
    doSend(`#${r.slug}`);
  };

  const handleInputChange = (e) => {
    const val = e.target.value;
    setMessageText(val);
    if (val.startsWith("#")) {
      const q = val.slice(1).toLowerCase();
      const partnered = restaurants.filter(
        (r) => r.name.toLowerCase().includes(q) || r.slug.toLowerCase().includes(q)
      ).map((r) => ({ ...r, partnered: true }));
      const nearby = nearbyPlaces.filter(
        (r) => r.name.toLowerCase().includes(q)
      ).map((r) => ({ ...r, slug: r.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""), partnered: false }));
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
                    return lastBot ? (
                      <div className="ai-message">
                        <div className="ai-avatar">✨</div>
                        <div className="ai-bubble">{renderContent(lastBot.content)}</div>
                      </div>
                    ) : null;
                  })()}

                  {/* Compact voice status bar (non-blocking) */}
                  {voiceMode && (
                    <div className="voice-status-bar">
                      <div className={`voice-dot ${voiceState}`} />
                      <span className="voice-status-text">
                        {voiceState === "speaking" ? "🔊 Speaking..." : voiceState === "listening" ? "🎙️ Listening..." : voiceState === "processing" ? "⏳ Processing..." : "🎤 Voice On"}
                      </span>
                      {voiceTranscript && <span className="voice-heard">“{voiceTranscript}”</span>}
                      <button className="voice-end-btn" onClick={toggleVoiceMode}>✕</button>
                    </div>
                  )}
                  {/* Hidden audio element for Sarvam TTS (DOM-rendered for iOS compatibility) */}
                  <audio ref={ttsAudioElRef} playsInline preload="none" style={{ display: 'none' }} />

                  {/* Input */}
                  <form onSubmit={handleSend} className="ai-chat-input-row" style={{ position: 'relative' }}>
                    <input ref={inputRef} className="ai-chat-input" value={messageText}
                      onChange={handleInputChange} onKeyDown={handleKeyDown}
                      placeholder={voiceMode ? "Voice active — speak or type..." : "Type # for restaurants, or ask anything..."} />
                    <button type="button" className={`mic-btn ${voiceMode ? "voice-active" : ""}`} onClick={toggleVoiceMode}
                      title={voiceMode ? "End voice mode" : "Start voice mode"}>
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
                          const isRejected = order.status === 'rejected';
                          const currentStep = isRejected ? -1 : steps.indexOf(order.status);
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
                                      <span className="progress-label">{s === 'confirmed' ? 'Ordered' : s.charAt(0).toUpperCase() + s.slice(1)}</span>
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
                        <div key={order.id} className="recent-order">
                          <div className="recent-order-info">
                            <div className="recent-order-name">🍽️ {order.restaurant_name}</div>
                            <div className="recent-order-detail">
                              {order.items.map((it) => `${it.quantity}x ${it.name}`).join(', ')} · ${(order.total_cents / 100).toFixed(2)}
                            </div>
                          </div>
                          <span className="delivered-badge">Delivered</span>
                        </div>
                      ))
                    )}
                  </>
                )}
              </>
            )}
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
        {showCartPanel && cartData && cartData.restaurants && (
          <motion.div className="cart-panel" initial={{ y: 300 }} animate={{ y: 0 }} exit={{ y: 300 }} transition={{ type: "spring", damping: 25 }}>
            <div className="cart-panel-header">
              <span>🛒 Your Cart</span>
              <button className="cart-panel-close" onClick={() => setShowCartPanel(false)}>✕</button>
            </div>
            <div className="cart-panel-body">
              {cartData.restaurants.map((group) => (
                <div key={group.restaurant_id} className="cart-restaurant-group">
                  <div className="cart-restaurant-name">🍽️ {group.restaurant_name}</div>
                  {group.items.map((item, i) => (
                    <div key={i} className="cart-item-row">
                      <span>{item.quantity}x {item.name}</span>
                      <span>${(item.line_total_cents / 100).toFixed(2)}</span>
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
        <button className={`nav-item ${tab === "profile" ? "active" : ""}`} onClick={() => setTab("profile")}>
          <span className="nav-icon">👤</span>
          <span>Profile</span>
        </button>
      </nav>
    </div>
  );
}
