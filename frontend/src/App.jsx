import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { listRestaurants, fetchNearby, login, register, sendMessage, fetchCart, checkout, fetchMyOrders } from "./api.js";
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
  [/bread|toast|baguette|roll|biscuit|garlic bread/i, "🍞"],
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

const welcomeMsg = {
  role: "bot",
  content: "Hello! Set your location above, then type # to pick a restaurant.",
};

export default function App() {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [messageText, setMessageText] = useState("");
  const [messages, setMessages] = useState([welcomeMsg]);
  const [sessionId, setSessionId] = useState(null);
  const [restaurants, setRestaurants] = useState([]);
  const [nearbyPlaces, setNearbyPlaces] = useState([]);
  const [status, setStatus] = useState("Ready.");

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

  // Autocomplete
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [filteredRestaurants, setFilteredRestaurants] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Cart
  const [cartData, setCartData] = useState(null); // { restaurants: [...], grand_total_cents: 0 }
  const [showCartPanel, setShowCartPanel] = useState(false);
  const [checkingOut, setCheckingOut] = useState(false);
  const [checkoutDone, setCheckoutDone] = useState(null);

  // Order tracking
  const [myOrders, setMyOrders] = useState([]);
  const [showOrderTracker, setShowOrderTracker] = useState(false);

  // Voice
  const [isListening, setIsListening] = useState(false);

  // Owner Portal
  const [showOwnerPortal, setShowOwnerPortal] = useState(() => {
    return localStorage.getItem("userRole") === "owner";
  });
  const [userRole, setUserRole] = useState(() => localStorage.getItem("userRole") || "customer");

  // Sticky category sidebar
  const [activeCategories, setActiveCategories] = useState([]);
  const [activeCategoryName, setActiveCategoryName] = useState(null);

  const inputRef = useRef(null);
  const chatEndRef = useRef(null);

  useEffect(() => {
    if (token) {
      localStorage.setItem("token", token);
      // Load cart on login
      fetchCart(token).then(setCartData).catch(() => { });
      // Load orders on login
      fetchMyOrders(token).then(setMyOrders).catch(() => { });
    }
  }, [token]);

  // Poll for order status updates every 15s
  useEffect(() => {
    if (!token || showOwnerPortal) return;
    const interval = setInterval(() => {
      fetchMyOrders(token).then(setMyOrders).catch(() => { });
    }, 15000);
    return () => clearInterval(interval);
  }, [token, showOwnerPortal]);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Fetch restaurants when location changes
  const fetchRestaurants = useCallback(async (lat, lng, r) => {
    try {
      const params = {};
      if (lat != null && lng != null) {
        params.lat = lat;
        params.lng = lng;
        params.radius_miles = r;
      }
      const data = await listRestaurants(params);
      setRestaurants(data);

      // Also fetch real nearby restaurants from OpenStreetMap
      if (lat != null && lng != null) {
        try {
          const nearby = await fetchNearby({ lat, lng, radius_miles: r });
          setNearbyPlaces(nearby);
        } catch {
          setNearbyPlaces([]);
        }
      }
    } catch {
      setRestaurants([]);
    }
  }, []);

  // Auto-detect location on mount
  useEffect(() => {
    // Try saved zipcode first
    const savedZip = localStorage.getItem("zipcode");
    if (savedZip) {
      setZipcode(savedZip);
      lookupZipcodeAuto(savedZip);
      return;
    }

    // Otherwise, auto-detect via GPS
    if (navigator.geolocation) {
      setLocating(true);
      setLocationLabel("Detecting location...");
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          setUserLat(lat);
          setUserLng(lng);
          // Reverse geocode to get city name
          try {
            const res = await fetch(`https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lng}&localityLanguage=en`);
            const geo = await res.json();
            setLocationLabel(`${geo.city || geo.locality || ""}, ${geo.principalSubdivisionCode || geo.countryCode || ""}`);
          } catch {
            setLocationLabel(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
          }
          await fetchRestaurants(lat, lng, radius);
          setLocating(false);
        },
        () => {
          // User denied or error — show all restaurants
          setLocationLabel("");
          fetchRestaurants(null, null, radius);
          setLocating(false);
        },
        { timeout: 5000 }
      );
    } else {
      fetchRestaurants(null, null, radius);
    }
  }, []);

  // Helper for auto-loading saved zipcode (no state setter for setLocating race)
  const lookupZipcodeAuto = async (zip) => {
    setLocating(true);
    try {
      const res = await fetch(`https://api.zippopotam.us/us/${zip}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const place = data.places[0];
      const lat = parseFloat(place.latitude);
      const lng = parseFloat(place.longitude);
      setUserLat(lat);
      setUserLng(lng);
      const cityLabel = `${place["place name"]}, ${place["state abbreviation"]}`;
      setLocationLabel(cityLabel);
      setCitySearch(cityLabel);
      await fetchRestaurants(lat, lng, radius);
    } catch {
      fetchRestaurants(null, null, radius);
    }
    setLocating(false);
  };

  // --- Location functions ---
  const lookupZipcode = async (zip) => {
    if (!zip || zip.length < 5) return;
    setLocating(true);
    try {
      const res = await fetch(`https://api.zippopotam.us/us/${zip}`);
      if (!res.ok) throw new Error("Invalid zipcode");
      const data = await res.json();
      const place = data.places[0];
      const lat = parseFloat(place.latitude);
      const lng = parseFloat(place.longitude);
      setUserLat(lat);
      setUserLng(lng);
      const cityLabel = `${place["place name"]}, ${place["state abbreviation"]}`;
      setLocationLabel(cityLabel);
      setCitySearch(cityLabel);
      localStorage.setItem("zipcode", zip);
      localStorage.setItem("radius", radius);
      await fetchRestaurants(lat, lng, radius);
    } catch {
      setLocationLabel("Invalid zipcode");
    }
    setLocating(false);
  };

  // Auto-trigger zipcode lookup when 5 digits entered
  const handleZipcodeChange = (val) => {
    const cleaned = val.replace(/\D/g, "").slice(0, 5);
    setZipcode(cleaned);
    if (cleaned.length === 5) {
      lookupZipcode(cleaned);
    }
  };

  // --- City search with suggestions ---
  const searchCity = async (query) => {
    if (!query || query.length < 2) {
      setCitySuggestions([]);
      return;
    }
    try {
      // Search US cities via postal API (try multiple states)
      const states = ["SC", "NC", "GA", "VA", "FL", "TX", "CA", "NY", "PA", "OH", "IL", "NJ", "MA"];
      const results = [];
      const seenZips = new Set();
      // Use the Nominatim (OpenStreetMap) geocoder for city search
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
          if (city && !seenZips.has(key)) {
            seenZips.add(key);
            results.push({
              city,
              state,
              zipcode: zip5,
              lat: parseFloat(item.lat),
              lng: parseFloat(item.lon),
              display: `${city}, ${state}${zip5 ? " · " + zip5 : ""}`
            });
          }
        }
      }
      setCitySuggestions(results.slice(0, 5));
      setShowCitySuggestions(results.length > 0);
    } catch {
      setCitySuggestions([]);
    }
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
    setUserLat(suggestion.lat);
    setUserLng(suggestion.lng);
    setShowCitySuggestions(false);
    if (suggestion.zipcode) localStorage.setItem("zipcode", suggestion.zipcode);
    localStorage.setItem("radius", radius);
    await fetchRestaurants(suggestion.lat, suggestion.lng, radius);
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) {
      setLocationLabel("Geolocation not supported");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        setUserLat(lat);
        setUserLng(lng);
        setLocationLabel(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
        await fetchRestaurants(lat, lng, radius);
        setLocating(false);
      },
      () => {
        setLocationLabel("Location denied");
        setLocating(false);
      }
    );
  };

  const handleRadiusChange = async (newRadius) => {
    setRadius(newRadius);
    localStorage.setItem("radius", newRadius);
    if (userLat != null && userLng != null) {
      await fetchRestaurants(userLat, userLng, newRadius);
    }
  };

  // --- Voice ---
  const startListening = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert("Voice not supported. Use Chrome."); return; }
    const rec = new SR();
    rec.lang = "en-US";
    rec.continuous = false;
    rec.interimResults = false;
    rec.onstart = () => setIsListening(true);
    rec.onresult = (e) => {
      const text = e.results[0][0].transcript;
      setMessageText(text);
      setIsListening(false);
      setTimeout(() => doSend(text), 200);
    };
    rec.onerror = () => setIsListening(false);
    rec.onend = () => setIsListening(false);
    rec.start();
  };

  // --- Send ---
  const doSend = async (text) => {
    if (!text.trim()) return;
    setMessages((p) => [...p, { role: "user", content: text.trim() }]);
    setMessageText("");
    setShowSuggestions(false);
    setStatus("Thinking...");
    try {
      const res = await sendMessage(token, { session_id: sessionId, text: text.trim() });
      setSessionId(res.session_id);
      setMessages((p) => [...p, {
        role: "bot", content: res.reply,
        categories: res.categories || null,
        items: res.items || null,
      }]);
      // Capture categories for sticky sidebar
      if (res.categories && res.categories.length > 0) {
        setActiveCategories(res.categories);
        setActiveCategoryName(null);
      }
      // Track which category is active
      if (res.items && res.items.length > 0) {
        setActiveCategoryName(text.trim());
      }
      // Update cart from cart_summary if present
      if (res.cart_summary) {
        setCartData(res.cart_summary);
      }
      // Always refresh cart from server after add commands
      if (text.trim().startsWith("add:")) {
        setTimeout(() => {
          fetchCart(token).then(setCartData).catch(() => { });
        }, 300);
      }
      setStatus("Ready.");
    } catch (err) {
      if (err.status === 401) {
        localStorage.removeItem("token");
        setToken(null);
        setStatus("Session expired. Please log in again.");
      } else {
        setStatus(err.message || "Failed.");
      }
    }
  };

  const handleSend = (e) => { e.preventDefault(); doSend(messageText); };
  const handleCategoryClick = (cat) => { setActiveCategoryName(cat.name); doSend(cat.name); };
  const handleAddItem = (item) => doSend(`add:${item.id}:1`);

  // --- # autocomplete ---
  const handleInputChange = (e) => {
    const val = e.target.value;
    setMessageText(val);
    if (val.startsWith("#")) {
      const q = val.slice(1).toLowerCase();
      // Combine partnered + nearby
      const partnered = restaurants.filter(
        (r) => r.name.toLowerCase().includes(q) || r.slug.toLowerCase().includes(q)
      ).map((r) => ({ ...r, partnered: true }));

      const nearby = nearbyPlaces.filter(
        (r) => r.name.toLowerCase().includes(q)
      ).map((r) => ({
        ...r,
        slug: r.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
        partnered: false,
      }));

      const combined = [...partnered, ...nearby];
      setFilteredRestaurants(combined);
      setShowSuggestions(combined.length > 0);
      setSelectedIndex(0);
    } else {
      setShowSuggestions(false);
    }
  };

  const handleKeyDown = (e) => {
    if (!showSuggestions) {
      if (e.key === "Enter") { e.preventDefault(); handleSend(e); }
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIndex((i) => (i + 1) % filteredRestaurants.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIndex((i) => (i - 1 + filteredRestaurants.length) % filteredRestaurants.length); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); if (filteredRestaurants[selectedIndex]) selectRestaurant(filteredRestaurants[selectedIndex]); }
    else if (e.key === "Escape") setShowSuggestions(false);
  };

  const selectRestaurant = (r) => { setShowSuggestions(false); doSend(`#${r.slug}`); };

  const handleAuth = async (e) => {
    e.preventDefault();
    setStatus("Signing in...");
    try {
      const res = mode === "login" ? await login({ email, password }) : await register({ email, password });
      setToken(res.access_token);
      const role = res.role || "customer";
      setUserRole(role);
      localStorage.setItem("userRole", role);
      if (role === "owner" || role === "admin") {
        setShowOwnerPortal(true);
      }
      setStatus("Ready.");
    } catch (err) { setStatus(err.message || "Auth failed."); }
  };

  const handleLogout = () => {
    setToken(""); setSessionId(null); setMessages([welcomeMsg]);
    setCartData(null); setShowCartPanel(false); localStorage.removeItem("token");
    setActiveCategories([]); setActiveCategoryName(null);
    setUserRole("customer"); localStorage.removeItem("userRole");
    setShowOwnerPortal(false);
  };

  const renderContent = (text) => {
    return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
      p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p
    );
  };

  if (showOwnerPortal) {
    return (
      <OwnerPortal
        token={token}
        onBack={() => {
          if (userRole === "owner") {
            handleLogout();
          } else {
            setShowOwnerPortal(false);
          }
        }}
        onTokenUpdate={(t) => {
          setToken(t);
          setUserRole("owner");
          localStorage.setItem("userRole", "owner");
          setShowOwnerPortal(true);
        }}
      />
    );
  }

  return (
    <div className="page">
      {/* Location Bar */}
      <div className="location-bar">
        <div className="location-left">
          <span className="location-icon">📍</span>
          <input
            className="zip-input"
            type="text"
            placeholder="Zip"
            value={zipcode}
            onChange={(e) => handleZipcodeChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") lookupZipcode(zipcode); }}
            maxLength={5}
          />
          <div className="city-search-wrapper">
            <input
              className="city-input"
              type="text"
              placeholder="Search city..."
              value={citySearch}
              onChange={(e) => handleCitySearchChange(e.target.value)}
              onFocus={() => { if (citySuggestions.length > 0) setShowCitySuggestions(true); }}
              onBlur={() => setTimeout(() => setShowCitySuggestions(false), 200)}
            />
            {showCitySuggestions && citySuggestions.length > 0 && (
              <div className="city-suggestions">
                {citySuggestions.map((s, i) => (
                  <div key={i} className="city-suggestion-item" onMouseDown={() => selectCity(s)}>
                    <span className="city-suggestion-name">{s.city}, {s.state}</span>
                    {s.zipcode && <span className="city-suggestion-zip">{s.zipcode}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
          <button className="location-btn gps-btn" onClick={useMyLocation} disabled={locating} title="Use my location">
            🎯
          </button>
        </div>
        <div className="location-center">
          {locating && <span className="location-label">⏳ Looking up...</span>}
          {!locating && locationLabel && <span className="location-label">{locationLabel}</span>}
        </div>
        <div className="location-right">
          <label className="radius-label">
            Within
            <select value={radius} onChange={(e) => handleRadiusChange(Number(e.target.value))}>
              {RADIUS_OPTIONS.map((r) => (
                <option key={r} value={r}>{r} mi</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <header className="hero">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        >
          <p className="badge">One chat for every restaurant</p>
          <h1>RestarentAI</h1>
          <p className="subtitle">
            A fast, single-chat ordering platform for nearby restaurants.
            No endless apps, no extra fees.
          </p>
        </motion.div>
        <div className="hero-card">
          {/* Partnered restaurants */}
          {restaurants.length > 0 && (
            <>
              <h2>🟢 Order Now</h2>
              <ul>
                {restaurants.map((r, idx) => (
                  <motion.li
                    key={r.id}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.1, duration: 0.4 }}
                    whileHover={{ scale: 1.02, x: 6 }}
                    onClick={() => token && selectRestaurant(r)}
                    style={{ cursor: token ? "pointer" : "default" }}
                  >
                    <div className="restaurant-info">
                      <strong>{r.name}</strong>
                      {r.city && <span className="restaurant-city">{r.city}</span>}
                    </div>
                    <div className="restaurant-meta">
                      {r.distance_miles != null && (
                        <span className="restaurant-distance">{r.distance_miles} mi</span>
                      )}
                      <span className="restaurant-slug">#{r.slug}</span>
                    </div>
                  </motion.li>
                ))}
              </ul>
            </>
          )}

          {/* Real nearby restaurants */}
          <h2 style={restaurants.length > 0 ? { marginTop: 20 } : {}}>📍 Nearby Restaurants</h2>
          {nearbyPlaces.length === 0 ? (
            <p className="hint">
              {locating ? "Discovering nearby restaurants..." : userLat ? "No restaurants found nearby." : "Set your location to discover restaurants."}
            </p>
          ) : (
            <ul>
              {nearbyPlaces.map((p, i) => (
                <motion.li
                  key={`nearby-${i}`}
                  className="nearby-item"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.08, duration: 0.35 }}
                  whileHover={{ scale: 1.02, x: 6 }}
                >
                  <div className="restaurant-info">
                    <strong>{p.name}</strong>
                    <span className="restaurant-city">
                      {p.cuisine && <span className="cuisine-tag">{p.cuisine}</span>}
                      {p.address && ` · ${p.address}`}
                    </span>
                  </div>
                  <div className="restaurant-meta">
                    <span className="restaurant-distance">{p.distance_miles} mi</span>
                  </div>
                </motion.li>
              ))}
            </ul>
          )}
        </div>
      </header>

      <main className="content">
        {!token ? (
          <motion.section
            className="auth"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          >
            <h2>{mode === "login" ? "👋 Welcome back" : "🚀 Get started"}</h2>
            <form onSubmit={handleAuth}>
              <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required placeholder="you@example.com" /></label>
              <label>Password<input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required minLength={6} placeholder="••••••••" /></label>
              <motion.button
                type="submit"
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.97 }}
              >{mode === "login" ? "Sign in" : "Create account"}</motion.button>
            </form>
            <button className="ghost" onClick={() => setMode(mode === "login" ? "register" : "login")}>
              {mode === "login" ? "Need an account?" : "Already have an account?"}
            </button>
            {status !== "Ready." && <p className="status-msg">{status}</p>}
          </motion.section>
        ) : (
          <section className="chat">
            <div className="chat-header">
              <div>
                <h2>Ordering chat</h2>
                <p className="chat-status">{status}</p>
              </div>
              <div className="chat-header-right">
                {cartData && cartData.restaurants && cartData.restaurants.length > 0 && (
                  <div style={{ position: "relative" }}>
                    <button className="cart-btn" onClick={() => setShowCartPanel((v) => !v)}>
                      🛒 ${(cartData.grand_total_cents / 100).toFixed(2)}
                      {cartData.restaurants.length > 1 && (
                        <span style={{
                          background: "#ef4444", borderRadius: "50%", fontSize: "0.65rem",
                          padding: "1px 5px", marginLeft: 4, fontWeight: 700, color: "#fff",
                        }}>{cartData.restaurants.length}</span>
                      )}
                    </button>
                    {showCartPanel && (
                      <div className="cart-panel">
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
                              <div className="cart-subtotal">
                                Subtotal: ${(group.subtotal_cents / 100).toFixed(2)}
                              </div>
                            </div>
                          ))}
                        </div>
                        <div className="cart-panel-footer">
                          <div className="cart-grand-total">
                            Grand Total: ${(cartData.grand_total_cents / 100).toFixed(2)}
                          </div>
                          <button
                            className="cart-checkout-btn"
                            disabled={checkingOut}
                            onClick={async () => {
                              setCheckingOut(true);
                              try {
                                const result = await checkout(token);
                                setCheckoutDone(result);
                                setCartData(null);
                                setShowCartPanel(false);
                                // Refresh orders with small delay to ensure DB commit, then auto-open
                                setTimeout(() => {
                                  fetchMyOrders(token).then((orders) => {
                                    setMyOrders(orders);
                                    setShowOrderTracker(true); // Auto-open to show new order
                                  }).catch(() => { });
                                }, 500);
                                // Refresh again at 2s and 5s for robustness
                                setTimeout(() => {
                                  fetchMyOrders(token).then(setMyOrders).catch(() => { });
                                }, 2000);
                                setTimeout(async () => {
                                  try {
                                    const c = await fetchCart(token);
                                    setCartData(c);
                                  } catch { }
                                  fetchMyOrders(token).then(setMyOrders).catch(() => { });
                                  setCheckoutDone(null);
                                }, 5000);
                              } catch (err) {
                                alert(err.message || "Checkout failed");
                              }
                              setCheckingOut(false);
                            }}
                          >
                            {checkingOut ? "⏳ Placing Order..." : "🛒 Place Order"}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {myOrders.length > 0 && (
                  <div style={{ position: "relative" }}>
                    <button className="orders-header-btn" onClick={() => setShowOrderTracker(!showOrderTracker)}>
                      📦 Orders ({myOrders.filter(o => !['completed', 'rejected'].includes(o.status) || (Date.now() - new Date(o.created_at).getTime() < 3600000)).length})
                    </button>
                    {showOrderTracker && (
                      <div className="orders-dropdown">
                        <div className="orders-dropdown-header">
                          <span>📦 My Orders</span>
                          <button className="cart-panel-close" onClick={() => setShowOrderTracker(false)}>✕</button>
                        </div>
                        <div className="orders-dropdown-body">
                          {myOrders.filter(o => !['completed', 'rejected'].includes(o.status) || (Date.now() - new Date(o.created_at).getTime() < 3600000)).slice(0, 5).map(order => {
                            const steps = ['confirmed', 'accepted', 'preparing', 'ready', 'completed'];
                            const isRejected = order.status === 'rejected';
                            const currentStep = isRejected ? -1 : steps.indexOf(order.status);
                            return (
                              <div key={order.id} className={`order-tracker-card ${isRejected ? 'rejected' : ''}`}>
                                <div className="order-tracker-restaurant">
                                  <span>🍽️ {order.restaurant_name}</span>
                                  <span className="order-tracker-total">${(order.total_cents / 100).toFixed(2)}</span>
                                </div>
                                <div className="order-tracker-items-summary">
                                  {order.items.map((it, i) => `${it.quantity}x ${it.name}`).join(', ')}
                                </div>
                                {isRejected ? (
                                  <div className="order-tracker-rejected">❌ Order Rejected</div>
                                ) : (
                                  <div className="order-tracker-steps">
                                    {steps.map((s, i) => (
                                      <div key={s} className={`order-step ${i <= currentStep ? 'active' : ''} ${i === currentStep ? 'current' : ''}`}>
                                        <div className="order-step-dot" />
                                        <span className="order-step-label">{s === 'confirmed' ? 'Ordered' : s.charAt(0).toUpperCase() + s.slice(1)}</span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                <button className="ghost" onClick={handleLogout}>Log out</button>
              </div>
            </div>

            <div className="chat-body-row">
              <div className="chat-window">
                {messages.map((msg, idx) => (
                  <div key={idx}>
                    {msg.role === "user" && msg.content.startsWith("add:") ? null : (
                      <motion.div
                        className={`bubble ${msg.role}`}
                        initial={{ opacity: 0, y: 10, scale: 0.95 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{ duration: 0.3 }}
                      >{renderContent(msg.content)}</motion.div>
                    )}
                    {msg.categories && (
                      <motion.div
                        className="chips-row"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ duration: 0.4, delay: 0.1 }}
                      >
                        {msg.categories.map((cat, ci) => (
                          <motion.button
                            key={cat.id}
                            className="chip"
                            onClick={() => handleCategoryClick(cat)}
                            initial={{ opacity: 0, scale: 0.8 }}
                            animate={{ opacity: 1, scale: 1 }}
                            transition={{ delay: ci * 0.06, duration: 0.3 }}
                            whileHover={{ scale: 1.08 }}
                            whileTap={{ scale: 0.95 }}
                          >
                            <span className="chip-emoji">{getFoodEmoji(cat.name)}</span>
                            <span className="chip-name">{cat.name}</span>
                            <span className="chip-count">{cat.item_count}</span>
                          </motion.button>
                        ))}
                      </motion.div>
                    )}
                    {msg.items && (
                      <div className="items-grid">
                        {msg.items.map((item, ii) => (
                          <motion.div
                            key={item.id}
                            className="item-card"
                            initial={{ opacity: 0, x: -15 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: ii * 0.05, duration: 0.3 }}
                            whileHover={{ scale: 1.02 }}
                          >
                            <span className="item-emoji">{getFoodEmoji(item.name)}</span>
                            <div className="item-info">
                              <span className="item-name">{item.name}</span>
                              {item.description && <span className="item-desc">{item.description}</span>}
                              <span className="item-price">${(item.price_cents / 100).toFixed(2)}</span>
                            </div>
                            <motion.button
                              className="add-btn"
                              onClick={() => handleAddItem(item)}
                              whileHover={{ scale: 1.2 }}
                              whileTap={{ scale: 0.9 }}
                            >+</motion.button>
                          </motion.div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>

              {/* Sticky Category Sidebar */}
              <AnimatePresence>
                {activeCategories.length > 0 && (
                  <motion.div
                    className="category-sidebar"
                    initial={{ opacity: 0, x: 40 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 40 }}
                    transition={{ duration: 0.3 }}
                  >
                    <div className="category-sidebar-header">
                      <span>📂 Categories</span>
                      <button className="category-sidebar-close" onClick={() => setActiveCategories([])}>✕</button>
                    </div>
                    <div className="category-sidebar-list">
                      {activeCategories.map((cat) => (
                        <motion.button
                          key={cat.id}
                          className={`category-sidebar-item ${activeCategoryName === cat.name ? 'active' : ''}`}
                          onClick={() => handleCategoryClick(cat)}
                          whileHover={{ scale: 1.03, x: 3 }}
                          whileTap={{ scale: 0.97 }}
                        >
                          <span className="category-sidebar-emoji">{getFoodEmoji(cat.name)}</span>
                          <span className="category-sidebar-name">{cat.name}</span>
                          <span className="category-sidebar-count">{cat.item_count}</span>
                        </motion.button>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <div className="chat-input-wrapper">
              {isListening && (
                <div className="voice-indicator">
                  <div className="voice-wave"><span></span><span></span><span></span><span></span><span></span></div>
                  <span>Listening... speak a restaurant name, item, or order</span>
                </div>
              )}
              <form className="chat-input" onSubmit={handleSend}>
                <div className="input-container">
                  <input ref={inputRef} value={messageText} onChange={handleInputChange}
                    onKeyDown={handleKeyDown} placeholder={isListening ? 'Listening...' : 'Type # for restaurants, or say what you want...'} />
                  {showSuggestions && (
                    <div className="suggestions">
                      {filteredRestaurants.map((r, i) => (
                        <div key={r.slug + "-" + i}
                          className={`suggestion-item ${i === selectedIndex ? "selected" : ""}`}
                          onMouseDown={(e) => { e.preventDefault(); selectRestaurant(r); }}
                          onMouseEnter={() => setSelectedIndex(i)}
                        >
                          <div>
                            <span className="suggestion-name">{r.name}</span>
                            {r.distance_miles != null && (
                              <span className="suggestion-distance"> · {r.distance_miles} mi</span>
                            )}
                            {r.cuisine && (
                              <span className="cuisine-tag" style={{ marginLeft: 6 }}>{r.cuisine}</span>
                            )}
                          </div>
                          <div>
                            {r.partnered ? (
                              <span className="partner-badge">🟢 Order Now</span>
                            ) : (
                              <span className="suggestion-slug">#{r.slug}</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <button type="button" className={`mic-btn ${isListening ? "listening" : ""}`}
                  onClick={startListening} title="Voice input — say a restaurant name or what you want to order">
                  {isListening ? "🔴" : "🎤"}
                </button>
                <button type="submit">Send</button>
              </form>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
